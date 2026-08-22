"""订单域子包。

从 order_crud.py 按职责拆分的子模块：
- _common:  事件发布/缓存失效/异常等共享辅助
- beile:    湖北订单+备货合并查询与确认（beile-order 页面）

order_crud.py 保留为 Facade，re-export 所有公共函数以保持向后兼容。
"""
