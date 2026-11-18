"""运维脚本的危险动作必须有闸门，且顺序正确（2026-10-17 审计 P1-25/27/28）。

为什么用「源码行号顺序」而不是跑脚本：
这三个脚本都直接动生产（删库、重启后端、覆盖部署目录），没有沙箱可跑 ——
本机既是生产机也是运维机（AGENTS §0）。所以守卫只能盯「危险动作之前有没有
那道闸门、顺序对不对」。这是源码级断言，不是行为测试，注释里都写清了。

覆盖：
  · P1-25 `deploy/install_package.ps1` —— DROP DATABASE 必须在停服务之后；
  · P1-28 同一文件 —— robocopy 之前必须先清掉旧的代码/产物目录，
    否则 /E 只覆盖同名文件，升级即得到「新旧混合代码树」；
  · P1-27 `scripts/restart_erp_prod.bat` —— nssm restart 之前必须有
    「分支是 main」+「工作区干净」两道闸门（erp-prod 吃工作区源码）。
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / 'deploy' / 'install_package.ps1'
RESTART_BAT = PROJECT_ROOT / 'scripts' / 'restart_erp_prod.bat'


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding='utf-8', errors='replace').splitlines()


def _first_line_matching(lines: list[str], pattern: str) -> int:
    """返回第一个匹配的行号（1-based）；找不到返回 -1。

    跳过整行注释（`#` / `REM`），否则「注释里提到 DROP DATABASE」会让顺序断言失真。
    """
    rx = re.compile(pattern)
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.upper().startswith('REM'):
            continue
        if rx.search(line):
            return i
    return -1


def test_files_exist() -> None:
    """守卫对象必须存在 —— 改名不能让下面的断言静默空转。"""
    for p in (INSTALLER, RESTART_BAT):
        assert p.is_file(), f'守卫对象不存在（改名/挪走后请同步本文件）：{p}'


def test_installer_drops_database_after_stopping_service() -> None:
    """P1-25：DROP DATABASE 必须在 Stop-Service 之后。

    原实现把删库放在停服务之前：DROP 的那一瞬间五个 NSSM 服务仍 RUNNING 并
    持有连接，DROP 要么直接失败，要么在「强制断开」的成功路径上留下一堆
    半个状态的进程。
    """
    lines = _lines(INSTALLER)
    stop = _first_line_matching(lines, r'Stop-Service')
    drop = _first_line_matching(lines, r'DROP\s+DATABASE')
    assert stop > 0, '没找到 Stop-Service —— 停服务这一步可能被删了'
    assert drop > 0, '没找到 DROP DATABASE'
    assert stop < drop, (
        f'DROP DATABASE(L{drop}) 早于 Stop-Service(L{stop}) —— 删库瞬间服务仍在跑'
    )


def test_installer_clears_stale_code_before_robocopy() -> None:
    """P1-28：代码复制段的 robocopy 之前必须先删旧目录，否则新旧混合代码树。

    robocopy /E 只覆盖同名文件、不删目标里多出来的旧文件。
    注意本文件里**还有其它 robocopy**（nginx 静态资源在更早的步骤），
    所以基准不是「第一个 robocopy」而是「`$copies` 之后的第一个 robocopy」。
    """
    lines = _lines(INSTALLER)
    copies_at = _first_line_matching(lines, r'^\s*\$copies\s*=')
    assert copies_at > 0, '没找到 $copies 定义 —— 部署步骤结构已变'
    first_robocopy = _first_line_matching(lines[copies_at:], r'^\s*robocopy\s')
    assert first_robocopy > 0, '$copies 之后没找到 robocopy'
    first_robocopy += copies_at          # 换算回全文行号

    before = '\n'.join(
        ln for ln in lines[copies_at: first_robocopy - 1]
        if not ln.strip().startswith('#')
    )
    # 「配置了」与「真的会执行」必须同时成立 —— 只断言出现 Remove-Item 是不够的：
    # 把 `if($c.PurgeCode){` 改成 `if($false){` 时源码里仍有 Remove-Item，
    # 但清目录再也不会发生（变异检查实测这一版会漏）。
    assert re.search(r"PurgeCode\s*=\s*\$true", before), (
        '`app` 那条没有标 PurgeCode=$true —— 代码树不会在 robocopy 前被清理，'
        '/E 会把旧 .py 留在目标目录（P1-28）'
    )
    assert re.search(r"PurgeWhole\s*=\s*\$true", before), (
        'runtime / frontend\\dist 没有标 PurgeWhole=$true —— 纯产物目录里的旧文件'
        '（旧 chunk、旧 exe）会与新文件混在一起'
    )
    assert re.search(r"if\s*\(\s*\$c\.PurgeCode\s*\)", before), (
        '标记了 PurgeCode 但没有对应的 `if($c.PurgeCode){...}` 实现 —— 配置与实现脱节'
    )
    assert re.search(r"if\s*\(\s*\$c\.PurgeWhole\b", before), (
        '标记了 PurgeWhole 但没有对应的 `if($c.PurgeWhole...){...}` 实现'
    )
    assert 'Remove-Item' in before, (
        f'代码复制段的第一个 robocopy(L{first_robocopy}) 之前没有删除动作 —— '
        '/E 会把旧文件留在目标目录，升级即产生新旧混合代码树（P1-28）'
    )
    # 必须显式排除运行期目录，否则「清代码」会顺手删掉 logs/backups/.env
    assert re.search(r'runtimeDirNames|runtimeKeep', before), (
        '清目录逻辑没有区分「代码目录」与「运行期目录」—— 直接清空安装根会删掉 '
        'logs/、backups/、.env 与 static/uploads。'
    )


def test_installer_never_purges_whole_target_root() -> None:
    """防回归：不得对安装根加 /PURGE（那会删运行期数据）。

    只看**可执行行**：注释里讨论「为什么不用 /PURGE」是必要的说明，
    不能因此让守卫红。
    """
    code_lines = [
        ln for ln in _lines(INSTALLER)
        if not ln.strip().startswith('#')
    ]
    offenders = [ln.strip() for ln in code_lines if '/PURGE' in ln]
    assert not offenders, (
        'install_package.ps1 的可执行行里出现了 /PURGE —— 安装根同时是运行期数据目录'
        '（logs/backups/.env/static/uploads），/PURGE 会把它们删掉：\n  '
        + '\n  '.join(offenders)
    )


def test_restart_bat_gates_before_nssm_restart() -> None:
    """P1-27：nssm restart 之前必须有「分支=main」与「工作区干净」两道闸门。

    erp-prod 跑的是 `python -m fastapi_app.core.prod_runner`，直接吃
    D:\\erp_system 工作区源码 —— 不是打包产物、不是固定 commit。工作区在别的
    分支或有未提交改动时重启，就把那条分支/半改代码跑进了生产（AGENTS §6.1-6/9）。
    """
    lines = _lines(RESTART_BAT)
    nssm = _first_line_matching(lines, r'nssm\.exe\s+restart')
    branch_gate = _first_line_matching(lines, r'rev-parse\s+--abbrev-ref\s+HEAD')
    dirty_gate = _first_line_matching(lines, r'git\s+status\s+--porcelain')

    assert nssm > 0, '没找到 nssm restart'
    assert branch_gate > 0, (
        'restart_erp_prod.bat 里没有分支闸门 —— 在别的分支上重启就会把那条分支'
        '的代码跑进生产（AGENTS §6.1-6）'
    )
    assert dirty_gate > 0, (
        'restart_erp_prod.bat 里没有脏工作区闸门 —— 未提交的半改代码同样会进生产'
        '（AGENTS §6.1-9，2026-10-22 因此连崩 8 次）'
    )
    assert branch_gate < nssm, f'分支闸门(L{branch_gate}) 晚于 nssm restart(L{nssm})'
    assert dirty_gate < nssm, f'脏工作区闸门(L{dirty_gate}) 晚于 nssm restart(L{nssm})'


def test_restart_bat_refuses_with_nonzero_exit() -> None:
    """闸门必须真的「拒绝」—— 只打一行提示然后继续重启等于没有闸门。"""
    text = RESTART_BAT.read_text(encoding='utf-8', errors='replace')
    lines = [ln for ln in text.splitlines()
             if not ln.strip().upper().startswith('REM')]
    body = '\n'.join(lines)
    assert re.search(r'RESULT:\s*REFUSED', body), '闸门没有 REFUSED 输出'
    # 每个 REFUSED 分支之后必须 exit /b 非 0
    refused_blocks = re.findall(
        r'RESULT:\s*REFUSED[^\n]*\n(?:.*\n){0,6}?\s*exit\s+/b\s+([1-9]\d*)', body,
    )
    assert len(refused_blocks) >= 2, (
        f'找到 {len(refused_blocks)} 处「REFUSED 后 exit /b 非0」；'
        '分支闸门与脏工作区闸门都应如此（否则脚本继续往下重启）'
    )
