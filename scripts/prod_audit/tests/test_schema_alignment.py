"""`audit_report.schema.json` ↔ pydantic 模型一致性守卫。

背景（第八轮报备、收口落地）：`schemas/audit_report.schema.json` 定义了
AuditIssue / LayerResult / AuditState 的 JSON 结构，但全仓**没有任何地方
加载或校验它** —— schema 与 pydantic 实现一旦漂移（加字段/改枚举），无人发现，
schema 沦为"看起来在守卫、实际是文档"。

本测试不引入 jsonschema 依赖，改用**字段集对齐**断言：
pydantic 模型的字段（含必填性）必须与 schema 定义的 properties/required 一致。
任一侧单独改动都会让本测试变红，逼着两处同步。
"""

from scripts.prod_audit.base.layer_base import AuditIssue, AuditState, LayerResult
from scripts.prod_audit.schemas import AUDIT_REPORT_SCHEMA_PATH


def _load_schema() -> dict:
    import json
    return json.loads(AUDIT_REPORT_SCHEMA_PATH.read_text(encoding='utf-8'))


def _assert_alignment(schema_defs: dict, schema_key: str, model) -> None:
    """模型字段 ↔ schema properties/required 双向对齐。"""
    definition = schema_defs.get(schema_key)
    assert definition is not None, f'schema 缺少 definition: {schema_key}'
    props = set(definition.get('properties', {}).keys())
    required = set(definition.get('required', []))

    model_fields = set(model.model_fields.keys())
    assert props == model_fields, (
        f'{schema_key}: schema properties 与 pydantic 模型字段漂移\n'
        f'  仅在 schema: {sorted(props - model_fields)}\n'
        f'  仅在模型  : {sorted(model_fields - props)}'
    )
    model_required = {
        name for name, field in model.model_fields.items() if field.is_required()
    }
    assert required == model_required, (
        f'{schema_key}: schema required 与 pydantic 必填字段漂移\n'
        f'  仅在 schema required: {sorted(required - model_required)}\n'
        f'  仅在模型必填        : {sorted(model_required - required)}'
    )


def test_schema_file_exists_and_loads() -> None:
    schema = _load_schema()
    assert schema.get('definitions'), 'schema 缺少 definitions'


def test_audit_issue_matches_schema() -> None:
    _assert_alignment(_load_schema()['definitions'], 'AuditIssue', AuditIssue)


def test_layer_result_matches_schema() -> None:
    _assert_alignment(_load_schema()['definitions'], 'AuditLayer', LayerResult)


def test_audit_state_matches_schema() -> None:
    _assert_alignment(_load_schema()['definitions'], 'AuditState', AuditState)
