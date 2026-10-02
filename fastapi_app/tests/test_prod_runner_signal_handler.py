"""prod_runner 控制台处理器回调的存活（回归：孤儿后端进程树，2026-10-02）。

背景：`_install_signal_handlers` 曾把 ctypes 回调只赋给**局部变量**。ctypes 回调失去引用
即被回收，而 `SetConsoleCtrlHandler` 只保存函数指针 —— 处理器随即悬空，Ctrl+C 到达时
`sup.shutdown()` 不执行，uvicorn 子进程无人回收，成为继续占用 :5002 的孤儿。

实测症状：`logs/erp-prod.log` 里「已启动」35 次、「正在关闭」/「已停止」各 0 次；
每次 `nssm restart erp-prod` 都留下一棵旧后端进程树，同一端口上堆着两台后端。

断言的是**引用生命周期**，不是行为 —— 所以用 weakref + gc 来锁，光调用一次是测不出来的。
"""
import gc
import os
import weakref
from unittest.mock import MagicMock

import pytest

from fastapi_app.core import prod_runner as pr

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows 控制台处理器专用')


def test_console_handler_callback_survives_gc():
    """回调必须由模块级持有：GC 后仍存活。"""
    sup = MagicMock()

    pr._install_signal_handlers(sup)

    assert pr._console_handler_ref is not None, '回调没有被模块级变量持有'
    probe = weakref.ref(pr._console_handler_ref)
    for _ in range(3):
        gc.collect()
    assert probe() is not None, '回调被 GC 回收 —— 注册的处理器会变成悬空指针'


def test_installed_handler_can_still_invoke_shutdown():
    """装上并 GC 之后，回调仍能被调用（即 Windows 派发 Ctrl+C 时 shutdown 会执行）。"""
    sup = MagicMock()
    pr._install_signal_handlers(sup)
    gc.collect()

    # 直接触发回调，等价于内核派发 CTRL_C_EVENT（ctrl_type=0）
    pr._console_handler_ref(0)

    sup.shutdown.assert_called_once()
