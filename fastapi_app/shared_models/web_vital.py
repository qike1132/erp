"""
Web Vitals 性能指标模型 - 持久化前端真实用户体验数据

**为什么需要这张表**

`api/v1/endpoints/monitoring.py` 此前把指标只存在**进程内存**
（`_vital_stats: dict[str, deque]`，maxlen=500），存在三个硬伤：

1. **重启即丢** —— 无法形成跨时间基线；
2. **多 worker 各自独立** —— 该端点 docstring 自认
   `"per-worker stats (multi-worker deployments aggregate separately)"`；
3. **只对 poor / needs-improvement 打日志** —— 正常样本不落任何地方，
   于是既拿不到真实分布，也无法计算 p50/p75。

结果是"前端体验提升 X%"永远无法验收。本表用于沉淀真实用户体验基线
（LCP / CLS / INP / TTFB），使前端优化从"凭感觉"变为"可量化"。

**写入来源**：`POST /api/v1/monitoring/vitals`（前端 `navigator.sendBeacon` 上报）。
该端点按设计**不认证**（sendBeacon 无法携带 auth header），因此写入侧必须
自带防护：批次上限 50 条/请求 + 保留期清理（见 monitoring.py）。
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class WebVital(Base):
    """单条 Web Vitals 采样

    一个页面加载会产生多条记录（LCP/CLS/INP/TTFB 各一条），
    通过 `path` + `created_at` 关联到同一次会话。
    """
    __tablename__ = 'web_vital'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(16), nullable=False, comment='指标名: LCP/CLS/INP/TTFB/FCP',
    )
    value: Mapped[float] = mapped_column(
        Float, nullable=False, comment='指标值（LCP/TTFB/FCP 单位 ms，CLS 为无量纲分数）',
    )
    rating: Mapped[str] = mapped_column(
        String(24), nullable=False, comment='评级: good/needs-improvement/poor',
    )
    delta: Mapped[float | None] = mapped_column(
        Float, comment='相对上一次上报的增量（web-vitals 语义）',
    )
    navigation_type: Mapped[str | None] = mapped_column(
        String(24), comment='导航类型: navigate/reload/back-forward/prerender',
    )
    path: Mapped[str | None] = mapped_column(
        String(500), comment='来源页面（取自 Referer），用于按页面维度分析',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
        nullable=False, comment='上报时间',
    )

    __table_args__ = (
        # 基线查询主路径：按指标名取时间窗内的样本算分位数
        Index('idx_wv_name_created', 'name', desc('created_at')),
        # 劣化排查：快速捞出 poor 样本
        Index('idx_wv_rating_created', 'rating', desc('created_at')),
        # 保留期清理：DELETE ... WHERE created_at < now() - interval
        # 注：created_at 列刻意不加 index=True —— 本 DESC 索引可反向扫描服务
        # 升序查询，再加单列索引是冗余（且会与迁移脚本建出的索引集合不一致）。
        Index('idx_wv_created_desc', desc('created_at')),
    )
