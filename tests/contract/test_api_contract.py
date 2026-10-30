"""接口契约快照测试（pytest 包装）。

设计说明
--------
本文件**不重复实现比对逻辑**，只断言 `scripts/contract_snapshot.py --check` 的结论。
工具是唯一真相源 —— 避免同一套规则维护两份（这正是本项目反复踩过的坑）。

执行条件
--------
契约比对需要一个**真实运行的后端**。CI 里没有常驻后端，因此当环境变量
`CONTRACT_BASE_URL` 未设置时，本文件整体跳过（跳过是正确行为，不是失败）。

    # 本地：先录制基线，再比对
    python scripts/contract_snapshot.py --record
    set CONTRACT_BASE_URL=http://127.0.0.1:5002 && pytest tests/contract -v

快照录制/更新只走工具，测试文件**不**负责录制。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACT_DIR = ROOT / "tests" / "contract"
SNAPSHOT_DIR = CONTRACT_DIR / "snapshots"

BASE_URL = os.environ.get("CONTRACT_BASE_URL", "").strip()

# 快照允许出现的键 —— 白名单式守卫，防止将来有人把原始响应体写进快照
# （那会把客户名/金额等真实业务数据提交进 git）
ALLOWED_SNAPSHOT_KEYS = {
    "schema_version",
    "name",
    "method",
    "path",
    "query",
    "auth",
    "http_status",
    "shape",
    "value_checks",
    "recorded_at",
}

# 只有"与真实后端比对"那条需要 CONTRACT_BASE_URL；
# 快照存在性与"不得夹带原始响应体"两条守卫属于纯静态检查，任何环境都能跑。
pytestmark = [pytest.mark.contract]

needs_backend = pytest.mark.skipif(
    not BASE_URL,
    reason="未设置 CONTRACT_BASE_URL，跳过契约比对（需真实后端）",
)


def _run_check() -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/contract_snapshot.py",
            "--check",
            "--json",
            "--base-url",
            BASE_URL,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        pytest.fail(
            f"契约工具未输出合法 JSON（exit={proc.returncode}）\n"
            f"stdout={proc.stdout[:400]}\nstderr={proc.stderr[:400]}"
        )


def test_contract_snapshots_exist() -> None:
    """必须先有基线，否则"比对通过"毫无意义。"""
    snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))
    assert snapshots, (
        f"未找到任何契约快照（{SNAPSHOT_DIR}）。"
        "请先执行：python scripts/contract_snapshot.py --record"
    )


def test_snapshots_contain_no_raw_response_body() -> None:
    """守卫：快照只允许存结构签名，不得夹带原始响应体。"""
    violations: list[str] = []
    for path in sorted(SNAPSHOT_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        extra = set(data) - ALLOWED_SNAPSHOT_KEYS
        if extra:
            violations.append(f"{path.name}: 多出键 {sorted(extra)}")
    assert not violations, "快照含白名单外的键（可能夹带了业务数据）：\n" + "\n".join(violations)


@needs_backend
def test_contract_snapshots_match() -> None:
    """核心断言：当前后端响应结构必须与基线快照一致。"""
    rc, report = _run_check()
    results = report.get("results", [])

    drifted = [r for r in results if r["status"] in ("drift", "missing-snapshot")]
    errored = [r for r in results if r["status"] == "error"]

    if errored:
        pytest.fail(
            "契约比对未能完成（目标不可达或鉴权失败），请确认后端在跑：\n"
            + "\n".join(f"  {r['name']}: {r.get('diffs')}" for r in errored[:5])
        )

    if drifted:
        lines = [f"检测到 {len(drifted)} 个端点的响应契约与基线不一致：", ""]
        for r in drifted:
            lines.append(f"● {r['name']}")
            for d in r["diffs"]:
                lines.append(f"    {d}")
        lines += [
            "",
            "若这是**有意的**接口变更：",
            "  1) 先确认前端已同步适配（否则前端会静默空白）",
            "  2) 再执行：python scripts/contract_snapshot.py --record",
            "  3) 把快照一并提交",
            "若这不是有意的：说明后端存在非预期改动，先查清再改快照。",
        ]
        pytest.fail("\n".join(lines))

    assert rc == 0, f"契约工具退出码异常：{rc}"


# ============================================================
# 录制语义（纯本地，不需要后端）
# ============================================================
def test_record_merge_never_drops_nested_shape(tmp_path: Path) -> None:
    """回归（2026-10-30）：合并录制不得丢掉历史基线里的嵌套字段。

    事故形态：在空库上直接 ``--record``，列表没有元素 → shape 变成
    ``xxx:array[0]``，历史基线里 ``xxx[].field`` 整片消失（实测 208 条）。
    门禁此后只剩顶层键，表面通过、实际已被削弱。
    """
    from scripts.contract_snapshot import _merge_snapshot, diff_snapshot

    path = tmp_path / "ep.json"
    path.write_text(
        json.dumps(
            {"http_status": 200, "shape": ["a:int", "list[].order_no:str"]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    live_empty = {"http_status": 200, "shape": ["a:int", "list:array[0]"]}

    merged, added = _merge_snapshot(live_empty, path)

    assert "list[].order_no:str" in merged["shape"], "合并后历史嵌套字段被删掉了"
    assert added == 1, f"只应新增 list:array[0]，实际新增 {added} 条"
    # 关键性质：空库比对靠 array[0] 容差通过，因此 CI 空库仍可执行门禁
    assert diff_snapshot(merged, live_empty) == []


def test_record_merge_keeps_field_removal_detectable(tmp_path: Path) -> None:
    """合并基线仍必须能检出「字段消失」——否则门禁等于失效。"""
    from scripts.contract_snapshot import _merge_snapshot, diff_snapshot

    path = tmp_path / "ep.json"
    path.write_text(
        json.dumps({"http_status": 200, "shape": ["a:int", "drop_me:str"]}),
        encoding="utf-8",
    )
    merged, _ = _merge_snapshot({"http_status": 200, "shape": ["a:int"]}, path)

    diffs = diff_snapshot(merged, {"http_status": 200, "shape": ["a:int"]})

    assert any("drop_me" in d for d in diffs), f"字段消失未被检出：{diffs}"


def test_empty_root_array_is_tolerated() -> None:
    """回归（2026-10-30）：根级空数组不得把 `[].field` 误报为「字段消失」。

    `shape_signature` 对根级数组用 label `<root>`，元素路径是 `[].desc`；
    旧容差只匹配 `<root>[]` 前缀，于是空库比对时整片字段被判为消失
    （dashboard_activities / products_search 实测命中）。
    """
    from scripts.contract_snapshot import diff_snapshot

    expected = {"http_status": 200, "shape": ["[].desc:str", "[].title:str"]}
    actual = {"http_status": 200, "shape": ["<root>:array[0]"]}

    assert diff_snapshot(expected, actual) == []


def test_empty_object_is_tolerated() -> None:
    """空对象（object{}）同样观测不到子键，不得据此判「字段消失」。"""
    from scripts.contract_snapshot import diff_snapshot

    expected = {
        "http_status": 200,
        "shape": ["data:object", "data.items[].code:str", "data.name:str"],
    }
    actual = {"http_status": 200, "shape": ["data:object{}"]}

    assert diff_snapshot(expected, actual) == []


def test_object_and_empty_object_are_not_a_type_change() -> None:
    """object ↔ object{} 只是「有没有子键」，不是类型契约变化。"""
    from scripts.contract_snapshot import diff_snapshot

    expected = {"http_status": 200, "shape": ["data:object"]}
    actual = {"http_status": 200, "shape": ["data:object{}"]}

    assert diff_snapshot(expected, actual) == []


# ============================================================
# 2026-10-30 审计 B-H1：基线里的 array[0] 不得永久赦免后代字段
# ============================================================
def test_baseline_array_sentinel_does_not_hide_field_removal_with_data() -> None:
    """实际数组有数据时，基线残留的 array[0] 不能掩盖「后代字段消失」。"""
    from scripts.contract_snapshot import diff_snapshot

    expected = {
        "http_status": 200,
        "shape": ["data:array[0]", "data[].field:str", "data[].other:int"],
    }
    actual = {"http_status": 200, "shape": ["data[].other:int"]}

    diffs = diff_snapshot(expected, actual)
    assert any("data[].field" in d for d in diffs), f"字段消失未被检出：{diffs}"


def test_array_sentinel_tolerates_only_when_actual_is_empty() -> None:
    """实际数组为空时（结构无从观测），才容忍后代字段缺失。"""
    from scripts.contract_snapshot import diff_snapshot

    expected = {"http_status": 200, "shape": ["data[].field:str"]}
    actual = {"http_status": 200, "shape": ["data:array[0]"]}

    assert diff_snapshot(expected, actual) == []


def test_merge_drops_redundant_sentinel_when_old_has_descendants(tmp_path: Path) -> None:
    """合并录制时，基线已有后代字段就不再写入空容器哨兵。"""
    from scripts.contract_snapshot import _merge_snapshot

    path = tmp_path / "ep.json"
    path.write_text(
        json.dumps({"http_status": 200, "shape": ["data[].field:str"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    merged, _ = _merge_snapshot({"http_status": 200, "shape": ["data:array[0]"]}, path)

    assert "data[].field:str" in merged["shape"]
    assert "data:array[0]" not in merged["shape"]
