"""运维脚本的危险动作必须有闸门，且必须复用唯一实现（审计 P1-25/27/28）。

为什么用「源码行号顺序 + 形态断言」而不是跑脚本：
这些脚本直接动生产（删库、重启后端、覆盖部署目录），没有沙箱可跑 ——
本机既是生产机也是运维机（AGENTS §0）。所以守卫只能盯「危险动作之前有没有
那道闸门、顺序对不对、有没有复用唯一实现」。

2026-11-18 评审后本文件改过一次形态，原因写在每个用例的 docstring 里：
  · `restart_erp_prod.bat` 不再自带闸门，改为**委托** `scripts/restart_backend.py`
    （评审 High1/High2/Med8：手写闸门 fail-open、`nssm restart` 假成功、
    与 `server_manager/git_guard.py` 构成第二真相源）。
  · `install_package.ps1` 无法证明完整回切前，只允许全新安装，不替换现有资源。
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / 'deploy' / 'install_package.ps1'
RESTART_BAT = PROJECT_ROOT / 'scripts' / 'restart_erp_prod.bat'
RESTART_PY = PROJECT_ROOT / 'scripts' / 'restart_backend.py'
BUILD_PACKAGE = PROJECT_ROOT / 'deploy' / 'build_package.ps1'
DEPLOY_LIB = PROJECT_ROOT / 'deploy' / '_lib.ps1'
INSTALL_CMD = PROJECT_ROOT / 'deploy' / 'install.cmd'
BUILD_CMD = PROJECT_ROOT / 'deploy' / 'build.cmd'


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding='utf-8', errors='replace').splitlines()


def _code_lines(path: Path) -> list[str]:
    """去掉整行注释（`#` / `REM`）后的行 —— 注释里提到危险动作不算违规。"""
    out: list[str] = []
    for ln in _lines(path):
        s = ln.strip().lstrip('\ufeff')
        if s.startswith('#') or re.match(r'REM(?:\s|$)', s, re.I):
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
    for p in (INSTALLER, RESTART_BAT, RESTART_PY, INSTALL_CMD, BUILD_CMD):
        assert p.is_file(), f'守卫对象不存在（改名/挪走后请同步本文件）：{p}'


def test_cmd_launchers_bypass_execution_policy() -> None:
    """T-03（2026-11-24 真机验证）：.cmd 入口必须带 -ExecutionPolicy Bypass。

    便携包目标机是全新 Windows 客户端机，Windows PowerShell 5.1 默认策略
    Restricted/RemoteSigned 会拦下无签名 .ps1 —— 实测本机 5.1 RemoteSigned
    对 D: 盘所有本地脚本报 UnauthorizedAccess（C: 盘同内容放行，非 MotW，
    D: 为 Fixed NTFS）。2026-10-08 设计意图即「自动 Bypass + pause」，pause
    落地了、Bypass 漏了。README 的 powershell.exe 示例同样缺该参数。
    """
    for cmd in (INSTALL_CMD, BUILD_CMD):
        code = '\n'.join(_code_lines(cmd))
        assert re.search(r'powershell(\.exe)?\s+-NoProfile\s+-ExecutionPolicy\s+Bypass\s+-File', code), (
            f'{cmd.name} 调用 powershell 未带 -ExecutionPolicy Bypass —— '
            '全新目标机默认执行策略会拦下无签名脚本，双击入口直接 UnauthorizedAccess'
        )


# --- install_package.ps1 ---------------------------------------------------

def test_installer_fails_closed_without_overwriting_existing_components() -> None:
    """没有验过完整回切，因此旧版本及旧库、服务、备份均不能被触碰。"""
    lines = _code_lines(INSTALLER)
    code = '\n'.join(lines)
    gate = _first_line_matching(lines, r'^\s*Assert-FreshInstallOptions \$Force \$AllowDropDatabase \$SkipVerify$')
    stage = _first_line_matching(lines, r'^\s*\$work=New-DeployStagingDirectory$')
    entry_lock = _first_line_matching(lines, r'^\s*if\(-not \$PreflightOnly\)\{ throw')
    terminal_lock = _first_line_matching(lines, r'^\s*throw .*拒绝进入数据库迁移和部署')
    create_db = _first_line_matching(lines, r'CREATE\s+ROLE')
    assert 0 < gate < entry_lock < stage < terminal_lock < create_db
    assert re.search(r"if\(\$PreflightOnly\)\{\s*Remove-DeployStagingDirectory \$work\s*\$work=\$null\s*Write-Ok '[^']+'\s*exit 0\s*}", code)
    assert re.search(r'if\(Test-Path -LiteralPath \$TargetDir\)\{ throw', code)
    assert code.index('Assert-NewDatabase $psql $dbName $dbUser') < code.index('CREATE ROLE')
    assert not re.search(r'DROP\s+DATABASE|ALTER\s+ROLE|Stop-Service|/PURGE|/MIR|Remove-Item[^\n]*-Recurse', code, re.I)
    service_install = '\n'.join(_code_lines(DEPLOY_LIB)).split('function Install-NssmService(', 1)[1]
    assert re.search(r'if\(\$null -ne \(Get-ServiceStatus \$name\)\)\{ throw', service_install)
    assert "@('remove'" not in service_install


def test_installer_requires_trusted_tls_and_package_before_mutations() -> None:
    lines = _code_lines(INSTALLER)
    tls = _first_line_matching(lines, r'^\s*Assert-DeploymentTls \$OpenSsl \$TlsCertificate ')
    stage = _first_line_matching(lines, r'^\s*\$work=New-DeployStagingDirectory$')
    verify = _first_line_matching(lines, r'^\s*Unprotect-File .* -ExpectedSha256 \$ExpectedSha256 ')
    unpack = _first_line_matching(lines, r'^\s*& \$tar -xzf ')
    build_db = _first_line_matching(lines, r'CREATE\s+ROLE')
    assert 0 < tls < stage < verify < unpack < build_db
    code = '\n'.join(lines)
    assert 'https://$hUrl/api/health' in code and 'SkipCertificateCheck' not in code
    assert not re.search(r'\s(?:-k|--insecure)\b', code)
    assert not re.search(r'\.sha256["\']', code, re.I)


def test_tls_preflight_verifies_leaf_only_from_chain_file() -> None:
    """证书文件常含「叶 + 中间 CA」；openssl verify 会把每张证书都当终端实体，
    中间 CA 在 -purpose sslserver 下被判用途不符，合法链会被误拒。"""
    code = '\n'.join(_code_lines(DEPLOY_LIB))
    tls = code.split('function Assert-DeploymentTls(', 1)[1].split('\nfunction ', 1)[0]
    assert re.search(r'& \$OpenSsl x509 -in \$Certificate -out \$leafFile', tls)
    assert re.search(
        r'& \$OpenSsl verify\b(?=[^\n]*-untrusted \$Certificate)(?=[^\n]*\$leafFile)(?![^\n]*\s\$Certificate\s*\|\s*Out-Null)', tls
    )
    assert re.search(r"\} finally \{\s*if\(Test-Path -LiteralPath \$leafFile\)\{ Remove-Item -LiteralPath \$leafFile", tls)


def test_builder_creates_only_encrypted_outputs_and_hides_temporary_data() -> None:
    code = '\n'.join(_code_lines(BUILD_PACKAGE))
    assert not re.search(r'Remove-Item[^\n]*-Recurse', code, re.I)
    assert code.index('$stage=New-DeployStagingDirectory') < code.index('& $pgDump')
    assert code.index('Protect-File -InPath $tgz') < code.index('[IO.File]::Copy($enc,$published,$false)')
    assert re.search(r'} finally \{\s*Remove-Item Env:PGPASSWORD[^\n]*\n\s*if\(\$stage\)\{ Remove-DeployStagingDirectory \$stage \}', code)


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
    `-DryRun` 只做前置检查且无产物；只有分支不符降为警告。
    """
    code = '\n'.join(_code_lines(BUILD_PACKAGE))

    assert '--abbrev-ref HEAD' in code, '构建脚本没有读当前分支'
    assert "'main'" in code, '构建脚本没有与 main 比对'
    assert '不是 main' in code, '缺少拒绝文案（拒绝时必须说清原因）'
    assert re.search(r"\$branch\.Trim\(\)\s+-ne\s+'main'", code), (
        '分支比对取的是原始 $branch（含空白）或已被改写 —— 必须是 $branch.Trim() -ne \'main\''
    )
    assert re.search(r'不是 main[^\n]*;\s*exit 1', code), (
        '「不是 main」的拒绝分支没有紧跟 exit 1（Write-Fail 只写 stderr、不退出 = fail-open）'
    )
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

    # 只断言「字符串还在」挡不住 fail-open：deploy/_lib.ps1 的 Write-Fail 只写 stderr、**不退出**，
    # 所以每条拒绝分支都是手写的 `Write-Fail ...; exit 1`。删掉 exit 1（或把条件改成 $false）后
    # 上面那些字符串全都还在、用例照绿，而脚本会继续 robocopy 并打出 BUILD COMPLETE
    # —— 正是这条用例要防的「特性分支/脏工作区的包被当发布版本」（2026-11-19 评审）。
    assert code.count('exit 1') >= 4, (
        f'拒绝分支少了退出：期望 ≥4 处 `exit 1`，实际 {code.count("exit 1")} 处'
        '（Write-Fail 不退出，只留文案等于放行）'
    )
    assert re.search(r'HEAD 失败[^\n]*拒绝打包"\)\s*\n\s*exit 1', code), (
        'git rev-parse HEAD 失败的分支没有紧跟 exit 1（fail-open）'
    )
    assert re.search(r'不是 main[^\n]*;\s*exit 1', code), (
        '「不是 main」的拒绝分支没有紧跟 exit 1（fail-open）'
    )
