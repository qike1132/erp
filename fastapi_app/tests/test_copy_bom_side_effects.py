"""复制 BOM 必须触发与「保存 BOM」同一套副作用（2026-11-16 上线前审计 A-8）。

拦哪种错：copy-bom 原先只写 BOM 四张表，不注册 post-commit 副作用，也不失效
`orders:unprocessed:*` —— 目标产品的「待生成」行与已有 pending 单都停在复制前的状态，
而前端复制完只 reload，用户看不到任何提示（快速复制 BOM 是「待配置→补配置」主流程）。

变异检查：删掉端点里的 `schedule_bom_saved_side_effects(db, target_product_id)`
或那行 `orders:unprocessed:*` 失效，对应用例必红。
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTES = PROJECT_ROOT / 'fastapi_app/api/v1/endpoints/purchase_center/product_routes.py'


def _copy_bom_body() -> str:
    src = ROUTES.read_text(encoding='utf-8')
    match = re.search(
        r"@router\.post\('/products/\{target_product_id\}/copy-bom'.*?(?=\n@router\.|\Z)",
        src, re.S,
    )
    assert match, '未找到 copy-bom 端点'
    return match.group(0)


def test_copy_bom_schedules_side_effects_inside_transaction():
    """副作用必须注册在 db_transaction 内（回调用 post_commit_callbacks 在提交后执行）。"""
    body = _copy_bom_body()
    assert 'schedule_bom_saved_side_effects(db, target_product_id)' in body, (
        '复制 BOM 未注册副作用：目标产品既不会生成采购单，也不会同步已有 pending 单'
    )
    # 顺序：复制 → 注册副作用；注册不能跑到事务外（那样回调挂不上 session.info）
    assert body.index('copy_bom_to_product') < body.index('schedule_bom_saved_side_effects')


def test_copy_bom_invalidates_unprocessed_cache():
    """unprocessed 列表有 30s Redis 缓存，复制后必须显式失效（与保存路径同口径）。"""
    body = _copy_bom_body()
    assert "'orders:unprocessed:*'" in body, '复制后未失效 orders:unprocessed:*，采购列表会旧 30s'
