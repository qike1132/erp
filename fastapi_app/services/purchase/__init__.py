"""采购查询辅助子包(从 purchase_order_query_helpers.py 拆分)。

- _common: 公共辅助
- _list: 列表查询
- _completed: 完成态查询
- _supplier: 供应商维度
- _factory: 工厂维度
- _unprocessed: 未处理记录

purchase_order_query_helpers.py 保留为 Facade,re-export 全部符号保持兼容。
"""
