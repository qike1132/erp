"""紧急停止窗口内 `op_aborted` 不得越权复位的回归测试（2026-10-16）。

背景：紧急停止打断一个在飞动作时，被取消的 worker 退出时**必然**投
`cancelled → op_aborted`。而清扫仍在后台跑（5 服务各至多 45s + 端口 3 轮
重试，数十秒）。旧实现里 `op_aborted` 分支无条件把 `_mode` 从 'stopping'
复位成 'none'，于是：

  T1 用户点「紧急停止」→ _mode='stopping'，按钮全灰（正确锁死）
  T2 被取消的 worker 上报 op_aborted/op_done → _mode='none'，按钮恢复可点
  T3 用户在清扫还没跑完时看到「启动开发」可点并点了它
     → _start_dual_flow 的 Popen(uvicorn --port 5002) 与清扫线程的
       _kill_port_sync(5002) / nssm start erp-prod 并发互踩

代码注释（app.py stop_all 段、hosting_view.py）明确把「清扫窗口内点启动会与
清扫互踩」列为要消灭的场景，但 op_aborted 这条新入口没被覆盖。

契约：**清扫期间（_stopping_all=True）的过渡态只能由 stop_all_done 复位**。

运行: python -m pytest tests/test_server_manager_stop_all_window.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queue

import server_manager.app as sm


def _make_app():
    """绕过 Tk 构造，仅取无状态逻辑。"""
    return object.__new__(sm.ServerManagerApp)


class _FakeDev:
    """dev 属性替身：_mode 是桥接 property，setter 会写 self.dev.mode。"""

    def __init__(self):
        self.mode = 'none'
        self.process = None
        self.frontend_process = None


class _RecordingUi:
    """记录式假控件：只数调用次数，不碰 Tk。"""

    def __init__(self):
        self.actions_enabled_calls = []
        self.update_all_ui_calls = 0

    def _set_actions_enabled(self, enabled):
        self.actions_enabled_calls.append(enabled)

    def _update_all_ui(self):
        # 纯记录：真实 _update_all_ui 会读 dev/svc 等未初始化属性，
        # 本测试只关心 _mode 的状态转换，不关心渲染。
        self.update_all_ui_calls += 1

    def _refresh_hosting_status(self):
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="server_manager 仅 Windows 可跑")
class TestOpAbortedDuringStopAll:
    """清扫窗口内 op_aborted 不得把过渡态复位。"""

    def test_op_aborted_does_not_reset_mode_during_sweep(self):
        """_stopping_all=True 时，op_aborted 不得把 'stopping' 复位成 'none'。"""
        app = _make_app()
        app._msg_queue = queue.Queue()
        app.dev = _FakeDev()
        app._log_buffer = []
        app._flush_pending = False
        ui = _RecordingUi()

        # 手动接上测试需要的属性（真机上由 __init__ 建，这里绕过 Tk）
        app._mode = 'stopping'
        app._current_mode_key = ''
        app._stopping_all = True
        app._set_actions_enabled = ui._set_actions_enabled
        app._update_all_ui = ui._update_all_ui
        app._refresh_hosting_status = ui._refresh_hosting_status

        # 真实路径：worker 被取消 → 投 op_aborted → 主线程在这里处理
        app._msg_queue.put(('op_aborted', {}))
        app._process_pending_messages()

        assert app._mode == 'stopping', (
            "清扫还在跑，op_aborted 就把 _mode 复位成 'none' —— "
            '按钮立刻恢复可点，用户点「启动」会与清扫线程并发互踩'
        )
        assert app._stopping_all is True

    def test_stop_all_done_resets_mode_after_sweep(self):
        """清扫完成后，stop_all_done 才复位过渡态并放开按钮。"""
        app = _make_app()
        app._msg_queue = queue.Queue()
        app.dev = _FakeDev()
        app._log_buffer = []
        app._flush_pending = False
        ui = _RecordingUi()

        app._mode = 'stopping'
        app._current_mode_key = ''
        app._stopping_all = True
        app._set_actions_enabled = ui._set_actions_enabled
        app._update_all_ui = ui._update_all_ui
        app._refresh_hosting_status = ui._refresh_hosting_status

        # 清扫完成的消息
        app._msg_queue.put(('stop_all_done', {}))
        app._process_pending_messages()

        assert app._mode == 'none', 'stop_all_done 应复位过渡态'
        assert app._stopping_all is False, 'stop_all_done 应清掉全停中标志'
        assert True in ui.actions_enabled_calls, 'stop_all_done 应放开操作按钮'

    def test_op_aborted_resets_mode_when_not_stopping_all(self):
        """非全停场景（普通动作被取消），op_aborted 仍要清过渡态（既有行为）。"""
        app = _make_app()
        app._msg_queue = queue.Queue()
        app.dev = _FakeDev()
        app._log_buffer = []
        app._flush_pending = False
        ui = _RecordingUi()

        app._mode = 'starting'
        app._current_mode_key = 'dev'
        app._stopping_all = False
        app._set_actions_enabled = ui._set_actions_enabled
        app._update_all_ui = ui._update_all_ui
        app._refresh_hosting_status = ui._refresh_hosting_status

        app._msg_queue.put(('op_aborted', {}))
        app._process_pending_messages()

        assert app._mode == 'none', '非全停时 op_aborted 应清掉过渡态（防 UI 卡死）'
        assert app._current_mode_key == ''
