# L5 API 契约与版本兼容审核

## 路由对齐
复用 check-api-alignment.mjs / check-route-alignment.mjs。

## Schema 一致性
对比 Pydantic 模型与前端 TypeScript 接口字段。

## 错误码统一
审查统一错误响应格式与白名单状态码(401/403/404/400/422/500)。

## 版本兼容
v2 不得破坏 v1 契约,v2 新接口须标注版本与迁移说明。
