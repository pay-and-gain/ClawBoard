"""Lazy startup boundaries for journal recovery and the explicit restore helper."""
import os
from pathlib import Path


def run_restore_mode(arguments, base_dir, *, no_save=False):
    """Return None for normal startup; helper mode never constructs an App."""
    if '--restore-job' not in arguments:
        return None
    if no_save or len(arguments) != 2 or arguments[0] != '--restore-job':
        return 2
    from clawboard.restore_job import run_restore_job
    result = run_restore_job(arguments[1], base_dir)
    return 0 if result.get('status') == 'success' else 1


def recover_before_start(base_dir, *, no_save=False):
    # Optional backup support adds no file writes or heavy archive imports to
    # ordinary startup. An interrupted restore must settle before loading data.
    if no_save or not os.path.lexists(Path(base_dir) / '.clawboard-restore-journal.json'):
        return None
    from clawboard.backups import BackupService
    return BackupService(Path(base_dir) / 'ClawBoard数据.json').recover_pending()


def consume_notice(base_dir, *, no_save=False):
    if no_save or not (Path(base_dir) / '.restore-jobs').is_dir():
        return None
    from clawboard.restore_job import consume_restore_result
    report = consume_restore_result(base_dir)
    if not report:
        return None
    if report.get('operation') == 'merge':
        if report['status'] == 'success':
            def count(key):
                value = report.get(key)
                return value if type(value) is int and 0 <= value <= 10000 else 0
            text = ('已加入 %d 条资料，跳过 %d 条重复内容。\n'
                    '%d 条冲突触发词已停用，请在常用语中检查。'
                    % (count('imported_count'), count('duplicate_count'),
                       count('disabled_trigger_count')))
            backup = report.get('backup_path')
            if isinstance(backup, str) and len(backup) < 4096:
                text += '\n导入前的完整备份：\n' + backup
            return '内容合并导入完成', text, False
        return ('内容合并导入未完成',
                '导入已取消或未完成，当前资料已保留或回退。\n'
                '请重新预览，检查容量、所选文件及目录权限后重试。', True)
    if report['status'] == 'success':
        text = '完整备份已恢复。'
        backup = report.get('backup_path')
        if isinstance(backup, str) and len(backup) < 4096:
            text += '\n恢复前的资料仍保存在：\n' + backup
        return '备份恢复完成', text, False
    if report['status'] == 'cancelled':
        return '备份恢复已取消', '恢复请求已取消，当前资料库未被替换。', True
    return ('备份恢复未完成',
            '恢复未完成，程序已重新启动。请保留当前数据文件夹及恢复前备份，再检查备份包或重试。', True)


def recovery_notice(recovery):
    """A crashed helper may never publish a result, so recovery must be visible."""
    if recovery is None:
        return None
    if recovery.status == 'rolled_back':
        return ('上次恢复已回退',
                '上次恢复被中断，已回到恢复前的资料。\n恢复前备份仍保留在：\n' + str(recovery.backup_path), True)
    if recovery.status == 'committed':
        text = '已完成上次被中断的恢复，资料库可以继续使用。'
        if recovery.cleanup_pending:
            text += '\n恢复的临时文件尚未清理，请检查数据目录的写入权限。'
        return '备份恢复检查完成', text, bool(recovery.cleanup_pending)
    return None
