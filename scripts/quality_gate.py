r"""统一代码质量门禁 runner（基线棘轮 / ratchet）。

为什么需要它
------------
`scripts/check_*.py` 这批 AST 门禁脚本已经写好，但此前只有 `file_size_gate.py`
接进了 CI，其余 5 个既不在 pre-commit 也不在 CI —— 等于门禁不存在。
直接把它们接进去又会立刻报红（存量违规：超长函数 11、宽泛 except 14、
service 层 commit 9、N+1 8、巨型组件 6），红着的门禁最终一定会被人关掉。

所以本 runner 采用**基线棘轮**语义：
  - 存量违规记录在 `scripts/gate_baseline.json`，不阻断；
  - 违规数**超过基线**即失败（有人新增了问题）；
  - 违规数**少于基线**则提示可以收紧基线（自动提示 `--update-baseline`）；
  - 门禁只可能变严，不会变松。

P0-11（2026-10-01）加固：违规数只来自机器可读来源
--------------------------------------------------
1. **不再解析子脚本的人类可读 stdout**。原先的正则
   `COUNT_RE = r"\[FAIL\][^\d]*(\d+)\s*(?:处|个)"` 已删除，违规数只有三种来源：
     * 子脚本 `--json` 输出的 JSON 字段（语义解析，允许 JSON 之后跟人类可读尾巴）；
     * 进程退出码（`mode="exit"`，只对基线为 0 的门禁有意义）；
     * `ruff --output-format json` 的诊断数组长度。
   任何门禁拿不到机器可读计数 → 按「环境/解析异常」保守失败（退出码 2），
   绝不静默记 0（这正是改输出就能把门禁变绿的那个洞）。
2. `--self-test`：**恒失败自检**。在临时目录里制造真实违规，断言本 runner 的
   退出码非 0；再移除违规，断言退出码回到 0。全程用 `--only` 隔离单门禁，
   不依赖其它门禁（尤其不依赖 env_drift）的状态；输出行一律 `[SELFTEST]` 前缀，
   且不含 `[FAIL]` 字面量。
3. `ruff` 门禁：把 `scripts/`、`server_manager/` 纳入棘轮基线。命令行**不追加**
   `--select`/`--ignore`，直接用 `ruff.toml` 已评审的口径（CLI 覆盖会绕过仓库
   ignore 清单）；要豁免只能在 `ruff.toml` 的 `[tool.ruff.lint.per-file-ignores]`
   里写具体规则 + 理由。
4. `pip_audit` 门禁：`[[tool.code-quality.pip-audit-ignores]]` 策略校验 ——
   id/reason/expires(ISO) 必填、过期即失败、有效期 >180 天失败、重复 id 失败、
   **僵尸条目**（当前漏洞库里匹配不到该 id）失败；并打印豁免条数与 ≤30 天内
   即将到期的条目。僵尸判定需要漏洞库数据：CI 用 `--audit-report` 传入现场
   `pip-audit --format json` 的结果，本地没有数据时如实 WARN 并跳过该项。
   本地现场审计的目标是**生产运行时** `.venv/Lib/site-packages`（pip_audit
   `--path` 模式）；无 `.venv` 时回退审计门禁自身解释器环境。

用法
----
    python scripts/quality_gate.py                    # 判定：新增违规即退出码 1
    python scripts/quality_gate.py --report           # 只报告，永不失败（人工巡检用）
    python scripts/quality_gate.py --update-baseline  # 重建基线（收紧时用）
    python scripts/quality_gate.py --verbose          # 打印失败门禁的机器可读输出
    python scripts/quality_gate.py --only n_plus_one  # 只跑某个门禁
    python scripts/quality_gate.py --self-test        # 恒失败自检（全部门禁）
    python scripts/quality_gate.py --self-test --only bare_except
    python scripts/quality_gate.py --only pip_audit --audit-report dependency-audit.json

阈值来自 `pyproject.toml` 的 `[tool.code-quality]`，缺省时回落到内置默认值。

退出码：0 = 无新增；1 = 有新增违规；2 = 环境/解析异常（保守失败）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = PROJECT_ROOT / "scripts" / "gate_baseline.json"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

DEFAULTS = {
    "max_function_length": 80,
    "max_vue_component_length": 400,
    "pip_audit_max_days": 180,
}

# 违规数的机器可读来源
MODE_JSON = "json"          # 子脚本 --json，stdout 起始处是 JSON 对象
MODE_EXIT = "exit"          # 只用退出码（0 = 0 违规；非 0 = 有违规，计数未知）
MODE_RUFF = "ruff"          # ruff --output-format json，计数 = 诊断数组长度
MODE_PIP_AUDIT = "pip-audit"  # 进程内校验 pyproject.toml 的豁免策略

SELFTEST_PREFIX = "[SELFTEST]"
RUFF_TARGETS = ("scripts", "server_manager")
# 复杂度 / 循环遮蔽门禁的扫描面：后端 + 脚本 + 桌面壳（第一方 Python）。
# 与 RUFF_TARGETS 不同——这两条规则的存量主要在 fastapi_app。
COMPLEXITY_TARGETS = ("fastapi_app", "scripts", "server_manager")


@dataclass(frozen=True)
class Gate:
    key: str
    title: str
    mode: str
    fix_hint: str
    script: str = ""
    extra_args: tuple[str, ...] = ()
    count_key: str = "total"
    accepts_paths: bool = False
    # 仅 MODE_RUFF 用：select 非空时命令行追加 `--select <select>`（供 C901/PLW2901
    # 这类**不进全局 select** 的规则单独设门禁——进全局会打红 CI 的 ruff 步骤）；
    # targets 非空时覆盖默认扫描面（默认 RUFF_TARGETS = scripts + server_manager）。
    select: str = ""
    targets: tuple[str, ...] = ()

    def argv(self, thresholds: dict[str, int], probe_dir: Path | None = None) -> list[str]:
        """构造调用命令（阈值来自 pyproject，按门禁类型注入）。"""
        if self.mode == MODE_RUFF:
            if probe_dir is not None:
                return [ruff_bin(), "check", str(probe_dir), "--select", self.select or "F401",
                        "--output-format", "json", "--no-cache"]
            cmd = [ruff_bin(), "check", *(self.targets or RUFF_TARGETS)]
            if self.select:
                cmd += ["--select", self.select]
            return [*cmd, "--output-format", "json", "--no-cache"]
        base = [sys.executable, str(PROJECT_ROOT / self.script), *self.extra_args]
        if self.key == "function_length":
            base += ["--max-length", str(thresholds["max_function_length"])]
        elif self.key == "vue_component_length":
            base += ["--max-length", str(thresholds["max_vue_component_length"])]
        if probe_dir is not None and self.accepts_paths:
            base += [str(probe_dir)]
        return base


GATES: tuple[Gate, ...] = (
    Gate(
        key="n_plus_one",
        title="N+1 查询（循环内 execute/scalar/scalars）",
        mode=MODE_JSON,
        script="scripts/check_n_plus_one.py",
        extra_args=("--json",),
        fix_hint="改 selectinload/joinedload 一次性加载，或收集外键 IN 批量查 + defaultdict 内存分组",
        accepts_paths=True,
    ),
    Gate(
        key="bare_except",
        title="裸 except / 宽泛 except Exception",
        mode=MODE_JSON,
        script="scripts/check_bare_except.py",
        extra_args=("--json",),
        fix_hint="收窄到具体异常类型；确需兜底请加 `# defensive: <理由>` 标注或登记白名单",
        accepts_paths=True,
    ),
    Gate(
        key="function_length",
        title="后端超长函数",
        mode=MODE_JSON,
        script="scripts/check_function_length.py",
        extra_args=("--json",),
        fix_hint="按职责拆分为私有辅助函数（单函数 ≤ 阈值行）",
        accepts_paths=True,
    ),
    Gate(
        key="vue_component_length",
        title="前端巨型 Vue 组件",
        mode=MODE_JSON,
        script="scripts/check_vue_component_length.py",
        extra_args=("--json",),
        fix_hint="拆子组件或把逻辑抽到 composable（单 SFC ≤ 阈值行）",
        accepts_paths=True,
    ),
    Gate(
        key="service_commit",
        title="service 层手动 commit()",
        mode=MODE_JSON,
        script="scripts/check_service_commit.py",
        extra_args=("--json",),
        fix_hint="改 flush-only，提交交给 get_async_db / db_transaction；"
        "确需独立事务时按 docs/TRANSACTION_BOUNDARY_GUIDE.md 标注 `# manual-tx: <理由>`",
        accepts_paths=True,
    ),
    Gate(
        key="bom",
        title="以 UTF-8 BOM 开头的 .py（AST 工具会静默跳过）",
        mode=MODE_EXIT,
        script="scripts/check_bom.py",
        fix_hint="跑 `python scripts/fix_bom.py` 剥离 BOM；编辑器保存为「UTF-8 无 BOM」",
        accepts_paths=True,
    ),
    Gate(
        key="alembic_heads",
        title="Alembic 迁移图形状（单 head / root 数不增）",
        mode=MODE_EXIT,
        script="scripts/check_alembic_heads.py",
        fix_hint="合并分支用 `alembic merge -m \"merge heads\" <rev1> <rev2>`；"
        "新增 root 需评审后上调 EXPECTED_MAX_BASES",
    ),
    Gate(
        key="env_drift",
        title="环境变量漂移（代码引用 与 .env.example 模板）",
        mode=MODE_JSON,
        script="scripts/ops/check_env_drift.py",
        extra_args=("--json", "--ci"),
        count_key="fail_count",
        fix_hint="把缺失键补进 .env.example（占位值）或删掉失效键；"
        "带 .env.production 的全量检查请手动跑 `python scripts/ops/check_env_drift.py`",
    ),
    Gate(
        key="ruff",
        title="ruff 违规（scripts/ + server_manager/，ruff.toml 口径）",
        mode=MODE_RUFF,
        fix_hint="修掉 ruff 报出的问题；确需豁免只能在 ruff.toml 的 "
        "[tool.ruff.lint.per-file-ignores] 里写具体规则 + 理由"
        "（不允许新增裸 ignore，也不允许命令行 --select/--ignore 覆盖）",
        accepts_paths=True,
    ),
    # C901 / PLW2901 刻意**不进** ruff.toml 的全局 select（进全局会把 CI 的
    # `ruff check fastapi_app tests ...` 步骤打红）。这里用独立门禁 + 棘轮基线
    # 只拦新增；阈值 max-complexity=25 配在 ruff.toml 的 [lint.mccabe]。
    Gate(
        key="complexity",
        title="圈复杂度 C901（ruff --select C901，阈值见 ruff.toml [lint.mccabe]）",
        mode=MODE_RUFF,
        select="C901",
        targets=COMPLEXITY_TARGETS,
        fix_hint="按职责拆函数降低分支数（早返回 / 提取子函数）；"
        "确需保留大函数请评审后上调 ruff.toml 的 max-complexity 并说明理由",
        accepts_paths=True,
    ),
    Gate(
        key="loop_shadow",
        title="循环变量遮蔽（ruff --select PLW2901）",
        mode=MODE_RUFF,
        select="PLW2901",
        targets=COMPLEXITY_TARGETS,
        fix_hint="重命名内层循环变量，别复用外层循环名（PLW2901）",
        accepts_paths=True,
    ),
    Gate(
        key="pip_audit",
        title="pip-audit 豁免策略（[[tool.code-quality.pip-audit-ignores]]）",
        mode=MODE_PIP_AUDIT,
        fix_hint="每条豁免必须 id + reason + expires(ISO)，单条 ≤180 天；"
        "过期/僵尸(匹配不到现存漏洞)/重复 id 一律失败 —— "
        "修复方式是升级依赖后删掉豁免，而不是续期",
    ),
)


@dataclass
class GateOutcome:
    """单个门禁的执行结果。count is None 表示拿不到机器可读计数。"""

    rc: int | None
    count: int | None
    output: str = ""
    error: str | None = None
    unknown_violation: bool = False
    notes: tuple[str, ...] = ()


@dataclass
class Judgement:
    status: str
    line: str
    base: int | None = None
    count: int | None = None


def ruff_bin() -> str:
    """定位 ruff：优先 venv 内，其次 PATH。"""
    sibling = Path(sys.executable).parent / ("ruff.exe" if sys.platform == "win32" else "ruff")
    if sibling.exists():
        return str(sibling)
    return shutil.which("ruff") or "ruff"


def load_thresholds() -> dict[str, int]:
    """从 pyproject.toml 读取阈值，缺失或不可解析时回落默认值。"""
    thresholds = dict(DEFAULTS)
    if not PYPROJECT.exists():
        return thresholds
    try:
        import tomllib

        with PYPROJECT.open("rb") as fh:
            data = tomllib.load(fh)
        section = (data.get("tool") or {}).get("code-quality") or {}
        for key in DEFAULTS:
            value = section.get(key)
            if isinstance(value, int) and value > 0:
                thresholds[key] = value
    except Exception as exc:  # broad-except: 配置解析失败不应阻断门禁
        print(f"[WARN] 读取 pyproject.toml 失败，使用默认阈值：{exc}", file=sys.stderr)
    return thresholds


def _first_json_object(text: str) -> dict | None:
    """取出文本**起始处**的 JSON 对象（子脚本可能在 JSON 后追加人类可读尾巴）。"""
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    try:
        payload, _end = json.JSONDecoder().raw_decode(stripped)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _json_count(gate: Gate, text: str) -> int | None:
    payload = _first_json_object(text)
    if payload is None:
        return None
    value = payload.get(gate.count_key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _ruff_count(text: str) -> int | None:
    stripped = text.strip()
    if not stripped.startswith("["):
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        return None
    return len(payload) if isinstance(payload, list) else None


def _collect_vuln_ids(payload: object) -> set[str]:
    """从 pip-audit JSON（新版列表 / 旧版 {dependencies:[...]}）里收集漏洞 id。"""
    ids: set[str] = set()
    stack: list[object] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            vulns = node.get("vulns")
            if isinstance(vulns, list):
                for vuln in vulns:
                    if isinstance(vuln, dict) and isinstance(vuln.get("id"), str):
                        ids.add(vuln["id"])
            for key, value in node.items():
                if key in ("vulns", "dependencies"):
                    continue
                if isinstance(value, (list, dict)):
                    stack.append(value)
            deps = node.get("dependencies")
            if isinstance(deps, list):
                stack.extend(deps)
    return ids


def load_vuln_ids(audit_report: str | None) -> tuple[set[str] | None, str, str | None]:
    """返回 (漏洞 id 集合 | None, 数据来源说明, 硬错误)。None 表示无数据可用。"""
    if audit_report:
        path = Path(audit_report)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            return None, str(path), f"--audit-report 指定的漏洞报告不存在：{path}"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, str(path), f"--audit-report 无法解析为 JSON：{exc}"
        return _collect_vuln_ids(payload), str(path), None

    if importlib.util.find_spec("pip_audit") is None:
        return None, "pip-audit 未安装", None
    venv_site_packages = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
    if venv_site_packages.is_dir():
        # 生产运行时是 .venv（NSSM erp-prod/erp-arq 的解释器）；必须审计它的
        # site-packages，而不是门禁自身解释器（全局工具链）环境——后者会拿
        # litellm/tornado 等开发依赖的漏洞淹没生产信号。
        audit_argv = [
            sys.executable,
            "-m",
            "pip_audit",
            "--format",
            "json",
            "--path",
            str(venv_site_packages),
        ]
        source = f"现场 pip_audit --path 审计生产 venv（{venv_site_packages.relative_to(PROJECT_ROOT)}）"
    else:
        audit_argv = [sys.executable, "-m", "pip_audit", "--format", "json"]
        source = "现场 `python -m pip_audit --format json`（无 .venv，审计门禁解释器环境）"
    try:
        proc = subprocess.run(
            audit_argv,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"pip-audit 执行失败（{exc}）", None
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError as exc:
        return None, f"pip-audit 输出不可解析（{exc}）", None
    return _collect_vuln_ids(payload), source, None


def audit_ignores(
    entries: object,
    max_days: int,
    today: date,
    vuln_ids: set[str] | None,
) -> tuple[list[str], list[str], int]:
    """校验豁免条目。返回 (问题列表, ≤30 天内到期条目, 条目总数)。

    vuln_ids 为当前漏洞库里的 id 集合（None = 无数据，跳过僵尸/未豁免判定）：
      - 豁免条目对应的 id 不在库里 → 僵尸条目（漏洞已消失，豁免该删）；
      - 库里存在但没有任何**有效**豁免覆盖的 id → 未豁免漏洞（CI 的 pip-audit 会红）。
    """
    problems: list[str] = []
    expiring: list[str] = []
    active_ids: set[str] = set()
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        return ["[[tool.code-quality.pip-audit-ignores]] 必须是数组表（[[...]]）"], [], 0

    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        label = f"第 {index} 条豁免"
        entry_problems: list[str] = []
        if not isinstance(entry, dict):
            problems.append(f"{label}：不是 TOML 表（缺 id/reason/expires）")
            continue
        vuln_id = entry.get("id")
        reason = entry.get("reason")
        expires_raw = entry.get("expires")
        if not isinstance(vuln_id, str) or not vuln_id.strip():
            entry_problems.append(f"{label}：缺 id")
            vuln_id = None
        if not isinstance(reason, str) or not reason.strip():
            entry_problems.append(f"{label}（id={vuln_id}）：缺 reason（必须写清为什么豁免）")
        if not isinstance(expires_raw, str) or not expires_raw.strip():
            entry_problems.append(f"{label}（id={vuln_id}）：缺 expires（ISO 日期，如 2026-12-31）")
            problems.extend(entry_problems)
            continue
        try:
            expires = date.fromisoformat(expires_raw.strip())
        except ValueError:
            entry_problems.append(f"{label}（id={vuln_id}）：expires={expires_raw!r} 不是 ISO 日期")
            problems.extend(entry_problems)
            continue
        if vuln_id is not None:
            if vuln_id in seen:
                entry_problems.append(f"{label}（id={vuln_id}）：id 重复")
            seen.add(vuln_id)
        if expires < today:
            entry_problems.append(
                f"{label}（id={vuln_id}）：已于 {expires.isoformat()} 过期，必须处理"
            )
        remaining = (expires - today).days
        if remaining > max_days:
            entry_problems.append(
                f"{label}（id={vuln_id}）：有效期 {remaining} 天 > 上限 {max_days} 天"
                "（不允许变相永久豁免）"
            )
        if 0 <= remaining <= 30:
            expiring.append(f"{vuln_id}（{expires.isoformat()}，剩 {remaining} 天）")
        if vuln_ids is not None and vuln_id is not None and vuln_id not in vuln_ids:
            entry_problems.append(
                f"{label}（id={vuln_id}）：僵尸条目 —— 当前漏洞库里没有该 id，"
                "说明漏洞已消失/依赖已升级，请删除该豁免"
            )
        problems.extend(entry_problems)
        if not entry_problems and vuln_id is not None:
            active_ids.add(vuln_id)

    if vuln_ids is not None:
        for unhandled in sorted(vuln_ids - active_ids):
            problems.append(
                f"未豁免漏洞 {unhandled}：pip-audit 会因此失败，"
                "请升级依赖，或按流程登记豁免（id + reason + expires）"
            )
    return problems, expiring, len(entries)


def run_pip_audit_gate(thresholds: dict[str, int], audit_report: str | None) -> GateOutcome:
    """校验 pyproject.toml 里的 pip-audit 豁免策略（进程内，无子进程）。"""
    try:
        import tomllib

        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return GateOutcome(None, None, "", f"pyproject.toml 不可读/不可解析：{exc}")

    section = (data.get("tool") or {}).get("code-quality") or {}
    raw_entries = section.get("pip-audit-ignores", [])
    max_days = thresholds["pip_audit_max_days"]

    vuln_ids, source, hard_error = load_vuln_ids(audit_report)
    if hard_error is not None:
        return GateOutcome(None, None, "", hard_error)

    problems, expiring, total = audit_ignores(raw_entries, max_days, date.today(), vuln_ids)

    notes = [f"豁免条目 {total} 条；上限 {max_days} 天；漏洞数据来源：{source}"]
    if vuln_ids is not None:
        notes.append(f"漏洞库共 {len(vuln_ids)} 条已知漏洞（未豁免的会被本门禁拦下）")
    if expiring:
        notes.append("≤30 天内到期：" + "、".join(expiring))
    if vuln_ids is None:
        notes.append(
            "[WARN] 无漏洞库数据，僵尸条目检测已跳过"
            "（CI 请传 --audit-report 或在 lint job 安装 pip-audit）"
        )
    output = "\n".join(problems) if problems else "[PASS] pip-audit 豁免策略合规"
    return GateOutcome(
        rc=0 if not problems else 1,
        count=len(problems),
        output=output,
        notes=tuple(notes),
    )


def run_gate(
    gate: Gate,
    thresholds: dict[str, int],
    probe_dir: Path | None = None,
    audit_report: str | None = None,
) -> GateOutcome:
    """执行单个门禁，返回机器可读结果。"""
    if gate.mode == MODE_PIP_AUDIT:
        return run_pip_audit_gate(thresholds, audit_report)

    if gate.mode == MODE_RUFF and shutil.which(ruff_bin()) is None and not Path(ruff_bin()).exists():
        return GateOutcome(None, None, "", "找不到 ruff 可执行文件（pip install ruff）")

    if gate.script and not (PROJECT_ROOT / gate.script).exists():
        return GateOutcome(None, None, f"[SKIP] 未找到 {gate.script}", f"未找到子脚本 {gate.script}")

    try:
        proc = subprocess.run(
            gate.argv(thresholds, probe_dir),
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return GateOutcome(None, None, "", "超时（>300s）")
    except OSError as exc:
        return GateOutcome(None, None, "", f"无法执行：{exc}")

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()

    if gate.mode == MODE_EXIT:
        if proc.returncode == 0:
            return GateOutcome(0, 0, output)
        return GateOutcome(proc.returncode, None, output, unknown_violation=True)

    if gate.mode == MODE_RUFF:
        count = _ruff_count(proc.stdout or "")
        if count is None:
            return GateOutcome(proc.returncode, None, output,
                               "ruff --output-format json 的输出不是 JSON 数组")
        # 与 MODE_JSON 分支对齐：ruff 以非 0/1 退出（配置错误等）时不能采信 stdout 的数组，
        # 否则空数组会被当成 count=0 而判成 TIGHTEN，掩盖真实故障。
        if proc.returncode not in (0, 1):
            return GateOutcome(proc.returncode, None, output,
                               f"ruff 以退出码 {proc.returncode} 结束（环境/配置异常）")
        return GateOutcome(proc.returncode, count, output)

    count = _json_count(gate, proc.stdout or "")
    if count is None:
        return GateOutcome(proc.returncode, None, output,
                           f"子脚本 --json 输出里没有可用的 int 字段 {gate.count_key!r}")
    if proc.returncode not in (0, 1):
        return GateOutcome(proc.returncode, count, output,
                           f"子脚本以退出码 {proc.returncode} 结束（环境/解析异常）")
    return GateOutcome(proc.returncode, count, output)


def evaluate(gate: Gate, outcome: GateOutcome, base: int | None) -> Judgement:
    """把一次执行结果判成 OK/TIGHTEN/REGRESS/NEW/ERROR。"""
    if outcome.error is not None:
        return Judgement("ERROR", f"  {'ERROR':>8}  {gate.title}  （{outcome.error}）")
    if outcome.count is None:
        if outcome.unknown_violation:
            detail = (
                "退出码非 0，违规数未知（该门禁基线为 0）"
                if not base
                else f"退出码非 0，违规数未知（基线 {base}）"
            )
            return Judgement("REGRESS", f"  {'REGRESS':>8}  {gate.title}: {detail}")
        return Judgement(
            "ERROR",
            f"  {'ERROR':>8}  {gate.title}  （拿不到机器可读计数，保守判定为失败）",
        )

    count = outcome.count
    if base is None:
        return Judgement("NEW", f"  {'NEW':>8}  {gate.title}: {count} 处（无基线，本次建立）",
                         base=None, count=count)
    if count > base:
        return Judgement(
            "REGRESS",
            f"  {'REGRESS':>8}  {gate.title}: {count} 处（基线 {base}）→ 新增 {count - base} 处",
            base=base,
            count=count,
        )
    if count < base:
        return Judgement(
            "TIGHTEN",
            f"  {'TIGHTEN':>8}  {gate.title}: {count} 处（基线 {base}）→ 已减少 {base - count} 处",
            base=base,
            count=count,
        )
    return Judgement("OK", f"  {'OK':>8}  {gate.title}: {count} 处（与基线一致）",
                     base=base, count=count)


def load_baseline() -> dict[str, int]:
    if not BASELINE_PATH.exists():
        return {}
    try:
        with BASELINE_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: int(v) for k, v in (data.get("counts") or {}).items()}
    except (OSError, ValueError) as exc:
        print(f"[WARN] 基线文件不可读，按空基线处理：{exc}", file=sys.stderr)
        return {}


def save_baseline(counts: dict[str, int]) -> None:
    payload = {
        "_comment": (
            "门禁基线（棘轮）。这些是当前存量违规数，不阻断；"
            "新增违规会被 scripts/quality_gate.py 拦下。数字只允许下调"
            "（P0-7 的 service_commit 9→12 是唯一一次例外，理由见 "
            "docs/TRANSACTION_BOUNDARY_GUIDE.md §4：2026-10-02 复核确认这 12 处 "
            "db.commit() 全部是既有代码，其中 3 处的 diff 只改了注释 —— 把旧的 "
            "'# independent-transaction' 旁路标记换成 '# manual-tx'，commit() 调用"
            "本身未变；旧正则正是靠那个标记静默豁免它们，改 AST 后才可见）。"
        ),
        "counts": counts,
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------
# 恒失败自检（--self-test）：人为违规 → 退出码非 0；移除违规 → 退出码 0
# --------------------------------------------------------------------------

_LONG_FUNC_BAD = (
    "def too_long():\n"
    + "".join(f"    value_{i} = {i}\n" for i in range(95))
    + "    return value_0\n"
)
_VUE_BAD = ("<template>\n" + "<div>cell</div>\n" * 420 + "</template>\n").encode()
_VUE_CLEAN = b"<template>\n<div>cell</div>\n</template>\n"
# 30 个 if 分支 → 圈复杂度 31 > ruff.toml [lint.mccabe] max-complexity(25) → C901 命中
_COMPLEX_BAD = ("def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(30))
                + "    return -1\n").encode()
_COMPLEX_CLEAN = b"def f(x):\n    return x\n"

# key -> ((违规文件名, 内容), (干净文件名, 内容))
SELFTEST_FIXTURES: dict[str, tuple[tuple[str, bytes], tuple[str, bytes]]] = {
    "bare_except": (
        ("probe.py", b"try:\n    pass\nexcept:\n    pass\n"),
        ("probe.py", b"try:\n    pass\nexcept ValueError:\n    pass\n"),
    ),
    "function_length": (
        ("probe.py", _LONG_FUNC_BAD.encode()),
        ("probe.py", b"def ok():\n    return 1\n"),
    ),
    "vue_component_length": (
        ("probe.vue", _VUE_BAD),
        ("probe.vue", _VUE_CLEAN),
    ),
    "service_commit": (
        ("probe.py", b"async def probe(db):\n    await db.commit()\n"),
        ("probe.py", b"async def probe(db):\n    await db.flush()\n"),
    ),
    "bom": (
        ("probe.py", b"\xef\xbb\xbfvalue = 1\n"),
        ("probe.py", b"value = 1\n"),
    ),
    "complexity": (
        ("probe.py", _COMPLEX_BAD),
        ("probe.py", _COMPLEX_CLEAN),
    ),
    "loop_shadow": (
        ("probe.py", b"for x in []:\n    for x in []:\n        pass\n"),
        ("probe.py", b"for x in []:\n    for y in []:\n        pass\n"),
    ),
}
SELFTEST_RUFF_PROBE = (("probe.py", b"import os\n"), ("probe.py", b"import sys\n\nprint(sys.path)\n"))


def _selftest_probe_run(gate_key: str, probe_dir: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--only", gate_key,
         "--probe-dir", str(probe_dir)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))


def _pip_audit_fixtures(max_days: int, today: date) -> list[tuple[str, bool, str]]:
    """返回 [(说明, 期望有无问题, TOML 文本)]，用于策略层合成自检。"""
    header = "[[tool.code-quality.pip-audit-ignores]]\n"
    return [
        ("过期条目", True,
         header + 'id = "PYSEC-2026-0001"\nreason = "自检用"\nexpires = "2020-01-01"\n'),
        ("僵尸条目", True,
         header + 'id = "PYSEC-1999-9999"\nreason = "自检用"\nexpires = "2099-01-01"\n'),
        ("超上限", True,
         header + f'id = "PYSEC-2026-0001"\nreason = "自检用"\nexpires = "{today.year + 5}-01-01"\n'),
        ("缺 reason", True,
         header + 'id = "PYSEC-2026-0001"\nexpires = "2099-01-01"\n'),
        ("合规条目", False,
         header + f'id = "PYSEC-2026-0001"\nreason = "等待上游修复"\n'
                  f'expires = "{(today + timedelta(days=90)).isoformat()}"\n'),
    ]



def run_selftest(gates: tuple[Gate, ...], thresholds: dict[str, int], audit_report: str | None) -> int:
    """恒失败自检：人为违规 → 退出码非 0；移除违规 → 退出码 0。"""
    import tomllib

    lines: list[str] = []
    failures: list[str] = []
    today = date.today()
    max_days = thresholds["pip_audit_max_days"]
    # 探针目录必须**位于仓库内**：多个子脚本用 file.relative_to(PROJECT_ROOT) 生成相对路径，
    # 仓库外的临时目录会让它们抛 ValueError（表现为门禁 ERROR 而非 REGRESS）。
    # 故在仓库根下开临时目录，并在 finally 里无条件清理。
    tmp_root = Path(tempfile.mkdtemp(prefix="_qgate_selftest_", dir=PROJECT_ROOT))

    def report(ok: bool, message: str) -> None:
        lines.append(f"{SELFTEST_PREFIX} {'PASS' if ok else 'FAIL'} {message}")
        if not ok:
            failures.append(message)

    try:
        for gate in gates:
            lines.append(f"{SELFTEST_PREFIX} >> 门禁 {gate.key}（mode={gate.mode}）")

            # 决策层：合成载荷 —— 计数高于基线必须判 REGRESS，拿不到计数必须保守失败
            if gate.mode == MODE_JSON:
                report(
                    _json_count(gate, '{"' + gate.count_key + '": 3}') == 3
                    and _json_count(gate, "这不是 JSON") is None,
                    f"{gate.key}: JSON 计数语义解析（3 → 3；非 JSON → None）",
                )
                report(
                    evaluate(gate, GateOutcome(1, 2, ""), 1).status == "REGRESS",
                    f"{gate.key}: 合成载荷 2 处 > 基线 1 → REGRESS",
                )
                report(
                    evaluate(gate, GateOutcome(1, None, "", "输出不可解析"), 0).status == "ERROR",
                    f"{gate.key}: 拿不到机器可读计数 → 保守 ERROR（绝不静默记 0）",
                )
            elif gate.mode == MODE_EXIT:
                report(
                    evaluate(gate, GateOutcome(1, None, "", unknown_violation=True), 0).status
                    == "REGRESS",
                    f"{gate.key}: 退出码非 0 → REGRESS",
                )
                report(
                    evaluate(gate, GateOutcome(0, 0, ""), 0).status == "OK",
                    f"{gate.key}: 退出码 0 → OK",
                )
            elif gate.mode == MODE_RUFF:
                report(
                    _ruff_count('[{"code": "F401", "filename": "x.py"}]') == 1
                    and _ruff_count("not-json") is None,
                    "ruff: --output-format json 诊断数语义解析（1 → 1；非 JSON → None）",
                )
                report(
                    evaluate(gate, GateOutcome(1, 1, ""), 0).status == "REGRESS",
                    "ruff: 1 条诊断 > 基线 0 → REGRESS",
                )
            elif gate.mode == MODE_PIP_AUDIT:
                for label, expect_problem, toml_text in _pip_audit_fixtures(max_days, today):
                    entries = tomllib.loads(toml_text)["tool"]["code-quality"]["pip-audit-ignores"]
                    problems, _expiring, _total = audit_ignores(
                        entries, max_days, today, {"PYSEC-2026-0001"}
                    )
                    report(
                        bool(problems) is expect_problem,
                        f"pip-audit: {label} → 判定有问题={bool(problems)}（期望 {expect_problem}）",
                    )
                report(
                    evaluate(gate, GateOutcome(1, 1, ""), 0).status == "REGRESS",
                    "pip-audit: 1 个策略问题 > 基线 0 → REGRESS",
                )

            # 端到端：真子脚本 + 真 runner（--probe-dir），双向验证退出码
            fixture = None
            if gate.key in SELFTEST_FIXTURES:
                fixture = SELFTEST_FIXTURES[gate.key]
            elif gate.mode == MODE_RUFF:
                fixture = SELFTEST_RUFF_PROBE
            if fixture is None:
                lines.append(
                    f"{SELFTEST_PREFIX} SKIP {gate.key}: 该门禁不接受路径覆盖，"
                    "端到端方向由上面的决策层断言覆盖"
                )
                continue

            probe_dir = tmp_root / gate.key
            probe_dir.mkdir(parents=True, exist_ok=True)
            bad_name, bad_bytes = fixture[0]
            clean_name, clean_bytes = fixture[1]
            (probe_dir / bad_name).write_bytes(bad_bytes)
            rc_bad, out_bad = _selftest_probe_run(gate.key, probe_dir)
            report(rc_bad != 0, f"{gate.key}: 人为违规 → runner 退出码 {rc_bad}（要求非 0）")
            report("REGRESS" in out_bad, f"{gate.key}: 人为违规 → 报告里出现 REGRESS")
            (probe_dir / bad_name).unlink()
            (probe_dir / clean_name).write_bytes(clean_bytes)
            rc_good, _ = _selftest_probe_run(gate.key, probe_dir)
            report(rc_good == 0, f"{gate.key}: 移除违规 → runner 退出码 {rc_good}（要求 0）")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    for line in lines:
        print(line)
    if any("[FAIL]" in line for line in lines):
        failures.append("自检输出里出现了 [FAIL] 字面量")
    print()
    if failures:
        print(f"{SELFTEST_PREFIX} 失败 {len(failures)} 项：")
        for item in failures:
            print(f"{SELFTEST_PREFIX}   - {item}")
        return 1
    passed = sum(1 for line in lines if " PASS " in line)
    print(f"{SELFTEST_PREFIX} 全部通过：{passed} 项断言")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="统一代码质量门禁（基线棘轮）")
    parser.add_argument("--report", action="store_true", help="只报告，不判定失败")
    parser.add_argument("--update-baseline", action="store_true", help="用当前结果重建基线")
    parser.add_argument("--verbose", action="store_true", help="打印失败门禁的机器可读输出")
    parser.add_argument("--only", help="只运行指定门禁（key）")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="恒失败自检：制造违规断言退出码非 0，移除违规断言退出码 0",
    )
    parser.add_argument(
        "--probe-dir",
        help="[仅自检/调试] 把扫描范围覆盖为临时目录，并按基线 0 判定",
    )
    parser.add_argument(
        "--audit-report", help="pip-audit --format json 的输出文件（僵尸豁免判定用）"
    )
    args = parser.parse_args()

    thresholds = load_thresholds()
    baseline = load_baseline()

    selected = tuple(g for g in GATES if not args.only or g.key == args.only)
    if not selected:
        print(f"[ERROR] 未知门禁：{args.only}；可选：{', '.join(g.key for g in GATES)}")
        return 2

    if args.self_test:
        return run_selftest(selected, thresholds, args.audit_report)

    probe_dir: Path | None = None
    if args.probe_dir:
        probe_dir = Path(args.probe_dir).resolve()
        if not probe_dir.is_dir():
            print(f"[ERROR] --probe-dir 不是目录：{probe_dir}")
            return 2
        if len(selected) != 1:
            print("[ERROR] --probe-dir 必须与 --only <单个门禁> 一起使用")
            return 2
        if not selected[0].accepts_paths:
            print(f"[ERROR] 门禁 {selected[0].key} 不接受路径覆盖，无法用 --probe-dir")
            return 2

    results: list[tuple[Gate, GateOutcome, Judgement]] = []
    for gate in selected:
        outcome = run_gate(gate, thresholds, probe_dir, args.audit_report)
        base: int | None = 0 if probe_dir is not None else baseline.get(gate.key)
        results.append((gate, outcome, evaluate(gate, outcome, base)))

    print("=" * 78)
    print("代码质量门禁报告（基线棘轮）")
    print("=" * 78)
    print(
        f"阈值：函数 ≤{thresholds['max_function_length']} 行 / "
        f"Vue 组件 ≤{thresholds['max_vue_component_length']} 行 / "
        f"pip-audit 豁免单条 ≤{thresholds['pip_audit_max_days']} 天"
    )
    if probe_dir is not None:
        print(f"[PROBE] 扫描范围被 --probe-dir 覆盖为：{probe_dir}")
        print("[PROBE] 该模式下基线按 0 判定，仅用于 --self-test / 本地调试。")
    print()

    hard_failure = False
    counts_now: dict[str, int] = {}
    regressions: list[tuple[Gate, GateOutcome, Judgement]] = []
    improvements: list[Judgement] = []

    for gate, outcome, judgement in results:
        print(judgement.line)
        for note in outcome.notes:
            print(f"  {'':>8}  · {note}")
        if judgement.status == "ERROR":
            hard_failure = True
            continue
        if judgement.count is not None:
            counts_now[gate.key] = judgement.count
        elif gate.key in baseline:
            # 计数未知（MODE_EXIT 门禁失败时 count=None 但判为 REGRESS 而非 ERROR，
            # 不会触发 hard_failure）——沿用旧基线值。否则 --update-baseline 会把
            # bom / alembic_heads 这类键整条丢掉，等于悄悄取消了它们的棘轮。
            counts_now[gate.key] = baseline[gate.key]
        if judgement.status == "REGRESS":
            regressions.append((gate, outcome, judgement))
        elif judgement.status == "TIGHTEN":
            improvements.append(judgement)

    if regressions:
        print()
        print("-" * 78)
        print("必须修复（新增违规）")
        print("-" * 78)
        for gate, outcome, judgement in regressions:
            now = judgement.count if judgement.count is not None else "未知"
            print(f"\n● {gate.title}：{judgement.base} → {now}")
            print(f"  通过标准：{gate.fix_hint}")
            if args.verbose and outcome.output:
                print("  --- 机器可读输出 ---")
                for line in outcome.output.splitlines():
                    print(f"  {line}")

    if improvements:
        print()
        print("可以收紧基线（建议稍后执行 `--update-baseline`）")
        for judgement in improvements:
            print(f"  ● {judgement.line.strip()}")

    print()
    if args.report:
        print("[REPORT 模式] 不判定失败。")
        return 0
    if args.update_baseline:
        if hard_failure:
            print("[ERROR] 有门禁拿不到机器可读计数，拒绝重建基线（避免把异常写成基线）。")
            return 2
        save_baseline(counts_now)
        print(f"[OK] 基线已更新：{BASELINE_PATH.relative_to(PROJECT_ROOT)}")
        return 0
    if hard_failure or regressions:
        print("[FAIL] 存在新增质量问题，请修复后重试。")
        return 1
    print("[PASS] 无新增质量问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
