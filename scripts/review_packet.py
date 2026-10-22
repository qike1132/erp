#!/usr/bin/env python3
"""生成代码评审包（只读）。

把「一个 CL 里改了什么、风险在哪、必须查什么、必须跑什么」一次性摊开，
让评审者不用靠翻 diff 猜重点。不修改工作区、不连数据库、不联网。

用法::

    python scripts/review_packet.py
    python scripts/review_packet.py --base origin/main
    python scripts/review_packet.py --base main --json
    python scripts/review_packet.py --base main --out logs/review-packet.md
    python scripts/review_packet.py --base main --fail-on-blocker   # CI 用

退出码：0 正常；1 发现 Blocker 且指定了 --fail-on-blocker；2 git 出错。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 有效行统计时排除的生成物 / 锁文件（它们不该撑大「评审批量」）
GENERATED_MARKERS = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "frontend-vite/dist/",
    ".min.js",
    ".min.css",
    ".map",
    "__pycache__/",
    ".pyc",
    ".snap",
)

PROD_CRITICAL = (
    "fastapi_app/core/prod_runner.py",
    "start.py",
    "server_manager.py",
    "server_manager/",
    "config/nginx",
    "config/pgbouncer/",
    "deploy/",
)

GATE_CONFIG = (
    ".githooks/",
    ".github/",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "ruff.toml",
    "mypy.ini",
    "alembic.ini",
    "scripts/quality_gate.py",
)

SENSITIVE_PREFIXES = (
    "_ops/credentials/",
    "config/pgbouncer/userlist.txt",
)
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
SENSITIVE_NAMES = ("id_rsa", "id_ed25519")

DOC_ASSET_PREFIXES = ("docs/", "deliverables/", "mockups/")


def is_sensitive(path: str) -> bool:
    """凭据/密钥文件。口径与 `scripts/scan_secrets.py` 的 `_KEY_SUFFIXES` / 名称片段对齐。

    `.env.example` 是模板（env_drift 门禁还要求同步它），不算敏感；`.envrc` 也不是。
    """
    name = path.rsplit("/", 1)[-1]
    if path.startswith(SENSITIVE_PREFIXES) or path.endswith(SENSITIVE_SUFFIXES):
        return True
    if name in SENSITIVE_NAMES:
        return True
    return path == ".env" or (path.startswith(".env.") and not path.endswith(".example"))


def is_test_path(path: str) -> bool:
    return path.startswith(("tests/", "fastapi_app/tests/")) or ".test." in path


SELF_PATH = "scripts/review_packet.py"


def is_suppression_site(path: str, line: str) -> bool:
    """真正的抑制是「行尾注释」；纯注释行与规则定义文件自身不算。

    例外：`secret-scan:allow-next-line` 本身就是独立一行声明，
    它豁免的是**下一行**，所以这行注释必须算作抑制点。
    """
    if path == SELF_PATH:
        return False
    stripped = line.strip()
    if stripped.startswith(("#", "//", "*", "/*", "<!--")):
        return "allow-next-line" in stripped
    return True


def is_code(path: str) -> bool:
    """内容规则只审生产代码。

    文档示例、测试夹具、工具自身的正则字面量都不该触发风险标记
    （本仓实测：评审包的 `.md` 说明与单测夹具曾把 4 类规则全部误报）。
    """
    if path.endswith(".md") or is_test_path(path):
        return False
    return path.startswith(("fastapi_app/", "frontend-vite/src/", "utils/", "server_manager/")) or path == "start.py"

LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("后端 API", ("fastapi_app/api/",)),
    ("后端服务/核心", ("fastapi_app/services/", "fastapi_app/core/", "fastapi_app/utils/", "utils/")),
    ("模型/迁移", ("fastapi_app/models/", "fastapi_app/schemas/", "migrations/")),
    ("前端", ("frontend-vite/",)),
    ("测试", ("tests/", "fastapi_app/tests/")),
    ("运维/配置", ("scripts/", "config/", "deploy/", ".githooks/", ".github/", "requirements/")),
    ("文档", ("docs/", "deliverables/", "mockups/")),
)

SUPPRESSION_PATTERNS = {
    "noqa": re.compile(r"#\s*noqa", re.IGNORECASE),
    "nosec": re.compile(r"#\s*nosec", re.IGNORECASE),
    "type: ignore": re.compile(r"#\s*type:\s*ignore", re.IGNORECASE),
    "secret-scan:allow": re.compile(r"secret-scan:allow", re.IGNORECASE),
}

BROAD_EXCEPT = re.compile(r"^\s*except\s+(?:Exception|BaseException)\b")
NAIVE_DATETIME = re.compile(r"datetime\.(?:now|utcnow)\(\s*\)")
PRINT_CALL = re.compile(r"^\s*print\(")
TODO_MARK = re.compile(r"\b(TODO|FIXME|XXX)\b")
MONEY_WORD = re.compile(r"(amount|price|total|cost|money|金额|单价|总价)", re.IGNORECASE)


class PacketError(RuntimeError):
    """git 调用失败或仓库状态不支持生成评审包。"""


@dataclass
class ChangedFile:
    status: str
    path: str
    old_path: str | None = None
    added: int = 0
    deleted: int = 0
    binary: bool = False
    layer: str = "其他"

    @property
    def lines(self) -> int:
        return self.added + self.deleted

    @property
    def generated(self) -> bool:
        return any(marker in self.path for marker in GENERATED_MARKERS)


@dataclass
class Risk:
    level: str
    title: str
    why: str
    action: str


@dataclass
class Packet:
    base: str
    head: str
    merge_base: str
    commits: list[str] = field(default_factory=list)
    files: list[ChangedFile] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    dirty_count: int = 0
    effective_added: int = 0
    effective_deleted: int = 0
    generated_at: str = ""

    @property
    def effective_lines(self) -> int:
        return self.effective_added + self.effective_deleted


def git(*args: str) -> str:
    """执行 git 并返回 stdout；失败抛 PacketError（不吞错）。"""
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise PacketError(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc.stdout


def try_git(*args: str) -> str | None:
    try:
        return git(*args)
    except PacketError:
        return None


def _remote_main_refs() -> list[str]:
    """列出所有远端 main 引用（本仓远端名是 erp，不是 origin）。"""
    raw = try_git("for-each-ref", "--format=%(refname:short)", "refs/remotes") or ""
    refs = [line.strip() for line in raw.splitlines() if line.strip()]
    return [ref for ref in refs if ref.endswith("/main")]


def resolve_base(explicit: str | None) -> str:
    if explicit:
        return explicit
    candidates = ["origin/main", *_remote_main_refs(), "main"]
    for candidate in dict.fromkeys(candidates):
        if try_git("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"):
            return candidate
    if try_git("rev-parse", "--verify", "--quiet", "HEAD~1^{commit}"):
        print(
            "review_packet: 未找到任何 main 引用，回退 HEAD~1 —— 评审范围可能不是完整 CL，请显式 --base",
            file=sys.stderr,
        )
        return "HEAD~1"
    raise PacketError("无法确定 base：请用 --base 显式指定（如 --base erp/main）")


def rename_target(path_field: str) -> str:
    """把 `old => new` / `dir/{old => new}/f` 归一成新路径。"""
    if " => " not in path_field:
        return path_field
    if "{" in path_field:
        collapsed = re.sub(r"\{[^{}]* => ([^{}]*)\}", r"\1", path_field)
        return collapsed.replace("//", "/")
    return path_field.split(" => ")[-1].strip()


def parse_name_status(text: str) -> list[tuple[str, str, str | None]]:
    entries: list[tuple[str, str, str | None]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]
        if status in {"R", "C"} and len(parts) >= 3:
            entries.append((status, parts[2], parts[1]))
        else:
            entries.append((status, parts[1], None))
    return entries


def parse_numstat(text: str) -> dict[str, tuple[int, int, bool]]:
    stats: dict[str, tuple[int, int, bool]] = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path_field = parts[0], parts[1], parts[2]
        path = rename_target(path_field)
        binary = added_raw == "-" or deleted_raw == "-"
        added = 0 if binary else int(added_raw)
        deleted = 0 if binary else int(deleted_raw)
        stats[path] = (added, deleted, binary)
    return stats


def classify(path: str) -> str:
    for name, prefixes in LAYERS:
        if path.startswith(prefixes):
            return name
    return "其他"


def collect_files(base: str, head: str) -> list[ChangedFile]:
    name_status = git("diff", "--name-status", "-M", f"{base}...{head}")
    numstat = parse_numstat(git("diff", "--numstat", "-M", f"{base}...{head}"))
    files: list[ChangedFile] = []
    for status, path, old_path in parse_name_status(name_status):
        added, deleted, binary = numstat.get(path, (0, 0, False))
        files.append(
            ChangedFile(
                status=status,
                path=path,
                old_path=old_path,
                added=added,
                deleted=deleted,
                binary=binary,
                layer=classify(path),
            )
        )
    return sorted(files, key=lambda item: (item.layer, item.path))


DIFF_ARGS: tuple[str, ...] = (
    "diff",
    "-U0",
    "--no-color",
    # 用户可能配了 diff.noprefix / diff.mnemonicPrefix，让 git 输出裸文件名而
    # 不带 a/ b/ 前缀。不显式钉住前缀时，下面的 "+++ b/" 匹配会全部失手，
    # 风险规则静默变成零命中——看起来「无风险」，其实是没看。
    "--src-prefix=a/",
    "--dst-prefix=b/",
)


def parse_added_lines(diff: str) -> dict[str, list[str]]:
    """按文件收集新增行（只看 + 行，用于风险规则）。"""
    added: dict[str, list[str]] = {}
    current: str | None = None
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[len("+++ b/") :]
            added.setdefault(current, [])
            continue
        if raw.startswith("+++ ") or raw.startswith("--- ") or raw.startswith("Binary files"):
            current = None
            continue
        if current and raw.startswith("+") and not raw.startswith("+++"):
            added[current].append(raw[1:])
    return added


def collect_added_lines(base: str, head: str) -> dict[str, list[str]]:
    return parse_added_lines(git(*DIFF_ARGS, f"{base}...{head}"))


def all_added(added: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(path, line) for path, lines in added.items() for line in lines]


def baseline_increases(base: str, head: str) -> list[str]:
    """gate_baseline 只允许下调；返回上调的键。"""
    path = "scripts/gate_baseline.json"
    base_raw = try_git("show", f"{base}:{path}")
    head_raw = try_git("show", f"{head}:{path}")
    if not base_raw or not head_raw:
        return []
    try:
        base_counts = json.loads(base_raw).get("counts", {})
        head_counts = json.loads(head_raw).get("counts", {})
    except json.JSONDecodeError:
        return ["scripts/gate_baseline.json 无法解析，需人工确认"]
    raised = []
    for key, value in head_counts.items():
        if key not in base_counts:
            continue  # 基线里没有这个键 = 新增门禁项，不算上调
        before = base_counts[key]
        if isinstance(value, int) and isinstance(before, int) and value > before:
            raised.append(f"{key}: {before} → {value}")
    return raised


def detect_risks(
    files: list[ChangedFile],
    added: dict[str, list[str]],
    base: str,
    head: str,
    dirty_count: int,
) -> list[Risk]:
    risks: list[Risk] = []
    paths = [item.path for item in files]
    flat = all_added(added)
    flat_code = [(path, line) for path, line in flat if is_code(path)]

    if any(path.startswith("migrations/versions/") for path in paths):
        risks.append(
            Risk(
                "H",
                "迁移改动",
                "迁移一旦在生产跑错，回滚成本高且可能锁表。",
                "确认单 head、无破坏性 DDL、回填分批；在临时空库跑 upgrade head + downgrade。",
            )
        )

    critical = [path for path in paths if path.startswith(PROD_CRITICAL)]
    if critical:
        risks.append(
            Risk(
                "H",
                f"生产启动/运维路径改动（{len(critical)} 个文件）",
                "这类改动直接影响生产可用性，且本机没有独立测试环境。",
                "写出回滚路径；重启前确认工作区在 main；重启后核实实际加载的代码指纹。",
            )
        )

    gate_config = [path for path in paths if path.startswith(GATE_CONFIG)]
    if gate_config:
        risks.append(
            Risk(
                "H",
                f"门禁/钩子/CI 配置改动（{len(gate_config)} 个文件）",
                "门禁放松会让后续所有提交失去保护，且很难事后发现。",
                "确认只收紧不放松；跑 `quality_gate.py --self-test`；基线只允许下调。",
            )
        )

    sensitive = [path for path in paths if is_sensitive(path)]
    if sensitive:
        risks.append(
            Risk(
                "B",
                "凭据/密钥相关文件改动",
                "本仓曾把 428 个浏览器凭据文件提交入库；凭据泄露不可回滚。",
                "确认文件未被 git 跟踪（git ls-files）；跑密钥扫描；泄露则轮换凭据。",
            )
        )

    tests_changed = any(is_test_path(path) for path in paths)
    logic_changed = any(
        not item.generated
        and item.path.startswith(("fastapi_app/", "frontend-vite/src/"))
        and not is_test_path(item.path)
        for item in files
    )
    ops_changed = any(
        not item.generated
        and not item.path.startswith((*DOC_ASSET_PREFIXES, "fastapi_app/", "frontend-vite/src/"))
        for item in files
    )
    if logic_changed and not tests_changed:
        risks.append(
            Risk(
                "H",
                "改了业务代码但没有测试改动",
                "逻辑缺陷门禁拦不住，唯一防线是改动对应的测试。",
                "说明为什么不需要测试，或补一条会红的测试；交付前做变异检查。",
            )
        )
    elif ops_changed and not tests_changed:
        risks.append(
            Risk(
                "M",
                "配置/运维/脚本改动且无测试改动",
                "这类改动未必需要测试，但「为什么不需要」必须有人回答。",
                "在 PR 里说明验证方式（演练/回滚/只读探针），能配测试的配测试。",
            )
        )

    deleted_tests = [item.path for item in files if item.status == "D" and is_test_path(item.path)]
    if deleted_tests:
        risks.append(
            Risk("H", f"删除了 {len(deleted_tests)} 个测试文件", "删除测试通常意味着覆盖缺口被静默扩大。", "确认对应行为已有替代覆盖，否则补回。")
        )

    for name, pattern in SUPPRESSION_PATTERNS.items():
        # secret-scan:allow 是仓库文档化的豁免标记，代码/配置都算，但文档示例与测试夹具不算；
        # 其余抑制标记只审生产代码（本仓实测：`.md` 说明与单测夹具曾把规则全部误报）。
        if name == "secret-scan:allow":
            pool = [
                (p, line)
                for p, line in flat
                if not p.endswith(".md") and not is_test_path(p) and is_suppression_site(p, line)
            ]
        else:
            pool = [(p, line) for p, line in flat_code if is_suppression_site(p, line)]
        hits = [(path, line) for path, line in pool if pattern.search(line)]
        if hits:
            sample = ", ".join(sorted({path for path, _ in hits})[:3])
            risks.append(
                Risk(
                    "M",
                    f"新增 {len(hits)} 处 `{name}` 抑制",
                    "每个抑制都是人工核验过的例外，可能掩盖真实缺陷。",
                    f"逐处写理由；确认不是为过门禁而加。涉及：{sample}",
                )
            )

    broad = [(path, line) for path, line in flat_code if BROAD_EXCEPT.match(line)]
    if broad:
        risks.append(
            Risk(
                "M",
                f"新增 {len(broad)} 处宽泛 `except Exception`",
                "吞掉异常会把故障变成更贵的行为缺陷（本仓已发生过）。",
                "收窄异常类型；确需兜底用 `# defensive: <理由>` 并保证日志可定位。",
            )
        )

    naive = [(path, line) for path, line in flat_code if NAIVE_DATETIME.search(line)]
    if naive:
        risks.append(
            Risk(
                "M",
                f"新增 {len(naive)} 处无时区 `datetime.now()/utcnow()`",
                "本仓出现过 tz-naive 订单日期导致的日期错位。",
                "改用 `datetime.now(timezone.utc)` 或统一走项目时间工具。",
            )
        )

    binding = [
        (path, line)
        for path, line in flat_code
        if "0.0.0.0" in line and (path.startswith("fastapi_app/") or path in {"start.py"} or path.startswith("server_manager"))
    ]
    if binding:
        risks.append(
            Risk(
                "B",
                "后端绑定 0.0.0.0",
                "绕过 nginx，并把 /metrics 暴露给同网段（红线）。",
                "改回 127.0.0.1；确需对外只经 nginx。",
            )
        )

    insecure = [
        (path, line)
        for path, line in flat_code
        if re.search(r"verify\s*=\s*False|shell\s*=\s*True", line) and not path.startswith(("tests/", "scripts/"))
    ]
    if insecure:
        risks.append(
            Risk("H", f"新增 {len(insecure)} 处不安全调用（verify=False / shell=True）", "关闭证书校验或走 shell 会引入注入与中间人风险。", "改回安全写法；确需例外须安全评审。")
        )

    contract = [path for path in paths if path.startswith(("fastapi_app/api/", "frontend-vite/src/api/", "frontend-vite/src/types/"))]
    if contract:
        risks.append(
            Risk(
                "M",
                "接口契约面改动",
                "前端新、后端旧（或反之）会造成「半坏」状态，最难排查。",
                "跑 check:api / check:routes / check:dto / check:types；确认字段同源。",
            )
        )

    baseline_path = "scripts/gate_baseline.json"
    if baseline_path in paths and not try_git("show", f"{base}:{baseline_path}"):
        risks.append(
            Risk(
                "M",
                "新增门禁基线文件",
                "基线是棘轮的起点，初值必须来自实测，不能拍脑袋。",
                "用 `quality_gate.py --update-baseline` 生成并说明各项来源。",
            )
        )

    raised = baseline_increases(base, head)
    if raised:
        risks.append(
            Risk(
                "B",
                "质量门禁基线被上调",
                "基线棘轮只允许下调；上调等于把新增违规洗成存量。",
                f"还原为原值或由 owner 书面批准。上调项：{'; '.join(raised)}",
            )
        )

    if any(item.status == "D" and not item.path.startswith(("tests/", "docs/")) for item in files):
        risks.append(
            Risk(
                "M",
                "删除了非测试文件",
                "本仓大量模块经 __init__.py 聚合接入，前缀 grep 会误判死代码。",
                "按全仓导入（ast）逐个确认零引用；确认不是删到夹在中间的活名字。",
            )
        )

    if dirty_count:
        risks.append(
            Risk(
                "L",
                f"工作区有 {dirty_count} 个未提交改动",
                "评审包只覆盖已提交内容；并发会话的改动不应混入本次评审。",
                "确认这些改动不属于本 CL；提交时只 add 本任务文件。",
            )
        )

    print_hits = [(path, line) for path, line in flat_code if PRINT_CALL.match(line) and path.startswith("fastapi_app/")]
    if print_hits:
        risks.append(Risk("L", f"新增 {len(print_hits)} 处 print()", "生产代码应走 logger，print 无法分级与轮转。", "改用 logger。"))
    todo_hits = [(path, line) for path, line in flat_code if TODO_MARK.search(line)]
    if todo_hits:
        risks.append(Risk("L", f"新增 {len(todo_hits)} 处 TODO/FIXME", "未闭环的标记容易变成永久债。", "转 issue 或在本 CL 解决。"))

    money = [
        (path, line)
        for path, line in flat_code
        if path.startswith("fastapi_app/services/") and "float(" in line and MONEY_WORD.search(line)
    ]
    if money:
        risks.append(Risk("M", f"金额相关新增 {len(money)} 处 float()", "浮点误差会在对账时变成真实差额。", "全程 Decimal，格式化只在展示层。"))

    return risks


def build_checks(files: list[ChangedFile], risks: list[Risk]) -> list[str]:
    checks: list[str] = []
    paths = [item.path for item in files]
    risk_titles = " ".join(risk.title for risk in risks)

    if any(path.startswith("migrations/") for path in paths):
        checks += [
            "迁移：单 head、无破坏性 DDL、回填分批可重跑、down_revision 正确",
            "迁移：临时空库已跑 upgrade head + downgrade，并在 PR 贴输出",
        ]
    if any(path.startswith("fastapi_app/api/") for path in paths):
        checks += [
            "端点：权限依赖是否挂上、是否默认拒绝、响应模型是否漏/多字段",
            "端点：分页上限、参数校验、业务异常是否映射 4xx",
        ]
    if any(path.startswith("fastapi_app/services/") for path in paths):
        checks += [
            "事务：service 只 flush，独立事务有 `# manual-tx:` 理由",
            "并发/幂等：同时到达、重复提交、重试会不会产生第二条记录",
            "查询：N+1、IN 上限、软删除与越权过滤（user/角色）",
        ]
    if any(path.startswith("frontend-vite/src/") for path in paths):
        checks += [
            "前端：loading/empty/error 三态、请求竞态（旧响应覆盖新结果）",
            "前端：按钮权限与后端一致、金额日期格式化统一、无 any/console.log",
        ]
    if "契约" in risk_titles:
        checks.append("契约：前端字段来自 @/types，错误码与分页默认值未破坏")
    if any("/auth" in path or "permission" in path for path in paths):
        checks.append("权限：按 id 访问带 user/角色条件（IDOR），token 过期/注销路径覆盖")
    if any(path.startswith(("config/", "deploy/")) or path.startswith(".env") for path in paths):
        checks.append("配置：新增键已进 .env.example，默认值在生产安全，回滚路径明确")
    if "生产启动/运维路径改动" in risk_titles:
        checks.append("运维：重启前工作区在 main，重启后核实实际加载代码（字段指纹）")
    if any(item.path.startswith(("tests/", "fastapi_app/tests/")) or ".test." in item.path for item in files):
        checks.append("测试：期望值手工推导（非镜像断言）、会红、变异检查已做")

    return checks or ["按标准 §3.1 通用四问审：正确性 / 契约 / 失败路径 / 影响面"]


def build_commands(files: list[ChangedFile], risks: list[Risk]) -> list[str]:
    paths = [item.path for item in files]
    risk_titles = " ".join(risk.title for risk in risks)
    commands = ["python scripts/quality_gate.py"]

    if any(path.startswith("migrations/") for path in paths):
        commands += [
            "python scripts/check_alembic_heads.py",
            "pytest fastapi_app/tests/test_migration_autogenerate_safety.py -q",
        ]
    if any(path.startswith("fastapi_app/") for path in paths):
        commands.append("pytest -q   # 聚焦到改动模块，输出存文件后再分析")
    if any(path.startswith("frontend-vite/") for path in paths):
        commands += [
            "cd frontend-vite && npm run type-check && npm run lint && npm test",
            "cd frontend-vite && npm run build",
        ]
    if "契约" in risk_titles:
        commands.append("cd frontend-vite && npm run check:api && npm run check:routes && npm run check:dto && npm run check:types")
    if any(path.startswith(("config/", ".env", "scripts/ops/check_env_drift.py")) for path in paths):
        commands.append("python scripts/ops/check_env_drift.py")
    if any(path.startswith((".githooks/", ".github/", "scripts/quality_gate.py")) for path in paths):
        commands.append("python scripts/quality_gate.py --self-test")
    if "凭据/密钥相关文件改动" in risk_titles:
        commands.append("python scripts/scan_secrets.py --verbose")
    return commands


def count_dirty() -> int:
    raw = try_git("status", "--porcelain") or ""
    return len([line for line in raw.splitlines() if line.strip()])


def build_packet(base: str, head: str) -> Packet:
    merge_base = git("merge-base", base, head).strip()
    commits = [line for line in git("log", "--oneline", f"{base}..{head}").splitlines() if line.strip()]
    files = collect_files(base, head)
    added = collect_added_lines(base, head)
    dirty = count_dirty()

    packet = Packet(
        base=base,
        head=head,
        merge_base=merge_base,
        commits=commits,
        files=files,
        dirty_count=dirty,
        generated_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
    )
    packet.risks = detect_risks(files, added, base, head, dirty)
    packet.checks = build_checks(files, packet.risks)
    packet.commands = build_commands(files, packet.risks)
    packet.effective_added = sum(item.added for item in files if not item.generated)
    packet.effective_deleted = sum(item.deleted for item in files if not item.generated)
    return packet


def render_markdown(packet: Packet) -> str:
    lines: list[str] = [
        "# 代码评审包",
        "",
        f"- 范围：`{packet.base}...{packet.head}`（merge-base `{packet.merge_base[:12]}`）",
        f"- 提交：{len(packet.commits)} 个",
        f"- 变更：{len(packet.files)} 个文件，有效 `+{packet.effective_added}/-{packet.effective_deleted}` 行",
        f"- 生成：{packet.generated_at}",
        "",
        "## 1. 提交",
        "",
    ]
    lines += [f"- `{commit}`" for commit in packet.commits] or ["- （无提交）"]
    lines += ["", "## 2. 变更清单", ""]

    for layer, _ in LAYERS:
        group = [item for item in packet.files if item.layer == layer]
        if not group:
            continue
        total = sum(item.lines for item in group)
        lines.append(f"### {layer}（{len(group)} 个文件，{total} 行）")
        lines.append("")
        lines.append("| 状态 | 文件 | + | - |")
        lines.append("|---|---|---|---|")
        for item in group:
            mark = "（生成物）" if item.generated else ""
            lines.append(f"| {item.status} | `{item.path}`{mark} | {item.added} | {item.deleted} |")
        lines.append("")

    others = [item for item in packet.files if item.layer == "其他"]
    if others:
        lines.append("### 其他")
        lines.append("")
        for item in others:
            lines.append(f"- `{item.path}`（{item.status}，+{item.added}/-{item.deleted}）")
        lines.append("")

    lines += ["## 3. 风险标记（先看这里）", ""]
    if packet.risks:
        lines.append("| 级别 | 标记 | 为什么 | 要求 |")
        lines.append("|---|---|---|---|")
        for risk in packet.risks:
            lines.append(f"| `{risk.level}` | {risk.title} | {risk.why} | {risk.action} |")
    else:
        lines.append("未命中自动风险规则——**不等于安全**，仍按标准 §3.1 四问人工审。")
    lines.append("")

    lines += ["## 4. 评审重点", ""]
    lines += [f"- [ ] {check}" for check in packet.checks]
    lines.append("")

    lines += ["## 5. 必跑命令", "", "```bash"]
    lines += packet.commands
    lines += ["```", ""]

    lines += [
        "## 6. 证据待填",
        "",
        "| 声称 | 命令 | 结果 |",
        "|---|---|---|",
        "| 门禁通过 | `python scripts/quality_gate.py` | |",
        "| 聚焦测试 | | |",
        "| 红→绿（修复类） | | |",
        "| 变异检查 | | |",
        "",
        "> 分级标准见 `docs/agents/code-review-standard.md`，流程见 `docs/agents/code-review-process.md`。",
    ]
    return "\n".join(lines) + "\n"


def emit(packet: Packet, as_json: bool, out: str | None) -> None:
    if as_json:
        payload = {
            "base": packet.base,
            "head": packet.head,
            "merge_base": packet.merge_base,
            "commits": packet.commits,
            "files": [asdict(item) for item in packet.files],
            "risks": [asdict(risk) for risk in packet.risks],
            "checks": packet.checks,
            "commands": packet.commands,
            "summary": {
                "file_count": len(packet.files),
                "effective_added": packet.effective_added,
                "effective_deleted": packet.effective_deleted,
                "dirty_count": packet.dirty_count,
                "blockers": sum(1 for risk in packet.risks if risk.level == "B"),
                "highs": sum(1 for risk in packet.risks if risk.level == "H"),
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = render_markdown(packet)

    if out:
        target = Path(out)
        if not target.is_absolute():
            target = REPO_ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"评审包已写入 {target}")
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成代码评审包（只读）")
    parser.add_argument("--base", help="评审基线 ref（默认 origin/main → main → HEAD~1）")
    parser.add_argument("--head", default="HEAD", help="评审终点 ref（默认 HEAD）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--out", help="写入文件（默认打印到 stdout）")
    parser.add_argument("--max-lines", type=int, default=400, help="有效 diff 行数上限（默认 400）")
    parser.add_argument("--fail-on-blocker", action="store_true", help="存在 Blocker 时退出码 1")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        base = resolve_base(args.base)
        packet = build_packet(base, args.head)
    except PacketError as exc:
        print(f"review_packet: {exc}", file=sys.stderr)
        return 2

    if packet.effective_lines > args.max_lines:
        packet.risks.append(
            Risk(
                "M",
                f"有效 diff 超过 {args.max_lines} 行（实际 {packet.effective_lines}）",
                "过大的 CL 会让评审退化成扫读，真问题被淹没。",
                "拆分为多个 CL；机械改动（重命名/格式化/锁文件）单独提交。",
            )
        )

    emit(packet, args.json, args.out)

    blockers = [risk for risk in packet.risks if risk.level == "B"]
    if blockers and args.fail_on_blocker:
        print(f"review_packet: 发现 {len(blockers)} 个 Blocker", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
