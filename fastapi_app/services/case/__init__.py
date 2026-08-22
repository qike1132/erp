"""皮套域子包(从 case_service.py 拆分)。

- _common: 日期/分页/过滤工具与常量
- _serializers: 入库/出库序列化
- queries: 查询域
- commands: 命令域

case_service.py 保留为 Facade,re-export 全部函数以保持向后兼容。
"""
