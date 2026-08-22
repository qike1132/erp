"""仪表盘服务子包(从 dashboard_service.py 拆分)。

- stats: 核心统计
- activities: 动态
- todos: 待办
- nav: 导航/系统状态
- customer: 客户维度聚合
- mobile: 移动端看板

Schema 已归位 schemas/dashboard.py。
dashboard_service.py 保留为 Facade,re-export 全部符号保持兼容。
"""
