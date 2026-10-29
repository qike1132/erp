"""清库范围的唯一真相源（审计 F1-6）。

背景
----
仓里有多个清库脚本，各自硬编码一份表清单，互不同步（审计实测 41 / 58 / 67 张），
**漏表没有任何自动发现手段**：

- `purge_simulated_data.py`（上线清库唯一入口）漏 4 张 ORM 表 ——
  product_customer / finished_stock_remark / import_file_registry / numbering_audit
  的数据会原样进生产；
- `cleanup_preserve_users.py` 漏 28 张，验证输出却宣称「其他数据已彻底清除」；
- `clear_all_data.py` 靠 P1-35 补齐了 22 张，但它自己一份清单，与 purge 那份
  仍是两套独立真相 —— 下次新增 ORM 表时又会分叉。

本模块把「哪些表是业务数据、哪些是身份/配置」集中成一份，并提供对 ORM metadata
的**启动期 fail-closed 覆盖校验**：新增 ORM 表而未分类 → 直接拒绝执行，
不再静默漏清。

三个 scope（语义不同，不能互相替代）
------------------------------------
- ``PRODUCTION`` —— 上线清库（`scripts/purge_simulated_data.py` 默认范围）：
  清业务数据，**保留**用户 / 客户 / 运行配置。
- ``DEV_FULL`` —— 开发期全量清空（`scripts/clear_all_data.py`）：连用户 / 客户一起清。
- ``DEV_KEEP_USERS`` —— 开发期清业务数据但**保留用户**（避免把自己锁在门外）：
  ``purge_simulated_data.py --scope DEV_KEEP_USERS``。

模块级工具（`clear_purchase_center_data.py`）按模块选择清理，不声称「全清」，
不纳入本模块。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 表分类
# ---------------------------------------------------------------------------

#: 身份/客户数据：上线清库必须保留；开发期全清可以清掉。
IDENTITY_TABLES = frozenset({
    'user',
    'user_permission',
    'customer',
    'customer_access_log',
    'order_sync_config',
})

#: 任何 scope 都不清：权限字典与运行配置。
CONFIG_TABLES = frozenset({
    'permission',
    'backup_settings',
    'backup_schedule',
})

#: 不在 ORM metadata 里、但同样绝不能清的表（删了会导致重复迁移）。
NON_ORM_TABLES = frozenset({'alembic_version'})

#: 保留表的稳定顺序 —— 快照 / 复核输出按此排列，保证同一范围每次输出可比对。
KEEP_ORDER = (
    'user',
    'user_permission',
    'permission',
    'customer',
    'customer_access_log',
    'backup_settings',
    'backup_schedule',
    'order_sync_config',
    'alembic_version',
)

#: 业务 / 模拟数据表。**严格按外键依赖排序（子表在前、父表在后）**，
#: 保证单事务内 DELETE 不触发约束冲突。
CORE_CLEAR_TABLES = (
    # 板房管理
    'customer_sampling_change_log',
    'customer_sampling_fabric_version',
    'customer_sampling_part',
    'customer_sampling_role',
    'customer_sampling_project',
    'pattern_maker',
    'file_records',
    # 核心业务 - 库存与出库
    'stock_return',
    'stock_out',
    'stock_in',
    'inventory_log',
    # 核心业务 - 皮套管理
    'case_movement',
    'case',
    # 核心业务 - 订单附属
    'notification',
    'approval_log',
    'approval_request',
    # 湖北订单 - 湖北外发
    'outsource_shipment_item',
    'outsource_shipment',
    'order_outsource_process_flow',
    'order_outsource_process',
    'outsource_process_type',
    # 核心业务 - 订单
    'order_item',
    'order_status_log',
    'order_batch_audit_log',
    'order_sync_record',
    'sync_retry_queue',
    'order',
    # 核心业务 - 批量导入暂存
    'staging_stock_out',
    'staging_stock_in',
    'staging_order',
    'staging_purchase_plan',
    # 核心业务 - 生产
    'production_plan_log',
    'production_plan',
    'daily_production_record',
    'craft_work',
    'packaging_record',
    # 采购中心 - 采购计划（引用 product，须在 product 之前删除）
    'purchase_plan_details',
    'purchase_plans',
    # 核心业务 - 产品与 BOM（product_packaging 已删，见迁移 pg_standalone_054）
    # product_customer / finished_stock_remark 引用 product，必须在 product 之前
    'product_accessory',
    'product_fabric',
    'product_material',
    'product_role',
    'product_customer',
    'finished_stock_remark',
    'product',
    # 采购中心
    'material_registration_item',
    'material_registration',
    'purchase_order_generate_attempt',
    'purchase_order_sku',
    'purchase_order_item',
    'purchase_order',
    'shipment_records',
    'supplier',
    'role',
    'modification_log',
    'saved_query',
    # 系统管理（用户管理 / 客户管理 / 备份配置除外）
    'app_version',
    'audit_log',
    'web_vital',
    'backup_record',
    # 编号计数器（重置，上线后单号从 001 重新开始）
    'numbering_counter',
    'numbering_audit',
    # 导入文件登记（引用 user；开发期全清时 user 在最后清，故放在身份表之前）
    'import_file_registry',
)


@dataclass(frozen=True)
class Scope:
    """一个清库范围：清哪些表、保留哪些表。"""

    name: str
    description: str
    clear: tuple[str, ...]
    keep: frozenset[str]


# 身份表放在业务表之后清：order / product_customer / import_file_registry 都引用
# 它们，必须先删子表再删父表。
_IDENTITY_CLEAR_ORDER = (
    'customer_access_log',
    'order_sync_config',
    'customer',
    'user_permission',
    'user',
)

PRODUCTION_SCOPE = Scope(
    name='PRODUCTION',
    description='上线清库：清业务数据，保留用户 / 客户 / 运行配置',
    clear=CORE_CLEAR_TABLES,
    keep=frozenset(CONFIG_TABLES | IDENTITY_TABLES | NON_ORM_TABLES),
)

DEV_FULL_SCOPE = Scope(
    name='DEV_FULL',
    description='开发期全量清空：连用户 / 客户一起清',
    clear=CORE_CLEAR_TABLES + _IDENTITY_CLEAR_ORDER,
    keep=frozenset(CONFIG_TABLES | NON_ORM_TABLES),
)

DEV_KEEP_USERS_SCOPE = Scope(
    name='DEV_KEEP_USERS',
    description='开发期清业务数据、保留用户管理',
    clear=(*CORE_CLEAR_TABLES, 'customer_access_log', 'order_sync_config', 'customer'),
    keep=frozenset(CONFIG_TABLES | NON_ORM_TABLES | {'user', 'user_permission'}),
)

SCOPES = {
    scope.name: scope
    for scope in (PRODUCTION_SCOPE, DEV_FULL_SCOPE, DEV_KEEP_USERS_SCOPE)
}


class ScopeError(RuntimeError):
    """清库范围与 ORM 不一致 —— 调用方必须拒绝执行。"""


def orm_tables() -> set[str]:
    """当前 ORM 的全部表名（运行时从 metadata 取，避免与模型漂移）。"""
    import fastapi_app.shared_models  # noqa: F401  确保全部模型已注册到 metadata
    from fastapi_app.shared_models import Base

    return {t.name for t in Base.metadata.tables.values()}


def ordered_keep(scope: Scope) -> list[str]:
    """按稳定顺序返回该 scope 的保留表（快照 / 复核输出要可重复）。"""
    return [table for table in KEEP_ORDER if table in scope.keep]


def verify_coverage(scope: Scope) -> list[str]:
    """既未清空也未保留的 ORM 表（空列表 = 覆盖完整）。"""
    tables = orm_tables()
    return sorted(tables - set(scope.clear) - set(scope.keep))


def verify_stale(scope: Scope) -> list[str]:
    """清单里已不存在的表（空列表 = 无过期登记）。"""
    tables = orm_tables()
    registered = (set(scope.clear) | set(scope.keep)) - NON_ORM_TABLES
    return sorted(registered - tables)


def scope_problems(scope: Scope) -> list[str]:
    """该 scope 的全部问题（空列表 = 可安全执行）。"""
    problems: list[str] = []
    uncovered = verify_coverage(scope)
    if uncovered:
        problems.append(f'既未清空也未保留的 ORM 表: {", ".join(uncovered)}')
    stale = verify_stale(scope)
    if stale:
        problems.append(f'清单里已不存在的表: {", ".join(stale)}')
    overlap = sorted(set(scope.clear) & set(scope.keep))
    if overlap:
        problems.append(f'同时出现在清除与保留清单: {", ".join(overlap)}')
    return problems


def assert_scope_sound(scope_name: str) -> Scope:
    """范围与 ORM 不一致时抛错（fail-closed）——调用方据此拒绝执行。"""
    scope = SCOPES[scope_name]
    problems = scope_problems(scope)
    if problems:
        detail = '\n  - '.join(problems)
        raise ScopeError(
            f'清库范围 {scope_name} 与 ORM 不一致，拒绝执行：\n  - {detail}\n'
            f'处置：在 scripts/purge_scope.py 里给这些表定级'
            f'（进 CORE_CLEAR_TABLES / IDENTITY_TABLES / CONFIG_TABLES）。'
        )
    return scope


__all__ = [
    'CONFIG_TABLES',
    'CORE_CLEAR_TABLES',
    'DEV_FULL_SCOPE',
    'DEV_KEEP_USERS_SCOPE',
    'IDENTITY_TABLES',
    'KEEP_ORDER',
    'NON_ORM_TABLES',
    'PRODUCTION_SCOPE',
    'SCOPES',
    'Scope',
    'ScopeError',
    'assert_scope_sound',
    'ordered_keep',
    'orm_tables',
    'scope_problems',
    'verify_coverage',
    'verify_stale',
]
