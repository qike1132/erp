"""运维脚本的危险动作必须有闸门，且必须复用唯一实现（审计 P1-25/27/28）。

为什么用「源码行号顺序 + 形态断言」而不是跑脚本：
这些脚本直接动生产（删库、重启后端、覆盖部署目录），没有沙箱可跑 ——
本机既是生产机也是运维机（AGENTS §0）。所以守卫只能盯「危险动作之前有没有
那道闸门、顺序对不对、有没有复用唯一实现」。

2026-11-18 评审后本文件改过一次形态，原因写在每个用例的 docstring 里：
  · `restart_erp_prod.bat` 不再自带闸门，改为**委托** `scripts/restart_backend.py`
    （评审 High1/High2/Med8：手写闸门 fail-open、`nssm restart` 假成功、
    与 `server_manager/git_guard.py` 构成第二真相源）。
  · `install_package.ps1` 的清理必须保留 `config`/`settings`（评审 Med3：
    否则会删掉部署机的 `config\\pgbouncer\\userlist.txt` 与 `config\\tls\\*.key`）。
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / 'deploy' / 'install_package.ps1'
RESTART_BAT = PROJECT_ROOT / 'scripts' / 'restart_erp_prod.bat'
RESTART_PY = PROJECT_ROOT / 'scripts' / 'restart_backend.py'
BUILD_PACKAGE = PROJECT_ROOT / 'deploy' / 'build_package.ps1'


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding='utf-8', errors='replace').splitlines()


def _code_lines(path: Path) -> list[str]:
    """去掉整行注释（`#` / `REM`）后的行 —— 注释里提到危险动作不算违规。"""
    out: list[str] = []
    for ln in _lines(path):
        s = ln.strip()
        if s.startswith('#') or s.upper().startswith('REM'):
            continue
        out.append(ln)
    return out


def _first_line_matching(lines: list[str], pattern: str) -> int:
    """返回第一个匹配的行号（1-based）；找不到返回 -1。"""
    rx = re.compile(pattern)
    for i, line in enumerate(lines, start=1):
        if rx.search(line):
            return i
    return -1


def test_files_exist() -> None:
    """守卫对象必须存在 —— 改名不能让下面的断言静默空转。"""
    for p in (INSTALLER, RESTART_BAT, RESTART_PY):
        assert p.is_file(), f'守卫对象不存在（改名/挪走后请同步本文件）：{p}'


# --- install_package.ps1 ---------------------------------------------------

def test_installer_drops_database_after_stopping_service() -> None:
    """P1-25：DROP DATABASE 必须在 Stop-Service 之后（防回归）。

    原实现把删库放在停服务之前：DROP 那一瞬间五个 NSSM 服务仍 RUNNING 并持有
    连接，要么 DROP 失败，要么在强制断开路径上留下一堆半个状态的进程。
    """
    lines = _code_lines(INSTALLER)
    stop = _first_line_matching(lines, r'Stop-Service')
    drop = _first_line_matching(lines, r'DROP\s+DATABASE')
    assert stop > 0, '没找到 Stop-Service —— 停服务这一步可能被删了'
    assert drop > 0, '没找到 DROP DATABASE'
    assert stop < drop, f'DROP DATABASE(L{drop}) 早于 Stop-Service(L{stop})'


def test_installer_keeps_local_credentials_when_purging() -> None:
    """评审 Med3：清理代码目录时**必须**保留 `config` / `settings`。

    这是本改动自己引入又自己修掉的一个破坏：`build_package.ps1` 打 `app\\` 时
    排除了 `config\\pgbouncer`（userlist.txt 是真凭据，只在部署机），并把
    `config\\jwt` 另存为 `settings\\jwt`。若把 `config` 当「包内有的代码目录」
    删掉，部署机会同时失去 pgbouncer 凭据（包内没有，删了就不恢复）和 TLS 私钥。
    """
    code = '\n'.join(_code_lines(INSTALLER))
    m = re.search(r'\$runtimeDirNames\s*=\s*@\(([^)]*)\)', code, re.S)
    assert m, '没找到 $runtimeDirNames 定义 —— 保留名单的结构已变'
    body = m.group(1).lower()
    for must in ('config', 'settings'):
        assert f"'{must}'" in body, (
            f'$runtimeDirNames 里没有 {must} —— 清理代码目录会删掉部署机的本地凭据'
            f'（config\\pgbouncer\\userlist.txt、config\\tls\\*.key）。当前名单：{m.group(1)}'
        )
    for must in ('logs', 'backups', 'static'):
        assert f"'{must}'" in body, f'$runtimeDirNames 里没有 {must} —— 运行期数据会被删'


def test_installer_clears_stale_code_before_robocopy() -> None:
    """P1-28：代码复制段的 robocopy 之前必须先删旧目录，否则新旧混合代码树。

    注意本文件里还有其它 robocopy（nginx 静态资源在更早的步骤），所以基准是
    「`$copies` 之后的第一个 robocopy」。
    """
    lines = _lines(INSTALLER)
    copies_at = _first_line_matching(lines, r'^\s*\$copies\s*=')
    assert copies_at > 0, '没找到 $copies 定义 —— 部署步骤结构已变'
    first_robocopy = _first_line_matching(lines[copies_at:], r'^\s*robocopy\s')
    assert first_robocopy > 0, '$copies 之后没找到 robocopy'
    first_robocopy += copies_at

    before = '\n'.join(
        ln for ln in lines[copies_at: first_robocopy - 1]
        if not ln.strip().startswith('#')
    )
    # 「配置了」与「真的会执行」必须同时成立 —— 只断言出现 Remove-Item 不够：
    # 把 `if($c.PurgeCode){` 改成 `if($false){` 时它仍在，清目录却不会发生。
    assert re.search(r'PurgeCode\s*=\s*\$true', before), '`app` 那条没有标 PurgeCode=$true'
    assert re.search(r'PurgeWhole\s*=\s*\$true', before), '产物目录没有标 PurgeWhole=$true'
    assert re.search(r'if\s*\(\s*\$c\.PurgeCode\s*\)', before), \
        '标记了 PurgeCode 但没有对应的 if($c.PurgeCode){...} 实现'
    assert re.search(r'if\s*\(\s*\$c\.PurgeWhole\b', before), \
        '标记了 PurgeWhole 但没有对应的 if($c.PurgeWhole...){...} 实现'
    # 删除目标必须是「目标目录 + 包内子目录名」，不能是根目录本身
    # （评审 Med6：`$dstChild = $c.Dst` 会删掉整个安装根，六条断言全绿）
    assert re.search(r'\$dstChild\s*=\s*Join-Path\s+\$c\.Dst\s+\$item\.Name', before), (
        '删除目标的表达式不再是「$c.Dst + 子目录名」—— 若改成 $c.Dst 本身，'
        '会把整个安装根（logs/backups/.env/static）删掉'
    )
    assert 'Remove-Item' in before, 'robocopy 之前没有删除动作 —— /E 会留下旧文件'


def test_installer_purge_whole_keeps_a_rollback_point() -> None:
    """评审 Med5：清空产物目录前必须先留回滚点。

    直接 `Remove-Item` 等于「五服务已 remove + 产物半份 + 无回滚点」：
    robocopy 中途失败时，`runtime` 目录里既没有完整的新运行时也没有旧运行时。
    """
    code = '\n'.join(_code_lines(INSTALLER))
    assert 'Move-Item' in code and '.bak-' in code, (
        'PurgeWhole 没有先改名留档 —— 清空后若复制失败，产物目录无法回滚'
    )
    assert re.search(r'\$purgeBaks\s*\+?=', code), '没有收集回滚点清单'
    # 回滚点必须在成功后才清（不能和清空同步做）
    assert re.search(r'foreach\s*\(\s*\$bak\s+in\s+\$purgeBaks\s*\)', code), \
        '没有「复制成功后清理回滚点」的收尾步骤'


def test_installer_never_purges_whole_target_root() -> None:
    """防回归：可执行行里不得出现 `/PURGE`（安装根同时是运行期数据目录）。

    注释里讨论「为什么不用 /PURGE」是必要说明，不算违规。
    """
    offenders = [ln.strip() for ln in _code_lines(INSTALLER) if '/PURGE' in ln]
    assert not offenders, (
        'install_package.ps1 的可执行行里出现了 /PURGE —— 安装根同时是运行期数据目录'
        '（logs/backups/.env/static/uploads），/PURGE 会把它们删掉：\n  '
        + '\n  '.join(offenders)
    )


# --- restart_erp_prod.bat --------------------------------------------------

def test_restart_bat_delegates_instead_of_calling_nssm_restart() -> None:
    """P1-27：不得再直接 `nssm restart`，必须委托 `scripts/restart_backend.py`。

    两个理由（评审 High1/High2）：
      · `nssm restart` 在停机阶段失败时返回非 0 且**不发出 start**，服务永停；
      · 健康 200 不绑定版本 —— 旧进程照样 200，脚本会打「new code is live」的假成功。
    `restart_backend.py` 已显式 stop→等 STOPPED→start→等 RUNNING，并复核
    响应 worker 的 runtime commit == 目标 HEAD。
    """
    code = '\n'.join(_code_lines(RESTART_BAT))
    assert 'restart_backend.py' in code, (
        'restart_erp_prod.bat 没有委托 scripts\\restart_backend.py —— '
        '手写重启序列会重犯「nssm restart 假成功」'
    )
    assert not re.search(r'nssm(\.exe)?\s+restart', code, re.I), (
        'restart_erp_prod.bat 里还有 nssm restart —— 停机失败时它不发出 start，'
        '且健康 200 无法证明新代码生效'
    )
    # 不得自己探健康当作发布成功判据
    assert '/api/health' not in code, (
        'restart_erp_prod.bat 又自己探 /api/health 了 —— 200 不绑定版本，'
        '旧进程也会 200；版本核对应由 restart_backend.py 的 commit 指纹负责'
    )


def test_restart_bat_checks_the_delegate_exit_code() -> None:
    """闸门/委托必须真的判失败 —— 只看回显等于没有判定。"""
    code = '\n'.join(_code_lines(RESTART_BAT))
    assert re.search(r'set\s+RC=%errorlevel%', code), '没有捕获 restart_backend.py 的退出码'
    assert re.search(r'if\s+not\s+"%RC%"\s*=="0"', code), '捕获了退出码却不判'
    assert re.search(r'exit\s+/b\s+%RC%', code), '失败时没有把退出码传出去'
    assert re.search(r'net\s+session', code), (
        '没有管理员检测 —— NSSM stop/start 需要提权，'
        '不提权会静默失败（NSSM 非提权调用退出码仍为 0）'
    )


def test_build_package_refuses_non_main_branch() -> None:
    """P2-5（2026-10-17 审计）：发布包只能来自 **main**。

    原实现只查「工作区脏」不查分支 —— 而 NSSM 的 AppDirectory 就是本仓库工作区，
    从特性分支打出来的包会被当作发布版本（2026-10-14 已有 75 分钟实害事故）。
    `-DryRun` 是演练（`deploy/tests/e2e_dryrun.ps1` 会 clone 当前分支后再跑），
    因此分支不符只 WARN —— 这条降级必须留着，否则演练在特性分支上就废了。
    """
    code = '\n'.join(_code_lines(BUILD_PACKAGE))

    assert '--abbrev-ref HEAD' in code, '构建脚本没有读当前分支'
    assert "'main'" in code, '构建脚本没有与 main 比对'
    assert '不是 main' in code, '缺少拒绝文案（拒绝时必须说清原因）'
    assert 'DryRun' in code, '分支闸门必须保留 DryRun 降级，否则演练在特性分支上跑不了'


def test_build_package_git_failure_is_fail_closed() -> None:
    """P2-5（2026-10-17 审计）：git 命令失败必须拒绝打包。

    原实现把 `git status --porcelain` 的输出直接当判据：命令失败（`.git/index.lock`
    残留 / 不在仓库 / `safe.directory` 拒绝）时输出为空 → 直接放行；同时下方 manifest
    的 `git_head` 会是空串 —— 事后无法证明发布的到底是哪个提交。
    """
    code = '\n'.join(_code_lines(BUILD_PACKAGE))

    for var in ('$rcBranch', '$rcDirty', '$rcHead'):
        assert var in code, f'缺少 {var}：git 退出码没有被消费（失败会 fail-open）'
    assert re.search(r'\$rcBranch\s+-ne\s+0', code), '没判 `git rev-parse --abbrev-ref` 的退出码'
    assert re.search(r'\$rcHead\s+-ne\s+0', code), '没判 `git rev-parse HEAD` 的退出码'
    assert 'Trim().Length' in code, '读不到 HEAD 时未拒绝（manifest 会写成空 git_head）'
