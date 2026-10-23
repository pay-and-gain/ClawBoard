# -*- coding: utf-8 -*-
"""注入路径的 JSON 仓库：保护损坏原件、延后迁移写入、原子替换。

不依赖 GUI、全局数据路径或 NO_SAVE。应用层决定何时保存以及测试是否允许写盘。
save 是同步 I/O 边界，应用层应把不可变快照交给单一后台写入器。
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid

from clawboard.config import SCHEMA_VERSION
from clawboard.models import default_data, normalize_data


class StorageError(OSError):
    """保存失败；调用方必须向日志或 UI 报告，不应静默伪装成功。"""


class RecoveryRequiredError(StorageError):
    """原数据不可读取，显式恢复前禁止自动覆盖。"""


@dataclass(frozen=True)
class LoadResult:
    data: dict
    recovery_required: bool = False
    notices: tuple = ()
    migrated: bool = False


class JsonStore:
    def __init__(self, path):
        self.path = Path(path)
        self.recovery_required = False
        self.migration_pending = False
        self._lock = threading.RLock()

    def load(self):
        """读取只改内存；启动/NO_SAVE 自测不会隐式迁移或覆盖磁盘。"""
        with self._lock:
            try:
                with self.path.open('r', encoding='utf-8-sig') as stream:
                    raw = json.load(stream)
                if not isinstance(raw, dict):
                    raise ValueError('数据根节点必须是对象')
            except FileNotFoundError:
                self.recovery_required = False
                self.migration_pending = False
                return LoadResult(default_data())
            except (OSError, ValueError, UnicodeError, RecursionError) as error:
                self.recovery_required = True
                self.migration_pending = False
                notice = ('数据文件读取失败（%s），已启用只读保护；原文件未改动，请恢复备份后重新载入。'
                          % type(error).__name__)
                return LoadResult(default_data(), True, (notice,))
            version = raw.get('schema_version', 1)
            if type(version) is not int:
                version = 1
            self.migration_pending = version < SCHEMA_VERSION
            self.recovery_required = False
            data = normalize_data(raw)
            notices = ()
            if self.migration_pending:
                notices = ('旧数据已在内存中迁移到 v%d；首次保存前将轮转备份。' % SCHEMA_VERSION,)
            return LoadResult(data, False, notices, self.migration_pending)

    def backup(self):
        """保存最近三份迁移前备份；失败时保留原数据并报告原因。"""
        with self._lock:
            if not self.path.exists():
                return None
            backup = Path(str(self.path) + '.bak')
            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(prefix='.' + self.path.name + '.backup-',
                                                  suffix='.tmp', dir=self.path.parent)
                os.close(fd)
                shutil.copy2(self.path, temporary)
                for source, destination in ((Path(str(backup) + '.1'), Path(str(backup) + '.2')),
                                            (backup, Path(str(backup) + '.1'))):
                    if source.exists():
                        os.replace(source, destination)
                os.replace(temporary, backup)
                return backup
            except OSError as error:
                raise StorageError('创建数据备份失败：%s' % error) from error
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

    def save(self, data):
        """写入独立临时文件并 fsync，然后原子替换；失败不改变现有数据。"""
        with self._lock:
            if self.recovery_required:
                raise RecoveryRequiredError('数据处于只读保护，自动保存已停止；请先恢复备份。')
            temporary = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix='.' + self.path.name + '.',
                                                  suffix='.tmp', dir=self.path.parent)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=1, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                if self.migration_pending:
                    self.backup()
                os.replace(temporary, self.path)
                self.migration_pending = False
                return True
            except (OSError, TypeError, ValueError) as error:
                if isinstance(error, StorageError):
                    raise
                raise StorageError('保存数据失败：%s' % error) from error
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

    def recover(self, data):
        """仅供用户明确恢复时调用：另存损坏原件，再尝试写入恢复数据。"""
        with self._lock:
            was_protected = self.recovery_required
            try:
                if was_protected and self.path.exists():
                    stamp = time.strftime('%Y%m%d-%H%M%S')
                    archive = Path(str(self.path) + '.corrupt-' + stamp + '-' + uuid.uuid4().hex[:8])
                    shutil.copy2(self.path, archive)
                self.recovery_required = False
                return self.save(data)
            except OSError as error:
                self.recovery_required = was_protected
                if isinstance(error, StorageError):
                    raise
                raise StorageError('恢复数据失败：%s' % error) from error
