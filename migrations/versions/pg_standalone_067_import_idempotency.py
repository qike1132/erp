"""导入幂等双层防护：文件指纹登记表 + inventory_log 幂等列

背景
----
第九轮审计修复了备货导入的库存翻倍（应用层两级去重），但证据链显示
防护缺口仍大：

1. **出货导入与订单导入完全没有应用层去重**（batch_import_core.py 的
   ``import_stockouts_from_data`` / ``import_orders_from_data`` 未传
   ``dedupe``），重传同一 Excel 会双扣库存 / 重复建单。
2. **备货导入的去重窗口仅限当天**（pre-load 只查当日记录），隔天重传
   同一文件绕过护栏。
3. **应用层去重存在 TOCTOU 竞态**：pre-load 查库与 INSERT 之间无锁，
   并发上传双写。
4. **单号防不住重传**：stockin_no / stockout_no 均为导入时系统新生成
   （numbering.py 的日期+序号），每次导入都是新单号，表上既有的
   UNIQUE 约束永不触发。

设计（两层，见 docs/superpowers/specs/2026-10-04-erp-incremental-path-decision.md P1-a）：

**第 1 层 —— ``import_file_registry``**：文件上传型导入的闸门。
sha256 哈希 + 导入类型构成业务唯一键，``UNIQUE (file_hash, import_type)``
在 DB 层原子拦截「完全相同的文件重复导入」（含并发双击：第二个事务
违反唯一约束回滚）。命中即整文件拒绝并提示上次导入时间，行为从备货
路径的「静默跳过重复行」改为「显式拒绝 + 提示」——换来出货/订单路径
从零到一的防护。

**第 2 层 —— ``inventory_log.idem_key``**：导入路径写入流水时填入
规范化业务组合键（与备货去重护栏同口径 ``客户|产品|日期|数量``），
部分唯一索引 ``WHERE idem_key IS NOT NULL`` 只约束导入来源。
拦第 1 层拦不住的场景：编辑后重传（新哈希）、多文件重叠行、隔天重传、
并发 TOCTOU。手工录入 / 审批回滚 / 修改删除等路径不填（NULL 不受
部分索引约束），行为零变化。

**明确不做**：
- 存量数据不回填 idem_key（无稳定业务键，强填制造假幂等）；
- ``related_id`` 原样保留（四种形态混存的展示字段，报表语义在用）；
- ``change_type`` 的 22 种中文取值不动。

幂等
----
建表用 ``IF NOT EXISTS``、加列用 ``ADD COLUMN IF NOT EXISTS``、
索引带存在性守卫——重复执行安全。

Revision ID: pg_standalone_067_import_idempotency
Revises: pg_standalone_066_case_product_root_unique
Create Date: 2026-10-04
"""
from alembic import op

revision = 'pg_standalone_067_import_idempotency'
down_revision = 'pg_standalone_066_case_product_root_unique'
branch_labels = None
depends_on = None

# DDL 提为模块级常量：测试复用同一份 SQL，避免测试与迁移漂移。
_DDL_REGISTRY_TABLE = """
        CREATE TABLE IF NOT EXISTS import_file_registry (
            id                BIGSERIAL PRIMARY KEY,
            file_hash         TEXT        NOT NULL,
            import_type       TEXT        NOT NULL,
            original_filename TEXT        NOT NULL,
            uploaded_by       BIGINT      REFERENCES "user" (id),
            row_total         INTEGER,
            result_summary    JSONB,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_import_file UNIQUE (file_hash, import_type)
        )
    """
_DDL_REGISTRY_INDEX = (
    'CREATE INDEX IF NOT EXISTS idx_import_registry_type_time '
    "ON import_file_registry (import_type, created_at DESC)"
)
_DDL_ADD_IDEM_COLUMN = 'ALTER TABLE inventory_log ADD COLUMN IF NOT EXISTS idem_key TEXT'
_DDL_IDEM_INDEX = (
    'CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_log_idem '
    'ON inventory_log (idem_key) WHERE idem_key IS NOT NULL'
)


def upgrade() -> None:
    # ---- 第 1 层：文件指纹登记表 ----
    op.execute(_DDL_REGISTRY_TABLE)
    op.execute(_DDL_REGISTRY_INDEX)

    # ---- 第 2 层：inventory_log 幂等列 + 部分唯一索引 ----
    op.execute(_DDL_ADD_IDEM_COLUMN)
    op.execute(_DDL_IDEM_INDEX)


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_inventory_log_idem')
    op.execute('ALTER TABLE inventory_log DROP COLUMN IF EXISTS idem_key')
    op.execute('DROP INDEX IF EXISTS idx_import_registry_type_time')
    op.execute('DROP TABLE IF EXISTS import_file_registry')
