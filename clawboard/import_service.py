"""Preview and journaled additive imports; callers stop writers and own the mutex.

The helper reads the final saved library after the original process exits. A
preview can therefore never overwrite captures made while its window was open.
"""
from dataclasses import dataclass
from pathlib import Path
import tempfile

from clawboard.backup_format import (
    BackupError, MAX_IMAGE_BYTES, MAX_JSON_BYTES, check_cancel, data_details,
    json_bytes, parse_json, plain_path, read_file, safe_name, stream_hash,
    write_package,
)
from clawboard.backups import BackupService
from clawboard.import_merge import plan_merge
from clawboard.import_source import read_source
from clawboard.trash import image_references


@dataclass(frozen=True)
class ImportPreview:
    source: object
    plan: object
    current_image_hashes: dict


@dataclass(frozen=True)
class ImportResult:
    backup_path: object
    imported_count: int
    duplicate_count: int
    disabled_trigger_count: int
    no_op: bool = False
    cleanup_pending: bool = False


class ImportService:
    def __init__(self, data_file, images_dir=None):
        self.data_file = Path(data_file).absolute()
        self.images_dir = (Path(images_dir).absolute() if images_dir is not None
                           else self.data_file.parent / 'images')

    def _image_hashes(self, data, cancelled):
        names = image_references(data)
        result = {}
        plain_path(self.images_dir, missing_ok=not names)
        for name in sorted(names):
            check_cancel(cancelled)
            safe_name(name)
            path = plain_path(self.images_dir / name)
            if not path.is_file():
                raise BackupError('当前库引用的图片不是有效文件，未开始导入。')
            with path.open('rb') as stream:
                result[name] = stream_hash(stream, MAX_IMAGE_BYTES, cancelled)[0]
        return result

    def inspect(self, path, current, *, cancelled=None):
        """Only inspect detached UI snapshots; never writes a library or assets."""
        source = read_source(path, cancelled=cancelled)
        hashes = self._image_hashes(current, cancelled)
        check_cancel(cancelled)
        return ImportPreview(source, plan_merge(current, source,
                             current_image_hashes=hashes), hashes)

    def merge(self, source_path, expected_sha256, selected, *, cancelled=None):
        """Idle-library operation, used only inside the helper's exclusive lease."""
        service = BackupService(self.data_file, self.images_dir)
        recovery = service.recover_pending()
        if recovery and recovery.cleanup_pending:
            raise BackupError('前一次事务尚未清理完成，未开始导入。')
        current_raw = read_file(self.data_file, MAX_JSON_BYTES, cancelled)
        data_details(current_raw)
        current = parse_json(current_raw)
        current_hashes = self._image_hashes(current, cancelled)
        # The directory is private to this invocation. TemporaryDirectory only
        # removes its own staged files, never names supplied by imported JSON.
        plain_path(self.data_file.parent)
        with tempfile.TemporaryDirectory(prefix='.clawboard-import-',
                                         dir=self.data_file.parent) as temporary:
            stage = Path(temporary)
            source = read_source(source_path, expected_sha256=expected_sha256,
                                 staging=stage / 'source', cancelled=cancelled)
            plan = plan_merge(current, source, selected,
                              current_image_hashes=current_hashes)
            if plan.error:
                raise BackupError(plan.error)
            if not plan.imported_count:
                return ImportResult(None, 0, plan.duplicate_count, 0, no_op=True)
            raw = json_bytes(plan.data)
            if len(raw) > MAX_JSON_BYTES:
                raise BackupError('合并后的资料超过大小上限，未开始导入。')
            details, names = data_details(raw)
            incoming = {new: old for old, new in plan.image_map.items()}
            existing_names = ({p.name.casefold() for p in self.images_dir.iterdir()}
                              if self.images_dir.exists() else set())
            assets = []
            for name in names:
                check_cancel(cancelled)
                if name in incoming:
                    target = self.images_dir / name
                    # Even an unreferenced spare image must not be overwritten.
                    if target.exists() or name.casefold() in existing_names:
                        raise BackupError('新图片名称发生冲突，请重新预览后导入。')
                    path = stage / 'source' / 'images' / incoming[name]
                else:
                    path = self.images_dir / name
                assets.append((name, path))
            package = write_package(stage / 'merged.zip', raw, assets,
                                    details=details, cancelled=cancelled)
            check_cancel(cancelled)
            # RestoreTransaction first makes a complete safety copy and journals
            # every replacement; crashes and failures use its tested rollback.
            result = service.restore(package.archive,
                                     expected_sha256=package.sha256,
                                     cancelled=cancelled)
            return ImportResult(result.backup_path, plan.imported_count,
                                plan.duplicate_count, plan.disabled_trigger_count,
                                cleanup_pending=result.cleanup_pending)
