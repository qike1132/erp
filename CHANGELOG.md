# 变更日志 (Changelog)

## [2026-09-28] 生产编排重构：erp-web 单一职责（拆 nginx 出 prod_runner）

### 🏗️ 五服务拓扑（消除监督器混管）
- **问题**：`prod_runner` 同时托管 nginx（无状态静态）与 uvicorn（有状态 API），生命周期不同却被绑在一个进程树里。历史事故：nginx spawn 方式不当阻塞监督器主循环 → NSSM 反复重启监督器 → nginx 周期性 kill/重建 → **全站连接每 ~35 秒被切断一次**。
- **改动**：新增 NSSM 服务 `erp-web` 直管 `nginx.exe`（AppExit=Restart，无依赖）；`prod_runner` 删除 `_FrontendNginx`/`_find_nginx`/vite preview 回退等约 260 行，瘦身为只守护 uvicorn；保留对 `:3000/nginx-health` 的**只读探针**（写 `frontend_ok` 字段，失败只报告绝不重启）。前后端启停解耦：重启 erp-prod 不再影响前端静态服务。
- **迁移**：`scripts/migrate_erp_web.ps1`（幂等，`-DryRun` 可预览命令序列；回滚步骤见脚本头注释，**必须含 `nssm set erp-web Start SERVICE_DISABLED` 防回滚后开机双 nginx**）。
- **GUI**：`server_manager.py` 七处服务元组扩为三元组（含 `_managed_service_pids` P0-4 闸门——dev 模式切换仍能抢到 :3000）；安装流注册 erp-web；前端徽章仿 ARQ `external` 范式改读服务状态 + 探针交叉验证。
- **nginx 日志轮转归属**：`_rotate_file_copytruncate` 下沉 `utils/log_rotation.py`；nginx access/error 日志轮转挂入 ARQ cron（每日 04:30，阈值 100MB；ARQ 停摆仅意味着暂不轮转，优雅降级）。
- **顺带**（同维护窗口生效）：nginx `worker_processes auto(12)→2`、`.env` `UVICORN_WORKERS 8→4`（6 物理核机器去过订阅）。
- **文档**：`docs/runbooks/service-lifecycle.md` 拓扑重写为五服务、新增 5.2b/5.2c 故障条目；删除被护栏拦死的死脚本 `restart_prod.ps1`。
- 设计与计划：`docs/superpowers/specs/2026-09-28-erp-web-single-responsibility-design.md`。

## [2026-09-18] 文件规模门禁阈值上调与单点化

### 🧱 `file_size_gate` 阈值 1200 → 1600，且不再三处硬编码
- **问题**：阈值原先写在 3 个地方（`pyproject.toml max_file_size`、`scripts/file_size_gate.py DEFAULT_THRESHOLD`、CI workflow 的 `--threshold 1200`），改一处必漏两处；而 1200 会让两个存量文件一旦被改动就阻断提交（`test_purchase_center.py` 1497 行、`recovery_test_service.py` 1353 行）。
- **改动**：`file_size_gate.py` 新增 `_threshold_from_pyproject()`，改为读取 `pyproject.toml [tool.code-quality] max_file_size`（与 `quality_gate.py` 同一约定，解析失败才回落内置默认值）；CI 步骤去掉 `--threshold 1200` 改为读配置。
- **定档依据**：受扫描的 777 个 `.py` 中仅上述 2 个超过 1200，故取 1600 留出余量，仍能拦住新增上帝类。
- **顺带修复**：`file_size_gate.py` 的 git 输出解码改为显式 `encoding="utf-8"`，并强制 stdout/stderr 为 UTF-8 —— 中文 Windows（cp936）下打印 `⚠` 会抛 `UnicodeEncodeError`，使门禁自身崩溃。

## [2026-08-22] 生产部署健壮性：服务依赖 + 日志轮转

### 🔗 NSSM 服务启动依赖（消除开机重启风暴）
- `server_manager.py` 安装 erp-prod / erp-arq 服务时自动扫描本机正在运行的 PostgreSQL/Redis 服务（名称含 postgres/redis/memurai 且 StartType=Automatic、Status=Running），写入 `DependOnService`——开机时数据库先就绪再拉起应用，避免后端健康检查失败触发监督器退避重启。只读副本（replica）与已停用旧实例（Automatic 但停止，如退役 Redis）自动排除，防止其启动失败连累主服务。本机实测探测到 `postgresql-x64-18 / erp-redis / erp-redis-broker`。
- 探测不到时打 WARNING 跳过（PG/Redis 可能在远端）；可用环境变量 `SERVICE_DEPENDS_ON=svc1,svc2` 显式指定。
- 顺带修复 `_run_capture` 在中文 Windows（OEM/GBK 代码页）+ PYTHONUTF8=1 环境下按 UTF-8 解码 sc/nssm 输出抛异常、stdout 丢失的问题（改按 OEM 解码 + replace）——此前含中文显示名的服务会被误判为"未安装"。
- **生效方式**：在 server_manager「生产托管」面板重新执行「安装服务」即可（已注册服务需重装才更新依赖）。

### 📜 生产日志轮转（防止磁盘占满）
- `prod_runner.py` 新增 copytruncate 轮转：子进程 `logs/<name>.out.log` 与 Nginx `access/error` 日志超过阈值（默认 50MB，`PROD_LOG_ROTATE_MB` 可调）时先复制为 `.1` 副本再原地截断，每 60 秒检查一次。
- Windows 下日志文件被子进程/nginx 以共享读写 + 追加方式占用无法 rename，copytruncate 是可行解；截断瞬间的少量行丢失对运维日志可接受。
- 此前仅 NSSM 自身的 `logs/erp-*.log` 有 10MB 轮转，子进程与 Nginx 日志无限增长。

## [2026-08-21] 代码质量修复（P1/P2/P3）

### 🧹 静态分析清零（ruff 全范围 All checks passed）
- **fastapi_app + scripts：114 → 0 项**（含 78 个 F401、20 个 import 排序等）。
- **tests + utils 存量：73 → 0 项**（N803 参数命名 ×10、RUF013 隐式 Optional ×30、RUF010/RUF012 等）。
- 兼容层保护：`purchase_plan_crud.py`、`stock_service.py` 等 re-export 文件加文件级 `# ruff: noqa: F401`，**未删任何兼容 import**（外部调用方零影响）。
- 修复 ruff 0.16 RUF013 unsafe-fix 误伤：`batch_upload_utils.py` 的 `callable` 内置名被改坏 → 修正为 `Callable | None`。
- 有意的 noqa（F403 star-import、S110 防御性降级、RUF012 只读常量）均保留并加注释说明。

### 🐛 存量 bug 修复（扫描中发现）
- **`utils/audit.py` 模块无法导入**：`from fastapi_app.core.database import SyncSession` 引用不存在的名称 → `database.py` 新增 `SyncSession()` 兼容工厂（lazy 初始化，带失败保护）。
- **`utils/number_generator.py` / `batch_import_handler.py` 参数命名**：`Order/StockIn/Product` 等大写参数重命名为 `order_model/stockin_model/product_model`（位置调用，调用方零影响）。
- **`pg_tune.py` 闭包捕获循环变量（B023）**：lambda 绑定默认参数 `v=value`。
- **`redis_cache.py` SQLAlchemy 布尔比较**：`== True` → `.is_(True)`。

### 🔒 安全复核（bandit 1.9.4 实跑）
- **0 个 MEDIUM/HIGH**（历史 bandit_report 的 27 个 MEDIUM B608 已全部消除），仅 2 个 LOW 噪音。

### 🧪 测试补强（前端 61 → 70 用例）
- 新增 `usePagedSearch.test.ts`（5 用例：防抖重置页码/连续输入/清空/卸载清理）。
- 新增 `useStockWarning.test.ts`（4 用例：库存充足/无记录/不足/接口异常 fail-closed）。
- 全量回归：后端 **834 passed**、前端 **70/70 passed**、`vue-tsc --noEmit` 零错误。

### 🛡️ 文件规模门禁（防新上帝类）
- 新增 `scripts/file_size_gate.py`：CI 中检查 git 变更文件行数（阈值 1200），存量超限文件不阻断。
- 已集成 `.github/workflows/ci-cd.yml` lint job。
- 当前超限存量：`tests/test_purchase_center.py`（1406 行）、`backup/orchestration/recovery_test_service.py`（1319 行）——建议后续拆分。

### 📊 类型检查扩展（mypy 13 → 20 文件）
- 纳入 `shared/shipment_calc.py`、`shared/stock_crud_service.py`、`shared/report_data_service.py` 及核心 shared_models；补全 8 处局部变量注解，`shipment_calc` 签名 `dict[int, float] → dict[int, int]`（与实际 SQL 聚合一致）。

### 📦 快照清理
- `ruff_issues.txt`、`ruff_endpoints.json`、`ruff_services.json`、`pytest_full.log`、`bandit_report.json` 均为过时快照，重命名为 `*.stale-20260821`。

### 🔄 P1 多 SKU（渐进式改造，部分完成）
- ✅ `order_crud.create_order` 现写入 `OrderItem` 明细（与批量创建路径对齐，消除"部分多 SKU"数据不一致）；单 SKU 行为等价，历史订单不受影响。
- ⏳ 其余 19 处 `TODO(multi-sku-order)`（库存扣减/报表/审批/编辑语义）为架构级改造：需业务 spec 确认语义（多 SKU 编辑改哪个 item、扣减粒度）+ 查询入口 selectinload 预加载联动，**未在本轮擅自动手**。

## [2026-08-21] PG 重启生效 + 索引清理 + 前端测试修复

### ⚡ PostgreSQL 调优生效（主从双库）
- 重启 `postgresql-x64-18`（主库）与 `postgresql-replica`（副本），**8 参数全部生效**（shared_buffers 3948MB / effective_cache_size 11844MB / maintenance_work_mem 512MB / wal_buffers 16MB / parallel 4 / statistics_target 200）。
- 修复 `scripts/pg_tune.py` 的 PGDATA 目录解析 bug（此前把 PGDATA 当文件判断，导致副本调优失效）；副本配置已同步并验证（in_recovery=True 流复制正常）。
- 主从配置文件均已备份（`postgresql.conf.bak-20260821_213655` 等）。

### 🔍 索引清理（备份+CONCURRENTLY+验证）
- **19 组重复索引全部删除**（保留各表的 `idx_*`/UNIQUE 约束），DDL 备份到 `docs/backups/index_cleanup_20260821_213825.sql`。
- **audit_log 9 个未使用索引全部删除**（60 天无扫描，仅剩主键），DDL 备份到 `docs/backups/audit_index_cleanup_20260821_213900.sql`。
- 全程 CONCURRENTLY 不锁表；删除前逐对对比列定义确认真重复；删除后复查保留索引完好。

### 🧪 前端测试修复（61/61 通过）
- **BeileOrderTab.export.test.ts（7 失败→8 通过）**：导出/打印按钮已从 BeileOrderTab 迁移到 **HubeiView 头部**（`bo-header-btn--export/print`），测试重写为挂载 HubeiView；修复 Pinia 缺失、HubeiSearchBar 内 PrimeVue AutoComplete jsdom 渲染失败（stub）、原生 checkbox 事件（setValue）。
- **PurchaseView.autorefresh.test.ts（2 失败→2 通过）**：`@tanstack/vue-query` mock 补全 `useQuery`（此前缺失导致 setup 崩溃）；增强 mock 支持 queryFn 挂载执行 + refetchInterval 响应式定时（watchEffect），模拟真实 auto-refresh。
- 全量回归：**61/61 通过**（此前 52/61），`vue-tsc --noEmit` 零错误。

## [2026-08-21] P2 扩展性优化 (PgBouncer / L1广播 / 索引审计)

### 🔌 PgBouncer 部署配置
- 新增 `config/pgbouncer/pgbouncer.windows.ini`（Windows 路径版，transaction 模式 + scram-sha-256）。
- 新增 `scripts/pgbouncer_gen_userlist.py`：自动生成 userlist.txt（明文/scram 或 md5 模式），替换占位符。
- 代码衔接已完备（`PGBOUNCER_ENABLED=true` 时应用侧连接池自动缩小，见 database.py）。

### 🔄 L1 缓存跨 worker 失效广播
- `.env.example` / `.env` 新增 `CACHE_L1_BROADCAST_ENABLED=false`（多 worker 生产建议开启）。
- **实测验证 PASS**：发布→监听→L1 清理闭环正确（执行计数 1→1→2 严格区分缓存命中/重算）。
- 注：单 worker/开发环境保持关闭（省一个 Redis 连接）。

### 🔍 索引审计 (scripts/index_audit.py)
- 新增只读审计脚本 `scripts/index_audit.py`（重复/未使用/膨胀/大小 4 类检查）。
- 报告见 `docs/index-audit-2026-08-21.md`：
  - **19 组重复索引**（建议删 `ix_*` 旧规范命名，保留 `idx_*`）
  - **20 个未使用索引**（audit_log 占 9 个、约 3.5MB 写入开销）
  - 无索引膨胀，无需 REINDEX

## [2026-08-21] PostgreSQL 调优 + 报表物化视图

### ⚡ PG 服务端调优 (scripts/pg_tune.py)
- 新增一键调优脚本 `scripts/pg_tune.py`（自动探测内存/CPU，`--check` 对比、`--apply` 备份写入）。
- 已应用到本机 PG 18.3（15.4GB RAM / 12 线程），8 参数写入 `D:\PostgreSQL\data\postgresql.conf`：
  - `shared_buffers 128MB → 3948MB`、`effective_cache_size → 11844MB`、`maintenance_work_mem 64MB → 512MB`、`wal_buffers 4MB → 16MB`、`max_parallel_workers_per_gather 2 → 4`、`default_statistics_target 100 → 200`
  - 原配置已备份: `postgresql.conf.bak-20260821_210748`
  - ⚠️ 需重启服务生效: `net stop postgresql-x64-18 && net start postgresql-x64-18`

### 📊 报表物化视图 (mv_product_aggregate)
- 新增迁移 `pg_standalone_017_product_aggregate_mv`：按产品维度聚合订单/入库/出库统计（order_count/order_quantity/stockin_*/stockout_* + 最近活动日期），与现有 3 个日统计 MV 互补。
- `maintenance_tasks.py` 重构：统一 `_refresh_materialized_views()`（每 MV 独立 session 并行刷新），新增产品 MV 不存在时优雅降级（不阻塞其他视图）。
- ARQ `refresh_dashboard_mv_task` 现刷新全部 4 个 MV（原 3 日统计 + 产品聚合）。
- 真实环境已验证：迁移执行成功、数据正确（9 个活跃产品）、burst worker 刷新任务返回 `success: True`。

## [2026-08-21] 前端产物体积优化 (Bundle Size)

### 📦 ECharts 按需打包 (Tree-shaking)
- `src/utils/echartsPreload.ts`: 由 `import('echarts/charts')` 动态整模块导入改为 **静态命名导入**（`echarts/core` + `echarts/charts` + `echarts/components` + `echarts/renderers` 具名导出），使 Rollup tree-shaking 生效。
- `src/views/production/composables/useProductionCharts.ts`: 复用 `ensureEcharts()` 统一注册，消除重复的动态全量导入。
- **结果**: `vendor-echarts` chunk 从 **1058KB → 547.6KB（-48%，减 510KB）**；gzip 后约 160KB。
- 已注册图表/组件: Line/Pie/Bar + Grid/Tooltip/Legend/Title/Dataset + CanvasRenderer，覆盖 dashboard 与生产页全部图表类型。

### 🎨 FontAwesome 规范化 (Icon Import)
- `src/icons.ts`: `import * as solidIcons`（namespace）改为**显式命名导入** + 直接引用，与 Rollup 静态分析语义对齐（产物已验证仅含 161 个已注册图标，未注册图标 0 引用）。
- `all.min.css` webfonts 保留（114 处 `fas fa-` class 用法依赖，删除会导致图标缺失）。

### 🧪 测试
- `vue-tsc --noEmit` 零错误；vitest 52/61 通过；**9 个失败为既有问题**（BeileOrderTab.export / PurchaseView.autorefresh，改动前后一致，与本优化无关）。

## [2026-08-21] 异步任务栈升级与清理

### ⚡ 依赖升级 (Dependency Upgrade)
- **arq 0.26.0 → 0.28.0**: 消除与 redis 版本范围的元数据冲突声明。
- **redis[hiredis] 7.4.1 → 5.3.1**: 匹配 arq 0.28 的 `redis<6` 约束，`pip install -r requirements/base.txt` 严格解析无冲突；hiredis parser 默认生效（`redis._parsers.hiredis`），性能不变。
- **删除 `fastapi_app/core/celery_app.py`**: Celery → ARQ 迁移兼容层已无引用，彻底移除。

### 🔧 异步任务端点重构 (Task API Refactor)
- `GET /api/v1/tasks/status/{task_id}`: 由 Celery `AsyncResult` 死代码改为 **ARQ Job 真实查询**（`Job.status()` / `Job.result_info()`），任务不存在返回 404，Redis 不可用返回 503。
- `GET /api/v1/tasks/download/{task_id}`: 同步改为 ARQ Job 结果查询，与提交端（import-orders / import-stockins / export-report 已用 ARQ）打通闭环。
- `fastapi_app/core/config.py`: 移除无消费方的 `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 配置项（ARQ 使用 `REDIS_BROKER_URL`）。
- 测试 `test_tasks.py` 重写为 ARQ 语义（NOT_FOUND→404、STARTED、SUCCESS、FAILURE、503 降级）。


## [2026-03-24] UI 优化: 产品列表页 (`/product/list`)

### 🎨 设计与排版 (Typography & Spacing)
- **增加留白与呼吸感**:
  - 引入 8-pt 栅格系统，统一内边距（如 `24px`、`32px`）与外边距。
  - 调整字体行高至 `1.5`，提升文本可读性。
- **字体层级优化**:
  - 主标题 (Page Title): `32px` -> `24px`，字重 `700` -> `400`。
  - 副标题 (Page Subtitle): `15px` -> `18px`，字重 `400`。
  - 正文与表单标签 (Body Text): `14px`，字重 `400`。

### 🖱️ 交互与触控 (Interaction & Touch Targets)
- **触控区域达标**:
  - 所有按钮 (`.btn`, `.btn-sm`, `.action-buttons .btn`) 最小尺寸调整为 `44x44 px`。
  - 输入框 (`.form-control`) 与下拉框 (`.form-select`) 最小高度设为 `44px`。
  - 分页控件 (`.page-link`) 最小尺寸调整为 `44x44 px`。
- **视觉降噪与元素分组**:
  - 弱化次要按钮的边框（`.btn-outline-secondary`），主操作按钮 (`添加产品`) 增加视觉高亮。
  - 搜索与排序控件组合进统一的 `toolbar-wrapper` 中。

### ♿ 可访问性 (Accessibility)
- **对比度达标 (>= 4.5:1)**:
  - 更新次要文本颜色 `#8B7B7B` 为 `#595959`。
  - 更新绿色图标 `#66BB6A` 为 `--plush-green-text` (`#2e7d32`)。
  - 更新蓝色文本颜色为 `--plush-blue-text` (`#02669e`)。
- **键盘可达性**:
  - 为图片预览、无图占位符、拖拽上传区域等交互元素增加 `tabindex="0"` 和 `:focus-visible` 焦点样式（2px 轮廓）。
  - 为分页控件、搜索框、排序下拉框补充 `aria-label` 等语义化标签。

### ⚡ 性能与响应式 (Performance & Responsive)
- **无布局偏移 (CLS < 0.1)**:
  - 避免图片加载导致的重排，占位符与图片尺寸严格固定 (`80x80 px`)。
  - 上传区域和列表区域指定了安全的最小高度。
- **多端适配**:
  - 完善了 `1920x1080`、`1366x768` (桌面端) 及 `375x667` (移动端) 的响应式断点，针对移动端缩小了触控元素的间距，但仍保证 `44x44 px` 的可点击区域。