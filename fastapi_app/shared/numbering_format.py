"""编号格式契约（单一来源）。

编号格式：``<前缀>-<YYMM>-<序号>``，如 ``PO-2611-001``（2026 年 11 月）。

历史格式 ``<前缀>-<YYYYMMDD>-<序号>``（如 ``PO-20261101-0001``）永久保留：
存量单号已打印、已对账、已进供应商往来，**不可重写**。故正则必须同时接受
两种期间段（4 位年月 / 8 位日期），用交替而不是 ``[0-9]{4,8}``——后者会把
5/6/7 位的手工错误也判成合法。

``NUMBERING_FORMAT_REGEX`` 是「格式守卫」正则，被以下位置共用**同一字面量**：

- 9 张编号表的**部分表达式索引** ``idx_*_no_date_seq`` 的谓词
  （``shared_models`` 各模型的 ``postgresql_where``，迁移 pg_standalone_116 重建）
- 取号 ``services/numbering_sequence.py::read_period_max`` 的过滤器
- 巡检 ``tasks/numbering_audit_task.py`` 的当期 max / 违规计数 SQL
- 对账 ``services/numbering_reconcile.py`` 的水位回填 SQL

为什么必须单一来源：PostgreSQL **不做正则蕴含推断**——查询谓词与索引谓词
任一处单独漂移，索引即静默失配、查询退回顺扫，**无任何报错**
（drift 对账脚本明确不比对谓词差异）。一致性由
``fastapi_app/tests/test_numbering_predicate_alignment.py`` 钉死。

注意：迁移文件内的 SQL 是静态快照，**不 import 本常量**（迁移执行时
运行时代码可能已变更）；迁移与常量的字面一致由上述对账测试保证。
"""
from __future__ import annotations

# 新号 4 位年月（YYMM）＋ 存量 8 位日期（YYYYMMDD）
NUMBERING_FORMAT_REGEX = r'^[A-Z]+-(?:[0-9]{4}|[0-9]{8})-[0-9]+$'
