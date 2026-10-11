"""L5 契约比对提取器「精度」回归护栏（评审 2026-10-11）。

旧提取器口径有三处缺陷，稳定产出假差异（v3 报告判定 9 条里 8 条是噪声）：
- 后端只扫顶层 ``fastapi_app/schemas/``，把那里的死模型当基准、漏掉 endpoints 里活模型；
- 前端同名 interface 跨文件取**并集**，把两个不相干的类型揉成一个；
- 字段正则用 ``[?:]``，把 ``A extends B ? C : D`` 里的 ``B ?`` 误当字段。

本测试锁死：修复后这些已知噪声名不再出现在差异集里。数据依赖当前仓内 schema/type
状态（同 tests/test_p3_redis_wrapper.py 的源断言范式），是刻意为之——它就是这份契约。
"""
from scripts.prod_audit.layers.l5_api_contract import (
    _SCHEMA_NAME_EXEMPTIONS,
    L5ApiContract,
)

# 评审逐条判定为口径噪声的名字（死模型 / 同名不同物 / 命名撞车 / 适配器产物 / 只活在测试里）
_KNOWN_NOISE = {
    "TrendResponse",              # 后端同名撞车
    "FabricItem",                 # 同名不同物
    "NavItem", "NavSection",      # 前端适配器产物
    "FactorySummarySaveRequest",  # 死模型当基准（活模型在 endpoints/**/schemas.py）
    "OneClickGenerateRequest",    # 同上
}


def _schema_diff() -> set[str]:
    inst = L5ApiContract.__new__(L5ApiContract)  # 不跑 __init__，只调提取器
    be = inst._extract_pydantic_models()
    fe = inst._extract_ts_interfaces()
    return {
        n
        for n in (set(be) & set(fe))
        if be[n] != fe[n] and n not in _SCHEMA_NAME_EXEMPTIONS
    }


def test_l5_extractor_no_longer_reports_known_noise():
    residual = _schema_diff() & _KNOWN_NOISE
    assert not residual, f"L5 仍把已知口径噪声当契约差异：{sorted(residual)}"


def test_l5_extractor_excludes_dead_and_colliding_models():
    """后端模型集应剔掉死模型（未被 schemas/ 之外引用）与撞名模型。"""
    inst = L5ApiContract.__new__(L5ApiContract)
    models = inst._extract_pydantic_models()
    assert models, "提取器不应为空"
    assert "TrendResponse" not in models, "撞名的后端模型应被剔除"
