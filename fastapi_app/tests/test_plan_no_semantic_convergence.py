"""_generate_plan_no 语义收敛测试（2026-10-11 复核 P2-13）。

此前 _generate_plan_no 是独立重写（自建 seed 会话 + 手拼 f-string），与
numbering.generate_number_async 行为等价但双真值。收敛后它必须真的走
generate_number_async 内核（PP 前缀 + PurchasePlan.plan_no + 传入的 db）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi_app.services import purchase_plan_common
from fastapi_app.shared_models import PurchasePlan


async def test_generate_plan_no_delegates_to_numbering_kernel() -> None:
    fake_kernel = AsyncMock(return_value="PP-20261011-0007")
    with patch(
        "fastapi_app.services.numbering.generate_number_async", fake_kernel
    ), patch(
        "fastapi_app.core.database.require_async_session_local"
    ) as fake_factory:
        fake_factory.return_value.__aenter__ = AsyncMock(return_value=object())
        fake_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        no = await purchase_plan_common._generate_plan_no()
    assert no == "PP-20261011-0007"
    fake_kernel.assert_awaited_once()
    args = fake_kernel.await_args.args
    assert args[0] == "PP"
    assert args[1] is PurchasePlan
    assert args[2] == "plan_no"
