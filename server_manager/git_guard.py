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
# 脏工作区覆盖开关（与分支覆盖分开：两者的风险面不同，运维通常只需临时放行其一）
DIRTY_OVERRIDE_ENV = 'ERP_ALLOW_DIRTY'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 「放行但需警告」的消息前缀（2026-10-18 OCR 复评：调用方不再靠嗅探中文字串）
WARNING_PREFIX = '警告：'


def is_warning(message: str) -> bool:
    """放行消息是否需要按 WARNING 级别展示（工作区脏 / override / 非 git 目录）。"""
    return message.startswith(WARNING_PREFIX) or '覆盖' in message


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
    # 若 HEAD 与 main 同一提交（CI/发布 checkout 常见），按 main 放行；
    # 否则仍拒绝（无法确定运行的是哪条线的代码）。
    # 2026-10-24 修复：main 引用按候选列表解析——本机远端名是 erp（AGENTS §4），
    # 原先写死 refs/remotes/origin/main 在本机永远不存在，导致按 SHA checkout 时
    # 即使 HEAD 就是 main 顶点也被拒。
    if branch == 'HEAD':
        c_head, head_sha, _ = _git(['rev-parse', 'HEAD'], base)
        main_sha = None
        for ref in ('refs/remotes/origin/main', 'refs/remotes/erp/main', 'refs/heads/main'):
            c_ref, ref_sha, _ = _git(['rev-parse', ref], base)
            if c_ref == 0 and ref_sha:
                main_sha = ref_sha
                break
        if c_head == 0 and main_sha and head_sha == main_sha:
            # 2026-10-18 OCR 评审：必须把 branch 归一成真正的允许值，
            # 否则后续 `branch not in ALLOWED_BRANCHES` 会立刻拒绝。
            branch = 'main'
        else:
            _, head_short, _ = _git(['rev-parse', '--short', 'HEAD'], base)
            return False, (
                f'当前处于 detached HEAD（HEAD {head_short}）且不指向 main，'
                f'生产启停只允许 main。请切回 main；确需用该提交请设置 {OVERRIDE_ENV}=1'
            )

    if branch not in ALLOWED_BRANCHES:
        _, head, _ = _git(['rev-parse', '--short', 'HEAD'], base)
        return False, (
            f'当前分支为 {branch}（HEAD {head}），生产启停只允许 main。'
            f'请切回 main 后重试；确需用该分支代码请设置 {OVERRIDE_ENV}=1'
        )

    # 2026-10-24（P1）：脏工作区必须阻断，不能只告警。
    # 生产直接吃工作区源码，2026-10-22 事故即「一个文件改了 import 而提供者未提交」，
    # 撤销链路 ImportError 连崩 8 次、采购单静默未撤销。AGENTS §6.1-9 要求
    # `git status --porcelain` 为空；本闸门此前只把「分支必须 main」机器化。
    code, status, status_err = _git(['status', '--porcelain'], base)
    if code != 0:
        # 查不出来按不可放行处理（并发提交的 index.lock 窗口也会走到这里）
        return False, (
            f'无法读取工作区状态（{status_err or "git status 失败"}），按不可放行处理。'
            f'确需继续请设置 {DIRTY_OVERRIDE_ENV}=1'
        )
    if status:
        if os.environ.get(DIRTY_OVERRIDE_ENV) == '1':
            return True, f'警告：工作区有未提交改动，已被 {DIRTY_OVERRIDE_ENV}=1 放行'
        changed = [ln for ln in status.splitlines() if ln.strip()][:5]
        return False, (
            '工作区有未提交改动，生产将加载半改代码（AGENTS §6.1-9）。'
            f'请先提交或 stash；确需继续请设置 {DIRTY_OVERRIDE_ENV}=1。改动示例：{changed}'
        )

    return True, f'分支校验通过（{branch}）'
