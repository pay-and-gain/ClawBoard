"""Public, path-injected complete backup API; standard library only.

Call restore/recover_pending only while capture, saves and image GC are stopped
and the caller holds the product's single-instance mutex. External file bodies
are never followed: a file-list record remains a reference to its original path.
"""
from pathlib import Path
from functools import wraps

from clawboard.backup_format import (
    BackupError, BackupCancelled, BackupPreview, MAX_JSON_BYTES, MAX_IMAGE_BYTES,
    MAX_TOTAL_BYTES, MAX_MEMBERS, MAX_MANIFEST_BYTES, MAX_ARCHIVE_BYTES,
    data_details, plain_path, read_file, read_package, safe_name, write_package,
)
from clawboard.backup_restore import RecoveryResult, RestoreResult, RestoreTransaction


def _operation(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (OSError, ValueError) as error:
            if isinstance(error, BackupError):
                raise
            raise BackupError('备份操作未完成：' + str(error)) from error
    return guarded


class BackupService:
    def __init__(self, data_file, images_dir=None):
        self.data_file = Path(data_file).absolute()
        self.images_dir = Path(images_dir).absolute() if images_dir is not None else self.data_file.parent / 'images'

    @_operation
    def create(self, destination, cancelled=None):
        destination = Path(destination).absolute()
        plain_path(self.data_file.parent)
        plain_path(self.images_dir, missing_ok=True)
        plain_path(destination, missing_ok=True)
        safe_name(destination.name)
        if destination.suffix.lower() != '.zip':
            raise BackupError('完整备份必须保存为 .zip 文件。')
        canonical = destination.resolve()
        image_root = self.images_dir.resolve()
        if (canonical == self.data_file.resolve() or canonical == image_root
                or image_root in canonical.parents
                or destination.exists() and self.data_file.exists()
                and destination.samefile(self.data_file)
                or canonical.name == '.clawboard-restore-journal.json'
                or any(part.startswith('.clawboard-restore-') for part in canonical.parts)):
            raise BackupError('备份目标不能覆盖数据文件或写入图片目录。')
        raw = read_file(self.data_file, MAX_JSON_BYTES, cancelled)
        details, names = data_details(raw)
        images = [(name, self.images_dir / name) for name in names]
        return write_package(destination, raw, images, details=details, cancelled=cancelled)

    @_operation
    def inspect(self, archive, cancelled=None):
        return read_package(archive, cancelled=cancelled).preview

    @_operation
    def restore(self, archive, expected_sha256=None, cancelled=None):
        return RestoreTransaction(self.data_file, self.images_dir).restore(
            archive, expected_sha256=expected_sha256, cancelled=cancelled)

    @_operation
    def recover_pending(self):
        return RestoreTransaction(self.data_file, self.images_dir).recover_pending()
