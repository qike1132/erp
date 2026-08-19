# L4 数据访问层审核

## N+1 基线验证
6 个高危文件循环内查询数应为 0。

## SQL 注入扫描
扫描 services/ 中 f-string/.format()/% 拼接。

## nosec B608 校验
stock_service.py 6 处 nosec B608 标注须保留。
