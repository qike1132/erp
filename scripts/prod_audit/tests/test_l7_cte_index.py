"""L7 索引提示检查 —— CTE 覆盖核对回归测试(2026-10-20)。

背景(审计 #18b,误报型检查器缺陷):

    原实现用 ``re.findall(r"(?im)^#{2,3}\\s+(\\w+)", doc_content)`` 从
    ``docs/cte_index_suggestions.md`` 提取「建议表名」。``\\w`` 在 Python 默认
    匹配 Unicode 字母,于是**中文小节标题**(库存结余 / 外协恢复校验 / 汇总)被
    当成表名;再拿这些中文词去源码里做子串匹配 → 零命中 → 对**每个** CTE 文件
    报「未按建议加索引」。实测一次 prod_audit 跑出 3 条必然误报。

本文件的作用是**让这个缺陷无法回归**:

    - 真实仓库的 CTE 文件不得被误报(回归前必红);
    - 反向能力必须保留: 新增 CTE 文件而未登记 ⇒ 必须报出;
    - 文档里的登记与实际代码不符(文件已无 CTE / 登记块缺失)⇒ 必须报出。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.layers import l7_performance as l7
from scripts.prod_audit.layers.l7_performance import L7Performance

_RULE_MISSING = "L7-CTE-INDEX-MISSING-001"
_RULE_REGISTRY = "L7-CTE-INDEX-REGISTRY-001"

_CTE_SQL = 'sql = text("""WITH agg AS (SELECT id FROM t) SELECT * FROM agg""")\n'


@pytest.fixture
def layer() -> L7Performance:
    """L7 层执行器实例。"""
    return L7Performance()


async def _run_index_hints(layer: L7Performance) -> tuple[list, str]:
    """执行索引提示子检查,返回 ``(issues, raw)``。"""
    return await layer._check_index_hints(IssueBuilder())


def _fake_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    """把检查器的扫描根指向临时目录,返回 ``(services 目录, 文档路径)``。"""
    services = tmp_path / "fastapi_app" / "services"
    services.mkdir(parents=True)
    doc = tmp_path / "docs" / "cte_index_suggestions.md"
    doc.parent.mkdir(parents=True)
    monkeypatch.setattr(l7, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(l7, "SERVICES_DIR", services)
    monkeypatch.setattr(l7, "_CTE_INDEX_DOC", doc)
    return services, doc


def _write_doc(doc: Path, entries: list[str], *, with_block: bool = True) -> Path:
    """写一份带(或不带)结构化清单块的建议文档。"""
    lines = ["# CTE 查询索引建议", ""]
    if with_block:
        lines.append(l7._CTE_REGISTRY_START)
        lines.extend(entries)
        lines.append(l7._CTE_REGISTRY_END)
    else:
        lines += ["## 库存结余", "", "中文小节标题不是表名。"]
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------------------
# 1. 真实仓库: CTE 文件不得被误报(回归前必红)
# ---------------------------------------------------------------------------


async def test_real_repo_cte_files_are_not_false_positive(layer: L7Performance) -> None:
    """真实仓库的 CTE 文件必须全部在结构化清单中登记,不得报「未登记」。

    修复前: 解析出的是中文标题,源码匹配零命中 ⇒ 3 条 L7-CTE-INDEX-MISSING-001 误报。
    """
    issues, raw = await _run_index_hints(layer)

    missing = [i for i in issues if i.rule_id == _RULE_MISSING]
    assert missing == [], (
        f"真实仓库的 CTE 文件被误报为未登记(检查器解析文档有误): "
        f"{[(i.file, i.line) for i in missing]}; raw={raw!r}"
    )


async def test_real_registry_contains_real_cte_files(layer: L7Performance) -> None:
    """结构化清单必须登记本仓真实的 3 个 CTE 源文件(防止登记被清空而无人察觉)。"""
    entries, errors = l7._parse_cte_registry(
        l7._CTE_INDEX_DOC.read_text(encoding="utf-8")
    )

    assert errors == [], f"真实文档的结构化清单解析失败: {errors}"
    assert set(entries) == {
        "fastapi_app/services/stock_inventory_service.py",
        "fastapi_app/services/report_service.py",
        "fastapi_app/services/backup/orchestration/drill_validator.py",
    }, f"结构化清单与实际 CTE 源文件不符: {sorted(entries)}"


async def test_real_registry_tables_are_identifiers_not_chinese_headings(
    layer: L7Performance,
) -> None:
    """登记的表名必须是 SQL 标识符,不能是中文小节标题(误报根因)。"""
    entries, _ = l7._parse_cte_registry(
        l7._CTE_INDEX_DOC.read_text(encoding="utf-8")
    )

    tables = {
        t.strip()
        for entry in entries.values()
        for t in entry.tables.split(",")
        if t.strip()
    }
    assert tables, "结构化清单未登记任何表名"
    assert all(t.isascii() for t in tables), f"表名含非 ASCII 字符: {sorted(tables)}"
    assert "stock_in" in tables, f"库存结余 CTE 的表名未登记: {sorted(tables)}"


# ---------------------------------------------------------------------------
# 2. 反向能力: 未登记 / 登记失配 必须报出
# ---------------------------------------------------------------------------


async def test_unregistered_cte_file_is_reported(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新增 CTE 文件而未在文档登记 ⇒ 必须报 L7-CTE-INDEX-MISSING-001。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "known.py").write_text(_CTE_SQL, encoding="utf-8")
    (services / "brand_new.py").write_text(_CTE_SQL, encoding="utf-8")
    _write_doc(doc, ["fastapi_app/services/known.py | agg | index | t"])

    issues, _ = await _run_index_hints(layer)

    missing = [i for i in issues if i.rule_id == _RULE_MISSING]
    assert len(missing) == 1, (
        f"未登记的 CTE 文件应报 1 条,实际 {[(i.rule_id, i.file) for i in issues]}"
    )
    assert missing[0].file.endswith("brand_new.py")


async def test_empty_registry_with_cte_files_is_reported(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """清单块存在但为空、而代码里确有 CTE ⇒ 必须报登记无效(不得静默放行)。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "any.py").write_text(_CTE_SQL, encoding="utf-8")
    _write_doc(doc, [])

    issues, _ = await _run_index_hints(layer)

    registry = [i for i in issues if i.rule_id == _RULE_REGISTRY]
    assert len(registry) == 1, (
        f"空清单应报 1 条,实际 {[(i.rule_id, i.description) for i in issues]}"
    )


async def test_registered_cte_file_produces_no_issue(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """登记完整的 CTE 文件不得被报出(守住上面的正向判定)。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "known.py").write_text(_CTE_SQL, encoding="utf-8")
    _write_doc(doc, ["fastapi_app/services/known.py | agg | index | t"])

    issues, _ = await _run_index_hints(layer)

    assert issues == [], f"已登记的 CTE 文件不应有问题: {[(i.rule_id, i.description) for i in issues]}"


async def test_stale_registry_entry_is_reported(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """登记的源文件已无 CTE(代码搬走/删除)⇒ 必须报登记失配。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "moved_away.py").write_text("x = 1\n", encoding="utf-8")
    _write_doc(doc, ["fastapi_app/services/moved_away.py | agg | index | t"])

    issues, _ = await _run_index_hints(layer)

    stale = [i for i in issues if i.rule_id == _RULE_REGISTRY]
    assert len(stale) == 1, (
        f"登记失配应报 1 条,实际 {[(i.rule_id, i.description) for i in issues]}"
    )
    assert "moved_away.py" in stale[0].description


async def test_doc_without_registry_block_is_reported(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文档缺结构化清单块 ⇒ 必须报登记无效(不得静默放行全部 CTE)。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "any.py").write_text(_CTE_SQL, encoding="utf-8")
    _write_doc(doc, [], with_block=False)

    issues, _ = await _run_index_hints(layer)

    registry = [i for i in issues if i.rule_id == _RULE_REGISTRY]
    assert len(registry) == 1, (
        f"缺结构化块应报 1 条,实际 {[(i.rule_id, i.description) for i in issues]}"
    )
    assert "结构化" in registry[0].description


async def test_malformed_registry_line_is_reported(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """清单行格式非法(字段数不对)⇒ 必须报登记无效。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "any.py").write_text(_CTE_SQL, encoding="utf-8")
    _write_doc(doc, ["fastapi_app/services/any.py | agg"])

    issues, _ = await _run_index_hints(layer)

    registry = [i for i in issues if i.rule_id == _RULE_REGISTRY]
    assert len(registry) == 1, (
        f"格式非法应报 1 条,实际 {[(i.rule_id, i.description) for i in issues]}"
    )


async def test_invalid_action_value_is_reported(
    layer: L7Performance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """动作字段取值非法 ⇒ 必须报登记无效。"""
    services, doc = _fake_project(monkeypatch, tmp_path)
    (services / "any.py").write_text(_CTE_SQL, encoding="utf-8")
    _write_doc(doc, ["fastapi_app/services/any.py | agg | whatever | t"])

    issues, _ = await _run_index_hints(layer)

    registry = [i for i in issues if i.rule_id == _RULE_REGISTRY]
    assert len(registry) == 1, (
        f"动作非法应报 1 条,实际 {[(i.rule_id, i.description) for i in issues]}"
    )
