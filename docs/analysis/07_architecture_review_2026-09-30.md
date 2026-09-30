# ERP 系统架构评审报告

**评审对象**：`D:\erp_system`（分支 `feat/production-cockpit-pc`，HEAD `ace65501`）
**评审日期**：2026-09-30
**评审视角**：软件架构（结构、边界、耦合、可逆性、运行形态），**不是**代码级缺陷审核
**评审方法**：10 轮 AST 结构扫描（`ast.parse` 解析成功 984 个 `.py`，失败 13 个全为 UTF-8 BOM）+ `alembic ScriptDirectory` 权威迁移图 + 2 个并行只读子代理（前端架构、运行期与部署）+ 仓库协作契约 `AGENTS.md`
**未做的事（声明边界）**：未启动应用、未连接数据库、未执行测试、未启停任何服务、未修改仓库任何文件。所有数字均可在附录 A 复现。
**与前两轮的关系**：本仓已完成两轮**代码级**审核（全局审核报告 + 修复实施轮，含 A/B/C/D 四项修复）。本轮**刻意不复核代码级问题**，只回答"这个系统的形状是什么、哪里会先坏、什么决定难改"。

---

## 0. 一页结论

**判定：这是一个结构健康的模块化单体。它的架构问题不在"分层不清"，而在"重心错位"与"运行体缺失"。**

三条最重要的判断：

1. **代码架构明显强于运行架构。** 代码侧（分层、Unit of Work、路由集中接线、前端单点 API 客户端、UoW 下服务层不自管事务）强于绝大多数同规模项目；运行侧（可观测性、发布回滚、灾备）则是"设计存在、运行体不存在"的系统性落差。**这个系统最可能先坏的地方不在代码里。**

2. **备份子系统是事实上的第一子系统，约 16,505 行（占后端应用代码 20.7%），却与它的可靠性等级不匹配。** 它是全仓最大子系统，承担最关键的可用性职责（RPO/RTO），同时是唯一"看着成功、实际可能缺表"的组件。体量与可靠性倒挂。

3. **不要拆服务。** 当前的耦合（6 个 import 环、`core→services` 反向依赖）都是**包结构层面的可逆问题**，不是拆成分布式的理由。按可逆性优先原则，先修可逆的，冻结不可逆的。

### 优先级总表（可逆性 × 影响）

| # | 问题 | 影响 | 可逆性 | 定性 |
|---|---|---|---|---|
| P0-1 | 备份无异地、与数据同盘（D:） | 全损级不可恢复 | 高（加同步目标） | 架构级缺口 |
| P0-2 | 可观测性整体无运行体（`/metrics` 503、采集配置指向不存在主机） | 故障靠用户报障，MTTR 不可控 | 高 | 架构级缺口 |
| P0-3 | 备份静默残缺（缺表仍记 success） | 备份不可信 = 灾备假象 | 中 | 正确性缺口 |
| P1-1 | 无一键回滚（DeployEngine 未实现、swap-dist 不留副本） | 发布失败恢复慢且易错 | 高 | 工程能力缺口 |
| P1-2 | 配置三份漂移（`.env` 107 键 vs `.env.production` 37 键） | 覆盖即静默降级（备份不加密） | 高 | 架构级缺口 |
| P1-3 | `core/container.py` 服务定位器造成 `core→services` 反向依赖 | 分层契约破损（12 条边） | 高 | 结构问题 |
| P1-4 | 双轨运维面（Windows/NSSM 真实 + Linux/Docker 死配置） | 改错文件的误操作风险 | 高 | 认知负荷 |
| P2-1 | PC/mobile 双 UI 树（同名文件 0 对、共享组件 0） | 同一领域两套实现、契约漂移 | 中 | 结构问题 |
| P2-2 | 前端路由权限粒度粗（只比对 path 第一段） | 前端越权直达（后端已兜底） | 高 | 纵深防御 |
| P2-3 | 健康检查两套实现语义相反 | 探活语义混乱 | 高 | 结构问题 |
| P3-1 | 迁移 4 个 root、仓库含 419MB 快照与真实客户图 | 可复现性、仓库卫生 | 中 | 卫生问题 |

---

## 1. 系统形态与边界

### 1.1 系统上下文

这是一个**单企业、单租户、单主机的 ERP 系统**，服务于制造/贸易型业务的完整链条：

```
采购(计划→下单→到货) → 订单(BOM/备料→审批→发货) → 外发加工 → 生产计划/日报
                                                        ↓
客户/打样/图案房 ←→ 库存(入库/出库/退货/盘点) ←→ 供应商/物料/产品主数据
                                                        ↓
                              横切：用户/角色/权限、通知、备份中心、报表、审计
```

**架构风格**：模块化单体（Modular Monolith）+ 前后端分离 + 单主机部署。这是**正确的选择**，理由见 §7。

### 1.2 容器视图（实测拓扑）

```
浏览器 ──> nginx :3000 ──> uvicorn 127.0.0.1:5002 (8 worker) ──> PostgreSQL :5432
             │  (config/nginx-windows.conf)          │                    │
             │  root = frontend-vite/dist             │                    └─ 只读副本(2s 超时回落主库)
             └── 静态资源                              └──> Redis :6379 (缓存/锁)
                                                              │
                                          ARQ worker (独立进程) ──> Redis :6380 (broker)
```

- **5 个 NSSM 服务**，全部 Auto 启动：`erp-web`（nginx）、`erp-prod`（`python -m fastapi_app.core.prod_runner --no-arq`）、`erp-arq`、`erp-redis`、`erp-redis-broker`（依赖关系见 `server_manager/constants.py:31-34`、`server_manager/app.py:1238-1253`）。
- uvicorn **仅绑回环**（`fastapi_app/core/prod_runner.py:173-186`），符合 `AGENTS.md` 红线③。
- 进程监督：`fastapi_app/core/prod_runner.py:394` `Supervisor` / `:227` `_Managed`，健康写入 `logs/prod_runner.json`（`:445` `write_status`，原子写 `:480-483`）。
- **容器化资产为零**：全仓无 `Dockerfile` / `docker-compose` / `Makefile` / `Procfile` / `*.service`。唯一的 `Dockerfile` 出现在 `_qa_tmp` 夹具目录。

### 1.3 组件视图（后端分层，AST 实测）

| 层 | 文件 | LOC | 职责 |
|---|---|---|---|
| `api/` | 60 | 15,233 | HTTP 边界：34 个 router、51 个 endpoint 模块 |
| `services/` | 182 | 44,783 | 业务逻辑（**最大层，占 56%**） |
| `core/` | 48 | 9,301 | 基础设施：DB/缓存/中间件/安全/监督器 |
| `shared_models/` | 46 | 4,368 | ORM 模型（67 个 `__tablename__`） |
| `schemas/` | 26 | 3,745 | Pydantic DTO |
| `tasks/` | 7 | 1,646 | ARQ 后台任务 |
| `utils` / `shared` | 7 | 766 | 遗留同步工具 / 共享并发原语 |
| **合计** | **376** | **79,842** | |

前端 `frontend-vite/src`：563 文件 / 89,104 LOC（views 275/50,284 = 56%、test 103/17,605、mobile 43/5,861、components 45/4,049、api 27/2,497）。

---

## 2. 约束（读这份报告前必须接受的现实）

这些约束来自 `AGENTS.md`（94 行，仓库唯一协作契约）与实测：

| # | 约束 | 架构后果 |
|---|---|---|
| C1 | **这台机器既是生产主机，也是运维主机**；无独立测试/预发环境 | 任何验证动作都是生产动作；架构演进必须"小步 + 可回滚" |
| C2 | 单机单点：D 盘、nginx、`erp-prod`、Redis 均无冗余 | 可用性上限 = 单机可用性；垂直扩展是唯一选项 |
| C3 | PostgreSQL 有读副本但**无自动故障切换**（`scripts/database/failover_drill.sh` 是人工演练） | 高可用是"人工可恢复"，不是"自动可恢复" |
| C4 | 部署形态是 **Windows + NSSM**，非容器 | 所有 Linux/Docker 取向的配置都是死配置（见 P1-4） |
| C5 | 备份是**外部进程**（`psql`）而非应用内事务 | 备份/恢复与 ORM 会话模型天然冲突（`core/database.py:210-212` 的宽容处理即为此） |
| C6 | `migrations` 必须单一 head；Alembic 只做结构/数据变更 | schema 演进路径受限，但历史可控 |
| C7 | 本机是 Windows PowerShell 5.1（`-Encoding utf8` 会写 BOM） | 脚本与文件编码必须显式处理 |

**C1 是理解一切的前提。** 它解释了为什么这个系统选择单机 NSSM 而非容器编排，也解释了为什么"没有 CI 部署"不是疏忽而是环境不可达（`.github/workflows/ci-cd.yml:281-302` 明确记录 2026-09-24 删除 deploy job）。

---

## 3. 结构度量（证据）

### 3.1 依赖方向：总体健康，一处倒置

跨层依赖边（`ast` 统计，top）：

```
api → core              198      ← 正常（边界依赖基础设施）
services → core         189      ← 正常
services → shared_models 134     ← 正常
api → services           67      ← 正常
api → schemas            39      ← 正常
services → schemas        8      ← 轻微倒置（服务层依赖 DTO，见下）
core → services          12      ← **倒置（分层契约破损）**
```

**`core → services` 的 12 条边全部来自一个文件**：`fastapi_app/core/container.py`（144 行）。它自称服务定位器，文件头注释写「让高层代码依赖"工厂/抽象"而非直接 import 模块级单例，改善 DIP」，但 9 个 getter 内部**硬编码具体实现类**并延迟 import：

```
get_customer_search_service()      -> services.customer_search_service.customer_search_service
get_product_search_service()       -> services.product_search_service.product_search_service
get_role_service()                 -> services.product.role_service
get_backup_cleanup_service()       -> services.backup.cleanup.service.cleanup_service
get_backup_alert_service()         -> services.backup.metrics.alert_service.alert_service
get_backup_metrics_service()       -> services.backup.metrics.service.metrics_service
get_backup_policy_service()        -> services.backup.orchestration.policy_service.policy_service
get_backup_recovery_test_service() -> services.backup.orchestration.recovery_test_service.recovery_test_service
get_backup_health_check_service()  -> services.backup.verify.health_check_service.health_check_service
```

这是**"为了解耦而增加耦合"**的典型样本：延迟 import 把编译期依赖藏到了运行期，DIP 的收益（可替换）没有兑现（`register_factory`/`override` 在生产路径无人调用），成本（`core` 层编译期依赖 9 个具体 service）却真实发生了。

**另外 `services → schemas` 8 条边**集中在 `batch_import_*` 与 `dashboard/*`。服务层依赖 Pydantic DTO 是常见取舍，但意味着 **DTO 改动会波及服务层**——属可接受，记录在案。

### 3.2 循环依赖：6 个，全部可逆

| 环 | 规模 | 判定 |
|---|---|---|
| `shared_models` | 45 模块 | **包级环**（`__init__.py` 聚合再导出），非运行时环 |
| `services.backup` | 18 模块 | 包级环，同上 |
| `order/outsource` | 6 模块（`order.commands`/`order_crud`/`outsource._order_processes`/`_queries`/`_shipments`/`outsource_service`） | **需二次判定**（可能是真实双向业务耦合） |
| `core.container` | 4 模块（`bom_service`/`product_search_service`/`product_service`） | 由 §3.1 的倒置引起 |
| `core.arq_app` | 2 模块（`tasks.backup_tasks`） | 正常（任务注册表） |
| `batch_import_service` | 2 模块 | 需判定 |

**结论：6 个环里只有 1 个（order/outsource）可能是真问题。** 这一条本身值得记录为教训——AST 报出的"环"如果不区分包级聚合与运行时环，会得到严重夸大的结论。

### 3.3 边界完整性与孤儿模块

- **路由接线 100% 完整**：`api/v1/router.py` 有 **34 个 `include_router`**，51 个 endpoint 模块 **wired 51 / orphans 0**。与 `AGENTS.md`「零孤儿」声明一致（曾因正则得出"48 个模块未接线"的伪影，见附录 B）。
- **真孤儿模块 5 个**（全仓零引用，含 `__init__.py` 聚合与动态 import 检查）：`fastapi_app/core/alert_rules.py`、`fastapi_app/core/domains.py`、`fastapi_app/services/backup/_stream.py`、`fastapi_app/services/batch_pipeline.py`、`fastapi_app/services/staging_utils.py`。其中 `alert_rules.py` 与 `domains.py` 的存在暗示**曾经有过（或计划过）一套告警与领域划分设计**，未落地。
- **`api/ws.py` 不是孤儿**：`main.py:30` `from fastapi_app.api.ws import register_websocket`，端点 `@app.websocket("/ws/notifications")`，票据鉴权在 `notification.py:11`（`_issue_ws_ticket`），有回归测试 `fastapi_app/tests/test_ws_ticket_auth.py`。

### 3.4 数据访问与事务

- **事务边界集中在单一依赖**：`core/database.py:203` `get_async_db()` 是 Unit of Work ——「请求成功自动 commit／请求异常自动 rollback／**服务层应使用 flush() 而非 commit()**」。业务代码里 commit 调用极少（`backup/json_backup.py` 4 次、`numbering_sequence.py` 2 次），385 次 commit 绝大多数在测试与脚本。**这是一个好架构**：事务边界单点、可推理、可替换。
- **原生 SQL 108 处 `text()` 调用点**，高度集中在备份子系统（`recovery_test_service.py` 12、`backup/verify/core.py` 11、`json_backup.py` 10、`incremental.py` 6、`orchestration/core.py` 6）。其中 26 处是 f-string 拼接，**全部带 `quote_table()` 白名单 + `# nosec B608` 标注**（例：`services/backup/json_backup.py:336`）。
- **未决项（需人工确认，非已证实漏洞）**：`services/stock_inventory_service.py:383/551/631/633/634` 的 CTE f-string SQL 未在扫描中看到显式白名单注释。扫描显示插值均为常量片段，但**这是本轮唯一需要人眼复核的数据访问点**。
- **ORM ↔ 迁移**：ORM 67 表；迁移 46 个 `op.create_table` + 43 个 raw `CREATE TABLE`（全在基线 `pg_standalone_001`）。**唯一无 DDL 的 ORM 表 `daily_production_record`** 已由 `migrations/versions/pg_standalone_054_sync_schema_with_orm_metadata.py:57` 对账补齐——这是**已知漂移 + 已写对账迁移**，属既有决策而非新问题。

### 3.5 迁移图（`alembic ScriptDirectory` 权威口径）

- **HEADS = 1**：`pg_standalone_060_fix_updated_at_varchar_columns`（与生产 `alembic current` 一致，符合红线⑦）。
- **ROOTS = 4**：`add_product_factory`、`add_product_price`、`add_pp_composite_idx`、`pg_standalone_001`。revisions = 99，6 个 merge revision 把它们收敛到单 head。
- 分支链长：`add_product_factory` → 8（tip `pg_standalone_025_add_cs_indexes`）、`add_product_price` → 7、`add_pp_composite_idx` → 3、`pg_standalone_001` → 5。
- **迁移文件零业务代码泄漏**（`migrations` 导入 `fastapi_app` 次数 = 0）。

---

## 4. 架构优势（先说做对了什么，否则改进建议没有基线）

1. **分层契约被真实执行**。`views` 内 0 处 `axios`/`fetch`，全仓仅 `src/api/request.ts:1` 与 `src/api/role.ts:16` 引入 axios；`views → api` 138 条边、`views → composables` 105 条边，方向一致。前端没有"随手请求"的溃堤。
2. **Unit of Work 单点事务**（§3.4）。服务层不自管事务，事务语义可推理、可统一改造。
3. **路由集中接线**。`api/v1/router.py` 绝对导入挂载，51/51 模块全部接线、0 孤儿——这让"某个功能到底有没有暴露"这类问题永远可回答。
4. **前端单点 API 客户端**（`src/api/request.ts`，285 行）：`baseURL` 收敛、`X-CSRF-Token` 注入（`:72-86`）、401 单飞刷新（`:54-70`）、502/503/504 重试（`:133-135`）。
5. **`tasks/` 与请求路径分离**。ARQ 独立进程 + `cron_jobs` 内置于 worker（`core/arq_app.py:135`），无独立 beat 进程；`max_jobs=10`、`job_timeout=1800`。
6. **安全基线扎实**（详见 §5.6）：全仓 `subprocess(shell=True)`=0、`os.system`=0、`eval/exec`=0、`pickle.load`=0、`yaml.load`（非 Safe）=0、`verify=False`=0、`allow_origins=["*"]`=0；口令用 argon2id；JWT 解码显式限定算法；凭据未入库。
7. **`container.py` 的设计意图是对的**（依赖抽象而非模块级单例）——只是实现方式（延迟 import 硬编码实现）没兑现意图。**意图值得保留，实现需要改**（§7.2）。

---

## 5. 架构级问题

以下每条按「现象 → 证据 → 为什么是架构问题而非代码问题 → 选项与权衡」组织。

### P0-1 备份无异地、与数据同盘 —— 全损级缺口

**现象**：备份写入 D 盘（与 PostgreSQL 数据同盘），无异地/离线副本。
**证据**：`docs/reports/2026-08-23-backup-benchmark-report.md` P1-8 自述；RPO ≈ 1 小时（`BACKUP_FULL_CRON=0 2 * * *`、`BACKUP_INCREMENTAL_CRON=0 */1 * * *`、保留 30 天）；最新加密备份 2026-09-30 10:05。
**为什么是架构问题**：这不是"忘了配"的运维疏漏，而是**部署形态（C2 单机）与灾备目标之间的结构性矛盾**。单机部署下，备份与数据共享同一个故障域（磁盘、主机、机房），备份无法覆盖它本应覆盖的主要故障模式。RPO/RTO 的承诺在这一条上不成立。
**选项与权衡**：

| 选项 | 权衡 | 可逆性 |
|---|---|---|
| A. 备份落第二块物理盘 + 网络共享/对象存储（最小改动） | 成本低、当天可做；但仍与主机同故障域（主机损坏时仍可恢复） | 高 |
| B. 异地异步复制（`rclone`/对象存储，每小时推送加密备份） | 覆盖主机/磁盘/机房级故障；引入外部依赖与凭据管理 | 高 |
| C. 搭建 PostgreSQL 流复制到第二台机 | 覆盖最全（RPO 秒级）；工作量最大，且与 C3 无自动切换的现状冲突 | 低（引入新主机形态） |

**建议**：先做 A+B（可逆、当天可回滚），把 C 记录为 ADR 待评估。

### P0-2 可观测性整体无运行体

**现象**：监控栈"有设计、无运行体"。
**证据**：
- `/metrics` 挂在 uvicorn:5002（`fastapi_app/core/health.py:200`），生产需 Bearer token，**未配 `METRICS_BEARER_TOKEN` 即返回 503 fail-closed**（`:206-213`）→ 当前实际不可用；
- `config/nginx-windows.conf` **没有 `/metrics`、`/grafana/`、`/prometheus/` 路由**（对比 `config/nginx.conf` 有这三个块）；
- `config/prometheus.yml`、`grafana/dashboards/*.json`、`otel-collector.yaml`、`promtail.yml`、`alertmanager.yml`、`alert_rules.yml` 全部使用 Docker 主机名（`app:5002`、`nginx:80`、`loki:3100`），而仓库 **0 个 docker-compose** → 7 条告警规则为死配置；
- 唯一有效可观测是 `logs/`：应用日志 `TimedRotatingFileHandler backupCount=3`（`fastapi_app/core/logger.py:67-70`，**只留 3 天**）；nginx 日志由 ARQ cron 轮转（`tasks/maintenance_tasks.py:21`）。
**为什么是架构问题**：可观测性是**非功能需求**，当前架构把它实现为一个"可选的外部 Docker 栈"，而运行环境不提供 Docker（C4）。这不是配置遗漏，是**架构决策与运行环境不匹配**。后果是 MTTR 不可控：故障只能靠用户报障。
**选项与权衡**：

| 选项 | 权衡 | 可逆性 |
|---|---|---|
| A. Windows 原生落地：`windows_exporter` + 本机 Prometheus + Grafana（`.zip` 运行） | 复用现有 `prometheus.yml`/dashboard JSON（改主机名为 `127.0.0.1`）；多两个 Windows 服务 | 高 |
| B. 不引入采集栈，只做"文件巡检 + 定时自检入日志 + `/api/health` 扩展" | 零新依赖、当天可做；没有时序数据、无法做趋势与告警 | 高 |
| C. 保持现状，把死配置显式归档删除 | 消除"以为有监控"的错觉；仍无观测能力 | 高 |

**建议**：短期 B（立即恢复"故障可见"），中期 A。**C 必须做**——死配置的存在本身是有害的，它让运维误判监控已就绪。

### P0-3 备份静默残缺 —— 备份不可信

**现象**：备份任务可能"记录成功但实际缺表"。
**证据**：增量备份 `approval_log` 报错仍记 `success(table_count:32)`；`backup_schedule.last_status` 恒为 `running`；服务环境缺 `pg_dump` 时降级为 JSON 备份。RTO 无实测：还原为 `DROP DATABASE` + 流式导入、非事务、`ON_ERROR_STOP=0`（`docs/reports/2026-08-23-backup-benchmark-report.md` P0-5）。
**为什么是架构问题**：备份子系统的**成功判据设计错误**。"任务未抛异常"被当作成功，而不是"目标表全部导出且可校验"。当 RPO/RTO 是系统的核心承诺时，**判据错误 = 承诺无效**。这比"备份失败"更危险，因为失败是可见的，假成功不是。
**选项与权衡**：

| 选项 | 权衡 | 可逆性 |
|---|---|---|
| A. 给备份加"成功判据"：导出表数 vs ORM 表数比对 + 抽样校验和 + `last_status` 状态机收敛 | 改动局限在备份子系统内；不改变备份方式 | 高 |
| B. 放弃 `psql` 外部进程，改应用内 `COPY`/流式导出 | 可纳入事务、判据自然；工作量中等，且与 `core/database.py:210-212` 的现有宽容逻辑交互复杂 | 中 |
| C. 用 `pg_basebackup` + WAL 归档替代逻辑备份 | 恢复最可靠（PITR）；存储与运维成本最高，需改 NSSM 服务集 | 低 |

**建议**：A（本周），B/C 记录为 ADR。**A 的收益/成本比在全仓排名第一。**

### P1-1 无一键回滚

**证据**：`erp_system.spec` 已废弃（`:3-6`）；`server_manager.spec` 仅打包 GUI；前端 `build:atomic` = `vite build --outDir dist-new` + `frontend-vite/scripts/swap-dist.mjs`（`package.json:13`），但 **swap 成功后不留回滚副本**（`docs/runbooks/service-lifecycle.md:301`）；P6 部署流水线（`DeployEngine`/`DeployHistory`）**只存在于 `docs/designs/2026-08-22-deploy-pipeline-p6-design.md`，`server_manager/` 内 grep 无实现**；CI 不部署（`.github/workflows/ci-cd.yml:281-302` 记录 2026-09-24 删除 deploy job）。
**为什么是架构问题**：在 C1（本机即生产）下，**回滚能力就是变更能力**。没有回滚，任何发布都是单向门；团队因此不敢发布，或发布后长时间处于"不可回退"状态。这是"可逆性优先"原则被违反的直接后果。
**权衡**：修法简单（swap 前保留 `dist-prev-<ts>` + 脚本化回滚 + 迁移降级清单），成本极低、收益极高，**属本轮性价比最高的改动之一**。注意 `service-lifecycle.md` §5.2c 提示回滚需先禁用 `erp-web` 自启防双 nginx——这一步应脚本化。

### P1-2 配置三份漂移 —— 静默降级风险

**证据**：`.env` 107 键 vs `.env.production` 37 键 vs `config/.env.production` 35 键，**后两者缺约 78 键（含全部 `BACKUP_*`）**；校验薄弱：`core/config.py:196-245` 只校验 `SECRET_KEY` 非空/≥32、`ALGORITHM` 白名单、`ALLOWED_HOSTS` 无 `*`、`CORS` 无 `null`；`extra="ignore"`（`:279`）静默吞键。
**为什么是架构问题**：`AGENTS.md` 红线④明写「不要让 `.env` 的 `BACKUP_ENCRYPTION_PASSWORD` 为空（会静默降级为不加密备份）」——**团队已经识别了这个失效模式，但防线只有"人不要做错"**。三份配置 + 弱校验 = 该失效模式有 3 条触发路径。架构上应把"配置缺失"从人的记忆移到启动检查。
**选项与权衡**：A. 单源配置（`.env` 为唯一真源，`.env.production` 改为符号链接或生成产物）+ 启动强校验 `BACKUP_*` 必填；B. 引入 Pydantic Settings `model_config(extra="forbid")` + 必填字段，启动即失败。**A 成本更低、可逆性更高，建议先 A 后 B。**

### P1-3 `core/container.py` 服务定位器造成分层倒置

见 §3.1。**为什么是架构问题**：分层架构的价值在于"依赖方向可推理"。`core` 依赖 `services` 之后，"`core` 可以独立于业务被替换/测试"这一属性消失——而 `core` 恰恰是最需要稳定的层。
**选项与权衡**：

| 选项 | 权衡 | 可逆性 |
|---|---|---|
| A. 删除 `container.py`，调用方直接 import 具体 service | 立即消除 12 条倒置边、消除 4 模块环；放弃（本就未兑现的）可替换性 | 高 |
| B. 保留容器，但把接口下沉到 `core/ports.py`（Protocol），service 在启动时注册 | 真正兑现 DIP，`core` 只依赖 Protocol；改动面较大，需要 9 处注册 | 中 |
| C. 保持现状 | 零成本；接受 12 条倒置边与"假 DIP"的认知负担 | — |

**建议**：若近期无替换实现的需求 → **A**（诚实、可逆）；若确实计划多实现（如搜索服务换引擎）→ **B**。**不要停在 C**：一个名字叫"容器"但没有容器语义的模块，会让后来者误判架构意图。

### P1-4 双轨运维面（死配置）

**证据**：真实拓扑是 Windows + NSSM + `config/nginx-windows.conf`；但 `config/` 下同时存在 `nginx.conf`（root `/app/...`，Windows 永不生效）、`pgbouncer/*.ini`、`postgres/init-*.sh`、`prometheus.yml`、`alertmanager.yml`、`alert_rules.yml`、`otel-collector.yaml`、`promtail.yml`、`grafana/dashboards/*.json`、`redis.production.conf`——全部 Linux/Docker 取向。**仓库无任何容器化资产。**
**为什么是架构问题**：`AGENTS.md` 已对 nginx 双轨发出警示，但**同类问题在另外 6 类配置上没有任何警示**。运维在"改 `config/prometheus.yml` 还是改别处"上的判断成本，以及"改了不生效"的误操作概率，都是架构认知负荷的直接来源。
**建议**：二选一，不要并存 —— 要么删除死配置（推荐，可逆性高，`git revert` 即可恢复），要么移动到 `config/_unused/` 并在 `AGENTS.md` 记录。**同时把 `AGENTS.md` §3 的"生效配置"清单扩展到全部配置类别。**

### P2-1 PC/mobile 双 UI 树

**证据**：`views` 274 个 `.vue` vs `mobile` 43 个 `.vue`，**同名对 = 0**；mobile 42 个 `.vue` 只用 `M*` 组件、不引用 `components/ui/`；`src/mobile/views/purchase/MPurchaseView.vue:109-121` 自声明 interface、`:134` 硬编码 `per_page 50`；`src/mobile/views/product/MProductView.vue:79-96` 自建字段映射；mobile 端 `useQuery` = 0（PC 端 30 处）；mobile→views 仅 2 处。
**为什么是架构问题**：同一领域模型（产品、采购）存在**两套契约映射**，且两端的缓存策略不同（PC 用 Vue Query，mobile 无）。后端字段变更时需两处修改，口径漂移是时间问题——**且已有真实事故记录**。
**权衡**：抽共享 view-model composable（`useProductListModel` 等）供两端复用，是唯一能消除重复的方案；但会把 mobile 从"独立演进"变为"跟随 PC"，短期降低移动端迭代速度。**建议先在"字段映射 + 查询参数"这一层共享（收益最大、耦合最小），UI 层继续分叉。**

### P2-2 前端路由权限粒度粗

**证据**：`src/router/index.ts:161-203` 守卫，`:195-199` **只比对 `path` 第一段**，且 `/dashboard`、`/notifications` 无条件放行。
**重要限定（避免夸大）**：后端 **376 个 route handler 中 353 个已保护**，且 **32/34 个 router 带 router 级 `Depends(get_current_user_id)`**（`backup_router` 用 `get_current_user_id_strict`）。**所以这不是鉴权缺口**，而是纵深防御与 UX 问题：用户可以直达无权页面（数据仍取不到），体验与预期不符。
**建议**：改 route `meta` 声明 `requiredPermission`，逐路由校验，与后端下发的 `permission_codes`（`src/stores/auth.ts:219-229`）对齐。可逆、成本低。

### P2-3 健康检查两套实现、语义相反

**证据**：`fastapi_app/api/v1/endpoints/auxiliary.py` 定义 `/health`、`/ready`、`/healthz`、`/readyz` 四个端点，但它们挂在被 `Depends(get_current_user_id)` 保护的 `auxiliary_router` 上 → **要求 JWT，外部探活不可用**；而真正的探活端点在 `core/health.py`（`main.py:391` `register_health_routes(app)`，无鉴权）：`/api/health`（`:82`）、`/api/health/db`（`:164`）、`/metrics`（`:200`）、`/api/health/live`（`:218`）、`/api/health/ready`（`:226`）、`/api/health/startup`（`:259`）、`/api/health/arq`（`:277`）。
**为什么是架构问题**：同一职责两处实现、语义相反（一个要鉴权、一个不要），后来者无法从代码判断"哪个是权威探活点"。建议删除 `auxiliary.py` 的 4 个端点（或改为无鉴权并统一到 `core/health.py`）。

### P3-1 迁移 4 个 root 与仓库卫生

- **4 个 root**（§3.5）：单 head 保证了生产可用，但**全新环境 `alembic upgrade head` 需重放 4 条分支链**，schema 历史不可线性重放。属历史遗留，**建议冻结现状 + 记录 ADR**，不要为"整洁"重写历史迁移（低可逆、高风险）。
- **仓库卫生**：`git ls-files` = 2277；`backups/` 17 个源码快照、`static/uploads` + customer-sampling **24 张真实客户图**被跟踪，与 `AGENTS.md`「`backups/`、`logs/` 运行期数据不入库」冲突；体积：`backups/` 419MB/3687 文件、`dist`+`build` 79MB、`.git` 519MB；**C 盘仅剩 33.1GB**（nginx/nssm/Redis/PG 数据在 C）。
- **客户图入库是隐私问题**，优先级应高于体积问题。

### 5.6 安全基线（扫描结论，供交叉验证）

- **危险调用全零**：`subprocess(shell=True)`=0、`os.system`=0、`eval/exec`=0、`pickle.load`=0、`yaml.load`（非 Safe）=0、`verify=False`=0、`allow_origins=["*"]`=0、`DEBUG=True`=0。
- **散列**：md5/sha1 7 处（`backup/validation.py:370`、`:608`、`core/cache.py:252`、`core/pg_locks.py:18`、`services/base_search_service.py:156`、`services/backup/verify/core.py:244`、`utils/redis_cache.py:508`）**全部用于缓存键/分布式锁**，非口令散列；`random` 1 处（`services/backup/cleanup/service.py:429`，备份抽样，带 `# nosec B311`）。
- **口令**：`fastapi_app/core/security.py` 主用 **argon2id**（`:13-14`），向后兼容 bcrypt（`:39-43`）与 legacy pbkdf2（`:52-60`，带 iterations 上限拒绝）。未使用 passlib。
- **JWT**：`core/auth/token.py:90` 解码显式限定 `algorithms=[settings.ALGORITHM]`（防 alg 混淆）；`core/config.py:202` `_ALLOWED_JWT_ALGORITHMS = {"HS256","RS256","ES256"}` 白名单；生产要求 `SECRET_KEY` 长度 ≥32（`:215-217`）。
- **凭据未入库**：仅跟踪 `.env.example`、`.env.production.example`、`config/pgbouncer/userlist.txt.example`、`frontend-vite/.env.example`、`docs/ops/2026-09-30-credential-rotation-runbook.md`、`scripts/scan_secrets.py` 及其测试。**未跟踪 `.env` / `userlist.txt` / `*.pem`** → 符合红线②。
- **中间件**：开发 CORS 白名单 `localhost:3000/5173`（`core/middleware.py:334-353`）；生产用 `settings.BACKEND_CORS_ORIGINS` + `allow_credentials=True`（`:360-364`）；`TrustedHostMiddleware`（`:371-372`）；`GZipMiddleware(minimum_size=1000)`（`:389`）；slowapi 限流（`main.py:269-277`）。

---

## 6. 需要重新审视的假设

架构评审的价值一半在于指出"哪些前提可能已经不成立"：

| 假设 | 现状 | 风险 |
|---|---|---|
| A1「单机部署足够」 | C2：D 盘/nginx/erp-prod/Redis 单点 | 可用性上限被单机锁定。**若业务已无法接受半天停机，这条假设已失效**，需要显式记录为接受的取舍而非默认 |
| A2「备份等于可恢复」 | P0-1（同盘无异地）+ P0-3（假成功）+ RTO 未实测 | 三重削弱。**"有备份"与"能恢复"之间目前没有证据链** |
| A3「Prometheus/Grafana 提供了监控」 | P0-2：配置存在但无运行体 | 监控是**错觉**。这比没有监控更危险——它抑制了"我需要监控"的决策 |
| A4「mobile 是 PC 的简化版」 | P2-1：两套独立 UI 树、0 共享 | 实际是两条产品线，维护成本按 2 倍计。**若按"简化版"规划资源，会持续欠配** |
| A5「`container.py` 改善了 DIP」 | P1-3：硬编码实现、生产路径无人注册 | 抽象没有兑现。**架构文档与实际能力不一致**，会误导后续设计 |
| A6「迁移历史是线性的」 | 4 个 root | 新环境搭建依赖 merge revision 的正确性；灾难恢复时重放路径非显然 |
| A7「CI 提供了质量门禁」 | CI 不部署 + 本机 pre-commit 未安装（hook 只剩 3 层） | 本地门禁弱于 CI 设计；**实际门禁强度 = 开发者记忆** |

---

## 7. 可逆性分析（技能核心视角）

按"改动成本"给关键决策排序，**优先投资高可逆项，对低可逆项要求更充分的论证**：

**高可逆（可当天改、当天回滚）**
- 备份异地/第二盘同步（P0-1 A/B）
- 备份成功判据（P0-3 A）
- `swap-dist` 留回滚副本 + 回滚脚本（P1-1）
- 单源配置 + 启动强校验（P1-2）
- 删除死配置（P1-4）
- 删除 `container.py` 或下沉 Protocol（P1-3 A/B）
- 前端路由 `meta` 权限（P2-2）
- 删除 `auxiliary.py` 重复健康端点（P2-3）
- 共享 mobile/PC 的字段映射层（P2-1 的第一步）

**中可逆（需几天、需验证）**
- Windows 原生监控栈（P0-2 A）
- 备份改应用内导出（P0-3 B）
- 抽取 mobile/PC 共享 view-model（P2-1 完整方案）
- 清理仓库历史体积（需 rewrite 或 `git filter-repo`，影响所有克隆）

**低可逆（改动前必须有 ADR）**
- PostgreSQL 流复制 + 自动故障切换（P0-1 C）
- `pg_basebackup` + WAL 归档 PITR（P0-3 C）
- 迁移历史重写/收敛 root（P3-1）——**建议不重写**
- 任何形式的服务拆分——**当前无理由**

---

## 8. 建议记录的 ADR

1. **ADR：备份存储拓扑与 RPO/RTO 承诺**（决定 P0-1/P0-3 的取舍，明确"接受的残余风险"）
2. **ADR：可观测性实现形态**（Windows 原生 vs 仅文件巡检 vs 不实现）
3. **ADR：发布与回滚流程**（含 `erp-web` 自启禁用步骤、迁移降级清单）
4. **ADR：配置真源**（`.env` 单源、必填校验清单、轮换流程）
5. **ADR：`core/container.py` 的去留**（删除 vs Protocol 化）
6. **ADR：mobile 与 PC 的代码共享边界**（哪一层共享、哪一层分叉）
7. **ADR：冻结迁移历史**（4 个 root 不重写，理由与影响）

---

## 9. 建议行动顺序

**第 1 周（全部高可逆、当天可验证）**
1. 备份加"成功判据"（P0-3 A）——**收益/成本比最高**
2. 备份同步到第二盘/异地（P0-1 A/B）
3. `swap-dist` 保留回滚副本 + 回滚脚本（P1-1）
4. 配置单源 + `BACKUP_*` 启动强校验（P1-2 A）
5. 删除死配置或移入 `config/_unused/`，并扩展 `AGENTS.md` 生效配置清单（P1-4）
6. 手工复核 `services/stock_inventory_service.py:383/551/631/633/634` 的 SQL 插值（§3.4 未决项）

**第 2–3 周（需少量设计）**
7. 可观测性最小可用：文件巡检 + 定时自检 + `/api/health` 扩展（P0-2 B），并决定中期方案
8. 删除 `container.py` 或 Protocol 化（P1-3）
9. 前端路由 `meta` 权限（P2-2）
10. 删除 `auxiliary.py` 重复健康端点（P2-3）
11. 从版本库移除 24 张真实客户图与 `backups/` 快照（P3-1，隐私优先）

**第 4 周起（需 ADR）**
12. Windows 原生监控栈（P0-2 A）
13. mobile/PC 共享字段映射层（P2-1 第一步）
14. 备份方式演进（P0-3 B/C）——**先写 ADR**

**明确不建议做的事**
- ❌ 拆分微服务（耦合可逆、单机部署、无独立伸缩需求）
- ❌ 重写迁移历史（低可逆、高风险、无收益）
- ❌ 为了"整洁"重排目录（`utils/`、`server_manager/` 是红线①保护项，且有真实用途）

---

## 附录 A：证据与复现

本轮全部结构数字来自以下脚本（`_qa_tmp/`，未纳入版本库）：

| 脚本 | 覆盖 |
|---|---|
| `_qa_tmp/arch_scan_arch1.py` | 解析健康度、分层文件数/LOC、跨层依赖边、fan-in/fan-out 枢纽、import 环 SCC、路由接线 |
| `_qa_tmp/dsh_arch_a2.py` | endpoint 模块规模、services 域分布、服务域间耦合、鉴权覆盖 |
| `_qa_tmp/dsh_arch_a4.py` | 辅助路由、API v2、UoW 事务语义、前端结构 |
| `_qa_tmp/dsh_arch_a5.py` / `a6.py` | 危险调用点、散列、原生 SQL、口令/JWT、孤儿模块复核 |
| `_qa_tmp/dsh_arch_a7.py` | ORM↔迁移漂移、git 跟踪面、nginx 双轨 |
| `_qa_tmp/dsh_arch_a8.py` | 前端模块规模、API 层、构建配置、路由 |
| `_qa_tmp/dsh_arch_a9.py` | 启动/运行时文件、`container.py`、ARQ 配置、`server_manager/`、容器化资产、定时任务 |

关键路径（供交叉验证）：`fastapi_app/core/database.py:203-240`（UoW）、`fastapi_app/core/container.py`、`fastapi_app/api/v1/router.py`、`fastapi_app/core/health.py`、`fastapi_app/core/prod_runner.py`、`fastapi_app/core/arq_app.py`、`fastapi_app/api/v1/endpoints/auxiliary.py`、`config/nginx-windows.conf` vs `config/nginx.conf`、`frontend-vite/src/router/index.ts:161-203`、`frontend-vite/vite.config.js:125`、`server_manager/constants.py:31-34`。

## 附录 B：分析方法坑（下次评审前必读）

1. **必须用 `ast`，不能用正则**：正则曾得出「15 个迁移 head」「48 个端点模块未接线」两个伪影；本轮又因文本匹配漏掉逗号列表，把 `backup/validation.py` 误判为孤儿。
2. **迁移图必须用 `alembic ScriptDirectory`**：朴素 AST 只认 `ast.Assign` 会漏掉 `AnnAssign`，得到「5 roots / 4 heads / dangling」的伪影。仓库**没有 `alembic.ini`**，需 `cfg.set_main_option("script_location", ROOT/migrations)`。
3. **`drop_table` 计数必须排除 `downgrade()`**：Alembic 自动生成文件的 downgrade 与 upgrade 一一对应，直接计数会得到「46 表被删」的伪影。
4. **同一正则内联与预编译结果不一致时，先怀疑脚本**（曾得到 `MIG=0`）。
5. **13 个 `.py` 解析失败全部是 UTF-8 BOM**，其中 8 个在仓库自带的 `scripts/prod_audit/` 里——**仓库自带的审计框架本身带 BOM**，这会让任何基于 `ast` 的审计在它身上失效（本机是 PowerShell 5.1，`-Encoding utf8` 会写 BOM，`AGENTS.md` §6 已记录）。
6. **中文文件必须用 `read` 工具读**：控制台代码页会让 `pyproject.toml` 等显示为乱码，不得据此判定编码损坏。
7. **区分包级环与运行时环**：`__init__.py` 聚合再导出会制造大量假环（本轮 6 个环里 5 个属此类）。
8. **`logs/erp.log` 不是生产日志**（格式对应 `utils/logger.py`，唯一导入者是 `tests/test_logger.py`，见 `fastapi_app/core/maintenance.py:19-23`）；`prod_runner.json` 的 `started_at` 是写盘时刻而非进程启动时刻。**不要据此判断生产异常。**

---

*本报告基于只读分析：未运行应用、未连接数据库、未执行测试、未启停任何服务、未修改仓库任何文件。所有"事实"标注均可通过附录 A 复现；标注为"未决项"的条目需要人工复核后才应作为结论使用。*
