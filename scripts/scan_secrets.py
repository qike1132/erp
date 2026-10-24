#!/usr/bin/env python3
"""全仓密钥扫描 —— CI 侧的第二道防线。

为什么需要它
------------
`.githooks/pre-commit` 已在本地做密钥扫描，但**本地 hook 可被
`git commit --no-verify` 绕过**（hook 头部自述），因此该文件把「CI 侧必须另有
一道独立的扫描」列为审计行动项。本脚本即该项的落地。

与 hook 的关系
--------------
规则语义与 `.githooks/pre-commit` 第 1/2 层一致，并**复用**
`scripts/_selftest_hook.py` 已镜像的那套规则 —— 避免出现第三份正则、互相漂移。
（`tests/test_scan_secrets_hook_parity.py` 会把镜像与 shell 里的模式逐字比对，防止静默漂移。）

**与 hook 的刻意差异（1 处）**：`require_quoted_rhs`（右值必须带引号）除 `.py` 外
也应用于 `.ts/.js/.vue`。hook 只对 `.py` 应用它，于是整仓扫描时 TS 对象属性
（`password: form.password`）与 Vue 模板绑定（`showPassword = !showPassword`）
会产生大量误报。代价：`.ts/.js/.vue` 里**纯数字**的赋值（如 `token: 1234567890123`）
不再命中 —— 已知且接受（真实凭据在本项目里都是字符串字面量）。
豁免同样读 `.githooks/allowlist.txt`。

与 hook 的区别
--------------
hook 只看**本次暂存**的文件；本脚本扫**全部受版本控制的文件**，因此能发现
历史上已入库的可疑文件（这正是本地 hook 补不回的那部分）。

与更专业的扫描器的关系
----------------------
本脚本只覆盖「本项目自己已知的模式」。独立的第三方扫描器（gitleaks / trufflehog）
能发现我们没有枚举过的特征，是更强的第二层；建议后续在 CI 追加（见优化方案 P0-5）。

用法：
    python scripts/scan_secrets.py             # 扫描全仓，命中即退出码 1
    python scripts/scan_secrets.py --verbose   # 额外打印扫描规模
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 复用已镜像的规则，不另写一份正则（见模块 docstring）
from scripts._selftest_hook import password_rule_hits, secret_rule_hits

ALLOWLIST_REL = Path('.githooks') / 'allowlist.txt'

# 与 hook 第 2 层一致：二进制与超大文件跳过
BINARY_SUFFIXES = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip', '.gz', '.7z', '.rar',
    '.woff', '.woff2', '.ttf', '.eot', '.mp4', '.mp3', '.xlsx', '.docx', '.pptx', '.pyc',
    '.so', '.dll', '.exe', '.bin', '.dat', '.db', '.sqlite', '.wal', '.shm',
}
MAX_FILE_BYTES = 2_000_000

# 「右值必须带引号」适用的后缀。
# `.py` 之外还要覆盖 ts/js/vue：对象属性/赋值里 `password: form.password`、
# `showPassword = !showPassword` 这类**表达式**同样不是硬编码字面量，
# 而 hook 的规则 ④ 原先只对 .py 生效 —— 整仓扫描时会因此产生大量误报。
# （下方把 `is_python=True` 传给共享规则函数，其第二个参数的真实语义是
#  「右值必须是带引号的字面量」，只是当初按 .py 命的名。）
_QUOTED_RHS_REQUIRED_SUFFIXES = ('.py', '.ts', '.js', '.vue')

# 内容层豁免：这些位置里的「凭据字样」是文档代码片段或测试夹具，不是真凭据。
# 与项目既有约定一致（bandit 跳过 B105/B106/B107；ruff per-file-ignores 对 tests）。
# ⚠️ 只豁免**内容层**；路径层（.pem/.env/keystore…）对所有文件一视同仁。
#
# 刻意**只保留 tests/ 与 fastapi_app/tests/**：实测只有这两处存在真实的夹具命中；
# `backups/`、`.archive/`、`deliverables/` 的内容命中全部来自 .md（已由后缀豁免），
# 继续保留前缀豁免等于"今天零收益、未来留洞"——例如 backups/ 里某份 db_dump.sql
# 恰好含真口令时会完全不可见。（上线前审计的同一发现：backups/、static/uploads/ 是风险区。）
_CONTENT_EXEMPT_PREFIXES = (
    # F3-4：docs/ 不再整体豁免——只豁免 .md（下方后缀）；docs 下的 .py/.sql/.json
    # 等内容仍要扫描，避免历史泄漏目录成为盲区。
    'tests/', 'fastapi_app/tests/',
)
_CONTENT_EXEMPT_SUFFIXES = ('.md',)

# 行内抑制标记：某行确认是误报时，在该行任意位置写下本标记即可跳过该行。
# 比「整文件加入 allowlist」精准得多 —— 豁免一行不会蒙住同一文件里的其它行。
# 用法示例（Vue 模板里的绑定属性名恰好含 password）：
#     v-model:show-password="showPassword"  <!-- secret-scan:allow -->
# ⚠️ 上面这行示例**依赖自身携带的标记**才不会被扫出来 —— 编辑时别把标记删掉。
INLINE_SUPPRESSION = 'secret-scan:allow'

# 显式的「抑制下一行」标记（写在**上一行**，本行必须只有该标记与注释符号）。
# 存在的理由：HTML/Vue 模板里注释**不能放在标签的属性列表中**，于是形如
# `<Comp v-model:show-password="x" >` 的误报无法用同行标记豁免，只能写在上一行。
NEXT_LINE_SUPPRESSION = 'secret-scan:allow-next-line'

# 浏览器凭据/历史库文件名（hook 第 1 层的精确 basename 命中）
_BROWSER_DB_BASENAMES = {
    'Login Data', 'Login Data For Account', 'Login Data-journal',
    'Local State', 'Cookies', 'Cookies-journal', 'Web Data', 'Web Data-journal',
    'History', 'History-journal', 'Vpn Tokens', 'Trust Tokens', 'Affiliation Database',
}
# 真实环境变量文件（模板不在内）
_REAL_ENV_BASENAMES = {'.env', '.env.production', '.env.development', '.env.local', '.env.backup'}
# 私钥/证书后缀
_KEY_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.keystore', '.jks')
_KEY_NAME_FRAGMENTS = ('id_rsa', 'id_ed25519')
# 私钥类文件的豁免（模板与文档里出现的是示意，不是真密钥）
_KEY_EXEMPT_SUFFIXES = ('.example', '.sample', '.template', '.md')


def dangerous_path_reason(path: str) -> str | None:
    """危险路径 → 原因；安全则 None。镜像 `.githooks/pre-commit` 第 1 层。"""
    base = path.rsplit('/', 1)[-1]

    if any(fnmatch.fnmatchcase(path, pat) for pat in (
        '*_edge_profile_*', '*_chrome_profile_*', '*_chromium_profile_*',
        '*_firefox_profile_*', '*_gecko_profile_*',
    )):
        return '浏览器用户配置目录'
    if any(fnmatch.fnmatchcase(path, f'*/{d}/*') for d in (
        'Crashpad', 'Session Storage', 'Local Storage', 'IndexedDB', 'Service Worker',
    )):
        return '浏览器运行态数据目录'
    if path.endswith(('.db-journal', '.sqlite-journal')):
        return '数据库 journal 文件'
    if base in _BROWSER_DB_BASENAMES:
        return '浏览器凭据/历史数据库文件'

    is_key_like = path.endswith(_KEY_SUFFIXES) or any(frag in base for frag in _KEY_NAME_FRAGMENTS)
    if is_key_like:
        # 只豁免模板与文档后缀。**刻意不豁免 docs/**：2026-09-17 的凭据泄漏事故正是
        # 提交在 docs/ui-redesign/ 下 —— 历史上最该盯的就是这个目录，在这里开豁免
        # 是最不该做的事（且与内容层的 docs/ 豁免叠加会形成双层洞）。
        if not path.endswith(_KEY_EXEMPT_SUFFIXES):
            return '私钥/证书文件'

    if base in _REAL_ENV_BASENAMES:
        return '真实环境变量文件（含明文凭据）'

    return None


def content_secret_reason(text: str, *, require_quoted_rhs: bool) -> str | None:
    """内容 → 原因；无命中则 None。规则与 hook 第 2 层同一套。

    :param require_quoted_rhs: 为真时，赋值右值必须是**带引号的字面量**才判定为凭据
        （`.py`/`.ts`/`.js`/`.vue` 这类解释执行的语言里，不带引号的右值是属性读取、
        变量引用或函数调用，不是硬编码字面量）。
    """
    suppress_next = False
    for line in text.splitlines():
        # 注意 INLINE_SUPPRESSION 是 NEXT_LINE_SUPPRESSION 的前缀：
        # 标记行自身必然也被跳过（这是想要的）。
        skip_line = suppress_next or INLINE_SUPPRESSION in line
        suppress_next = NEXT_LINE_SUPPRESSION in line
        if skip_line:
            continue
        if secret_rule_hits(line):
            return '命中私钥/云凭据特征'
        if password_rule_hits(line, require_quoted_rhs):
            return '疑似明文口令/密钥赋值'
    return None


# 命中原因只能在这组固定文案里取值（见 dangerous_path_reason / content_secret_reason）。
# 原实现把 content_secret_reason() 的返回值直接打印，CodeQL 顺着「该函数读过文件文本」
# 把它判成明文记录敏感数据（py/clear-text-logging-sensitive-data）——但返回值本就是
# 常量文案，不含任何凭据值。下面这层白名单收敛让污点追踪终止在常量上，同时保证将来
# 若有人把命中内容塞进 reason，也不会被原样打进 CI 日志。
_REASON_LABELS: tuple[str, ...] = (
    '浏览器用户配置目录',
    '浏览器运行态数据目录',
    '数据库 journal 文件',
    '浏览器凭据/历史数据库文件',
    '私钥/证书文件',
    '真实环境变量文件（含明文凭据）',
    '命中私钥/云凭据特征',
    '疑似明文口令/密钥赋值',
)


def _display_reason(reason: str) -> str:
    """把命中原因收敛到固定文案；未知原因一律泛化，绝不回显原值。"""
    for label in _REASON_LABELS:
        if label == reason:
            return label
    return '命中疑似凭据'


def load_allowlist(root: Path) -> list[str]:
    """读取 `.githooks/allowlist.txt` 的 glob（去掉注释与空行）。"""
    f = root / ALLOWLIST_REL
    if not f.is_file():
        return []
    patterns: list[str] = []
    for raw in f.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if line:
            patterns.append(line)
    return patterns


def _is_allowed(path: str, patterns: list[str]) -> bool:
    # 用 fnmatchcase 而非 fnmatch：后者在 Windows 上大小写不敏感、Linux 上敏感，
    # 会让「本机扫描通过、CI 扫描失败」（或反之），且与 hook 的 shell case 语义不符。
    return any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


def _tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ['git', 'ls-files'], cwd=str(root),
        capture_output=True, text=True, encoding='utf-8', errors='replace',
    )
    if proc.returncode != 0:
        raise RuntimeError(f'git ls-files 失败: {proc.stderr.strip()}')
    return [line for line in (proc.stdout or '').splitlines() if line.strip()]


def content_scan_applies(rel: str) -> bool:
    """该文件是否参与**内容层**扫描（路径层不受影响）。"""
    if rel.endswith(_CONTENT_EXEMPT_SUFFIXES):
        return False
    return not rel.startswith(_CONTENT_EXEMPT_PREFIXES)


def scan_tracked(
    root: Path,
    *,
    allow_patterns: list[str],
    files: list[str] | None = None,
) -> list[tuple[str, str]]:
    """扫描全部受版本控制的文件，返回 [(路径, 原因)]。

    :param files: 已取好的受控文件列表（避免与 verbose 打印重复跑 `git ls-files`）。
    """
    findings: list[tuple[str, str]] = []
    for rel in files if files is not None else _tracked_files(root):
        if _is_allowed(rel, allow_patterns):
            continue

        reason = dangerous_path_reason(rel)
        if (
            reason is None
            and content_scan_applies(rel)
            and not rel.endswith(tuple(BINARY_SUFFIXES))
        ):
            abs_path = root / rel
            try:
                if abs_path.stat().st_size <= MAX_FILE_BYTES:
                    raw = abs_path.read_bytes()
                    # P1（2026-10-24）：不能把「UTF-8 解码失败」当成二进制整篇跳过。
                    # 本机 locale 是 cp936，中文注释的 .sql/.log/.txt/.ini 天然非 UTF-8，
                    # 于是即使里面有一行 DB_PASSWORD=真口令 也 0 命中；而本地钩子按字节
                    # grep 能扫到 ⇒ CI 这道「第二防线」在 GBK 上比本地还弱。
                    # 依次尝试 utf-8 / gbk / utf-16，最后用 latin-1（无损逐字节）兜底；
                    # 仅当出现 NUL 且无 BOM 时按二进制跳过。
                    text = _decode_for_scan(raw)
                    if text is not None:
                        reason = content_secret_reason(
                            text,
                            require_quoted_rhs=rel.endswith(_QUOTED_RHS_REQUIRED_SUFFIXES),
                        )
            except OSError:
                # 读不了 → 跳过内容层（路径层已判过）
                reason = None

        if reason:
            findings.append((rel, reason))
    return findings


def _decode_for_scan(raw: bytes) -> str | None:
    """把文件字节解成可扫描文本；判定为二进制时返回 None。

    顺序：UTF-16（仅认 BOM）→ UTF-8 → GBK → latin-1（无损逐字节）。
    含 NUL 且无 BOM 一律按二进制跳过（PNG/PDF/编译产物），避免把二进制解成
    乱码文本后产生误报把 CI 卡死。
    """
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return raw.decode('utf-16')
        except UnicodeDecodeError:
            return None
    if b'\x00' in raw:
        return None
    for enc in ('utf-8', 'gbk'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='全仓密钥扫描（CI 第二道防线）')
    ap.add_argument('--root', default=str(PROJECT_ROOT), help='仓库根目录')
    ap.add_argument('--verbose', action='store_true', help='打印扫描规模')
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    allow_patterns = load_allowlist(root)
    files = _tracked_files(root)

    if args.verbose:
        print(f'扫描 {len(files)} 个受版本控制文件，豁免 {len(allow_patterns)} 条 glob')

    findings = scan_tracked(root, allow_patterns=allow_patterns, files=files)

    if findings:
        print('', file=sys.stderr)
        print('━━━ 检出疑似凭据（受版本控制的文件） ━━━', file=sys.stderr)
        for path, reason in findings:
            print(f'  ✗ {path}  —— {_display_reason(reason)}', file=sys.stderr)
        print('', file=sys.stderr)
        print(f'处置：改用环境变量/密钥管理注入；若为脱敏测试夹具，把路径加入 {ALLOWLIST_REL}。', file=sys.stderr)
        return 1

    print('[PASS] 受版本控制的文件中未检出疑似凭据')
    return 0


if __name__ == '__main__':
    sys.exit(main())
