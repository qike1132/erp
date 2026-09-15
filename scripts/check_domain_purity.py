"""Domain 层纯度门禁 —— 保证领域层零 I/O、可 100% 单测。

为什么需要它
------------
重构方案（docs/ui-redesign/v5.33重构方案-GitHub对标与落地建议-20260914.md）§4 风险 R2：
    「Domain 层纯度极易失守 —— 实际写代码时很容易在 domain 里偷偷
      import subprocess / 读文件，导致又变成不可测的一坨。」

这是**零容忍**规则，不是棘轮：`server_manager_v8/domain/` 下任何文件出现
下列导入，门禁立即失败。领域层必须只依赖标准库的纯计算能力。

允许：dataclasses / enum / typing / collections / datetime / re / math /
      json（仅做内存内结构转换，不读写文件）。
禁止：任何触达 OS、进程、网络、文件系统、GUI 的模块。

另有**反向门禁**（P2 适配层引入）
--------------------------------
`server_manager_v8/adapters/` 下禁止出现**领域判定逻辑**的复刻：
    · 禁止把服务状态文本与「未安装」/「未知」字面量比较
      （必须经 domain.service_state 判定）
    · 禁止在适配层出现 `'1060'` 这类 sc 返回码的裸字面量
    · 禁止 import domain 之外的 L3/L4（分层方向：L1 → L2，禁止反向）

为什么反向门禁同样重要：v5.36 与 v5.39 两次互杀事故的成因，
都是「sc 输出解析规则散落在调用点」，同一规则在两处漂移。
判定逻辑必须唯一收口在领域层。

用法
----
    python scripts/check_domain_purity.py            # 违规即退出码 1
    python scripts/check_domain_purity.py --verbose  # 打印每处违规的行号

退出码：0 = 纯净；1 = 检测到违规；2 = 环境/解析异常（保守失败）。
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PKG = PROJECT_ROOT / "server_manager_v8"
DOMAIN_DIR = PKG / "domain"
ADAPTERS_DIR = PKG / "adapters"
APPLICATION_DIR = PKG / "application"

# 禁止在 domain 层出现的顶层模块（含子模块前缀匹配，如 'os.path' 命中 'os'）
FORBIDDEN: dict[str, str] = {
    # 进程 / 系统
    'subprocess': '进程操作必须在 adapters 层',
    'os': '系统调用必须在 adapters 层',
    'sys': '解释器/环境访问必须在 adapters 层',
    'shutil': '文件操作必须在 adapters 层',
    'pathlib': '文件操作必须在 adapters 层',
    'glob': '文件操作必须在 adapters 层',
    'tempfile': '文件操作必须在 adapters 层',
    'signal': '进程信号必须在 adapters 层',
    'ctypes': 'Win32 调用必须在 adapters 层',
    'winreg': '注册表访问必须在 adapters 层',
    'socket': '网络必须在 adapters 层',
    'http': '网络必须在 adapters 层',
    'urllib': '网络必须在 adapters 层',
    'requests': '网络必须在 adapters 层',
    'httpx': '网络必须在 adapters 层',
    'psutil': '系统指标采集必须在 adapters 层',
    'logging': '日志是 I/O，应由 adapters/presentation 承担',
    'time': '时间/睡眠是外部依赖，须由调用方注入',
    'datetime': '时间须由调用方注入（除非仅做纯日期算术，见下方白名单）',
    # GUI
    'tkinter': 'GUI 属于 presentation 层',
    'webview': 'GUI 属于 presentation 层',
    # 可选：启用后连 json 也禁（当前允许内存结构转换）
}

# 显式白名单：允许的“看似危险”但实为纯计算的模块
ALLOWED_OVERRIDES: set[str] = set()


def _module_root(name: str) -> str:
    return name.split('.', 1)[0]


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """返回 [(行号, 模块名, 原因)]。"""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except SyntaxError as exc:
        print(f'[ERROR] 无法解析 {path}: {exc}', file=sys.stderr)
        raise SystemExit(2)

    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if root in FORBIDDEN and root not in ALLOWED_OVERRIDES:
                    hits.append((node.lineno, alias.name, FORBIDDEN[root]))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                root = _module_root(node.module)
                if root in FORBIDDEN and root not in ALLOWED_OVERRIDES:
                    hits.append((node.lineno, node.module, FORBIDDEN[root]))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description='分层纯度门禁')
    parser.add_argument('--verbose', action='store_true', help='打印每处违规的行号')
    parser.add_argument('--no-adapters', action='store_true',
                        help='跳过适配层反向门禁（仅查 domain）')
    parser.add_argument('--no-application', action='store_true',
                        help='跳过应用层门禁（仅查 domain + adapters）')
    args = parser.parse_args()

    failed = False

    # ── 正向门禁：domain 不得有 I/O ──────────────────────────────
    total = 0
    if DOMAIN_DIR.is_dir():
        files = sorted(DOMAIN_DIR.rglob('*.py'))
        for path in files:
            rel = path.relative_to(PROJECT_ROOT)
            hits = scan_file(path)
            if hits:
                total += len(hits)
                print(f'\n❌ {rel}')
                for lineno, mod, reason in hits:
                    print(f'   L{lineno:<4} import {mod:<16} — {reason}')
            elif args.verbose:
                print(f'✅ {rel}')

        print()
        if total:
            print('═' * 68)
            print(f'Domain 纯度门禁失败：{total} 处违规导入')
            print('领域层必须零 I/O、可 100% 单测。请把上述依赖下沉到 adapters 层，')
            print('或在 domain 内定义 Protocol 端口，由 adapters 实现后注入。')
            print('═' * 68)
            failed = True
        else:
            print(f'✅ Domain 纯度门禁通过：{len(files)} 个文件，零违规')
    else:
        print(f'[SKIP] 领域层目录不存在: {DOMAIN_DIR}')

    # ── 反向门禁：adapters 不得复刻领域判定 ─────────────────────
    if not args.no_adapters:
        a_hits = check_adapters(args.verbose)
        print()
        if a_hits:
            print('═' * 68)
            print(f'适配层反向门禁失败：{len(a_hits)} 处领域判定复刻')
            print('适配器只做 I/O；判定逻辑必须唯一收口在 domain 层。')
            print('（v5.36/v5.39 两次互杀事故的成因就是规则散落在调用点。）')
            print('═' * 68)
            failed = True
        elif ADAPTERS_DIR.is_dir():
            n = len(sorted(ADAPTERS_DIR.glob('*.py')))
            print(f'✅ 适配层反向门禁通过：{n} 个文件，零领域判定复刻')

    # ── 应用层门禁：依赖倒置 + 不得直接做 I/O ───────────────────
    if not args.no_application:
        app_hits = check_application(args.verbose)
        print()
        if app_hits:
            print('═' * 68)
            print(f'应用层门禁失败：{len(app_hits)} 处违规')
            print('应用层只依赖 domain 的 Protocol；实现由 container 装配时注入。')
            print('（L3 → L1 的直接依赖会让用例无法在无 Windows 环境的 CI 里测试。）')
            print('═' * 68)
            failed = True
        elif APPLICATION_DIR.is_dir():
            n = len(sorted(APPLICATION_DIR.rglob('*.py')))
            print(f'✅ 应用层门禁通过：{n} 个文件，零违规')

    return 1 if failed else 0


# ═══════════════════════════════════════════════════════════════════
# 反向门禁：适配层不得复刻领域判定
# ═══════════════════════════════════════════════════════════════════

# 领域层的状态字面量 —— 适配层若直接比较它们，说明判定被复刻了
DOMAIN_LITERALS: dict[str, str] = {
    '未安装': '必须经 domain.service_state.STATE_ABSENT 判定',
    '未知': '必须经 domain.service_state.STATE_UNKNOWN 判定',
}

# sc 的返回码 —— 判定「未安装」是领域层的职责
FORBIDDEN_SERVICE_CODES: tuple[str, ...] = ('1060',)

# 适配层允许 import 的顶层包（分层方向：L1 → L2；禁止 L1 → L3/L4）
ADAPTER_ALLOWED_INTERNAL = ('server_manager_v8.domain', 'server_manager_v8.adapters')


def check_adapters(verbose: bool = False) -> list[tuple[Path, int, str]]:
    """检查适配层是否复刻了领域判定逻辑。"""
    if not ADAPTERS_DIR.is_dir():
        return []

    hits: list[tuple[Path, int, str]] = []
    for path in sorted(ADAPTERS_DIR.rglob('*.py')):
        rel = path.relative_to(PROJECT_ROOT)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except SyntaxError as exc:
            print(f'[ERROR] 无法解析 {path}: {exc}', file=sys.stderr)
            raise SystemExit(2)

        for node in ast.walk(tree):
            # 1) 领域字面量比较
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in DOMAIN_LITERALS:
                    hits.append((rel, node.lineno,
                                 f'出现领域状态字面量 {node.value!r} —— '
                                 f'{DOMAIN_LITERALS[node.value]}'))
            # 2) sc 返回码裸字面量
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                if str(node.value) in FORBIDDEN_SERVICE_CODES:
                    hits.append((rel, node.lineno,
                                 f'出现 sc 返回码裸字面量 {node.value} —— '
                                 f'服务状态判定属于 domain.service_state'))
            # 3) 非法跨层 import
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                if mod.startswith('server_manager_v8.'):
                    if not mod.startswith(ADAPTER_ALLOWED_INTERNAL):
                        hits.append((rel, node.lineno,
                                     f'适配层非法 import {mod} —— '
                                     f'只允许依赖 domain（L1 → L2）'))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('server_manager_v8.'):
                        if not alias.name.startswith(ADAPTER_ALLOWED_INTERNAL):
                            hits.append((rel, node.lineno,
                                         f'适配层非法 import {alias.name} —— '
                                         f'只允许依赖 domain（L1 → L2）'))

    for rel, lineno, msg in hits:
        print(f'❌ {rel}:L{lineno}  {msg}')
    return hits


# ═══════════════════════════════════════════════════════════════════
# 应用层门禁：依赖倒置 + 不得直接做 I/O
# ═══════════════════════════════════════════════════════════════════

#: 应用层禁止导入的顶层模块 —— 与 domain 的禁令基本一致
#:
#: 理由：应用层也是**会被单测覆盖**的层。若它自己 import subprocess，
#: 用例就必须在真实 Windows 上、有真实服务时才能测 ——
#: 「用 Fake 替换依赖」的能力就白费了。
#:
#: ★ 与 domain 的差异：应用层**可以** import time（它需要给事件打时间戳），
#:   但时序控制（sleep / 超时判定）仍应走注入的 ClockPort。
#:   这个差异是有意的：事件时间戳是**数据**，不是**时序控制**。
APPLICATION_FORBIDDEN: dict[str, str] = {
    'subprocess': '进程操作必须走注入的 ProcessPort / ServicePort',
    'shutil': '文件操作必须走注入的 StoragePort',
    'pathlib': '文件操作必须走注入的 StoragePort',
    'glob': '文件操作必须走注入的 StoragePort',
    'tempfile': '文件操作必须走注入的 StoragePort',
    'signal': '进程信号必须走 adapters 层',
    'ctypes': 'Win32 调用必须走 adapters 层',
    'winreg': '注册表访问必须走 adapters 层',
    'socket': '网络必须走注入的 HealthPort',
    'urllib': '网络必须走注入的 HealthPort',
    'requests': '网络必须走注入的 HealthPort',
    'httpx': '网络必须走注入的 HealthPort',
    'psutil': '系统指标必须走注入的 MetricsPort',
    'logging': '日志是 I/O，由 adapters / presentation 承担（用事件总线替代）',
    'tkinter': 'GUI 属于 presentation 层',
    'webview': 'GUI 属于 presentation 层',
}

#: 应用层允许依赖的内部包
#:
#: ★ 关键约束：**不含 `server_manager_v8.adapters`**。
#:   这是依赖倒置的核心 —— 应用层只认 domain 的 Protocol，
#:   具体实现在 `container.py` 装配时注入。
#:   若允许 import adapters，用例就无法被 Fake 替换，CI 里跑不了。
APPLICATION_ALLOWED_INTERNAL = ('server_manager_v8.domain',)

#: 应用层禁止出现的领域状态字面量（同 adapters 的理由：判定必须收口）
APPLICATION_FORBIDDEN_LITERALS: dict[str, str] = {
    '未安装': '必须经 domain.service_state.STATE_ABSENT 判定',
    '未知': '必须经 domain.service_state.STATE_UNKNOWN 判定',
}

#: 允许 import `time` 的具体场景白名单（模块相对路径 → 说明）
#:
#: ★ 这是一个**刻意收窄**的白名单：只允许 pipeline 拿时间戳做耗时统计。
#:   其它任何地方 import time 都要走注入的 ClockPort ——
#:   否则「30 分钟过期」「3 轮 × 0.5s 重试」这类时序逻辑又会变得不可测。
APPLICATION_TIME_ALLOWLIST: dict[str, str] = {
    'application/pipeline.py': '仅用于在无注入时钟时给步骤耗时兜底打点',
}


def check_application(verbose: bool = False) -> list[tuple[Path, int, str]]:
    """检查应用层是否违反依赖倒置或直接做 I/O。"""
    if not APPLICATION_DIR.is_dir():
        return []

    hits: list[tuple[Path, int, str]] = []
    for path in sorted(APPLICATION_DIR.rglob('*.py')):
        rel = path.relative_to(PROJECT_ROOT)
        rel_key = str(path.relative_to(PKG)).replace('\\', '/')
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except SyntaxError as exc:
            print(f'[ERROR] 无法解析 {path}: {exc}', file=sys.stderr)
            raise SystemExit(2)

        for node in ast.walk(tree):
            # 1) 禁止直接做 I/O
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = _module_root(alias.name)
                    if root == 'time' and rel_key not in APPLICATION_TIME_ALLOWLIST:
                        hits.append((rel, node.lineno,
                                     '应用层不得 import time —— 时序控制须走注入的 ClockPort'))
                        continue
                    if root in APPLICATION_FORBIDDEN:
                        hits.append((rel, node.lineno,
                                     f'应用层不得 import {alias.name} —— '
                                     f'{APPLICATION_FORBIDDEN[root]}'))
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root = _module_root(node.module)
                if root == 'time' and rel_key not in APPLICATION_TIME_ALLOWLIST:
                    hits.append((rel, node.lineno,
                                 '应用层不得 import time —— 时序控制须走注入的 ClockPort'))
                elif root in APPLICATION_FORBIDDEN:
                    hits.append((rel, node.lineno,
                                 f'应用层不得 import {node.module} —— '
                                 f'{APPLICATION_FORBIDDEN[root]}'))

            # 2) ★ 依赖倒置：不得 import adapters（或 presentation）
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                if mod.startswith('server_manager_v8.'):
                    if not mod.startswith(APPLICATION_ALLOWED_INTERNAL):
                        hits.append((rel, node.lineno,
                                     f'★ 违反依赖倒置：应用层 import {mod} —— '
                                     f'只允许依赖 domain，实现在 container 装配时注入'))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('server_manager_v8.'):
                        if not alias.name.startswith(APPLICATION_ALLOWED_INTERNAL):
                            hits.append((rel, node.lineno,
                                         f'★ 违反依赖倒置：应用层 import {alias.name} —— '
                                         f'只允许依赖 domain'))

            # 3) 禁止复刻领域判定字面量
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in APPLICATION_FORBIDDEN_LITERALS:
                    hits.append((rel, node.lineno,
                                 f'出现领域状态字面量 {node.value!r} —— '
                                 f'{APPLICATION_FORBIDDEN_LITERALS[node.value]}'))

    for rel, lineno, msg in hits:
        print(f'❌ {rel}:L{lineno}  {msg}')
    return hits


if __name__ == '__main__':
    sys.exit(main())
