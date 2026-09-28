"""server_manager v5.33 状态判定回归测试（纯函数，无 Tk 实例）。

背景：H1 三态语义修复（2026-09-23）—— 旧实现把 `sc query` 任何非 0 返回码
（含 5=拒绝访问、超时、被安全软件拦截）一律判「未安装」，导致
_ensure_production_stopped 会静默跳过仍在运行的生产服务，开发模式随即抢占
5002/3000 与生产互杀。本文件锁定三态语义防线，防止回退。

运行: python -m pytest tests/test_server_manager_v533_state.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_manager.app as sm  # (模块级代码无 Tk root, 导入安全;2026-09-28 包化)


def _make_ops():
    """绕过 Tk 构造;三态判定逻辑已迁 ServiceOps(T4 包化),直接取该层。"""
    return object.__new__(sm.ServiceOps)


def _svc_state_for(code, out):
    ops = _make_ops()
    # svc_state 只依赖 self.run_capture，直接以实例属性覆盖（实例属性优先于类方法）
    ops.run_capture = lambda args, timeout=20: (code, out)
    return ops.svc_state('erp-prod')


class TestSvcStateTristate:
    """H1 回归：'未安装' 只认 rc==1060 或无 STATE 行的 1060 错误文本。"""

    def test_running_with_pid_1060_must_not_be_absent(self):
        # 旧版 `code != 0 or 'SERVICE_NAME' not in out` 之外的 bug 变体：
        # 输出含 PID=1060 的运行中服务，绝不能因 '1060' in out 误判「未安装」。
        out = 'SERVICE_NAME: erp-prod\nSTATE              : 4  RUNNING\nPID                : 1060\n'
        assert _svc_state_for(0, out).endswith('RUNNING')

    def test_running_normal(self):
        out = 'SERVICE_NAME: erp-prod\nSTATE              : 4  RUNNING\nPID                : 17044\n'
        assert _svc_state_for(0, out).endswith('RUNNING')

    def test_stopped(self):
        out = 'SERVICE_NAME: erp-prod\nSTATE              : 1  STOPPED\n'
        assert _svc_state_for(0, out).endswith('STOPPED')

    def test_rc1060_is_absent(self):
        assert _svc_state_for(1060, '[SC] EnumQueryServicesStatus:指定的服务未安装。') == '未安装'

    def test_error_text_1060_without_state_is_absent(self):
        # rc 不透传的极端场景: 输出含 1060 但没有 STATE 行 → 仍可判未安装(兜底保留)
        assert _svc_state_for(1, 'OpenService 失败 1060:') == '未安装'

    def test_access_denied_is_unknown(self):
        # ★ H1 核心: rc=5 拒绝访问绝不判「未安装」，否则跳过停止运行中的生产服务
        assert _svc_state_for(5, '拒绝访问。') == '未知'

    def test_nonzero_without_service_name_is_unknown(self):
        assert _svc_state_for(2, '') == '未知'

    def test_ok_without_state_is_unknown(self):
        assert _svc_state_for(0, 'SERVICE_NAME: erp-prod\n') == '未知'

    def test_subprocess_exception_is_unknown(self):
        # _run_capture 异常路径返回 (-1, str(e))，必须落「未知」而非「未安装」
        assert _svc_state_for(-1, 'sc 被拦截') == '未知'
