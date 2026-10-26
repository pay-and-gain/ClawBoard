"""Owner-thread recycling actions; persistence and media GC remain controller-owned."""
from clawboard.trash import TrashError


class RecycleMixin:
    def _recycle_writable(self):
        if self.application.store.recovery_required:
            self.tip('资料处于只读保护，请先恢复完整备份')
            return False
        return True

    def _recycle_move(self, ids, group=None):
        if not self._recycle_writable():
            return False
        try:
            self.application.trash.move(ids, group=group)
        except TrashError as error:
            self.tip(str(error))
            return False
        return True

    def _recycle_changed(self, removed=()):
        self._purge_image_files(removed)
        history = self.application.history
        history.sequence = max(history.sequence,
            max((int(item.get('seq') or 0) for item in self.data['clip']), default=0))
        if hasattr(self, '_trigger_engine'):
            self._refresh_triggers()
        self.save(True)
        self.render()

    def recycle_restore(self, ids):
        if not self._recycle_writable():
            raise TrashError('资料处于只读保护，不能恢复')
        result = self.application.trash.restore(ids)
        if result:
            self._recycle_changed()
        return result

    def recycle_purge(self, ids=None):
        if not self._recycle_writable():
            raise TrashError('资料处于只读保护，不能永久删除')
        removed = self.application.trash.purge(ids)
        if removed:
            self._recycle_changed(removed)
        return removed

    def recycle_expire(self):
        if not self._recycle_writable():
            raise TrashError('资料处于只读保护，不能清理到期条目')
        removed = self.application.trash.expire()
        if removed:
            self._recycle_changed(removed)
        return removed
