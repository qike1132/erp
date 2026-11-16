"""测试期「运行期证据隔离」自身的守卫（2026-11-16 评审 ocr-s3b4-2）。

拦哪种错：`fastapi_app/tests/evidence_isolation.py` 把死信目录与审计溢出文件重定向到
临时目录，但**没有任何测试引用它** —— 删掉/改名那个 fixture，全量 pytest 依然全绿，
而测试会重新开始往仓库 `logs/`（生产巡检读的那份）写噪音。隔离"半失效"不报错，
正是这个 fixture 的 docstring 自己点名的失败模式。

本文件断言「会话级隔离确实生效」：死信目录不在仓库 `logs/`、审计溢出路径也不在。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_deadletter_dir_is_redirected_out_of_repo_logs():
    from fastapi_app.core.deadletter_path import deadletter_dir

    target = deadletter_dir().resolve()
    repo_logs = (PROJECT_ROOT / 'logs').resolve()
    assert target != repo_logs, (
        '死信仍指向仓库 logs/：测试会往生产巡检读的文件里写噪音'
        '（evidence_isolation 的 autouse fixture 失效了？）'
    )
    assert repo_logs not in target.parents, f'死信目录落在仓库 logs/ 之下: {target}'


def test_audit_overflow_path_is_redirected_out_of_repo_logs():
    from fastapi_app.core import audit_middleware

    overflow = Path(audit_middleware._OVERFLOW_PATH).resolve()
    repo_logs = (PROJECT_ROOT / 'logs').resolve()
    assert repo_logs not in overflow.parents and overflow.parent != repo_logs, (
        f'审计溢出文件仍写在仓库 logs/ 下: {overflow}'
    )
