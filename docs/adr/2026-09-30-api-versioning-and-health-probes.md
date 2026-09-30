# API 版本化与健康探针单一来源（ADR）

> 2026-09-30 架构评审（docs/analysis/07_architecture_review_2026-09-30.md）与优化方案
> （docs/analysis/08_optimization_plan_2026-09-30.md）S7 项的落地记录。
> 按软件架构师纪律：记录"为什么"，不只记录"什么"；同时记录被拒绝的替代方案。

---

## ADR-005: 暂不做 API 版本化——删除 /api/v2（状态：已接受）

**上下文**：`fastapi_app/api/v2/` 提供了 `/api/v2/health` 与 8 个 dashboard 端点
（stats / activities / todos / system-status / mobile / nav-sections /
customer-out-details / customer-order-details），并给每个响应加
`API-Version: 2.0.0`、`Sunset`、`Deprecation` 三个响应头。但这 8 个端点与
`fastapi_app/api/v1/endpoints/dashboard.py` 的同名端点**逐一重复**，实现是
同一批服务函数的薄包装；前端 `frontend-vite/src` 对 `/api/v2` 的请求数为 **0**
（39 处 "v2" 命中全是版本号文案、CSS 类名与测试数据）。同时维护两套等价端点，
唯一实际效果是让 `prod_audit` 的 l5/l6/l11 各多一条扫描路径、让 l8 的健康检查
把 K8s 别名当作契约。

**决策**：删除整个 `fastapi_app/api/v2/` 包、`fastapi_app/main.py` 的导入与
`app.include_router(api_v2_router, prefix="/api")` 挂载，以及随之失效的
`tests/test_api_v2.py`、`scripts/mock_dashboard_v2_test.py`；
`tests/qa/test_smoke.py` 的 9 条 v2 用例与
`fastapi_app/tests/test_dashboard_production_scope.py` 的 v2 孪生用例一并删除
（其 v1 版本保留了完全相同的断言）。`scripts/prod_audit` 的 l5/l6/l11 里对
`api/v2/endpoints` 的引用**保留**：它们都被 `if not endpoints_dir.exists(): continue`
守护，属"将来若再引入 v2 仍适用"的前瞻性常量，删除只会制造无谓 diff。

**后果**：单一 API 面，路由表、OpenAPI schema 与审计扫描范围各减一套；
代价是"版本化接缝"这一扩展位被撤掉——需要版本化的那天要重新引入。

**何时才需要重新引入版本化**（触发条件，不是时间表）：
1. 存在**无法同版本兼容**的破坏性变更（响应字段语义变更、必填参数新增），
   且有外部系统（非本项目前端）在调用；
2. 或需要按调用方分批灰度迁移，而兼容层（字段同时返回新旧两种形状）已不足以覆盖。

在此之前，正确的做法是**在 v1 内做向后兼容的增量演进**（新增可选字段、
新端点），而不是维护一套并行前缀。

**被拒绝的替代方案**：
- **保留 v2 并逐步把前端迁到 v2**：迁移收益为零（功能完全等价），却让
  "两套端点长期并存"变成常态，重复实现会继续漂移。
- **保留 v2 但加 `Deprecation: true` 头做过渡**：前端从未调用 v2，
  没有需要过渡的调用方，过渡期只是延迟清理。

---

## ADR-006: 健康探针单一来源（状态：已接受）

**上下文**：系统里有两套健康端点。
- **真实探针**（app 层，`fastapi_app/core/health.py` 的 `register_health_routes(app)`，
  由 `fastapi_app/main.py` 调用）：`GET /api/health`（含备份状态汇总）、
  `GET /api/health/live`（liveness）、`GET /api/health/ready`（readiness，
  真实检查 DB 连通性与 Redis ping）、`GET /api/health/startup`、
  `GET /api/health/arq`（ARQ worker 存活探针）、`GET /metrics`。
- **重复别名**（`fastapi_app/api/v1/endpoints/auxiliary.py`）：
  `/aux/health`、`/aux/ready`、`/aux/healthz`、`/aux/readyz`，
  返回硬编码 `{"status": "ok", "timestamp": ...}`，docstring 自称 "K8s probe alias"。

问题在于：`auxiliary_router` 是以**路由器级** `Depends(get_current_user_id)` 挂载的
（`fastapi_app/api/v1/router.py`），因此这四个别名端点**必须带 JWT 才能访问**——
对外部探活工具（nginx / NSSM / 负载均衡）完全不可用，且返回固定 "ok" 而不反映
DB/Redis 依赖状态，属于"看起来有探针、实际探不出故障"的假监控。
真正的探活入口是 `/api/health/live` 与 `/api/health/ready`（nginx 已按此配置）。

**决策**：删除 auxiliary.py 的四个别名端点、`HealthCheckResponse` 模型与仅为其
服务的 `import time`；真实探针成为唯一健康契约。同步把
`scripts/prod_audit/layers/l8_observability.py` 的 `_HEALTH_ENDPOINT_PATHS`
从 `("/health", "/ready", "/healthz", "/readyz")` 收敛为
`("/health", "/health/live", "/health/ready")`，并把 `core/health.py` 加入
该检查的扫描文件（探针注册在 app 层，不在 endpoints 目录内）——否则删除别名后
l8 会误报一条 LOW "部分健康检查端点缺失"。

**后果**：健康检查只有一个真相源；l6 的鉴权白名单与 l11 的部署检查无需改动
（`core/health.py` 已在 l11 扫描范围内，`/api/health` 满足其
`path.endswith("/health")` 判据，不产生新告警）。运维侧的探活命令与
`scripts/ops/watchdog.py` 检查项保持一致。

**已知残留（有意保留，非遗漏）**：
- `scripts/prod_audit/layers/l11_deployment.py:67` 的
  `_HEALTH_ENDPOINT_PATHS = ("/health", "/ready", "/healthz", "/readyz")`
  与 `:654` 的 `"/healthz" not in found_paths` 判断保留原样：该层扫描
  `core/health.py`，`/api/health` 已满足其 HIGH 级判据，删除别名不会产生
  新告警；改动它只增加 diff 与回归面。
- `scripts/PERFORMANCE_REPORT.md` 与 `scripts/performance_report.json` 里的
  `/api/v1/aux/health` 是**历史压测记录**（当时确实压的是该端点），不改写历史；
  `scripts/quick_benchmark.py` 的目标端点已改为 `/api/health/live`，脚本仍可用。

**验收**：`GET /api/health/live` 无 token 返回 `{"status": "alive"}`；
`grep -rn "healthz\|readyz" fastapi_app/api/` 为空。
