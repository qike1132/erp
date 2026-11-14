"""NSSM 服务安装后的注册表回读校验（P0-6 / 评审 H11）。

为什么单独成文件：``server_manager/app.py`` 顶着 1600 行的规模门禁
（``tests/test_gates_cover_repo_root.py::test_file_size_gate_package_file_within_limit``），
而这段逻辑与 Tk 界面零耦合 —— 输入是注册表，输出是问题清单。

★ 为什么必须有这个校验：2026-09-16 的部署漂移事故 —— 源码已修，线上服务却跑旧版
约 10 小时无人发现，因为「安装成功」只证明命令返回 0，不证明**下次启动**会加载哪份代码。

⚠️ **必须读 ``Parameters\\Application``，不能读顶层 ``ImagePath``**：
``ImagePath`` 永远是 ``C:\\nssm\\nssm.exe``（NSSM 自己是宿主进程），真正被拉起的
解释器存在 ``<service>\\Parameters\\Application``。实测（本机真实注册表）只看
``ImagePath`` 会对 erp-prod / erp-arq 双双误报「解释器不一致」—— 校验器自己成了噪声源。

H11（评审）：除 Application/AppDirectory，还要回读 AppParameters、
AppEnvironmentExtra、AppExit —— 只写了一半的配置同样是「装了但不可用」。
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Protocol

#: 需要回读的 ``Parameters`` 子键（键缺失 = 该配置项没写过）
PARAM_FIELDS: tuple[str, ...] = (
    'Application',
    'AppParameters',
    'AppDirectory',
    'AppEnvironmentExtra',
    'AppExit',
)

LogFn = Callable[..., None]


class _WinReg(Protocol):  # pragma: no cover - 仅用于类型标注
    HKEY_LOCAL_MACHINE: object
    KEY_READ: int

    def OpenKey(self, key, sub_key: str, reserved: int = 0, access: int = 0): ...  # noqa: N802
    def QueryValueEx(self, key, value_name: str): ...  # noqa: N802


def read_nssm_params(name: str, winreg: _WinReg) -> dict[str, object]:
    """回读一条 NSSM 服务的 ``Parameters`` 子树（缺失项不写入 = 未配置）。"""
    values: dict[str, object] = {}
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        rf'SYSTEM\CurrentControlSet\Services\{name}',
        0,
        winreg.KEY_READ,
    ) as key:
        with winreg.OpenKey(key, 'Parameters', 0, winreg.KEY_READ) as pk:
            for field_name in PARAM_FIELDS:
                with contextlib.suppress(OSError):
                    values[field_name] = winreg.QueryValueEx(pk, field_name)[0]
    return values


def nssm_param_problems(
    values: Mapping[str, object],
    *,
    expected_app: str,
    expected_dir: str,
    expected_token: str | None,
    expected_env: list[str] | None,
) -> list[str]:
    """把一条服务的回读值与期望值比对，返回问题清单（空列表 = 一致）。"""
    problems: list[str] = []
    actual_app = values.get('Application')
    actual_params = values.get('AppParameters')
    actual_dir = values.get('AppDirectory')
    actual_env = values.get('AppEnvironmentExtra')
    actual_exit = values.get('AppExit')

    if not actual_app:
        problems.append(r'Parameters\Application 缺失（服务未正确配置）')
    elif expected_app.lower() not in str(actual_app).lower():
        problems.append(f'解释器={actual_app} 期望含 {expected_app}')

    if actual_dir and str(actual_dir).lower() != expected_dir.lower():
        problems.append(f'工作目录={actual_dir} 期望 {expected_dir}')

    if expected_token and expected_token not in str(actual_params or ''):
        problems.append(f'启动参数={actual_params or "(空)"} 期望含 {expected_token}')

    exit_text = (
        ' '.join(str(v) for v in actual_exit)
        if isinstance(actual_exit, (list, tuple))
        else str(actual_exit or '')
    )
    if 'restart' not in exit_text.lower():
        problems.append(f'AppExit={exit_text or "(空)"} 期望含 Restart（崩溃自动重启）')

    if expected_env:
        env_text = (
            '\n'.join(str(v) for v in actual_env)
            if isinstance(actual_env, (list, tuple))
            else str(actual_env or '')
        )
        missing_env = [item for item in expected_env if item not in env_text]
        if missing_env:
            problems.append(f'环境变量缺失: {", ".join(missing_env)}')

    return problems


def verify_installed_services(
    *,
    names: Iterable[str],
    expected_tokens: Mapping[str, str | None],
    python_exe: str,
    project_dir: str,
    log: LogFn,
    expected_env: list[str] | None = None,
    winreg: _WinReg | None = None,
) -> list[str]:
    """逐条回读并比对，返回问题清单（空列表 = 全部一致）。

    调用方负责平台判定（非 Windows 直接跳过）与解释器可用性检查，并把
    ``log(message, level)`` 传进来 —— 本模块不依赖 Tk、不依赖全局状态。
    """
    if winreg is None:
        try:
            import winreg as _winreg  # type: ignore[no-redef]
        except ImportError:
            log('无法校验服务指向（winreg 不可用），请手工核对服务参数', 'WARNING')
            return []
        winreg = _winreg  # type: ignore[assignment]

    all_problems: list[str] = []
    for name in names:
        try:
            values = read_nssm_params(name, winreg)
        except OSError as e:
            problem = f'{name} 指向校验失败（读注册表出错）: {e}'
            log(problem, 'WARNING')
            all_problems.append(problem)
            continue

        problems = nssm_param_problems(
            values,
            expected_app=python_exe,
            expected_dir=project_dir,
            expected_token=expected_tokens.get(name),
            expected_env=expected_env,
        )
        if problems:
            message = f'{name} 安装后校验不一致，服务可能加载非当前源码/配置：' + '；'.join(problems)
            log(message, 'WARNING')
            all_problems.append(message)
        else:
            actual_app = str(values.get('Application') or '')
            log(
                f'{name} 配置校验通过（app={Path(actual_app).name if actual_app else "?"}，'
                f'params={str(values.get("AppParameters") or "")[:80]}）',
            )
    return all_problems
