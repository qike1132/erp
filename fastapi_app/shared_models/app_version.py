"""app_version —— 移动端 App（OTA）版本表。

**为什么有这张表却没有模型**

`app_version` 是历史遗留表：由 `migrations/versions/add_app_version.py`
的注释明确记载「表在 Alembic 之外手工创建」，该迁移只是空转占位（用于维持
下游 `add_stock_return` 的 `down_revision`）。此后 060 也仅 ALTER 了它的
`updated_at` 列。因为没有 ORM 模型，它一直是 `alembic check` 的「库有、模型无」
漂移项（`remove_table`）——一旦有人对生产库跑 autogenerate，它会被生成成
`DROP TABLE`，直接打挂引用它的 OTA/备份脚本。

**本模型的职责**

把该表纳回 ORM，消除这一漂移源。**列定义逐项对齐生产库真实结构**
（`information_schema.columns` 实测，2026-10-05）：类型、可空性、server_default
均以库为准，不加库里没有的注释，避免引入新的漂移。

**已知现状**：生产库 0 行；API 层与前端均无引用；仅
`scripts/insert_test_app_versions_simple.py` / `scripts/clear_all_data.py` /
`scripts/purge_simulated_data.py` 等运维脚本用裸 SQL 访问。注意
`scripts/insert_1_3_version.py` 用的是不存在的 `file_md5` / `is_pushed` 列
（陈旧脚本），真实列名是 `md5_hash` / `pushed`。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class AppVersion(Base):
    """单条 App 版本记录（OTA 发布/推送状态）。"""

    __tablename__ = 'app_version'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'android'"),
    )
    version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[str] = mapped_column(String(50), nullable=False)
    download_url: Mapped[str] = mapped_column(String(500), nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int | None] = mapped_column(Integer)
    md5_hash: Mapped[str | None] = mapped_column(String(64))
    force_update: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text('false'),
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text('true'),
    )
    pushed: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text('false'),
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(), server_default=text('now()'),
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())

    __table_args__ = (
        Index('idx_app_version_platform_code', 'platform', 'version_code'),
    )
