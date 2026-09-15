"""Web Vitals 持久化表：web_vital

**背景**

前端体验指标此前只存在于进程内存（`endpoints/monitoring.py` 的 `_vital_stats`），
存在三个硬伤，导致"前端体验提升 X%"永远无法验收：

1. 重启即丢，无法形成跨时间基线；
2. 多 worker 各自独立（原 docstring 自认 per-worker）；
3. 仅 poor / needs-improvement 打日志，正常样本不落任何地方。

本表用于沉淀真实用户体验基线（LCP / CLS / INP / TTFB），使前端优化可被量化。

**写入方**：`POST /api/v1/monitoring/vitals`（前端 sendBeacon 上报，按设计不认证）。
防护不依赖全局限流（`core/limiter.py` 中 `enabled=False`），而是靠：
单请求批次上限 50 条 + 30 天保留期清理 + 落库失败熔断。

Revision ID: pg_standalone_041_web_vital
Revises: pg_standalone_040_notification_related_order_idx
Create Date: 2026-09-14
"""
from alembic import op

revision = 'pg_standalone_041_web_vital'
down_revision = 'pg_standalone_040_notification_related_order_idx'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS：与项目既有迁移风格一致，允许重复执行
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS web_vital (
            id              SERIAL           PRIMARY KEY,
            name            VARCHAR(16)      NOT NULL,
            value           DOUBLE PRECISION NOT NULL,
            rating          VARCHAR(24)      NOT NULL,
            delta           DOUBLE PRECISION,
            navigation_type VARCHAR(24),
            path            VARCHAR(500),
            created_at      TIMESTAMPTZ      NOT NULL DEFAULT now()
        );
        """
    )
    # 基线查询主路径：按指标名取时间窗样本算分位数
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_wv_name_created '
        'ON web_vital (name, created_at DESC);'
    )
    # 劣化排查：快速捞出 poor 样本
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_wv_rating_created '
        'ON web_vital (rating, created_at DESC);'
    )
    # 保留期清理：DELETE ... WHERE created_at < now() - interval
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_wv_created_desc '
        'ON web_vital (created_at DESC);'
    )
    op.execute(
        "COMMENT ON TABLE web_vital IS "
        "'前端 Web Vitals 采样（LCP/CLS/INP/TTFB），用于建立真实用户体验基线';"
    )


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS web_vital;')
