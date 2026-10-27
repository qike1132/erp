# 滨发协同系统全栈测试与代码审查报告

- 审查日期：2026-10-27
- 审查基线：`0e89794f5c343325f5c4ec9d04832270cd4a544b`（main，2026-10-26 22:22）
- 审查范围：`fastapi_app/`、`frontend-vite/`、`tests/`、迁移、配置、CI、构建与部署脚本
- 安全边界：未重启服务、未修改生产配置、未向生产库写入。只使用 `*_test` 测试库、隔离 Redis 库 15、隔离前端产物和模拟 HTTP
- 原始审查结论：**打回（测试与发布证据不通过）**。未在业务源码中证实 Blocker 或 High 级功能缺陷，但存在 3 项 High 级测试安全问题/失真问题
- **修复后结论（2026-10-27，见 §7）：全部已列问题已关闭；本地真实 PostgreSQL 全量、首次 GitHub Actions 远端门禁和独立只读复审均通过，本次范围内通过**

> §3 保留原始审查快照；实际处置与回归证据以 §7 为准。

## 1. 项目结构与技术栈

| 层级 | 路径 | 实际情况 |
|---|---|---|
| 后端 | `fastapi_app/` | FastAPI 全异步、SQLAlchemy 2.0、asyncpg、PostgreSQL 18、Redis 7、ARQ、WebSocket |
| 接口层 | `fastapi_app/api/v1/` | 45 个端点模块；当前 OpenAPI 共 348 条路径，业务路由通过 `router.py` 绝对挂载 |
| 业务层 | `fastapi_app/services/` | 订单、库存、采购、生产、板房、审批、备份等领域服务；以 `flush` 为主，事务由端点/依赖收口 |
| 数据层 | `shared_models/`、`migrations/` | SQLAlchemy 2.0 模型、Alembic 单 head；CI 校验升级与模型一致性 |
| 前端 | `frontend-vite/` | Vue 3.5、TypeScript 6、Vite 7.3.6、Pinia、Vue Query、Vitest 4、Playwright 运行库 |
| 测试 | `tests/`、`fastapi_app/tests/` | 真实 PostgreSQL 集成树与 Mock/SQLite 单测树并存 |
| 部署 | nginx :3000 → uvicorn 127.0.0.1:5002 → PostgreSQL/Redis | NSSM 托管 `erp-web/erp-prod/erp-arq/erp-redis/erp-redis-broker` |
| CI | `.github/workflows/ci-cd.yml` | test / lint / frontend / build 四个 job；不执行真实部署 |

核心链路已沿“页面/API 客户端 → 路由端点 → 服务 → 模型/表”核对：

1. 客户订单创建：`CustomerOrderView` → `orderApi.create` → `/api/v1/orders/create` → `order_service.create_order` → `Order/OrderItem/Product`
2. 出库扣减：`StockOutView` → `/api/v1/stock/out/create` → `stock_service` → `StockOut/Product/库存流水`
3. 一键采购：采购中心 → `/api/v1/purchase-center/orders/one-click-generate` → 采购服务 → `PurchaseOrder/PurchaseOrderItem`
4. 鉴权：登录页 → `/api/v1/auth/login` → Cookie/Bearer 双认证 → 路由守卫与后端权限依赖

只读健康快照 `logs/prod_runner.json` 在 11:01 显示 `ready: true`、`frontend_ok: true`，后端/Redis/broker 均为 ready/ok；这只说明进程健康，不等同于业务正确。

## 2. 测试补充与执行结果

### 2.1 新增测试

| 文件 | 层级 | 覆盖 |
|---|---|---|
| `frontend-vite/tests/e2e/login-flow.e2e.mjs` | 浏览器 E2E | 正常登录进仪表盘；401 错误凭据；503 服务异常后按钮恢复；空必填字段；未登录深链重定向 |
| `fastapi_app/tests/test_order_boundary_api.py` | 单元 + 接口 | 数量 1/9,999,999 合法；0、负数、10,000,000 非法；空客户、超长客户、零产品 ID 在业务副作用前返回 422；上限值原样传到服务层 |
| `frontend-vite/package.json` | 测试入口 | 新增 `test:e2e`，使用 Node 原生测试运行器和现有 Playwright 依赖，未新增依赖 |

浏览器 E2E 使用隔离构建产物 `logs/fullstack-audit-20261027/frontend-dist`，通过 Playwright 路由拦截模拟 API，不触碰真实账号、生产 API 或数据库。它验证的是前端鉴权与错误处理，不是真实前后端联合链路。

### 2.2 已执行结果

| 检查 | 命令/范围 | 结果 |
|---|---|---|
| Python Ruff | `ruff check fastapi_app tests fastapi_app/tests utils` | 通过 |
| Python 类型 | `mypy --config-file mypy.ini --no-native-parser` | 通过，380 个源文件 |
| 质量门禁 | `python scripts/quality_gate.py --verbose` | 通过；N+1 0、裸 except 0、env drift 0、单 head；Bandit 21 条存量基线 |
| 前端类型 | `npm run type-check` | 通过 |
| 前端 ESLint | `npm run lint` | 通过 |
| 前端单测 | `npm test` | **232 文件 / 1757 项全部通过** |
| 浏览器 E2E | `npm run test:e2e` | **5/5 通过**，有成功页截图 |
| 后端聚焦测试 | `test_order.py`、订单 Schema、认证服务 | **36/36 通过** |
| 新增后端测试 | `test_order_boundary_api.py` | **13/13 通过** |
| 后端完整测试树 | `fastapi_app/tests` + coverage | 运行到 100%，但汇总被 `WinError 5` 截断；失败集复核为 4 failed / 28 errors，抽查均为数据库连接被重置或 `.env` 无权读取，**不计为通过** |
| 真实 PostgreSQL 全量 pytest | `tests + fastapi_app/tests` | **未执行**：进程未提权，UAC 未完成；不伪造全量结果 |
| 前端生产构建 | 隔离 `outDir` 执行 Vite | 通过，31.26s；未覆盖线上 `dist`；存在 >600KB chunk 提示 |
| 依赖漏洞 | `pip-audit`、`npm audit --omit=dev` | 均 0 个已知漏洞 |
| 依赖锁 | `check_requirements_lock.py` | 七档 `.txt/.lock` 全部同步 |
| 密钥扫描 | `scan_secrets.py` | 通过，无受版本控制凭据 |
| OpenAPI 对齐 | 后端快照 + 前端端点 | 348 条后端路径；147 个字面量端点全部命中；快照一致 |
| 跨端对齐 | `check:api` / `check:api:pc` / `check:routes` / `check:dto` / `check:types` | 全部通过 |
| 孤儿模块 | `check_orphan_modules.py` | 通过；1 条 WARN，见 L-03 |
| 文件规模 | `file_size_gate.py --all` | 1900 个文件均未超 1600 行 |

前端覆盖率补充测量（只含 3 个核心测试文件，共 63 项通过，不是全项目覆盖率）：

| 范围 | 语句 | 分支 | 函数 | 行 |
|---|---:|---:|---:|---:|
| 三项核心模块汇总 | 67.96% | 66.02% | 60.91% | 68.67% |
| `src/stores/auth.ts` | 96.58% | 90.42% | 92.85% | 98.07% |
| `OutsourcePresetTab.vue` | 81.11% | 74.66% | 50% | 81.25% |
| `src/api/request.ts` | 38.15% | 33.33% | 43.58% | 37.87% |

后端没有可采信的全项目覆盖率：真实数据库全量套件未满足运行前提，局部 Mock 覆盖率会误导，故不报百分比。

## 3. 分级问题清单

### High

#### H-01 旧 Selenium E2E 默认指向生产，并包含写操作

- 位置：`tests/e2e/conftest.py:35-38`；`tests/e2e/test_e2e_order_flow.py:47-48, 75-101, 103-125, 127-143`
- 原因：`E2E_BASE_URL` 默认值是 `http://localhost:5002`，即生产 uvicorn；用例硬编码 `admin/admin123`，并会创建订单、入库、审批列表第一条记录。路径与选择器（`/orders/new`、`/stock/in`、`approval-list`）已与当前 Vue 路由/组件脱节。
- 影响：在唯一的生产环境执行 `pytest tests/e2e --e2e` 时，一旦选择器被补齐，测试会直接写入生产业务数据；即使当前多数用例先失败，危险默认值仍然存在。CI 又通过 `--ignore=tests/e2e` 完全跳过它，问题不会被流水线发现。
- 建议：删除默认 URL，要求显式 `E2E_BASE_URL` 且拒绝 3000/5002 和生产主机；测试写操作只允许指向一次性测试栈；账号从受控测试夹具注入；按当前路由克隆为 Playwright E2E，并纳入隔离环境。

#### H-02 API E2E 的“生产指纹守卫”可被端口 3000 + 测试 DSN 绕过

- 位置：`tests/e2e_api/conftest.py:133-154`；写路径见 `tests/e2e_api/test_write_paths.py:355-599`
- 原因：守卫只拒绝 API 端口 5002 和 DSN 名恰为 `erp_system`。生产对外入口是 nginx `:3000`，因此设置 `E2E_API_BASE_URL=http://host:3000`、同时把 `ERP_E2E_REAL_DATABASE_URL` 指向测试库即可通过检查；但该后端实际连接生产库，写用例仍会写生产。
- 影响：守卫注释声称“无绕过开关”，实际存在真实旁路，可能造成订单、产品、采购和库存生产数据污染。
- 建议：按主机/端口白名单只允许显式隔离实例；禁止 3000、5002 和生产域名；让后端暴露仅测试环境可用的实例指纹（例如测试库 nonce），E2E 在发起写请求前校验指纹；守卫失败必须 fail-closed。

#### H-03 核心订单/库存测试存在自证或恒真，制造假覆盖

- 位置：`tests/test_order_management.py:13-17, 162-182, 354-374`；`tests/test_stock_management.py:12-16, 131-143`；`tests/test_integration.py:93-103, 129-134`
- 原因：订单测试明确不导入生产代码，自建 SQLite 模型，并断言 `quantity=-10`、`quantity=0` 可以成功入库，直接违背生产 `OrderCreate(gt=0)`。库存测试也是自建模型；库存不足用例只 `print` 不调用任何业务、也无拒绝断言。`test_concurrent_stock_operations` 没有并发，`test_insufficient_stock_detection` 只断言 `requested > current_stock`，是恒真条件。
- 影响：这些文件会显示为绿色，却无法发现订单负数、超卖、并发扣减等核心回归；评审标准将这类恒真/镜像测试定为 High。
- 建议：将文件改为导入当前 `OrderCreate`/ASGI 测试客户端和真实测试库；删除自建模型；对库存不足断言状态码、库存不变、无流水；并发用 `asyncio.gather` 或独立连接制造真实竞争；补变异检查证明测试会红。

### Medium

#### M-01 Token 撤销检查在 Redis 故障时对所有普通业务端点 fail-open

- 位置：`fastapi_app/core/auth/blacklist.py:175-214`；默认接线 `fastapi_app/api/v1/router.py:95-101, 119-125, 327-341`；仅备份使用 strict `router.py:278-284`；access token 默认 60 分钟 `core/config.py:364`
- 原因：Redis 不可用且进程本地 LRU 未命中时，`fail_closed=False` 直接返回“未撤销”。普通订单、库存、采购、用户、权限接口都走这个版本，只有 `/backup` 使用 strict。
- 影响：Redis 故障窗口内，已登出/被吊销的 token 仍可访问业务接口，最长持续到 token 自然过期（默认 60 分钟）。用户状态仍会检查，因此禁用账号不全然失效，但“登出即失效”的保证不成立。
- 建议：高风险写端点（订单、库存、采购、用户/权限）统一使用 strict 或独立撤销存储；缩短 access token TTL；把降级指标接入告警；若坚持可用性优先，应在风险接受记录和运维手册中明确该窗口，而不是只写在代码注释。

#### M-02 工序预设存在两套实现，带完整防护的 composable 未被使用

- 位置：活跃组件 `frontend-vite/src/views/outsource/components/OutsourcePresetTab.vue:117-165`；未消费实现 `src/views/outsource/composables/useOutsourcePresetTypes.ts:119-206`
- 原因：组件仍保留自己的 `fetchAllProcessTypes`，后续页失败只保留当前已取数据并直接覆盖 query 缓存；没有旧缓存完整性比较、`refetchOnMount:'always'`、partial 状态和重试语义。`useOutsourcePresetTypes` 已实现这些防护，但全 `src` 没有导入点。
- 影响：刷新时第 2 页起网络失败，会以不完整列表覆盖此前完整缓存；用户可能把缺失产品误判为“未配置”并重复添加。相关 R7/R8/R13/R36 回归实际保护的是死代码。
- 建议：组件改用 `useOutsourcePresetTypes`，删除重复取数逻辑，补“后续页失败保留旧完整缓存”的组件级回归；若 composable 暂不启用，应删除避免虚假安全感。

#### M-03 测试门禁没有覆盖真实浏览器链路，前端覆盖率无阈值

- 位置：`.github/workflows/ci-cd.yml:126-138, 368-386`；`frontend-vite/vitest.config.ts:32-37`
- 原因：pytest job 明确 `--ignore=tests/e2e`；frontend job 只跑 Vitest、构建和静态对齐，不执行浏览器测试，也没有覆盖率门槛。本次新增的 `test:e2e` 可手工执行，但尚未接入 CI。
- 影响：登录跳转、真实前端产物、浏览器路由/存储、接口联调回归只能在人工环境发现；前端覆盖率下降不会阻止合并。现有后端覆盖率门槛 40% 也偏低，但与当前实测无直接等式关系。
- 建议：在 frontend job 构建后安装 Chromium 并执行 `npm run test:e2e`；为关键模块设置逐步收紧的覆盖率阈值；真实后端 E2E 放到一次性测试栈，不在生产共机执行。

### Low

#### L-01 前端环境变量模板已过期

- 位置：`frontend-vite/.env.example:2-3`
- 原因：模板仍写 `VITE_API_URL` / `VITE_WS_URL`，但全前端源码零消费；实际读取的是 `src/api/request.ts:38` 的 `VITE_API_BASE_URL`，WebSocket 由 `useWebSocket.ts:73-76` 从 `window.location` 推导同源地址。
- 影响：新环境照模板配置后，API 地址和 WebSocket 地址不会生效，排查成本高。
- 建议：改为 `VITE_API_BASE_URL` 和 `VITE_STATIC_ORIGIN` 的说明，删除两个失效键，并纳入 env drift 检查。

#### L-02 文档仍把 Celery 写成现行任务队列

- 位置：`fastapi_app/README.md:9-10, 34, 156`
- 原因：前文写 Celery Broker/Worker，末尾又明确“使用 ARQ，不是 Celery”，同一文件存在两个真相源。
- 影响：新成员可能按 Celery 排查 ARQ 故障或安装错误依赖。
- 建议：统一为 ARQ/Celery 的历史边界，删除现行 Celery 描述。

#### L-03 工序预设极端数据量下无虚拟化

- 位置：`OutsourcePresetTab.vue:41-64, 117-120, 152`
- 原因：护栏允许最多 10,000 条预设，模板会为每条记录渲染完整 chip 节点，没有虚拟滚动或按需展开。
- 影响：目标用例渲染 10,000 个 chip 在 jsdom 中耗时约 4.2s；真实低配终端可能出现明显卡顿。属于极端容量风险，不是当前普通数据下的故障。
- 建议：限制单行展示数量并提供展开，或使用虚拟列表；为 10k 上限建立浏览器性能预算。

#### L-04 孤儿模块检查有一条生产导入图不可达告警

- 位置：`fastapi_app/services/purchase_order_spare.py`
- 原因：`check_orphan_modules.py` 判定其有入边但仅被 scripts/测试引用，生产导入图不可达；仍在 mypy 白名单中。
- 影响：可能是动态调用或历史遗留，无法仅凭静态图确认可删；会增加类型保护与维护成本。
- 建议：确认运行时调用后删除，或补显式入口与原因注释。

## 4. 分层审查结论

- 前端：认证/路由、缓存隔离、CSRF、错误反馈、写请求默认不盲目重试等设计成熟；主要问题是工序预设双实现、模板配置漂移和缺少 CI 浏览器回归。
- 后端/接口：统一错误封装、事务回滚、工厂隔离、分页上限、文件上传防护等实现较完整；未发现可直接复现的越权或注入缺陷。Token 撤销 fail-open 是需明确接受的可用性/安全权衡。
- 数据层：迁移单 head、锁文件同步、事务回滚和库存乐观锁均有专项测试；核心风险不在 SQL 形态，而在测试是否真正触达生产语义。
- 配置/构建/部署：依赖锁、环境漂移门禁、OpenAPI 对齐、密钥扫描、文件规模均通过；CI 不部署生产是符合当前内网 NSSM 拓扑的正确设计。浏览器 E2E 与覆盖率尚未进入发布门禁。
- 可维护性：存在两套工序预设实现、Celery/ARQ 文档冲突、失效环境变量模板和自建测试模型，均会提高后续修改踩坑概率。

## 5. 未验证项与风险

1. 真实 PostgreSQL 全量 pytest 未完成：当前 shell 非提权，根 `.env` ACL 拒绝读取；提权运行器未获得 UAC 确认。最终发布前必须在独占测试库执行并保存完整 VERDICT。
2. 后端完整 `fastapi_app/tests` 的 4 failed / 28 errors 已抽查为环境型失败（DB 连接被重置、`.env` 权限、子进程读取 `.env`），但不能据此宣称整套通过。
3. 浏览器 E2E 使用模拟 API，未验证真实 gunicorn/nginx/数据库全链路；真实写链路仍需一次性隔离栈。
4. 未做压测、容量测试和真实浏览器性能采样；L-03 只是 jsdom 观察结果。
5. 三个并行复核代理因服务端 503 未产出结果，本报告只采用主流程中可复核的源码与命令证据，未虚构独立复核结论。

## 6. 放行前建议顺序

1. 修复 H-01/H-02：删除生产默认值和旁路，所有 E2E 写入 fail-closed。
2. 修复 H-03：重写或明确 skip 自建模型测试，补真实订单/库存并发与边界断言。
3. 提权执行完整 pytest，独占 `erp_system_test`，收集通过数、skip 数、失败数和后端覆盖率。
4. 将已验证的 `test:e2e` 接入 CI 的 frontend job，并保留失败截图。
5. 处理 M-01/M-02，之后再考虑放行；L 级问题可单独排期。

> 原始审查阶段仅新增测试与测试入口。后续修复按用户要求修改了认证依赖、工序预设组件与测试/CI/配置，详见 §7。测试日志位于 `logs/fullstack-audit-20261027/`，其中前后端产物与截图仅作本次审计证据，不应提交版本库。

## 7. 修复实施记录（2026-10-27）

### 7.1 问题关闭状态

| ID | 状态 | 修复内容 |
|---|---|---|
| H-01 | 已关闭 | 删除默认连接生产且写数据的 Selenium 套件；`tests/e2e/conftest.py` 改为必须显式隔离 URL、仅允许回环主机、显式非 3000/5002 端口；移除 Selenium 依赖并刷新 `test.lock`；浏览器回归迁移到隔离 Playwright |
| H-02 | 已关闭 | `tests/e2e_api/conftest.py` 现在同时校验回环主机、显式隔离端口、拒绝 3000/5002、DSN 必须以 `_test` 结尾、拒绝可覆盖目标库/主机/端口的 query 参数；新增 9 项守卫测试 |
| H-03 | 已关闭 | 删除 8 个自建 Flask/SQLite 或恒真测试：`test_order_management.py`、`test_stock_management.py`、`test_integration.py`、`test_product_management.py`、`test_models_coverage.py`、`test_shipment_limit.py`、`test_user_management.py`、`test_routes_coverage.py`；保留真实生产代码测试并新增 13 项订单边界单元/API 测试 |
| M-01 | 已关闭 | 新增 `get_current_user_id_write_strict`：业务写请求在撤销状态不可判定时 401，GET/HEAD/OPTIONS 保留可用性；`/users`、`/permissions`、`/backup` 全方法 strict；上传和前端错误上报也改为写严格 |
| M-02 | 已关闭 | `OutsourcePresetTab.vue` 接入 `useOutsourcePresetTypes`，删除组件内重复取数实现；旧缓存保留、partial 横幅、重试和 `refetchOnMount` 改为单一来源 |
| M-03 | 已关闭 | CI 的 pytest 不再忽略 `tests/e2e`；frontend job 执行覆盖率门禁并向 CI 传 Chromium；CI 构建后执行 `npm run test:e2e`；前端覆盖阈值设为 statements/lines 45%、branches/functions 40% |
| L-01 | 已关闭 | `.env.example` 改为 `VITE_API_BASE_URL`/`VITE_STATIC_ORIGIN`，移除零消费键；同步根 README 与 `PROJECT_MANUAL` |
| L-02 | 已关闭 | `fastapi_app/README.md` 统一为 PostgreSQL 18 + ARQ，目录树改为 `arq_app.py`；项目手册对应待办已标注完成 |
| L-03 | 已关闭 | 单产品首屏最多渲染 50 个工序 chip，其余可展开/收起；新增 60 chip 展开回归 |
| L-04 | 已关闭（确认非缺陷） | `purchase_order_spare.py` 是文档明确标注的“已实现待产品决策接线”特性，不是死代码，保留 WARN；本次不擅自接入业务链路 |
| — | 已关闭 | 修复审计钩子测试的环境假红：保留真实密钥触发串，同时用 `# noqa: S105` 中和与测试目标无关的 Ruff 降级门禁 |

### 7.2 修复后验证

| 验证 | 结果 |
|---|---|
| 前端全量 Vitest | **232 文件 / 1759 项全部通过** |
| 前端全量覆盖率 | **语句 53.55% / 分支 46.29% / 函数 47.70% / 行 54.83%**，均高于 45/40/40/45 阈值 |
| 修复后隔离生产构建 | 通过，Vite 7.3.6，38.73s；未覆盖线上 `dist` |
| 浏览器 E2E（新构建） | **5/5 通过**，正常、401、503、空字段、未登录深链 |
| 订单/认证后端相关回归 | **59/59 通过** |
| 认证、权限、上传回归 | **94/94 通过** |
| Python E2E 目标守卫 | **7/7 通过** |
| API E2E 生产指纹守卫 | **9/9 通过** |
| 工序预设分页/缓存/展开 | **10/10 通过** |
| 质量门禁 | **PASS**，新增违规 0，Vue 超长组件回到基线 4 |
| Ruff / mypy | 通过；mypy 380 个源文件无问题 |
| 前端 type-check / ESLint | 通过 |
| CI YAML | 解析通过，jobs：test/lint/frontend/build |
| 依赖锁 | 七档同步；`test.lock` 已移除 Selenium 及其传递依赖 |
| Python 依赖审计 | 177 个依赖，0 个已知漏洞 |
| `scripts/prod_audit/tests` | 钩子测试文件修复前 12/16（4 项因缺失 `pre-commit` 降级跑 Ruff）；修复夹具后 **16/16 通过** |
| 真实 PostgreSQL 全量 pytest（本地管理员） | **5109 收集；5046 passed / 0 failed / 63 skipped；EXITCODE=0；561.50s** |
| 后端全量覆盖率（本地） | **71.02%**（39837 行中覆盖 28291 行），高于 40% 门槛 |
| 修复合集编译 | `compileall` 通过 |
| **GitHub Actions run 40472413989（PR #21）** | **全部 SUCCESS**：lint / frontend / test / build / CodeQL |
| 远端 test job | **5034 passed / 0 failed / 83 skipped**（CI 环境额外跳过外部依赖项）；覆盖率 **70.83%** |
| 远端 Chromium / 浏览器 E2E | Chromium 148 下载成功；**5/5 pass，0 fail** |
| 远端前端覆盖率门禁 | 232 文件；语句 53.55% / 分支 46.30% / 函数 47.70% / 行 54.84%，阈值通过 |
| 独立只读复审 | 两轮；4 个 Medium 与最终 1 个 AST 接线漏检全部修复，最终 **VERDICT: PASS** |

全量首次运行暴露 **124 failed**，归因为 123 项根测试套件未适配新的写鉴权依赖、1 项服务重启测试缺少 `svc_pid_ex` 打桩。修复 `tests/conftest.py` 测试装配与 `tests/test_sm_workers_apply.py` 后，第二次全量运行 **0 failed**。

63 个 skip 均有显式原因，不是静默缺失：15 项未配置隔离 `E2E_API_BASE_URL`、1 项未配置契约后端、7 项未启用 `--e2e`，其余为可选第三方库未安装、受限 shell/Redis/只读副本/超级用户路径等环境型跳过。

前端全量覆盖率在本机因宿主批量删除保护无法清理 233 个 coverage 临时文件，测试和覆盖率报告均已生成、阈值数值全部达标；CI 的 Linux runner 不加载该本机 shim，不构成产品失败。

### 7.3 后续发布动作

1. 代码已在独立分支 `fix/fullstack-audit-20261027`，PR #21：https://github.com/qike1132/erp/pull/21
2. 远端 CI 已全绿且 PR 可合并；是否合并、何时上线由项目负责人决定，本次未合并、未部署。
3. 生产服务未重启，未写生产库。

**修复后结论：通过（本地全量 + 远端 CI + 独立复审）。** 已无未处置的 Blocker/High/Medium；本地真实 PostgreSQL 全量 0 失败、覆盖率 71.02%，GitHub Actions run 40472413989 全绿（覆盖率 70.83%），独立复审 PASS。
