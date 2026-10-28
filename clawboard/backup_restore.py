"""Journaled restore of an idle library; the caller owns the product mutex.

Before-images and the complete plan precede the first replacement. A process
that stops at any instruction before the committed marker can replay rollback.
No directory-wide deletion or application/history IDs participate in restore.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid

from clawboard.backup_format import (
    BackupError, BackupPreview, CHUNK_SIZE, MAX_JSON_BYTES, MAX_IMAGE_BYTES,
    MAX_MEMBERS, MAX_MANIFEST_BYTES, check_cancel, data_details, json_bytes,
    parse_json, plain_path, read_file, read_package, safe_name, stream_hash, write_package,
)


@dataclass(frozen=True)
class RestoreResult:
    backup_path: Path
    preview: BackupPreview
    cleanup_pending: bool = False


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    backup_path: Path
    cleanup_pending: bool = False


def _digest(path, limit):
    plain_path(path)
    with Path(path).open('rb') as stream:
        return stream_hash(stream, limit)[0]


def _copy(source, destination, limit, cancelled=None):
    plain_path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plain_path(destination.parent)
    plain_path(destination, missing_ok=True)
    total = 0
    with Path(source).open('rb') as reader, destination.open('wb') as writer:
        while True:
            check_cancel(cancelled)
            chunk = reader.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise BackupError('恢复文件大小超过上限。')
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())


class RestoreTransaction:
    def __init__(self, data_file, images_dir):
        self.data_file = Path(data_file).absolute()
        self.images_dir = Path(images_dir).absolute()
        self.root = self.data_file.parent
        self.journal = self.root / '.clawboard-restore-journal.json'

    def _locations(self):
        plain_path(self.root)
        if not self.root.is_dir():
            raise BackupError('数据目录无效。')
        plain_path(self.data_file, missing_ok=True)
        plain_path(self.images_dir, missing_ok=True)
        plain_path(self.journal, missing_ok=True)

    def _write_journal(self, plan):
        self._locations()
        raw = json_bytes(plan)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise BackupError('恢复事务记录超过上限。')
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.restore-journal-', dir=self.root)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.journal)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _validate_plan(self, plan):
        if (not isinstance(plan, dict) or plan.get('format') != 'clawboard-restore'
                or type(plan.get('version')) is not int or plan['version'] != 1
                or plan.get('data_file') != self.data_file.name
                or plan.get('images_dir') != str(self.images_dir)
                or plan.get('phase') not in ('prepared', 'applying', 'committed', 'rolled_back')):
            raise BackupError('恢复事务记录无效，需要保留现场人工检查。')
        if not isinstance(plan.get('transaction'), str) or not re.fullmatch(
                r'\.clawboard-restore-[0-9a-f]{32}', plan['transaction']):
            raise BackupError('恢复事务目录无效。')
        safe_name(plan.get('backup_name'))
        if not plan['backup_name'].startswith('ClawBoard恢复前_') or not plan['backup_name'].endswith('.zip'):
            raise BackupError('恢复前备份名称无效。')
        if type(plan.get('images_dir_existed')) is not bool:
            raise BackupError('恢复事务目录状态无效。')
        entries = plan.get('images')
        if not isinstance(entries, list) or len(entries) + 2 > MAX_MEMBERS:
            raise BackupError('恢复事务成员数量无效。')
        folded = set()
        for entry in [plan.get('data'), *entries]:
            if not isinstance(entry, dict) or type(entry.get('existed')) is not bool:
                raise BackupError('恢复事务成员无效。')
            for key in ('new_sha256', 'old_sha256'):
                value = entry.get(key)
                if key == 'old_sha256' and not entry['existed'] and value is None:
                    continue
                if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                    raise BackupError('恢复事务校验值无效。')
        for entry in entries:
            name = safe_name(entry.get('name'))
            if name.casefold() in folded:
                raise BackupError('恢复事务图片名称重复。')
            folded.add(name.casefold())
        transaction = self.root / plan['transaction']
        plain_path(transaction, missing_ok=plan['phase'] in ('committed', 'rolled_back'))
        if transaction.exists() and not transaction.is_dir():
            raise BackupError('恢复事务目录无效。')
        if transaction.exists():
            for base, dirs, files in os.walk(transaction, followlinks=False):
                for name in (*dirs, *files):
                    plain_path(Path(base) / name)
        return transaction

    def _clean(self, plan):
        transaction = self._validate_plan(plan)
        # Only delete the fixed, verified child created for this transaction.
        if transaction.parent.absolute() != self.root or not transaction.name.startswith('.clawboard-restore-'):
            raise BackupError('事务清理路径越界。')
        if transaction.exists():
            for base, dirs, files in os.walk(transaction, followlinks=False):
                for name in (*dirs, *files):
                    plain_path(Path(base) / name)
            shutil.rmtree(transaction)
        self.journal.unlink(missing_ok=True)

    def _rollback_entry(self, entry, target, original, limit):
        plain_path(target, missing_ok=True)
        current = _digest(target, limit) if target.exists() else None
        if current not in (None, entry['new_sha256'], entry['old_sha256']):
            raise BackupError('恢复中断后目标文件被其他程序改动，已保留现场：' + target.name)
        if entry['existed']:
            if current == entry['old_sha256']:
                return  # A previous replay may already have consumed this before-image.
            if _digest(original, limit) != entry['old_sha256']:
                raise BackupError('恢复前原件校验失败，已保留现场。')
            # Same-volume rename needs no second full-file allocation when the
            # disk is full. Replay recognizes the restored target by its hash.
            os.replace(original, target)
        elif current == entry['new_sha256']:
            target.unlink()

    def recover_pending(self):
        self._locations()
        if not self.journal.exists():
            return None
        try:
            plan = parse_json(read_file(self.journal, MAX_MANIFEST_BYTES))
            transaction = self._validate_plan(plan)
            status = 'committed' if plan['phase'] == 'committed' else 'rolled_back'
            if plan['phase'] not in ('committed', 'rolled_back'):
                plain_path(self.images_dir, missing_ok=True)
                for entry in plan['images']:
                    self._rollback_entry(entry, self.images_dir / entry['name'],
                                         transaction / 'old/images' / entry['name'], MAX_IMAGE_BYTES)
                self._rollback_entry(plan['data'], self.data_file,
                                     transaction / 'old/data.json', MAX_JSON_BYTES)
                if not plan['images_dir_existed'] and self.images_dir.is_dir():
                    try:
                        self.images_dir.rmdir()
                    except OSError:
                        pass  # Never remove unrelated files left in this directory.
                plan['phase'] = 'rolled_back'
                self._write_journal(plan)
            try:
                self._clean(plan)
                pending = False
            except OSError:
                pending = True
            return RecoveryResult(status, self.root / plan['backup_name'], pending)
        except (OSError, ValueError) as error:
            if isinstance(error, BackupError):
                raise
            raise BackupError('恢复中断事务处理失败，原件与事务记录已保留。') from error

    def _safety_backup(self, cancelled):
        present = self.data_file.exists()
        raw = read_file(self.data_file, MAX_JSON_BYTES, cancelled) if present else b'{}'
        image_paths, folded = [], set()
        if self.images_dir.exists():
            if not self.images_dir.is_dir():
                raise BackupError('图片目录不是文件夹。')
            for path in self.images_dir.iterdir():
                check_cancel(cancelled)
                if len(image_paths) + 2 >= MAX_MEMBERS:
                    raise BackupError('原图片目录成员数量超过上限，未开始恢复。')
                plain_path(path)
                safe_name(path.name)
                if not path.is_file() or path.name.casefold() in folded:
                    raise BackupError('原图片目录含不支持的成员，未开始恢复。')
                folded.add(path.name.casefold())
                image_paths.append((path.name, path))
            image_paths.sort(key=lambda pair: pair[0])
        try:
            details, _ = data_details(raw)
        except BackupError:
            details = None
        name = 'ClawBoard恢复前_%s_%s.zip' % (time.strftime('%Y%m%d-%H%M%S'), uuid.uuid4().hex[:8])
        result = write_package(self.root / name, raw, image_paths, details=details,
                               safety=True, data_present=present, cancelled=cancelled)
        return result.archive

    def restore(self, archive, *, expected_sha256=None, cancelled=None):
        self.root.mkdir(parents=True, exist_ok=True)
        self._locations()
        pending = self.recover_pending()
        if pending and pending.cleanup_pending:
            raise BackupError('前一次恢复事务尚未清理完成，请先检查目录权限。')
        transaction = self.root / ('.clawboard-restore-' + uuid.uuid4().hex)
        transaction.mkdir()
        plan = None
        try:
            package = read_package(archive, staging=transaction / 'new',
                                   expected_sha256=expected_sha256, cancelled=cancelled)
            _, referenced_images = data_details(package.data)
            referenced_images = set(referenced_images)
            check_cancel(cancelled)
            backup = self._safety_backup(cancelled)
            entries = []
            new_data = next(member for member in package.manifest['members'] if member['path'] == 'data.json')
            data_entry = dict(existed=self.data_file.exists(), old_sha256=None,
                              new_sha256=new_data['sha256'])
            if data_entry['existed']:
                _copy(self.data_file, transaction / 'old/data.json', MAX_JSON_BYTES, cancelled)
                data_entry['old_sha256'] = _digest(transaction / 'old/data.json', MAX_JSON_BYTES)
            # An NTFS name can address an existing file with different casing.
            # Reject ambiguous replacements instead of silently changing its name.
            existing = {path.name.casefold(): path.name for path in self.images_dir.iterdir()} if self.images_dir.exists() else {}
            for member in package.manifest['members']:
                if not member['path'].startswith('images/'):
                    continue
                name = member['path'][7:]
                if name not in referenced_images:
                    continue  # A safety copy preserves spare files but never overwrites unrelated targets.
                if name.casefold() in existing and existing[name.casefold()] != name:
                    raise BackupError('目标图片目录存在大小写冲突，未开始恢复。')
                target = plain_path(self.images_dir / name, missing_ok=True)
                entry = dict(name=name, existed=target.exists(), old_sha256=None,
                             new_sha256=member['sha256'])
                if entry['existed']:
                    _copy(target, transaction / 'old/images' / name, MAX_IMAGE_BYTES, cancelled)
                    entry['old_sha256'] = _digest(transaction / 'old/images' / name, MAX_IMAGE_BYTES)
                entries.append(entry)
            plan = dict(format='clawboard-restore', version=1, phase='prepared',
                        data_file=self.data_file.name, images_dir=str(self.images_dir),
                        images_dir_existed=self.images_dir.exists(), transaction=transaction.name,
                        backup_name=backup.name, data=data_entry, images=entries)
            self._write_journal(plan)
            check_cancel(cancelled)
            plan['phase'] = 'applying'
            self._write_journal(plan)
            if entries:
                self.images_dir.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                check_cancel(cancelled)
                plain_path(self.images_dir)
                plain_path(self.images_dir / entry['name'], missing_ok=True)
                os.replace(transaction / 'new/images' / entry['name'], self.images_dir / entry['name'])
            check_cancel(cancelled)
            plain_path(self.data_file, missing_ok=True)
            os.replace(transaction / 'new/data.json', self.data_file)
            # Cancellation after replacing JSON still rolls the entire plan back.
            check_cancel(cancelled)
            plan['phase'] = 'committed'
            self._write_journal(plan)
            try:
                self._clean(plan)
                cleanup_pending = False
            except OSError:
                cleanup_pending = True
            return RestoreResult(backup, package.preview, cleanup_pending)
        except Exception as error:
            if self.journal.exists():
                try:
                    self.recover_pending()
                except Exception as recovery_error:
                    raise BackupError('恢复未完成，自动回退受阻；已保留事务记录和原库备份。') from recovery_error
            else:
                # No journal means the first target replacement has not happened.
                if transaction.exists():
                    if transaction.parent.absolute() != self.root:
                        raise BackupError('事务清理路径越界。') from error
                    shutil.rmtree(transaction)
            if isinstance(error, BackupError):
                raise
            raise BackupError('恢复失败，原库已保留或回退。') from error
