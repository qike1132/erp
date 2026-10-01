# binfa-ERP 优化实施方案（基于 2026-10-01 全面技术评估）

- **依据**：`docs/architecture-review-2026-10-01.md`（同日全面技术评估报告）
- **性质**：方案文档，未动任何代码。每项经确认后单独执行：一个提交做一件事、先过门禁、留回滚锚点。
- **规模假设**：单人执行；生产主机无预发环境，涉服务变更项（OPT-07/15~19）必须在业务低峰窗口 + 备份完成后进行。

## 0. 总览

| 编号 | 事项 | 优先级 | 工作量 | 风险 | 前置 |
|---|---|---|---|---|---|
| OPT-01 | 提交 22 个 WIP 文件（按主题拆分） | P0 | 0.5d | 低 | — |
| OPT-02 | 修复 6 个 pytest 失败，恢复回归信号 | P0 | 0.5-1d | 低 | OPT-01 |
| OPT-03 | ruff --fix 78 条 + 收紧门禁基线 | P0 | 0.5d | 低 | OPT-02 |
| OPT-04 | 删除死代码（useListQuery、api/v2 空壳） | P0 | 0.1d | 极低 | OPT-01 |
| OPT-05 | 修复 git-bash `_lc` 命令劫持 | P0 | 0.5d | 低（本机环境） | — |
| OPT-06 | 根目录审计草稿归档 | P0 | 0.1d | 极低 | — |
| OPT-07 | web_vital 真实性能数据离线分析（只读） | P0 | 0.5d | 零 | — |
| OPT-08 | 生产 Python venv 隔离 | P1 | 1d | 中（涉 NSSM） | 低峰窗口 |
| OPT-09 | 前端写操作统一 useApiMutation（试点→推广） | P1 | 4-6d | 低 | OPT-02 |
| OPT-10 | customer/supplier 迁 UiDataTable + 列表 composable 合一 | P1 | 2-3d | 低 | OPT-04 |
| OPT-11 | API 层 5 处事务违规下沉 service | P1 | 2-3d | 低 | OPT-02 |
| OPT-12 | core/config 增加 field_validator | P1 | 0.5-1d | 低 | — |
| OPT-13 | mypy 覆盖 106 → 全量（分批 ratchet） | P1 | 3-5d | 低 | OPT-03 |
| OPT-14 | 迁移图 4 根显式收敛 | P1 | 1d | 低（drill 验证） | — |
| OPT-15 | 前端 bundle 拆分（primevue/echarts 延迟化） | P1 | 1-2d | 低 | OPT-01 |
| OPT-16 | 部署 PG 只读副本，消除数据库单点 | P2 | 2-3d | 中 | drill 环境 |
| OPT-17 | 内网 TLS（nginx 443） | P2 | 1d + 证书流程 | 中 | — |
| OPT-18 | nginx limit_req 双层限流 | P2 | 0.5d | 低 | OPT-17 |
| OPT-19 | /static/uploads/ 免鉴权直出改造 | P2 | 2d | 中（存量链接） | — |
| OPT-20 | 进程内状态 Redis 化（WS 票据/L1 广播） | P2 | 1-2d | 低 | — |
| OPT-21 | fastapi 0.137.1 → 0.142.2 | P2 | 0.5d | 低 | OPT-08 |
| OPT-22 | 备份"解密+校验"演练季度化 | P2 | 0.5d/季 | 零 | — |

合计约 **P0 ≈ 3 人日、P1 ≈ 15-22 人日、P2 ≈ 8-10 人日**。P0+P1 是本轮整改主体；P2 按季度排期。

---

## 1. P0 详案（本周，全部零/低风险）

### OPT-01 提交 22 个 WIP 文件

- **问题**：工作区 22 个改动/新增文件（外发 TAB 重构、客户订单录入编辑等）已 build 上线但未入库——线上运行的是"没有 git 身份"的代码，回滚与追溯断链。
- **做法**：按主题拆 4 个提交，每个提交前跑 `python scripts/quality_gate.py` + 密钥扫描：
  1. `feat(customer-order): 记录录入/编辑弹窗与查询筛选`（EditStockinModal.vue、useStockinEdit.ts、OrderRecordFilter/Query/Table、CustomerOrderView、useOrderActions、stock.ts、相关测试）
  2. `refactor(outsource): 出货面板拆分为 Strip/Actions 组件`（OutsourceShipment*、OutsourceShipDialog、OutsourceOrderView、docs/outsource/）
  3. `refactor(hubei,report): TAB 与报表筛选栏调整`（HubeiRouteTabs、ReportFilterBar）
  4. `chore: mockup 与 components.d.ts 同步`（mockups/、components.d.ts）
- **验收**：`git status --porcelain` 干净；每个提交通过 pre-commit。
- **回滚**：git revert，各主题独立。

### OPT-02 修复 6 个 pytest 失败

- **问题**：`pytest -q` = 3491 过 / **6 败**（tests/qa/test_smoke.py ×3、tests/qa/test_database.py ×1、test_numbering_sequence_integration ×1、test_customer list total ×1），伴随 "Event loop is closed"、审计中间件 `'NoneType' send` 噪音——回归信号不可信。
- **做法**（先诊断后修，禁止用 skip 掩盖）：
  1. 单独跑每个失败文件定位孤立失败还是顺序污染：`python -m pytest tests/qa/test_smoke.py -q`；
  2. 若孤立失败 → 真 bug，按断言修代码/夹具；
  3. 若顺序污染（event loop 复用）→ 检查 pytest-asyncio 的 loop scope 配置与 conftest 的 engine 生命周期（fastapi_app/tests/conftest.py 已把 async_engine patch 为 None，重点查 tests/qa 自己的夹具）；
  4. 审计中间件 `'NoneType' send`：确认测试客户端关停顺序，必要时在夹具里显式 await app shutdown。
- **工作量**：0.5-1 天。**验收**：`pytest -q` 全绿；3677 例无 skip 增加。

### OPT-03 ruff 自动修 + 基线收紧

- **问题**：ruff 145 errors（78 条可自动修：UP031 printf×24、RUF100 无效 noqa×22、S110 try-pass×19…）；quality_gate 基线可收紧（裸/宽 except 5/9）。
- **做法**：
  1. `ruff check . --fix`（自动修 78 条），逐条抽查 UP031 → f-string 无语义变化；
  2. 剩余 67 条按规则族分 2-3 批手工修（S110 逐个确认吞异常是否合理，不合理改记日志）；
  3. `python scripts/quality_gate.py --update-baseline` 收紧（目标：裸 except 9→5、其他不动）。
- **验收**：ruff 0 error；`pytest -q` 全绿；baseline 数字下降。

### OPT-04 删除死代码

- **问题**（已实证）：`frontend-vite/src/composables/useListQuery.ts` 全仓 0 引用；`fastapi_app/api/v2/endpoints/` 只有 `__pycache__`，无任何 .py——误导版本策略认知。
- **做法**：`git rm` useListQuery.ts；删除 api/v2 目录（先确认 `router.py` 与全仓 grep 无 `api.v2` 导入）；跑 vitest + pytest。
- **验收**：全仓 grep 0 引用；两套回归全绿。

### OPT-05 修复 git-bash `_lc` 劫持

- **问题**：本机 git-bash 启动脚本 `embedded-search-startup-*.sh` 第 12 行 `rg()` 定义语法错误，导致 lean-ctx 包装只装一半——`npm`、`ls`、`cat`、`head`、`cmd`、`type`、管道等报 `_lc: command not found`。评估期间前端五项门禁曾因此**静默全灭**（后台任务 exit 0 只是 echo 的）。这是下一次运维操作的地雷。
- **做法**：升级/重装 lean-ctx 或在其 bash 集成入口加保护；修复后新开会话验证 `npm --version`、`git log`、`ls | head`。
- **验收**：新 git-bash 会话中上述命令全部正常；后台命令真实退出码可信。

### OPT-06 根目录审计草稿归档

- **问题**：`_qa_tmp/`、`_ops/audit_scratch/`、`_beile_detail_*.py` 等未入库草稿散落仓库根（已被 .gitignore 覆盖），是 Mimosa 扫描 136 条 high 误报的主要来源，也污染后续任何扫描工具的信噪比。
- **做法**：移入 `_ops/scratch-archive-2026-10/`（仍在 .gitignore 内）或直接删除（确认无未沉淀结论后）。
- **验收**：仓库根无散落草稿；重跑 mimosa 扫描 high 数显著下降。

### OPT-07 web_vital 真实性能画像（只读分析）

- **问题**：生产库 `web_vital` 表已积累 4,147 条真实用户性能上报（LCP/INP/CLS 等），从未被分析——这是零成本、零风险的真实性能数据。
- **做法**：只读 SQL 按页面路由 × 指标聚合 p75/p95，产出 `docs/perf/web-vitals-baseline-2026-10.md`；作为 OPT-15 bundle 优化的前后对比基线。
- **验收**：报告落盘，含 Top 慢页面清单；不做任何写操作。

---

## 2. P1 详案（本月，低风险结构改进）

### OPT-08 生产 Python venv 隔离（需低峰窗口）

- **问题**：生产解释器是全局 Python 3.13（291 包，含 litellm/openai/locust/opencv 等无关重包）——任何一次全局 `pip install` 都可能意外升级 ERP 依赖；requirements 钉死形同虚设。
- **做法**：
  1. `python -m venv D:\erp_system\.venv` → `pip install -r requirements/base.txt`；
  2. `pip freeze` 与当前全局环境 diff，人工确认差异包均为 ERP 不需要的；
  3. 先在 drill 冒烟（用 .venv 起 uvicorn 到临时端口跑 health + 登录）；
  4. 低峰窗口：NSSM 五服务中 erp-prod/erp-arq 的启动命令指向 `.venv\Scripts\python.exe`，重启，验证 `logs/prod_runner.json` ready=true；
  5. 全局环境冻结不动（回滚锚点）。
- **回滚**：NSSM 命令改回全局解释器，重启即回。
- **验收**：`logs/prod_runner.json` ready 且 erp-prod 进程命令行含 `.venv`；pytest（.venv 内）全绿。

### OPT-09 前端写操作统一 useApiMutation（核心重构）

- **问题**：66 个 view 文件直呼 `@/api` 写接口，成功后的缓存失效全靠人工维护失效清单——"客户订单改了、贝莱/外包/采购页不同步"这类 bug 的模式性根源（此前已修过一次）。
- **方案**：
  1. 建 `src/composables/useDomainInvalidation.ts`：领域→query key 注册表（orders 域失效时显式包含 beile-orders/outsource-orders/purchase），把现有 `invalidateStockDataQueries` 泛化；
  2. `useApiMutation` 封装：统一错误 toast、成功后按领域失效、写操作 502/503/504 重试语义从 request.ts 收编；
  3. 试点 customer-order（本次 WIP 已在动这个模块，顺势做）；再按 outsource → purchase → 其余顺序推广，每模块一个提交；
  4. 加 lint 规则（先 warn）禁止 views 直接 import `@/api` 的写函数。
- **验收**：每迁移一个模块跑对应 vitest；最终 grep views 下 `from '@/api'` 仅剩查询；跨页同步回归测试（已有）全绿。
- **回滚**：按模块 git revert。

### OPT-10 customer/supplier 迁 UiDataTable + composable 合一

- **问题**：CustomerTable(247 行)/SupplierTable(285 行) 手写镜像表格绕过自家 UiDataTable；列表状态三套并存（usePagedSearch×10 / useEnhancedList×3 / useListQuery×0 已删）。
- **做法**：CustomerTable → UiDataTable 改造（参照 product 模块既有模式，逐列比对行为）；supplier 复制同一改造；useEnhancedList 3 处迁到 usePagedSearch 后删除。
- **验收**：两模块 vitest + 手工冒烟（筛选/分页/操作列）；全仓只剩一套列表 composable。

### OPT-11 API 层 5 处事务违规下沉 service

- **问题**：`endpoints/order.py:334-394`（delete_order：commit+事件+缓存失效全在端点）、`customer.py:114,302`、`purchase_plan.py:112,529`、另 `auxiliary.py:275,288`、`purchase_center/order_routes.py:98,122`——违反 `docs/TRANSACTION_BOUNDARY_GUIDE.md`。
- **做法**（每处一个提交）：
  1. 先写集成测试锁定现状行为；
  2. 把 commit/异常映射/领域事件/缓存失效移入对应 service（服务层保持 flush-only 约定）；
  3. 跑 `python scripts/quality_gate.py`（"service 手动 commit" 计数不得上升）+ 全量 pytest。
- **验收**：端点函数只剩"解析→调 service→包响应"；新集成测试全绿。

### OPT-12 core/config 增加 field_validator

- **问题**：config.py 42 字段 0 个校验器，配置错误运行期才暴露；特别是红线 #4——`BACKUP_ENCRYPTION_ENABLED=true` 且密码为空会**静默降级不加密**。
- **做法**：加 `@field_validator`：① 上述加密联动 fail-fast（最高优先）；② CORS 白名单格式；③ DB 池参数范围；④ API_PREFIX 必须以 / 开头。配套单元测试（monkeypatch 环境变量断言 ValidationError）。
- **验收**：故意注入错误配置时启动即失败；pytest 全绿。

### OPT-13 mypy 覆盖 106 → 全量

- **问题**：mypy.ini 只纳入 106/536 个文件（services 仅 82/156），类型防线有大片盲区。
- **做法**：按现有 ratchet 机制分 3-4 批纳入（每批 ~20 文件）：先依赖清晰的（schemas 型服务），后复杂服务；每批修复到 0 错再纳入；确实难标注的加 `# type: ignore[具体码]` 带理由。
- **验收**：mypy 覆盖 ≥ 90% 文件且保持 0 错；quality_gate 不退化。

### OPT-14 迁移图 4 根显式收敛

- **问题**：99 个迁移单 head 但 4 个根（AST 实证）+ 2 个同号 017——全新环境 upgrade 依赖根执行顺序，链路可读性差。属低急迫度"可维护性"问题，功能无损。
- **做法**（不重写历史）：`alembic merge -m "merge: 收敛四个根分支" <root1> <root2> <root3> <root4>` 生成显式 merge revision；在 drill 库从零 `upgrade head` 验证；同号 017 不改名（改文件名会破坏已应用环境的 version 表，只加注释说明）。
- **验收**：drill 库空库 upgrade 到 head 成功；生产库 `alembic current` 不变。

### OPT-15 前端 bundle 拆分

- **问题**：vendor-primevue 672KB（全 PC 共享）+ vendor-echarts 557KB + 入口 index 443KB。
- **做法**：
  1. 用 rollup-plugin-visualizer 产一次性 stats 分析（确认 index 443KB 构成）；
  2. echarts 仅报表页用 → 改 `import()` 动态加载，让其 chunk 只在 /report 加载；
  3. primevue chunk 拆分：theme 运行时与组件族（form/table/overlay）manualChunks 分开；
  4. 走既有发布流程（build:atomic + 上线后 curl 比对 live hash + 查 erp-web——按既有运维记忆流程）。
- **验收**：首屏 JS 体积对比（OPT-07 的 web_vital 基线前后对照）；live hash 验证通过。

---

## 3. P2 详案（季度基础设施）

### OPT-16 部署 PG 只读副本

- **问题**：PG/Redis×2/nginx/后端全在一台 Windows 主机，PG 无从库——主机故障=全站停机。
- **方案选型**：现有 `config/postgres/init-replica.sh` 是 **docker 镜像方案**（docker-entrypoint-initdb.d），与当前 Windows 原生 PG 18.3 拓扑不匹配。二选一：
  - **路线 A（推荐）**：异机/异盘 docker 容器跑副本（沿用现脚本，改造量最小）——需要一台第二主机或至少独立数据盘；
  - **路线 B**：同机第二 PG 实例（pg_basebackup + standby.signal + 注册 NSSM 服务 erp-pg-replica）——只防 PG 进程故障，不防主机故障，价值有限。
- **步骤（路线 A）**：备机装 docker → 配 POSTGRES_PASSWORD 环境注入 → 起 replica 容器 → 验证复制槽 lag → 备份告警接入复制状态 → 演练提升主库切换一次。
- **回滚**：删除 standby/复制槽，应用连接串不动（副本只读不承载流量）。

### OPT-17 内网 TLS

- **问题**：nginx 仅 `listen 3000`，凭据/Cookie 明文（`nginx-windows.conf:37`）。
- **做法**：自建 CA（或企业 AD CS）签发主机证书 → nginx 443 ssl + 3000 过渡期 301 → security-headers 的 HSTS 在确认全站 https 后启用 → 前端同源无 CORS 影响。
- **回滚**：保留 3000 监听，随时切回。

### OPT-18 nginx limit_req

- **问题**：网关层零限流，防爆破全靠应用层（登录已双层但网关无第二道）。
- **做法**：`limit_req_zone` 全局 $binary_remote_addr 泛率 + `/api/v1/auth/` 登录路径收紧；`/api/health`、`/metrics`（本机）白名单豁免；先 `limit_req_log_level` 观察一周再 enforce。
- **验收**：压测 drill 环境确认限流生效且不误伤正常操作。

### OPT-19 uploads 免鉴权直出改造

- **问题**：`/static/uploads/` nginx alias 直出，知道 URL 即可 GET（`nginx-windows.conf:93-99`）。
- **做法**（推荐 secure_link，文件仍不占 worker）：后端下发带过期时间的 HMAC 签名 URL → nginx `secure_link_md5` 校验；存量明文 URL 设 7 天兼容期（与现有 expires 一致）；OCR 导入等大文件路径单独确认。
- **回滚**：nginx 配置摘掉 secure_link 即恢复直出。
- **验收**：无签名 URL 访问 403；带签名 URL 正常；兼容期内旧链接可用。

### OPT-20 进程内状态 Redis 化

- **问题**：WS 票据内存 dict（`api/ws.py:41`）、权限 L1 TTLCache 广播默认关（`deps.py:34-71`）——锁死单实例。
- **做法**：票据写 Redis（TTL 60s）；开启已有的广播失效开关；用本机双端口起两个 uvicorn + nginx upstream 双节点做双实例冒烟（只做验证，不常驻双实例）。
- **验收**：双实例下登录/WS 通知/权限变更广播全部正常——横向扩展能力就位（平时仍单实例跑）。

### OPT-21 fastapi 0.137.1 → 0.142.2

- **做法**：requirements pin 改 0.142.2 → .venv 重建（依赖 OPT-08）→ 全量 pytest + drill 冒烟 → 低峰窗口 NSSM 重启 → prod_runner.json 验证。
- **回滚**：pin 改回 + venv 重建，5 分钟内可回。

### OPT-22 备份"解密+校验"演练季度化

- **问题**：曾有"备份成功但不可解密"事故；现有 restore_drill 未显式验证解密。
- **做法**：`scripts/restore_drill.py` 增加"解密 → 校验和比对 → 空库恢复"三步证据输出；结果归档 `docs/ops/`；日历季度触发。

---

## 4. 明确不做的事（防过度工程）

当前 7 用户/29 订单的规模下，以下事项**不做**，避免为想象中的规模付复杂度税：

1. **不做**微服务拆分、不引入 Kafka/RabbitMQ（ARQ 四队列够用）；
2. **不做**读写分离/分库分表/缓存层加速（31MB 库，PG 预热即全内存）；
3. **不追** Vite 8 major（等 8.x 稳定半年）；
4. **不做**前端框架/状态库更换（当前栈是 2026 主流最优组合）；
5. **不做**生产 OpenAPI 文档站（刻意关闭，内网用代码内类型对齐 + check:api 已够）；
6. **不用 skip 掩盖** pytest 失败（修根因，OPT-02）；
7. **暂不做** audit_log 分区归档（4,858 行，距阈值极远；放观察项，季度复查）。

## 5. 执行纪律（每项通用）

1. 一个提交只做一件事，提交信息写"为什么"；
2. 变更前后各跑一次全套门禁（§评估报告 6.1 的 9 项），数字记录进提交说明；
3. 涉 NSSM/PG/nginx 的项（OPT-08/16/17/18/19）：备份完成后 + 低峰窗口 + 有人在岗；
4. 每项留回滚锚点（pin/freeze/配置副本），回滚演练不省略；
5. 前端上线后按既有流程验证 live hash（curl 比对 + 查 erp-web 服务）。

## 6. 度量基线（优化前后对照用）

| 指标 | 基线（2026-10-01） | 目标 |
|---|---|---|
| pytest | 3491 过/6 败/180 跳 | 全绿 |
| ruff errors | 145（78 可自动修） | 0 |
| quality_gate 基线 | 裸 except 5/9 等 73 处存量 | 收紧至 5 并持续下降 |
| mypy 覆盖 | 106/536 文件 | ≥ 90% 且 0 错 |
| eslint | 0 错/165 警 | 0 错 ≤ 20 警 |
| 首屏 JS | index 443KB + primevue 672KB | echarts 延迟化 + primevue 拆分，web_vital p75 对比 |
| PG 单点 | 无副本 | 只读副本 + 切换演练 1 次 |
| 传输安全 | 明文 3000 | 443 TLS |
| 直出暴露 | uploads 免鉴权 | 签名 URL |
| 横向扩展 | 单实例锁死 | 双实例冒烟通过（能力就绪） |
