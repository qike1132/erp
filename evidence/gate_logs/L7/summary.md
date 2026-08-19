# L7 性能与可扩展性审核

## 查询模式
扫描 SELECT * / 循环内查询(N+1)。

## 索引提示
CTE 查询索引校验,参考 docs/cte_index_suggestions.md。

## 分页
列表端点须含 offset/limit/page/page_size 参数。

## 缓存
dashboard/stats 类服务须使用 Redis 缓存。

## 前端性能
路由 lazy loading / code splitting / 图片 loading="lazy"。

## 产物体积
前端 dist/ 总体积 gzip 后 ≤ 2MB。
