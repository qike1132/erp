"""`/backup/status` 必须上报备份加密状态（审计批次4：P1-20）。

## 拦哪种出错

前端手动备份硬编码 `encrypt: true`（表达「希望加密」的意图），而
`BACKUP_ENCRYPTION_ENABLED=false` 时后端**静默**忽略它、产出明文包 —— 页面上的密码框
照样在，运维填了密码、看到「备份成功」，就以为拿到的是加密包。反过来「加密开了但
服务端没配密码」时后端会 fail-closed 拒绝，页面也该提前说清楚。

所以状态接口必须把两件事分别说清：
- `encryption_enabled`：总开关（false ⇒ encrypt=true 会被忽略）；
- `encryption_password_configured`：是否有**可用**密码（开关开 + 配了密码才 true）。
"""
from __future__ import annotations

from fastapi_app.services.backup import records


def test_status_reports_encryption_disabled(monkeypatch):
    """开关关闭 + 没有密码 → 两个字段都 False，且原有字段不受影响。"""
    monkeypatch.setattr(records, 'is_encryption_enabled', lambda: False)
    monkeypatch.setattr(records, 'get_backup_encryption_password', lambda: None)

    status = records.get_backup_status()

    assert status['encryption_enabled'] is False
    assert status['encryption_password_configured'] is False
    # 新增字段不能把既有契约挤掉
    assert 'timestamp' in status
    assert 'backup_dir' in status
    assert status['success'] is True


def test_status_reports_encryption_enabled_with_password(monkeypatch):
    """开关开启且配了密码 → 两个字段都 True（前端据此保留密码框并提示留空可用服务端密码）。"""
    monkeypatch.setattr(records, 'is_encryption_enabled', lambda: True)
    monkeypatch.setattr(records, 'get_backup_encryption_password', lambda: 'pw')

    status = records.get_backup_status()

    assert status['encryption_enabled'] is True
    assert status['encryption_password_configured'] is True


def test_status_reports_enabled_but_no_password(monkeypatch):
    """开关开启但没密码 → enabled=True / configured=False（前端要提示补密码，否则后端会拒绝）。"""
    monkeypatch.setattr(records, 'is_encryption_enabled', lambda: True)
    monkeypatch.setattr(records, 'get_backup_encryption_password', lambda: None)

    status = records.get_backup_status()

    assert status['encryption_enabled'] is True
    assert status['encryption_password_configured'] is False


def test_status_schema_exposes_encryption_fields():
    """响应模型必须显式声明这两个字段，否则会被 FastAPI 过滤掉（前端永远读不到）。"""
    from fastapi_app.schemas.backup import BackupStatusOut

    fields = set(BackupStatusOut.model_fields)
    assert 'encryption_enabled' in fields
    assert 'encryption_password_configured' in fields
