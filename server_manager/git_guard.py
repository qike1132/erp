"""生产启停前的 git 分支闸门（2026-10-17 审计 AUD-28）。

背景：NSSM 五服务的 AppDirectory 固定为仓库根目录，重启 = 把工作区**当前签出**
的代码跑进生产。2026-10-14 工作区停在 ``claude/*`` 分支期间重启后端，生产 API
返回旧字段 ``order_nos``，前端「订单号」列空白 75 分钟（AGENTS.md §6.1-6 在案）。

本模块把「重启前先看分支」这条人防规则机器化：非 ``main`` 分支拒绝启动/重启。
紧急情况可显式设置 ``ERP_ALLOW_NON_MAIN=1`` 放行（等同声明「我知道我在做什么」）。
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_BRANCHES = frozenset({'main'})
OVERRIDE_ENV = 'ERP_ALLOW_NON_MAIN'
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """执行只读 git 命令，返回 (exitcode, stdout, stderr)；异常不外抛。"""
    try:
        proc = subprocess.run(
            ['git', *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return proc.returncode, (proc.stdout or '').strip(), (proc.stderr or '').strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, '', str(exc)


def check_production_branch(root: Path | str | None = None) -> tuple[bool, str]:
    """检查生产启停是否允许执行。

    Returns:
        (True, message) 允许；message 可能是警告（dirty / override / 非 git 目录）。
        (False, message) 拒绝；message 含当前分支与覆盖方法。
    """
    base = Path(root) if root is not None else PROJECT_ROOT

    code, branch, err = _git(['rev-parse', '--abbrev-ref', 'HEAD'], base)
    if code != 0:
        # 非 git 检出（打包部署）不应被闸门打死；但必须留痕
        msg = f'警告：无法确定 git 分支（{err or "git 不可用"}），已放行'
        logger.warning(msg)
        return True, msg

    if os.environ.get(OVERRIDE_ENV) == '1':
        return True, f'分支闸门已被 {OVERRIDE_ENV}=1 覆盖，当前分支 {branch}'

    # 2026-10-18 OCR 评审：detached HEAD 时 abbrev-ref 返回字面量 'HEAD'。
    # 若 HEAD 与 origin/main 同一提交（CI/发布 checkout 常见），按 main 放行；
    # 否则仍拒绝（无法确定运行的是哪条线的代码）。
    if branch == 'HEAD':
        c_head, head_sha, _ = _git(['rev-parse', 'HEAD'], base)
        c_main, main_sha, _ = _git(['rev-parse', 'refs/remotes/origin/main'], base)
        if c_head == 0 and c_main == 0 and head_sha and head_sha == main_sha:
            branch = 'main (detached at origin/main)'
        else:
            _, head_short, _ = _git(['rev-parse', '--short', 'HEAD'], base)
            return False, (
                f'当前处于 detached HEAD（HEAD {head_short}）且不指向 origin/main，'
                f'生产启停只允许 main。请切回 main；确需用该提交请设置 {OVERRIDE_ENV}=1'
            )

    if branch not in ALLOWED_BRANCHES:
        _, head, _ = _git(['rev-parse', '--short', 'HEAD'], base)
        return False, (
            f'当前分支为 {branch}（HEAD {head}），生产启停只允许 main。'
            f'请切回 main 后重试；确需用该分支代码请设置 {OVERRIDE_ENV}=1'
        )

    code, status, _ = _git(['status', '--porcelain'], base)
    if code == 0 and status:
        return True, '警告：工作区有未提交改动，生产将加载工作区当前源码'

    return True, f'分支校验通过（{branch}）'
