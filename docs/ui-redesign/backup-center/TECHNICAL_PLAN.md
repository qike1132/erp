# 滨发 ERP · 数据备份系统重构技术方案 v2（评审修订版）

> 主理人（Hua·画统筹）Phase 6 交付；**v2 为 2026-08-22 评审修订版**
> 配套文件：前端原型 `backup-center-prototype.html`、设计规范 `DESIGN.md`、交付说明 `DELIVERY.md`
> 修订依据：对 `services/backup/`（27 文件 / 约 9,600 行）、`api/v1/endpoints/backup/`（28 条路由）、
> 前端 `views/backup/` + `components/backup/`、`tasks/` + `core/arq_app.py`、`backups/server/` 生产实物的三路代码调查

---

## 0. 评审总结论

**v1 的「删除重写（新建 services/backup_center/）」路线整体推翻，改为「演进而非重写」。**

核心论据（v1 未探明的四个事实）：

1. **现有 `services/backup/` 已是目标架构形态**：六边形 10 端口（Protocol）+ 8 适配器 + 策略选择器，
   orchestrator 七阶段状态机（`RestorePhase` 10 态 + journal）、三层并发控制（进程内 asyncio.Lock +
   PG advisory lock `20240427` + 1800s 超时）、AES-256-GCM 加密、ZIP+manifest 打包、四层还原校验。
   v1 计划新建的 BackupOrchestrator / Strategy / VerifyEngine / ProgressHub / BackupStore 在现包中全部有对应物。
2. **生产链路是活的**：`backups/server/` 有每日全量 `erp_auto_daily_*.zip`（08-16～08-22）、
   加密包 `*.zip.enc`（06～08 月）、每天 5 班增量 `erp_incremental_*.zip`（06/10/14/18/22 点，与
   ARQ cron 完全吻合）。换 `.bfp` 新格式 = 磁盘上全部历史备份对新代码不可读。
3. **重写会静默丢能力**：现包还含 cleanup（重要性评分+增量链保护）、metrics（日采集）、alerts（SMTP+Webhook）、
   health_check（5 类巡检）、policy（策略 CRUD）、recovery_test（灾备演练，1,319 行）六个子系统，
   约一半带成建制测试（alert 410 行 / health 552 行 / metrics 637 行 / policy 664 行测试）。
   **v1 的范围里没有这六项 = 功能倒退**。
4. **v1 删除清单已过时**：所列 `services/backup_service.py` + 7 个 `backup_*_service.py` 已在 fa156a3
   （备份域收敛为单一包）中删除。

同时调查发现一个 **P0 级现存缺陷（与本方案是否实施无关，须立即热修）**：

> fa156a3 删除旧模块后，包内 **7 处函数级惰性导入仍指向已删除的 `fastapi_app.services.backup_service`**，
> 这些运行时路径会直接 `ModuleNotFoundError`：
>
> | 文件:行 | 导入符号 | 现在的家 |
> |---|---|---|
> | `services/backup/strategies.py:61` | `restore_database_via_psql` | `services/backup/dump.py:81` |
> | `services/backup/strategies.py:120` | `restore_database_from_json` | `services/backup/json_backup.py:172` |
> | `services/backup/adapters.py:82` | `create_pre_restore_backup` | `services/backup/orchestration/core.py:343` |
> | `services/backup/adapters.py:97` | `restore_non_dependent_components` | `services/backup/restore.py:25` |
> | `services/backup/adapters.py:177` | `verify_restore` | `services/backup/verify/core.py:113` |
> | `services/backup/orchestrator.py:271` | `sha256_bytes` | `services/backup/crypto.py:17` |
> | `services/backup/format_strategy.py:474` | `generate_encryption_key` | `services/backup/crypto.py:33` |
>
> 受影响路径：**psql 全量还原、恢复前安全备份、组件恢复、还原后校验、格式策略加密**——即还原主干当前是坏的。

### v1 → v2 决策裁定表

| # | v1 决策 | v2 裁定 | 理由 |
|---|---------|---------|------|
| 1 | 删除重写，新建 `services/backup_center/` | **推翻 → 演进 `services/backup/`** | 见上，六边形已成型 + 保住 6 子系统 + 历史备份兼容 |
| 2 | 新格式 `.bfp`（滨发备份包） | **推翻 → 保留 ZIP+manifest v2.0** | 60+ 个生产备份兼容是硬约束；manifest+AES-GCM 能力已齐 |
| 3 | 全量 = pg_dump 逻辑备份 | **保留（现状即是）** | dump.py 已做 pg_dump+gzip+JSON 回退；**补充：备份含 filestore/config/redis/meili 全系统组件，必须保留** |
| 4 | 增量 = updated_at 变更追踪 | **保留但补短板** | 硬 DELETE 不可见（仅软删除可捕获）；补逐表 count+fingerprint 对账；WAL 增量是未完成占位，明确冻结 |
| 5 | 定时 = APScheduler（同进程） | **推翻 → 保留 ARQ** | ARQ 已在产（独立 worker 进程）；APScheduler 在 4 个 uvicorn worker 下会重复调度，且长任务不该跑在 API 进程 |
| 6 | 进度 = SSE 推送 | **降级为可选增强** | 进度已在 Redis（8 备份阶段/10 还原阶段），还原侧 800ms 轮询已验证；全仓无 SSE 先例、有 WebSocket 先例；M4 按需再上 |
| 7 | 互斥 = 全局 `asyncio.Lock` | **推翻 → PG advisory lock 为真相源** | 生产 4 worker，进程内锁无效；现有 `BACKUP_LOCK_ID=20240427`/`RESTORE_LOCK_ID=20240426` 直接沿用；Redis restore 锁 fail-open 改 fail-closed |
| 8 | 新增 4 张表 | **修订为 2 新 1 演进** | `backup_record` 已存在（演进加列）；新增 `backup_schedule`、`backup_settings`；**不建 `backup_task_state`**（运行态用 Redis+advisory lock，审计用 backup_record.status='running'） |
| 9 | 全新 12 条 API | **修订 → 增量式** | 现有 28 条路由大部分前端在用；新增任务化触发/settings/schedule CRUD/restore-plan，旧同步入口在前端切换后下线 |
| 10 | 前端 Vue3+PrimeVue 映射 | **保留（栈核实无误）** | Vue 3.5.34 / PrimeVue 4.5.5 / Tailwind 4.2.4 / vue-query 5.100.10；补充：复用现有 RestoreProgressBar 与轮询 composable，合并 3 套轮询实现 |
| 11 | 旧代码删除清单 | **修正** | 见 §4，真正要删的很少（前端孤儿/死代码）；v1 所列后端 8 个旧服务文件已不存在 |
| 12 | 测试集中在 M5 | **推翻 → 测试随阶段** | 每里程碑带测试与验收门；M3 验收门 = 历史备份还原回归（用现成 DR 测试库 `erp_backup_test`） |

---

## 1. 现状基线（v1 缺失的关键事实）

### 1.1 后端能力地图（`fastapi_app/services/backup/`）

| 能力 | 现状 | 位置 |
|------|------|------|
| 全量备份 | pg_dump→gzip→ZIP（database/filestore/config/redis/meilisearch + manifest.json：行数/SHA-256/MD5 指纹），pg_dump 不可用回退 JSON 纯 SQL 导出 | `orchestration/core.py:124-288`、`dump.py`、`json_backup.py` |
| 增量备份 | `updated_at` 系时间戳列比对（候选列见 `_constants.py:31`），变更行 JSON→ZIP，manifest 记 `base_timestamp` | `incremental.py:34-114` |
| 还原 | 预校验（ZIP 魔法数/manifest/解密/SHA-256）→ psql 重建库 或 JSON upsert → 组件并行恢复 → 重建连接池 → 缓存失效 → 校验；恢复前自动安全备份（保留 5 份） | `restore.py:99-294`、`orchestrator.py` |
| 一致性校验 | L0 全局校验和 / L1 行数比对 / L2 数据指纹（MD5 聚合）/ L3 主键抽样；**无 DDL 比对** | `verify/core.py:113-247` |
| 并发控制 | asyncio.Lock + PG advisory lock（备份 20240427 / 还原 20240426）+ 1800s 超时；还原另有 Redis 锁 `erp:restore_lock`（**Redis 故障时降级放行 = fail-open**） | `orchestration/core.py:49-97`、`restore.py:297-335` |
| 进度上报 | Redis（key 前缀 `erp:backup_progress:` / `erp:restore_progress:`，TTL 3600），前端轮询 `GET /progress/{task_id}` | `core/backup_progress.py` |
| 加密 | AES-256-GCM + PBKDF2（600k 迭代）；密钥优先级 用户密码 > env 密码 > env key > **随机生成（=备份不可还原，隐患）** | `crypto.py:33-68`、`core/backup_encryption.py` |
| 六个子系统 | cleanup（评分保留 30 天/50 个/增量链保护）、metrics（日 JSON）、alerts（SMTP+Webhook）、health_check（5 类）、policy（`backup_policy.json` CRUD）、recovery_test（`erp_backup_test` 独立库演练） | `cleanup/`、`metrics/`、`verify/health_check_service.py` 等 |
| 存储 | `BACKUP_DIR`（env，默认 `backups/server`），无运行时可配、无写入前空间门禁 | `_constants.py:15` |

### 1.2 API 与调度现状

- **28 条路由**（`/api/v1/backup/*`）：records 8、export 6、restore 6、validation 7；权限码
  backup_read/create/restore/delete（`_deps.py:37-98`，JWT 认证）。
- **手动备份是同步在请求内执行的**（`GET /export`、`POST /save`、`POST /save-incremental`）——全量耗时可达
  30 分钟（`BACKUP_OPERATION_TIMEOUT=1800s`），同步 HTTP 长请求在 Nginx/代理层极易超时，**这是「备份任务化」的真正论据**。
  还原已有异步形态（`async-import` / `async-restore-by-name` 返回 task_id），但用进程内 `asyncio.create_task`
  句柄集合，4 worker 间不可见。
- **调度 = ARQ**（Redis 队列，独立 worker 进程 `python -m arq fastapi_app.core.arq_app.WorkerSettings`），
  cron **硬编码**在 `core/arq_app.cron_schedules`：每日全量 02:00（timeout=1800）、增量 06/10/14/18/22、
  完整性巡检 03:00、清理 04:00。定时配置无 DB 持久化、无 UI。
- **审计**：AuditLogMiddleware 只审计写方法（POST/PUT/PATCH/DELETE），`GET /export`（下载整库备份）**不审计**。
- **部署形态**：uvicorn 多 worker（`UVICORN_WORKERS` 默认 4）+ ARQ worker 独立进程；本机即生产服务器。

### 1.3 前端现状（`frontend-vite/src/`）

- 双 Tab 页面（备份与恢复 / 备份记录）+ 完整性巡检横幅；还原链路完整（验证→危险确认→异步任务→进度条→结果），
  备份无任务进度（同步请求 + 按钮 loading）。
- 轮询 composable 有 **3 套**：`useRestoreProgressPolling.ts`（在用，800ms）、`useRestorePolling.ts`
  （仅类型被引用，函数死代码）、`src/composables/useBackupProgress.ts`（孤儿，无引用）。
- `api/backup.ts` 中 `/backup/schedule`、`/schedule/trigger`、`/backup/status` 三个调用已定义但**无组件使用**（死代码）。
- 无 SSE/EventSource 先例；有 WebSocket 先例（采购模块 `useWebSocket.ts` 含自动重连）。
- 菜单由后端权限表驱动（`permission` 表 `backup_manage` → `/backup`）。

### 1.4 现状问题清单（v2 要修的）

| 级别 | 问题 | 位置 |
|------|------|------|
| **P0** | 7 处惰性导入指向已删除模块，还原主干运行时崩溃 | 见 §0 表 |
| **P0** | 加密密码回退「随机生成」→ 备份文件事实上不可还原 | `endpoints/backup/_deps.py:112-142` |
| P1 | 手动备份同步执行，无任务化/进度/互斥反馈 | `export.py` |
| P1 | 定时配置硬编码，无 DB、无 UI | `core/arq_app.py:69-108` |
| P1 | 备份路径仅 env 只读，无可写性/空间预检门禁 | `_constants.py:15` |
| P1 | 还原锁 fail-open（Redis 故障时放行高危操作） | `restore.py:297-335` |
| P1 | 无维护模式：「执行期间系统停止写入」只是文案，无工程保障 | — |
| P1 | verify 无表结构（DDL）比对 | `verify/core.py` |
| P2 | 增量检测不到硬 DELETE | `incremental.py` |
| P2 | `GET /export` 下载不审计；异步还原句柄进程内不跨 worker | `audit_middleware.py`、`restore.py:275` |
| P2 | 磁盘上混存加密/非加密备份与孤儿 `.enc.meta`，加密策略无声明 | `backups/server/` |
| P2 | dump/incremental/restore/orchestrator/strategies 核心路径无测试 | `fastapi_app/tests/` |

---

## 2. 需求差距分析（原型六模块 × 现状）

| # | 需求 | 现状 | 差距（v2 工作量所在） |
|---|------|------|----------------------|
| 1 | 一键全量备份 | ✅ 有（同步、无进度） | 任务化（ARQ）+ task_id + 进度 + 互斥 409 |
| 2 | 增量备份 | ✅ 有（updated_at 比对） | 同上任务化；补 count/fingerprint 对账 |
| 3 | 定时备份 | ⚠️ 有（ARQ 硬编码 cron；trigger API 已有） | cron 落 `backup_schedule` 表 + CRUD API + 前端 UI |
| 4 | 路径配置 | ❌ env 只读 | `backup_settings` 表 + validate-path 预检 + 前端 UI |
| 5 | 一键还原 + 一致性校验 | ✅ 有（四层校验、安全备份、双锁、确认参数） | 修 P0 导入；加 `/restore/plan` 差异预览、维护模式、L4 DDL 比对 |
| 6 | 实时进度 | ⚠️ 仅还原有（800ms 轮询） | 备份接入同一 Redis 进度通道；（可选）SSE |

附加（原型有、v1 漏列）：概览四卡数据源 `/status` 增强（健康度聚合复用 health_check + stats）、备份记录表（已有 records API + 卡片 UI，按原型升级为表格）。

---

## 3. 修订后架构

```
┌─────────────────────────── 前端 (Vue3 + PrimeVue，按原型六模块重做) ───────────────────────────┐
│  概览四卡(轮询 /status) · 一键全量/增量(task_id+进度) · 定时配置(/schedule CRUD)              │
│  路径设置(/settings+validate-path) · 记录表格(/records) · 还原向导(plan→execute→报告)        │
│  进度 = 轮询 GET /progress/{task_id}（M4 可选升级 SSE）                                       │
└────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                 │ HTTP
┌────────────────────────────────▼───────────────────────────────────────────────────────────┐
│  FastAPI  /api/v1/backup/*（多 worker）                                                      │
│  ─ 只做：鉴权/参数校验/入队/查询 —— 不再同步执行长任务                                        │
│  ─ MaintenanceModeMiddleware：还原期间拒绝非备份域写请求                                     │
└──────────────┬─────────────────────────────────────┬───────────────────────────────────────┘
               │ enqueue_job                         │ 读进度
┌──────────────▼──────────────────┐   ┌──────────────▼─────────────────────┐
│  ARQ worker（唯一执行面）        │   │  Redis                             │
│  ├─ manual_full_backup_task ★新 │   │  ├─ 进度 erp:*_progress:*（现有）  │
│  ├─ manual_incr_backup_task ★新 │   │  ├─ 还原锁（fail-closed ★改）      │
│  ├─ scheduler_poller ★新(5min)  │   │  └─ 维护模式标志 ★新               │
│ │    └─ 读 backup_schedule 表   │   └────────────────────────────────────┘
│  ├─ auto_daily/incr/cleanup/…（现有 4 cron 语义迁入表）│
│  └─ 全部经 services/backup/ 编排 │
│     互斥 = PG advisory lock（跨进程真相源）            │
└──────────────┬──────────────────┘
               ▼
   PostgreSQL（数据源 + backup_record/schedule/settings）＋ 备份存储（BACKUP_DIR，settings 表可配）
```

核心原则：

1. **执行面收敛到 ARQ worker**：手动与自动备份/还原统一入队执行。API 进程不再跑长任务，
   `asyncio.create_task` 进程内句柄模式废弃。互斥由 advisory lock 保证（worker 内串行 + 跨进程互斥双保险）。
   注意 ARQ 默认 `job_timeout=600` 与全量 1800s 冲突，入队处显式传 `timeout=1800`（auto-daily 已有先例）。
2. **进度单一通道**：一切任务写现有 Redis 进度结构（`core/backup_progress.py`，8 备份/10 还原阶段），
   前端统一轮询 `/progress/{task_id}`。还原侧 800ms 轮询已验证够用。
3. **格式不动**：ZIP + manifest v2.0 原样保留；manifest 可加列（schema 快照、schedule_id），只增不改，
   旧包缺新字段走默认值。
4. **配置优先级**：`backup_settings` 表 > env（向后兼容）。路径写入前必须过 validate-path 预检。

---

## 4. 代码变更清单（替代 v1 删除清单）

### 4.1 P0 热修（立即，独立分支，当天可合）

1. 修 §0 表中 7 处惰性导入，改指包内新家；补一个「psql 还原路径冒烟」测试防回归。
2. 加密密码回退链去掉「随机生成」分支：显式配置密码/密钥或明确不加密，禁止静默随机（`_deps.py:112-142`）。

### 4.2 后端（`fastapi_app/`，全部为修改/新增，无整域删除）

| 变更 | 内容 |
|------|------|
| `tasks/backup_tasks.py` 增任务 | `manual_full_backup_task` / `manual_incremental_backup_task`（复用 `_do_auto_backup` 骨架，trigger_type=manual，写进度）；`scheduler_poller`（每 5 分钟读 `backup_schedule`，按 `last_run_at` 与 cron 判断到期入队，幂等靠 advisory lock per schedule） |
| `core/arq_app.py` | `cron_schedules` 中备份 4 项迁入 `backup_schedule` 表种子数据（保持 02:00/06-22/03:00/04:00 不变），注册 poller；auto 任务函数保留 |
| `services/backup/` 新模块 `settings_service.py` | 读写 `backup_settings`（单行）；`validate_path()`：绝对路径、盘符白名单、无 `..`、目录可写探测、`psutil.disk_usage` 空间 ≥ 阈值（复用 health_check 的 psutil 用法）、系统目录黑名单 |
| `services/backup/` 新模块 `restore_plan.py` | 差异预览：读目标包 manifest（行数/指纹）vs 当前库实时 count（复用 `verify/core.py` 工具），输出表级差异 + 影响汇总 —— 即原型向导第 2 步的数据源 |
| `verify/core.py` 增 L4 | 表结构比对：manifest 增 `schema` 快照（`information_schema.columns` 摘要），还原后逐表比对；旧 manifest 无此字段则跳过并标注 |
| `restore.py` | Redis 还原锁 fail-open → fail-closed；还原执行前置/清理维护模式标志 |
| `core/` 新增 `maintenance.py` + 中间件注册 | 维护模式（Redis 标志 + 兜底 DB 查询）：开启时非备份域写请求返回 503 `MAINTENANCE`，备份域 GET 放行 |
| `endpoints/backup/` | 新增 `actions.py`（POST /full、/incremental → 202 {task_id}）、`settings.py`（GET/POST /settings、POST /settings/validate-path）、扩 `records.py` 的 schedule CRUD、新增 POST /restore/plan；`export.py` 同步入口标记 deprecated（前端切换后删）；`GET /export` 下载补显式审计记录 |
| `shared_models/` + `migrations/` | 新表 `backup_schedule`、`backup_settings`；`backup_record` 加列（manifest 摘要 jsonb、schedule_id、加密标志）；Alembic 迁移一份 |

### 4.3 前端（`frontend-vite/src/`）

| 变更 | 内容 |
|------|------|
| `views/backup/` 按原型重做 | 六模块组件（OverviewCards / BackupActions / ScheduleConfig / PathSettings / BackupRecordTable / RestoreWizard），令牌按 DESIGN.md 映射 PrimeVue theme |
| 合并轮询 | 3 套 → 1 套 `useBackupTask.ts`（备份+还原共用，800ms，终态停止，404 容忍上限取自 useRestorePolling 的 MAX_NOT_FOUND=3） |
| 清理 | 删孤儿 `src/composables/useBackupProgress.ts`、`useRestorePolling.ts` 死函数（保留类型）、`api/backup.ts` 死绑定改接新 UI |
| 还原向导 | 复用 RestoreProgressBar/结果卡，向导化包装；危险确认沿用「输入 确认还原」三重屏障 |

---

## 5. API 增改清单

**新增**（均需 backup_create/backup_restore 权限，沿用 `_deps.py` 权限码）：

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/backup/full` | 202 `{task_id}`（ARQ 入队；互斥冲突 409 `{code:"TASK_RUNNING"}`） |
| POST | `/api/v1/backup/incremental` | 202 `{task_id, base_snapshot}` |
| POST | `/api/v1/backup/restore/plan` | `{filename}` → 差异预览（表级 count 对比 + 影响清单 + 加密/完整性预检） |
| POST | `/api/v1/backup/restore/execute` | 还原执行（`confirm=true`；开启维护模式 → 入队 → 完成自动关闭；替代 async-* 两接口） |
| GET/POST | `/api/v1/backup/settings` | 读取/保存路径与保留策略（POST 前置 validate） |
| POST | `/api/v1/backup/settings/validate-path` | 路径预检（可写/空间/合法性） |
| GET/POST/PUT/DELETE | `/api/v1/backup/schedule` | 定时任务 CRUD（替代硬编码 cron；trigger 接口保留） |

**保留**（前端在用，不动）：`/tables /export /save /save-incremental /list /records /restore-by-name
/restore-incremental /async-* /progress/{task_id} /validate /integrity-check /health /stats
/delete-by-name /ping /schedule(GET) /schedule/trigger`。
**下线**（M4 前端切换后删除）：`/save /save-incremental /async-import /async-restore-by-name /import`（同步还原入口）。
**增强**：`/status` 聚合健康度（复用 health_check + stats + 最近记录）供概览四卡。

---

## 6. 数据库变更（Alembic，一份迁移）

| 表 | 变更 | 关键列 |
|----|------|--------|
| `backup_record` | 演进 | + `manifest_summary`(jsonb：checksums/fingerprints 摘要)、`schedule_id`(FK 可空)、`encrypted`(bool)；现有列与索引不动 |
| `backup_schedule` ★新 | 定时配置 | id、name、task_type(full/incremental)、cron_expr、enabled、last_run_at、last_status、created/updated；种子 = 现有 4 条硬编码 cron |
| `backup_settings` ★新 | 系统设置（单行） | backup_dir、retention_days、max_count、encryption_mode(off/password/key)、updated_by、updated_at |

不建 `backup_task_state`：运行态以 Redis 进度 + advisory lock 为准，审计以 `backup_record.status='running'` 行为准。

---

## 7. 实施路线（修订）

| 阶段 | 内容 | 验收门（含测试） |
|------|------|------------------|
| **M0 热修**（0.5 天） | §4.1 两项 | psql 还原冒烟测试过；加密回退链单测过；生产分支当天合入 |
| **M1 备份任务化** | ARQ 手动任务 + /full /incremental + 409 互斥 + backup_record 迁移 + settings 表与 validate-path | 任务触发→进度到 100%→记录落库 e2e（对 `erp_backup_test` 库）；互斥并发单测；迁移可回滚 |
| **M2 调度 DB 化** | backup_schedule 表 + poller + CRUD API + 种子迁移 | 种子迁移后定时行为与现状等价（02:00/06-22/03:00/04:00）；poller 幂等单测 |
| **M3 还原强化** | restore_plan + 维护模式 + L4 DDL 比对 + fail-closed 锁 + execute 接口 | **历史备份还原回归：对 `backups/server/` 抽样（各代全量/增量/加密包）在 `erp_backup_test` 库全部还原+校验通过**；维护模式中间件单测 |
| **M4 前端落地** | 六模块组件 + 统一轮询 + 清理死代码；（可选）SSE | 对照原型走查六需求；还原向导三重屏障齐备；旧同步入口下线 |
| **M5 收尾** | /export 审计、磁盘加密策略声明与孤儿 `.enc.meta` 清理方案、文档、生产演练 | 演练报告；全量单测绿 |

风险控制：全程 feature 分支小步合入；**本机即生产**——M1/M3 的执行类验收只打 `erp_backup_test` 库，禁止对生产库跑还原；演练窗口由用户在 server_manager 中手动开（停写入 = 开窗）。

---

## 8. 风险与禁区

1. **禁止换格式/迁移历史备份文件**：`.bfp` 类新格式明确否决；manifest 只增字段不改语义。
2. **禁止在 API 进程跑长任务**：4 worker 部署下进程内锁/句柄/任务全部不可靠，一切经 ARQ。
3. **还原是高危域**：fail-closed、维护模式、恢复前安全备份（保留 5 份）三重保障缺一不可；还原演练只打测试库。
4. **加密策略必须显式**：不允许任何「随机密码」静默路径；settings 落地时声明当前磁盘混存状态的处理方式。
5. **ARQ job_timeout 陷阱**：全量任务入队必须传 `timeout≥1800`，否则默认 600s 会被杀。
6. **调度迁移等价性**：M2 种子必须与现 cron 逐条对齐，迁移后观察一周 `backup_record`（trigger_type=auto）无缺班。

## 9. 非目标（明确不做）

- 不重写 `services/backup/` 域、不新建 backup_center 包；
- 不做备份加密密钥自动轮换（policy 中 `key_rotation_days=90` 仅有配置无实现，另立项）；
- 不做 WAL 增量（现状为元数据占位，冻结）；
- 不引入 APScheduler 或任何新调度依赖；
- 不做异地/云端备份与多机拓扑。

---

*主理人 · 画统筹（Hua）| Phase 6 v2 修订（评审依据：services/backup、endpoints/backup、frontend backup、arq 调度、backups/server 生产实物的全量代码调查）| 待确认后从 M0 热修启动*
