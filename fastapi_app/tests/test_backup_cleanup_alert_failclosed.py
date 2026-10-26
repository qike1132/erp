"""M2 / M3 / M4 回归锁：清理扫描、告警冷却、Webhook 日志。

M2 清理扫描 unknown
    扫描失败返回空列表 → 调用方看到「没有备份文件」并报 success=True。权限、
    挂载、IO 故障与「本来就没备份」因此给出同一个绿灯。
M3 告警冷却
    只要 notify=True 就写 last_alert_times —— 渠道全未启用或投递失败也进入冷却，
    下一条真实告警被自己的冷却窗口吞掉。
M4 Webhook 回显
    失败响应正文整段进日志：接收端回显的载荷/令牌被复制到 logs/。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from fastapi_app.services.backup.cleanup import service as cleanup_service
from fastapi_app.services.backup.metrics.alert_service import BackupAlertService


# ---------------------------------------------------------------------------
# M2：扫描失败 != 没有备份
# ---------------------------------------------------------------------------
class _FakeBackupPath:
    """只实现扫描用到的接口；可让 stat() 抛 OSError 模拟不可读文件。"""

    def __init__(self, name: str, *, stat_error: bool = False, age_days: float = 30.0):
        self.name = name
        self._stat_error = stat_error
        self._mtime = time.time() - age_days * 86400
        self.parent = self

    def __truediv__(self, _other):
        return SimpleNamespace(exists=lambda: False)

    def is_file(self) -> bool:
        return True

    def stat(self):
        if self._stat_error:
            raise PermissionError('access denied')
        return SimpleNamespace(st_size=1024, st_mtime=self._mtime)


@pytest.mark.asyncio
async def test_scan_failure_is_not_reported_as_no_backups(monkeypatch):
    svc = cleanup_service.BackupCleanupService()
    monkeypatch.setattr(type(svc), '_check_disk_space', _async_return({}))

    class _Dir:
        def iterdir(self):
            raise PermissionError('access denied')

        def mkdir(self, **_kw):
            raise PermissionError('access denied')

    monkeypatch.setattr(cleanup_service, 'BACKUP_DIR', _Dir())
    alerts = []

    async def _fake_alert(**kwargs):
        alerts.append(kwargs)
        return True

    monkeypatch.setattr(cleanup_service.alert_service, 'send_alert', _fake_alert)

    result = await svc.smart_cleanup()

    assert result['success'] is False, '扫描失败绝不能报 success=True（会被当成干净结果）'
    assert '扫描失败' in result['message']
    assert alerts and alerts[0]['task_name'] == 'smart_cleanup', '必须告警，不能只返回给调用方'


@pytest.mark.asyncio
async def test_unreadable_file_is_surfaced_in_report(monkeypatch):
    svc = cleanup_service.BackupCleanupService()
    good = _FakeBackupPath('erp_backup_good.zip', age_days=1)
    bad = _FakeBackupPath('erp_backup_bad.zip', stat_error=True)

    class _Dir:
        def iterdir(self):
            return [good, bad]

        def mkdir(self, **_kw):
            return None

    monkeypatch.setattr(cleanup_service, 'BACKUP_DIR', _Dir())
    monkeypatch.setattr(type(svc), '_check_disk_space', _async_return({}))
    monkeypatch.setattr(type(svc), '_execute_cleanup', _async_return(
        {'deleted_count': 0, 'errors': [], 'deleted_files': [], 'freed_mb': 0}))

    async def _report(*_a, **_k):
        return {'success': True, 'cleaned_files': [], 'kept_files': []}

    monkeypatch.setattr(type(svc), '_generate_cleanup_report', _report)

    result = await svc.smart_cleanup()

    assert result['success'] is True
    assert result['unreadable_files'] == [
        {'name': 'erp_backup_bad.zip', 'error': 'PermissionError'}
    ], '读不懂的备份文件必须出现在报告里（它们永远不会过期）'


def _async_return(value):
    async def _fn(*_a, **_k):
        return value
    return _fn


# ---------------------------------------------------------------------------
# M3：冷却只在真的投递成功后生效
# ---------------------------------------------------------------------------
def _alert_service(monkeypatch, *, email=False, webhook=True):
    svc = BackupAlertService()
    svc.alert_config.update({
        'email_enabled': email, 'webhook_enabled': webhook,
        'failure_threshold': 1, 'alert_cooldown_minutes': 30,
    })
    svc.failure_counts['backup'] = {'error': 5, 'critical': 0, 'last_failure_time': None}
    return svc


@pytest.mark.asyncio
async def test_no_cooldown_when_no_channel_enabled(monkeypatch):
    svc = _alert_service(monkeypatch, email=False, webhook=False)

    assert await svc.send_alert('backup', 'boom', task_type='backup') is True
    assert 'backup' not in svc.last_alert_times, '没有任何渠道实际投递，不得进入冷却'


@pytest.mark.asyncio
async def test_no_cooldown_when_delivery_fails(monkeypatch):
    svc = _alert_service(monkeypatch)

    async def _fail(_data):
        return False

    monkeypatch.setattr(svc, '_send_webhook_alert', _fail)

    assert await svc.send_alert('backup', 'boom', task_type='backup') is False
    assert 'backup' not in svc.last_alert_times, '投递失败不进入冷却，否则下一条告警被吞'


@pytest.mark.asyncio
async def test_cooldown_entered_after_successful_delivery(monkeypatch):
    svc = _alert_service(monkeypatch)

    async def _ok(_data):
        return True

    monkeypatch.setattr(svc, '_send_webhook_alert', _ok)

    assert await svc.send_alert('backup', 'boom', task_type='backup') is True
    assert 'backup' in svc.last_alert_times

    # 冷却期内第二次不再投递（原有语义不变）
    calls = []

    async def _count(_data):
        calls.append(1)
        return True

    monkeypatch.setattr(svc, '_send_webhook_alert', _count)
    await svc.send_alert('backup', 'boom again', task_type='backup')
    assert calls == [], '冷却期内不应重复投递'


# ---------------------------------------------------------------------------
# M4：Webhook 失败日志不回显正文
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_webhook_failure_log_does_not_echo_body(monkeypatch, caplog):
    svc = BackupAlertService()
    svc.alert_config['webhook_url'] = 'https://example.invalid/hook'

    class _Resp:
        status_code = 500
        text = 'secret-token=abcdef&echo=payload'

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *_a, **_k):
            return _Resp()

    monkeypatch.setattr('httpx.AsyncClient', lambda *a, **k: _Client())

    with caplog.at_level('ERROR'):
        ok = await svc._send_webhook_alert({'task_name': 'backup'})

    assert ok is False
    log_text = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'secret-token' not in log_text, '不得把响应正文（可能含令牌）写进日志'
    assert 'status=500' in log_text and 'body_len' in log_text
