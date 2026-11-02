"""OCR 上传暂存行的会话归属绑定（Hardening#7，2026-11-02 审计核实修复）。

`POST /ocr-import/upload` 此前把客户端 session_id 原样透传给服务层写入
staging_stock_out——而 staging_stockout 家族的读/确认/清除端点全部按
`u{uid}:{session_id}` 作用域过滤，后果：

1. **孤儿行（功能缺陷）**：OCR 写入的裸 session_id 行对所有 scoped 读端点
   不可见——无法列出、确认、清除；
2. **定向注入（安全）**：攻击者传 `u<受害者uid>:x`，行落入受害者的可读
   命名空间，受害者确认后即成真实出货单。

修复：端点层用 staging 家族的 `_build_scoped_session` 加 `u{uid}:` 前缀。
本文件钉住「服务层收到的必须是 scoped id」接线。变异检查：去掉前缀拼接，
用例变红。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.api.v1.endpoints import ocr_import as endpoint_mod

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def _fake_png(name: str = 'a.png') -> MagicMock:
    f = MagicMock()
    f.filename = name
    f.read = AsyncMock(return_value=_PNG_MAGIC)
    return f


async def test_upload_scopes_session_id_to_current_user(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_import(db, content, session_id, *, filename='', task_id=''):
        captured['session_id'] = session_id
        return (1, 'ok', [])

    monkeypatch.setattr(endpoint_mod.svc, 'import_staging_stockouts_from_file', fake_import)
    monkeypatch.setattr(endpoint_mod.svc, '_update_progress', AsyncMock())
    monkeypatch.setattr(endpoint_mod.svc, 'create_progress', AsyncMock(return_value='t-1'))

    result = await endpoint_mod.upload_shipping_docs(
        files=[_fake_png()],
        session_id='batch-abc',
        task_id='t-1',
        db=AsyncMock(),
        current_user=SimpleNamespace(id=7),
    )

    assert result.total_imported == 1
    # 关键断言：服务层必须收到带 u{uid}: 归属前缀的 scoped id
    assert captured['session_id'] == 'u7:batch-abc', (
        f"OCR 上传必须把 session_id 规范为 u{{uid}}: 归属作用域，"
        f"实际收到 {captured['session_id']!r}"
    )


async def test_upload_malicious_prefix_cannot_reach_victim_namespace(monkeypatch) -> None:
    """攻击者自带 u<受害者>: 前缀时，叠加自己的 scope 后不会落入受害者命名空间。"""
    captured: dict[str, object] = {}

    async def fake_import(db, content, session_id, *, filename='', task_id=''):
        captured['session_id'] = session_id
        return (1, 'ok', [])

    monkeypatch.setattr(endpoint_mod.svc, 'import_staging_stockouts_from_file', fake_import)
    monkeypatch.setattr(endpoint_mod.svc, '_update_progress', AsyncMock())
    monkeypatch.setattr(endpoint_mod.svc, 'create_progress', AsyncMock(return_value='t-1'))

    await endpoint_mod.upload_shipping_docs(
        files=[_fake_png()],
        session_id='u9:evil',  # 试图冒充 uid=9 的作用域
        task_id='t-1',
        db=AsyncMock(),
        current_user=SimpleNamespace(id=7),
    )

    scoped = str(captured['session_id'])
    assert scoped == 'u7:u9:evil', '恶意前缀应被叠加而非透传'
    assert not scoped.startswith('u9:'), '绝不能落入受害者 u9 的命名空间'
