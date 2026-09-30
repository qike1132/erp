# ERP 系统优化方案（2026-09-30）

> 依据：`docs/analysis/07_architecture_review_2026-09-30.md` 的问题清单（P0-1…P3-1）+ 本轮补充锚点实测。
> 原则：**每项都能验收、都能回滚、都不引入新基础设施**。凡是没有「一条命令能证明它成了」的改动，不进本方案。
> 复核声明：本轮对 07 号报告的部分结论做了二次核实，**有 4 条已过时/不准确**，集中列在文末第 9 节，避免重复劳动。

---

## 0. 一页速览

### 0.1 四条优化原则

1. **可靠性优先于整洁性**。这台机器上「备份不可信 / 看不到 / 回不去」的代价，远大于「代码不够优雅」。先把这三件事闭环，再谈结构。
2. **只做能验收的改动**。每项必须有一条可执行的验证命令。
3. **不引入新基础设施**。现有 5 个 NSSM 服务 + 单机内网。任何需要 Docker / K8s / 新中间件的方案，先回答「谁来运维」。当前 Prometheus 栈连运行体都没有，这就是答案。
4. **存量不动**。已上生产的迁移历史不动，已入库的数据不动，优化只往前加。

### 0.2 行动总表

按「影响 × 成本」排序。S 前缀 = 建议做，D 前缀 = 需单独决策。

| 编号 | 事项 | 为什么现在做 | 成本 | 验收 |
|---|---|---|---|---|
| **S1** | 备份异地副本 + 还原演练 | 备份与数据同盘 = 备份约等于没有。这是唯一「一旦发生就无法补救」的风险 | 0.5 天 | 主备份目录改名后，能从异地完整还原一次 |
| **S2** | 打开 /metrics + 巡检脚本 + 告警 | 当前对「服务死了 / 磁盘满了 / 备份停了」三类事故完全无感知 | 0.5 天 | 手动停 `erp-arq`，15 分钟内收到告警 |
| **S3** | `.env.production` 补全 + 关键项启动校验 | 覆盖 `.env` 会静默丢掉全部 `BACKUP_*`（含加密口令） | 0.5 天 | 用 `.env.production` 启动后加密备份仍是加密的 |
| **S4** | 备份 success 判据（表数比对 → partial） | 当前「备份成功」只等价于「进程没抛异常」 | 1 天 | 故意删一张表跑增量 → 结果为 partial 并报出表名 |
| **S5** | 前端发布保留回退副本 + rollback 脚本 | 当前发布成功后**没有**可回退版本 | 1 天 | 发布后 2 分钟内回到上一版本 |
| **S6** | 后端一键发布 / 回滚脚本 | 回滚靠人记步骤，且踩过双 nginx 的坑 | 1.5 天 | 完整演练一次回滚，期间无双 nginx |
| **S7** | 清理重复健康端点 + `api/v2` | 两套健康检查，探活那套还被 JWT 挡住 | 0.5 天 | 无 token `curl /api/health/live` 返回 200 |
| **S8** | 拆掉 `core/container.py` 服务定位器 | core 反向依赖 9 个 service，实际调用点只有 4 处 | 1 天 | AST 扫描 core→services 边 12 → 3 |
| **S9** | 前端路由守卫改完整路径匹配 | 只比对 path 第一段，跨模块 URL 可绕过菜单限制 | 0.5 天 | 非超管手输无权 URL 被重定向 + 单测覆盖 |
| **S10** | 剥 BOM（13 文件）+ 补 `alembic.ini` + 迁移图文档 | 仓库自带的审计框架自己 `ast.parse` 不过 | 0.5 天 | 全仓 `.py` 的 `ast.parse` 0 失败 |
| **S11** | 误提交文件清出索引 | `backups/` 17 个源码快照 + `static/uploads/` 24 张真实客户图在库里 | 0.5 天 | `git ls-files backups/` 为空 |
| **S12** | 移动端数据层与 PC 统一 | mobile 自建 interface / 字段映射，`useQuery=0` | 3-5 天 | mobile 复用 `src/api` 与 `src/types` |
| **D1** | 历史重写清除大文件（`.git` 519MB） | 需要 force-push，影响所有协作者 | 独立立项 | — |

### 0.3 时间轴

```
本周（< 1 天，零风险）        S1 异地备份 · S2 巡检告警 · S3 配置止血
第 1-2 周（可靠性闭环）        S4 备份判据 · S1 正式化 + 恢复演练
第 3-4 周（可逆性）            S5 前端回滚 · S6 后端回滚 · S7 双轨清理
第 2 个月（结构债）            S8 拆容器 · S9 路由守卫 · S10 卫生 · S11 清索引
第 3 个月起（需产品决策）      S12 移动端统一 · D1 历史重写
```

---

## 1. 先做的三件事（本周内，合计 < 1 天，零风险）

这三件事的共同点：**不改一行业务代码，不动数据库，失败可原地撤销**，但能立刻消掉三个最大的「看不见」。

### S1 异地备份（0.5 天）

**现状（实测）**
- 备份落在 `D:\\erp_system\\backups\\`，与数据库数据同盘；`backups/` 419MB / 3687 文件。
- 最新加密备份 2026-09-30 10:05；RPO ≈ 1h（`BACKUP_INCREMENTAL_CRON=0 */1 * * *`、`BACKUP_FULL_CRON=0 2 * * *`、保留 30 天）。
- `docs/reports/2026-08-23-backup-benchmark-report.md` 已把「备份与数据同盘、无异地」列为最大灾备风险（P1-8），并指出还原为 DROP DATABASE + 流式导入、非事务、`ON_ERROR_STOP=0`（P0-5）。
- C 盘仅剩 33.1GB（nginx / nssm / Redis / PG 数据都在 C）。

**方案 A（推荐，当天可完成，零新依赖）**
1. 在一台常开的内网机 / NAS 上建共享，例如 `\\\\nas\\erp-backup`。
2. 加 Windows 计划任务（每 30 分钟）：
   ```
   robocopy D:\\erp_system\\backups \\\\nas\\erp-backup /E /R:2 /W:5 /NP /LOG+:D:\\erp_system\\logs\\robocopy-backup.log
   ```
   > **必须用 `/E`，不要用 `/MIR`**。`/MIR` 会镜像删除——远端若是唯一副本，本地误删会被同步过去。若要节省空间，宁可定期人工清理远端旧文件。
3. 每月一次恢复演练：从 `\\\\nas` 取最新备份，还原到测试库。仓库已内置测试库配置键（`BACKUP_TEST_DB_HOST/PORT/NAME/USER/PASSWORD`、`BACKUP_CLEANUP_TEST_DB`、`BACKUP_TEST_SAMPLE_RATE`），演练不需要新写代码。

**方案 B（后续演进，先确认基础设施存在）**
仓库已有 `requirements/s3.txt` 与 `S3_*` 配置键，若内网确有 MinIO/S3，可把 `BACKUP_STORAGE_LOCATION` 切过去。
> ⚠️ **先验证再设计**：Prometheus / Grafana / OTel / Promtail / Alertmanager 的配置文件全部使用 Docker 主机名（`app:5002`、`nginx:80`、`loki:3100`），而仓库 0 个 docker-compose、Dockerfile 只存在于 `_qa_tmp` 夹具——说明这类「文档里的基础设施」未必真实存在。**任何依赖新基础设施的方案都要先 `Test-NetConnection` 验证。**

**权衡**：A 当天完成、无运维负担，但依赖一台常在线机器；B 更规范但引入新依赖与新故障点。先 A，把 B 写进 ADR 备查。

**验收**
- robocopy 日志末尾无错误，远端文件数与主目录一致。
- **还原演练成功**：从异地副本还原到测试库，行数与主库一致。
- 把 `D:\\erp_system\\backups` 临时改名后，异地副本仍完整（证明不是硬链接 / 符号链接）。

**回滚**：删除计划任务即可，无副作用。

### S2 打开可观测性（0.5 天）

**现状（实测）**
- `/metrics` 注册在 **app 层**：`fastapi_app/core/health.py:200` `@app.get("/metrics")`。生产要求 `METRICS_BEARER_TOKEN`，未配置即 **503 fail-closed**（`:209-211`）；`.env` 里没有任何 `METRICS_*` 键 → **该端点当前不可用**。
- 生产实际使用的 `config/nginx-windows.conf` 有 `location /api/health`（`:130`）与 `/nginx-health`（`:167`），**没有 `/metrics`**。
- `config/nginx.conf`（Docker 版，**未部署**）里反而有 `/metrics`（`:152`）、`/grafana/`（`:165`）、`/prometheus/`（`:175`）——又一处死配置。
- 应用日志 `TimedRotatingFileHandler(..., when="midnight", backupCount=3)`（`core/logger.py:67-70`）→ **只留 3 天**。
- 盲区：无服务存活指标、无磁盘水位、ARQ 心跳未进 `/api/health`。

**方案（推荐 B：先做进程内巡检，不引入 Prometheus）**

1. 配 `METRICS_BEARER_TOKEN`（`.env` 与 `.env.production` 都加），验证：
   ```
   curl -H "Authorization: Bearer <token>" http://127.0.0.1:5002/metrics
   ```
2. `config/nginx-windows.conf` 增加 `/metrics` 路由，**只允许回环 / 指定内网网段**（`allow 127.0.0.1; deny all;`），不要直接暴露。
3. 新增 `scripts/ops/watchdog.py`，Windows 计划任务每 5 分钟执行，检查六项：
   - 5 个 NSSM 服务状态（erp-web / erp-prod / erp-arq / erp-redis / erp-redis-broker）
   - `GET http://127.0.0.1:5002/api/health` 与 `/api/health/ready` 的 status
   - `backups/` 下最新文件时间：**超过 90 分钟未更新即告警**（RPO 是 1h，留 50% 余量）
   - `C:` / `D:` 剩余空间（低于 `BACKUP_MIN_FREE_SPACE_GB` 或 20% 即告警）
   - ARQ worker 探针（`core/health.py:279` 已有严格探针，离线即 503，语义已文档化于 `:302-303`）
   - 告警通道：**复用已有的** `BACKUP_ALERT_WEBHOOK_URL` / 邮件配置与 `notification_service`，不要新建通道
4. 日志保留 3 天 → 14 天（`core/logger.py:70` `backupCount=3` → `14`）。
5. **死配置归档**：把 `config/prometheus.yml`、`alertmanager.yml`、`alert_rules.yml`、`otel-collector.yaml`、`promtail.yml`、`config/grafana/` 移到 `config/unused/`，或在 `config/README.md` 顶部注明「**未部署，勿据此判断监控现状**」。
   > 这一步的目的不是整洁，而是**防止下一次审计再把死配置当成真实监控**——07 号报告的第一版就差点这么判断。

**权衡**：B 与内网现实匹配、当天可完成、覆盖三类最要命的盲区；A（真跑 Prometheus + windows_exporter）更完整，但要新装 3 个服务并长期运维。**先 B，等真有容器平台再上 A。**

**验收**：`nssm stop erp-arq` → 15 分钟内收到告警；`nssm start erp-arq` → 告警恢复。

### S3 配置漂移止血（0.5 天）

**现状（实测）**
`.env` = 106 键 / `.env.example` = 115 键 / `.env.production` = 37 键 / `config/.env.production` = 35 键。
**`.env` 有而 `.env.production` 缺失 82 个键**，其中：

- **全部 `BACKUP_*`（约 70 个）**：`BACKUP_DIR`、`BACKUP_ENCRYPTION_PASSWORD`、`BACKUP_ENCRYPTION_ENABLED`、`BACKUP_ENCRYPTION_ALGORITHM`、`BACKUP_ENCRYPTION_KEY_PATH`、`BACKUP_FULL_CRON`、`BACKUP_INCREMENTAL_CRON`、`BACKUP_STORAGE_LOCATION`、`BACKUP_RETENTION_DAYS`、`BACKUP_*_THRESHOLD`、`BACKUP_ALERT_*`、`BACKUP_TEST_*`、`BACKUP_VALIDATE_*` …
- 另有 `ALLOWED_HOSTS`、`API_URL`、`APP_ENV`、`ASYNC_DATABASE_REPLICA_URL`、`CACHE_L1_BROADCAST_ENABLED`、`FASTAPI_DEBUG`、`OTEL_ENABLED`、`PG_SUPER_PASSWORD`、`UVICORN_WORKERS`、`WS_ALLOWED_ORIGINS`

**危害链**：生产部署若按 `.env.production` 覆盖 `.env` → `BACKUP_ENCRYPTION_ENABLED` 与 `BACKUP_ENCRYPTION_PASSWORD` 双双回落默认值 → **备份从加密静默退化为明文 / JSON**，而 `BACKUP_DIR` 也回落到默认路径。整个过程不报错。

**现状校验强度（实测）**：`core/config.py:124` `class Settings(BaseSettings)`，`:196` `__init__` 里只校验：SECRET_KEY 非空（`:198-200`）、ALGORITHM ∈ {HS256, RS256, ES256}（`:202-206`）、生产环境 SECRET_KEY ≥ 32 字符（`:214-217`）。`:279` `SettingsConfigDict(..., extra="ignore")` 会**静默吞掉拼错的键**。**无任何 `BACKUP_*` 校验。**

**修法**
1. 以 `.env.example`（115 键）为唯一权威模板，重生成 `.env.production` 全量骨架（值留空 + 注释标注必填）。
2. `core/config.py` 的 `:196 __init__` 里加最小必填校验（**生产环境 fail fast，不要静默降级**）：
   - `BACKUP_ENCRYPTION_ENABLED=true` 时 `BACKUP_ENCRYPTION_PASSWORD` 必须非空 → 否则 raise
   - `BACKUP_DIR` 必须存在且可写 → 否则 WARNING，生产 raise
   - 生产环境 `BACKUP_STORAGE_LOCATION` / `BACKUP_FULL_CRON` / `BACKUP_INCREMENTAL_CRON` 缺失 → raise
   - 保留 `extra="ignore"`，但启动时打印一条「未识别的环境变量」清单（抓拼写错误）
3. 新增 `scripts/ops/check_env_drift.py`：比较 `.env.example` 与 `.env.production` / `config/.env.production` 的键集合，差集非空则退出码 1。挂进 CI 或 pre-commit。
4. **收敛配置来源**：明确「生产只读一份 `.env`」，`.env.production` 与 `config/.env.production` 二选一保留，另一份删除或改名为 `.example`。

**验收**：把 `.env.production` 拷成 `.env` 启动 → **若缺加密口令则启动失败**（而不是静默跑起来）；补齐后加密备份产物文件头不是 `PK` / 明文 JSON。

**回滚**：校验逻辑用环境变量开关（如 `STRICT_CONFIG_CHECK=false`）临时关闭。
> ⚠️ 严格模式上线前**必须先跑一次 dry-run 打印校验结果**，确认生产 `.env` 里加密口令是齐的，否则重启会直接失败。

---

## 2. 阶段一（第 1-2 周）：把「备份能信」闭环

### S4 备份 success 判据（1 天）

**现状（实测，注意——部分已修，不要重复做）**

✅ **已修**：
- **恢复路径的 partial 语义已实现**：`json_backup.py:368` `'status': 'ok' if not result['errors'] else 'partial'`；`:484-485` 批次错误记 `{'status': 'partial', 'inserted': ..., 'batch_errors': ...}`；`:547` 汇总 `'database': {'status': 'ok' if not errors else 'partial', 'total_inserted': ...}`；`:552` 注释「必须进入 errors 让端点报 partial，避免用户误以为已精确回滚到备份点」。
- **行级降级跳过已实现**：`json_backup.py:237` `skipped = []`、`:238` `fatal_errors: dict[int, str] = {}`、`:274` `skipped.append(row)`、`:283` `if fatal_errors:`、`:294` `return skipped`。
- **`backup_schedule.last_status` 的终态落定已实现**：`core/arq_callbacks.py:42` `on_job_end` → `:46` `_mark_schedule_outcome(ctx, STATUS_SUCCESS)`；`:65` `on_job_failed` → `:100` `STATUS_FAILED`；`core/arq_app.py:202-203` 注册钩子。**07 号报告里「last_status 恒为 running」的结论已过时。**

❌ **未修（本项要做的）**：**备份路径的 success 判据**
- `services/backup/records.py:113` `status: str = 'success',` —— **默认值就是 success**，调用方不传即成功。
- `services/backup/orchestration/core.py:292` `'table_count': len(table_stats)` —— 只是把**统计到的**表数写进 manifest，**没有与库内实际表数比对**。
- `tasks/backup_tasks.py:114`/`:127` 直接透传 manifest 的 `table_count`，`:125` 固定 `'status': 'ok', 'type': 'full'`。

→ 结论：**当前「备份成功」只等价于「进程没抛异常」。**

**修法**
1. `orchestration/core.py` 在 `:292` 附近取 `information_schema.tables` 的当前表数（排除 `alembic_version` 等），与 `len(table_stats)` 比对：
   - 相等 → `status='success'`
   - 不等 → `status='partial'`，把缺失表名（最多 10 个）写入 remark
2. `records.py:113` 把 `status: str = 'success'` 改为**必填**（去掉默认值），强制所有调用方显式声明状态。
3. `records.py:639-643` 的文件系统同步分支（`table_count=fs_entry.get('table_count'), status='success'`）与 `:668-677` 的僵尸修正分支（`if r.status == 'running' and r.filename and r.filename in fs_filenames: r.status = 'success'`）要区分「**文件存在**」与「**内容完整**」：僵尸修正应改为 `'unknown'` 并在 remark 标记为推断，而不是直接判 success。
4. `backup_tasks.py:125` 的 `'status': 'ok'` 改为透传 orchestration 返回的真实 status。
5. 增量备份：确认 `query_table_rows` 的异常会进 `errors` 并让上层变 partial。
   > ⚠️ **历史坑**：asyncpg 错误在 Python 侧的类型是 `sqlalchemy.exc.DBAPIError`（`.orig` 才是 `asyncpg.Error`），**不是 `DataError`**。写 `except DataError` 会永远漏捕，使回退分支变成死代码——这正是「增量备份静默漏表」的成因。
6. 加三方一致性自检：manifest.table_count ↔ record.table_count ↔ 磁盘文件内实际表数，不一致即告警。

**验收**：故意 `DROP TABLE` 一张业务表 → 跑一次增量备份 → `backup_record.status == 'partial'` 且 remark 里有表名；恢复该表后回到 success。

**回滚**：纯增量判据，出问题可把默认值改回 `'success'` 并关掉比对。

### S1′ 异地备份正式化 + 恢复演练（第 2 周，0.5 天）

在 S1 跑通两周后：
- 把 robocopy 计划任务写进 `docs/runbooks/service-lifecycle.md`。
- 固化「每月 1 次恢复演练」为日历项，演练记录归档到 `docs/reports/`。
- 确认 `BACKUP_TEST_DB_*` 配置齐备（这依赖 S3 的配置补全）。

**为什么必须演练**：`docs/reports/2026-08-23-backup-benchmark-report.md` P0-5 已指出还原是 DROP DATABASE + 流式导入、**非事务、`ON_ERROR_STOP=0`**。这意味着**还原中途失败会留下半库状态且不报错**。不演练，就不知道 RTO 是 20 分钟还是 4 小时。

---

## 3. 阶段二（第 3-4 周）：可逆性

### S5 前端发布保留回退副本（1 天）

**现状（实测）**：`frontend-vite/scripts/swap-dist.mjs`（99 行）
- `:51-54` dist-new 缺 `index.html` 则拒绝交换；`:57` 先清理上次遗留 dist-old。
- `restoreDist()`（`:60-69`）rename 优先、失败则 cp 递归兜底。
- `:8-19` 记录了 EPERM 根因：vite dev server 的 chokidar watcher 持有 dist-new 句柄；vite 的 `resolveChokidarOptions()` 只在 `emptyOutDir` 为真时把 `build.outDir` 追加进 ignored，而 `--outDir dist-new` 是 CLI 参数故被忽略；修复 = `vite.config.ts` 的 `server.watch.ignored` 已显式排除 dist-new/dist-old/dist-old-swap/dist_prev_*（ignored 是**追加**语义）。
  > **改暂存目录名必须同步加那一行，否则 EPERM 复发。**
- **`:94-97` 交换成功后立即 `await rm(distOld, { recursive: true, force: true })`** → 发布成功即无可回退副本。脚本注释自认这一点，并给出替代做法 `cp -r frontend-vite/dist backups/frontend-dist-$(date +%Y%m%d-%H%M%S)`。
- `package.json:13` `build:atomic = vue-tsc -b && vite build --outDir dist-new --logLevel info && node scripts/swap-dist.mjs`

**修法**
1. 在 `swap-dist.mjs` 的 `:96` 删除动作**之前**，先把 dist-old rename 成 `dist_prev_<YYYYMMDD-HHmmss>`（rename 比 cp 快且原子），只保留最近 3 份。
2. 新增 `frontend-vite/scripts/rollback-dist.mjs`：列出 `dist_prev_*`，把选中那份 rename 回 `dist`（原 dist 先挪成 `dist_broken_<ts>`），并校验 `index.html` 存在。
3. `package.json` 加 `"rollback": "node scripts/rollback-dist.mjs"`。
4. 把 `dist_prev_*` / `dist_broken_*` 加进 `vite.config.ts` 的 `server.watch.ignored`（**关键**）与 `.gitignore`。
5. 顺手清掉残留的 `dist-old-swap`、`dist_prev_*` 目录。

**验收**：`npm run build:atomic` → `npm run rollback` → `dist/index.html` 引用的构建哈希回到上一版；全过程 < 2 分钟。
**回滚**：脚本可删，dist 结构不变。

### S6 后端一键发布 / 回滚（1.5 天）

**现状（实测）**
- CI **不部署**：`.github/workflows/ci-cd.yml:281-302` 明示 2026-09-24 删除 deploy job（内网机不可达）。
- P6 部署流水线（DeployEngine / DeployHistory）**只存在于** `docs/designs/2026-08-22-deploy-pipeline-p6-design.md`，`server_manager/` 内 grep 无实现。
- `docs/runbooks/service-lifecycle.md:301` 记录 swap 成功后不留回滚副本。
- 回滚需**先禁用 erp-web 自启防双 nginx**（runbook §5.2c）。
- 本地门禁弱于 CI：pre-commit 未安装，只剩 hook 前 3 层。
- 当前分支 `feat/production-cockpit-pc`，HEAD `ace65501`「feat(production): 生产页重构为一屏驾驶舱 + 明细抽屉」，**工作区有 2 个脏文件**（发布前需先处理）。

**修法**
1. 发布前打 tag：`git tag deploy-YYYYMMDD-HHmm`。
2. 新增 `scripts/ops/deploy.py`：
   - 前置：`git status --porcelain` 必须为空
   - 记录当前 revision 到 `logs/deploy-history.jsonl`
   - `alembic upgrade head`（**注意：仓库没有 `alembic.ini`**，需先补，见 S10）
   - `nssm restart erp-prod` / `erp-arq`（顺序按 runbook）
   - 健康等待：轮询 `/api/health/ready` 直到 200 或超时 60s，超时即判定发布失败并提示走 rollback
3. 新增 `scripts/ops/rollback.py`：
   - 入参：tag 或 `deploy-history.jsonl` 里的一条记录
   - **第一步先 `nssm stop erp-web`**（防双 nginx 踩坑）
   - `git checkout <tag>` → `pip install -r requirements.txt` → `alembic downgrade <target>`（若涉及迁移）
   - `nssm start erp-web` → 健康检查
4. 把发布 / 回滚步骤重写进 `docs/runbooks/service-lifecycle.md`，替换掉现在靠人记的版本。

**验收**：完整演练一次——发布一个无害改动（例如改 `APP_VERSION`），用 `rollback.py` 在 10 分钟内回到上一版，且期间 nginx 未出现双实例。
**回滚**：脚本是纯增量，删掉不影响现有流程。

> ⚠️ **依赖**：回滚涉及 `alembic downgrade`。现有 99 个迁移里 `downgrade()` 是否真正可用需逐个确认；不可用的迁移只能走「还原备份」路径——这又回到 S1 / S4。**先做 S1、S4 再做 S6，顺序不能反。**

### S7 双轨清理（0.5 天）

**现状（实测）**
- **健康检查两套**：
  - 真实探针注册在 **app 层**（`core/health.py:79` `register_health_routes(app)`，`main.py:391` 调用）：`/api/health`（`:82`，用 `_get_optional_user` 可选鉴权，未登录返回公开数据）、`/metrics`（`:200`）、`/api/health/live`（`:218`）、`/api/health/ready`（`:226`）。
  - 重复的一套在 `api/v1/endpoints/auxiliary.py:123-151`：`/health`（`:126`）、`/ready`（`:135`）、`/healthz`（`:141`）、`/readyz`（`:147`）四个裸函数，挂在 `api/v1/router.py:186-191` 的 `auxiliary_router` 上，**前缀 `/aux` 且带 router 级 `Depends(get_current_user_id)`** → **探活要 JWT，外部监控根本用不了**。
- **`api/v2` 只接了一个端点**：`api/v2/router.py`（29 行）、`versioning.py`（14 行）、`endpoints/dashboard.py`（149 行）；`main.py:395` `app.include_router(api_v2_router, prefix="/api")`。而 v1 也有 dashboard。
- 另：`monitoring_router` 与 `auth_router` 是唯二无 router 级鉴权的（auth 设计如此；monitoring 内部单点声明）。

**修法**
1. 删除 `auxiliary.py:123-151` 的 4 个端点，以及 `HealthCheckResponse`（`:23-25`，确认无其他引用后删）。
   > ⚠️ **不能整文件删**——同文件 `:153` 起还有 16 个真实业务端点：`/cache/stats`、`POST /cache/clear`、`/product-search`（`:182` 用了 `get_product_search_service`）、`/product-available-stock`、`/inventory-logs/{product_id}`、`/available-stockins`、`/stockin-info/{stockin_id}`、`/available-shipment`、`DELETE /stockout|stockin|customer|supplier/{id}`、`POST /batch-submit-orders|stockins|stockouts`、`/system/stats`。
2. 确认 `nginx-windows.conf:130` 的 `location /api/health` 指向真实探针（**是**）——探活链路本来就通，删掉重复端点不影响任何现有调用方。
3. `api/v2` 二选一：
   - **方案 A（推荐）**：删除 `api/v2`（29+14+149 行）与 `main.py:395` 的挂载，把「为什么暂不做版本化」写成 ADR。
   - **方案 B**：保留 v2，但明确它只服务 dashboard 的下一版契约，写 ADR 说明 v1/v2 并行期限。
   **权衡**：A 减少一条并行契约路径；B 保留演进空间但要维护两套。v2 当前只有 1 个端点，**A 的信息损失几乎为零**。

**验收**：无 token `curl http://127.0.0.1:5002/api/health/live` 返回 `{"status":"alive"}`；`grep -rn "healthz\|readyz" fastapi_app/api/` 为空。
**回滚**：单 commit revert。

---

## 4. 阶段三（第 2 个月）：结构债

### S8 拆掉服务定位器（1 天）

**现状（实测，删除成本极低）**
- `core/container.py` 反向 import **9 个 service**（占 `core→services` 12 条边中的 9 条）：`backup.cleanup.service`、`backup.metrics.alert_service`、`backup.metrics.service`、`backup.orchestration.policy_service`、`backup.orchestration.recovery_test_service`、`backup.verify.health_check_service`、`customer_search_service`、`product`、`product_search_service`。
- **实际调用点只有 4 个生产文件**：
  - `services/customer_service.py:63-64`（`get_customer_search_service`）
  - `services/bom_service.py:978-979`、`services/product_service.py:402-403`（`get_product_search_service`）
  - `api/v1/endpoints/auxiliary.py:182-183`（`get_product_search_service`）
  - `api/v1/endpoints/purchase_center/role_routes.py:22` + `:74/:86/:99/:111`（`get_role_service`）
- **9 个 getter 里 6 个（全部 `get_backup_*` 系列）零调用者。**
- 唯一测试用户：`fastapi_app/tests/test_global_role.py:142`/`:146`/`:151`（`container.override` / `reset`）。

**修法（推荐 A：直接删除）**
1. 4 个调用点改成直接 import 并实例化——这些文件本来就已 import service 层，改动是机械的。
2. 删除 `core/container.py` 与 6 个零调用 getter。
3. `test_global_role.py` 改用 FastAPI 的 `app.dependency_overrides` 注入 fake，替代 `container.override`/`reset`。
4. **方案 B（备选）**：保留 container，把 getter 改成函数内惰性 import，消除**模块级**反向依赖。成本更低，但保留服务定位器反模式。

**权衡**：A 彻底消除倒置，成本 1 天；B 半天但留下反模式。**推荐 A** —— 调用面只有 4 处，这是少见的「反模式可以便宜删掉」的情况。

**验收**：`grep -rn "core.container" fastapi_app/` 为空；AST 扫描 `core→services` 边从 12 降到 3。
**回滚**：单 commit revert。

### S9 前端路由守卫（0.5 天）

**现状（实测，`frontend-vite/src/router/index.ts`）**
- 守卫在 `:161-203`；`:184` 只对 `!authStore.user.is_super` 生效；`:185-193` navSections 未加载时 `await` 而非直接拦（fail-closed 意图，注释明确）。
- **`:195` `const targetPath = '/' + to.path.split('/').filter(Boolean)[0]`** —— 只取第一段。
- **`:197` `/dashboard`、`/notifications`、`/` 无条件放行**。
- 菜单由后端下发（`stores/auth.ts:127` → `api/dashboard.ts:66` → `endpoints/dashboard.py:73`），前端按 `permission_codes` 过滤（`auth.ts:219-229`）。
- 前端测试覆盖：router **0/1**。

**危害**：只比对第一段意味着「有 `/purchase` 权限」就等于「能进 `/purchase` 下所有子页面」，即使菜单没给。
> 必须说清：**这不是安全边界**。后端 32/34 个 router 带 router 级 `Depends(get_current_user_id)`，越权请求会被后端 403 拦住。这项修的是体验与审计一致性，不是漏洞。

**修法**
1. `:195` 改为完整路径匹配：`const allowed = allowedPaths.some(p => to.path === p || to.path.startsWith(p + '/'))` —— 保持「父路径授权覆盖子路径」语义，但不再是模块级。
2. `:197` 的白名单改为显式 `meta: { public: true }` 标记，而不是硬编码三个字符串。
3. 加 vitest 单测覆盖守卫：无权限路径被重定向、navSections 未加载时的行为、super 用户直通。

**验收**：非超管账号手输一个未授权子路径 URL → 被重定向到 `/dashboard`；单测通过。

### S10 卫生：BOM / alembic.ini / 迁移图（0.5 天）

**现状（实测）**
- **BOM（13 个 .py）**：带 UTF-8 BOM 导致 `ast.parse` 报 `SyntaxError: invalid non-printable character U+FEFF line 1`：
  - `scripts/prod_audit/` 下 8 个：`__init__.py`、`base/issue_builder.py`、`base/layer_base.py`、`config_loader.py`、`evidence_archiver.py`、`exceptions.py`、`layers/__init__.py`、`orchestrator.py`
  - `tests/qa/__init__.py`
  - `_ops/audit_scratch/` 下 4 个：`_probe_tables.py`、`_probe_token.py`、`_probe_users.py`、`_tmp_env_probe.py`
  > **仓库自带的审计框架，自己解析不过自己。**
- **无 `alembic.ini`**（本轮实测确认不存在）→ `alembic` 命令必须靠脚本拼 `script_location`，无法直接 `alembic current`。
- **迁移图**：99 个 revision、**单一 head**（`pg_standalone_060_fix_updated_at_varchar_columns`）、**4 个 root**（`add_product_factory`、`add_product_price`、`add_pp_composite_idx`、`pg_standalone_001`）、6 个 merge revision。迁移文件**零业务代码泄漏**（migrations 导入 fastapi_app 的次数 = 0）。

**修法**
1. 批量剥 BOM：python 读 bytes，去掉前 3 字节 `EF BB BF` 后以 UTF-8 重写（13 个文件）。
2. 加 CI / pre-commit 检查：`.py` 不得以 BOM 开头。
3. 补 `alembic.ini`（`script_location = migrations`，`sqlalchemy.url` 从环境变量取），让 `alembic current/upgrade` 直接可用。
4. **不动已上生产的迁移历史**。只加 `migrations/versions/README.md` 记录 4 个 root 的来历与 merge 图，并加 CI 检查「revision graph 单 head 且 root 数不增」。
   > ⚠️ 解析迁移图**必须用 alembic `ScriptDirectory`**（或兼容 `AnnAssign` 的 AST）。朴素 AST 只认 `ast.Assign`，会得出「5 roots / 4 heads / dangling」的纯解析伪影。

**验收**：全仓 `.py` 的 `ast.parse` 0 失败；`alembic current` 可直接运行。**零风险。**

### S11 误提交文件清出索引（0.5 天）

**现状（实测）**：`git ls-files` = 2277；其中 `backups/` **17** 个（源码快照）、`static/uploads/` **24** 个（真实客户图，含 `customer-sampling`）。工作树干净，这些文件已被 `.gitignore` 忽略但仍被跟踪。

**修法（两步，第二步风险高需独立立项）**
1. **只清索引（低风险，立即做）**：
   ```
   git rm -r --cached backups/ static/uploads/
   ```
   + 确认 `.gitignore` 覆盖 + 提交。**文件仍在磁盘上，功能不受影响。**
2. **清历史（高风险，独立立项 D1）**：用 `git filter-repo` / BFG 从全部历史剔除这些 blob，随后 force-push。当前 `.git` 519MB，清理后应显著缩小。**必须先确认所有协作者能重新 clone。** 这是本方案里唯一需要 force-push 的操作。

**验收**：`git ls-files backups/` 与 `git ls-files static/uploads/` 均为空；服务重启后上传 / 备份功能正常。
**回滚**：第 1 步可 revert。

---

## 5. 阶段四（第 3 个月起，需产品决策）

### S12 移动端数据层统一（3-5 天）

**现状（实测）**：42 个 mobile `.vue` 只用 `M*` 组件，不引用 `components/ui/`；`MPurchaseView.vue:109-121` 自声明 interface、`:134` 硬编码 `per_page 50`；`MProductView.vue:79-96` 自建字段映射；**mobile 端 `useQuery = 0`**（PC 端 30 处），两端缓存策略不一致；`mobile→views` 仅 2 处引用。前端测试覆盖 mobile **1/43**。

**两个选项**
- **A. 数据层统一（3-5 天）**：mobile 改用 `src/api/*.ts` 与 `src/types`，删掉自声明 interface 与字段映射，补 `useQuery`。**不减少文件数**，但消除「同一后端字段两处映射」的漂移源。
- **B. 功能面收敛（1 周，需业务确认）**：移动端只保留「审批 + 查询」两类只读场景，其余引导到 PC。**大幅减少维护面**，但改变用户习惯。

**权衡**：A 是纯技术收益、无业务风险；B 收益更大但需要业务方拍板。**推荐先 A，B 单独立项。**

**验收（A）**：`src/mobile/views/` 里不再有对后端 DTO 的重复 interface 声明；mobile 与 PC 调用同一批 api 函数。

---

## 6. 明确不做的事（以及理由）

| # | 不做 | 理由 |
|---|---|---|
| 1 | **不拆微服务** | 1277 个 `.py` 的模块化单体，34 个 router **零孤儿**、services 按域分包、跨域边极少（最多的是 `order→notification` 6 条）。拆开要付分布式事务、跨进程调试、5 个 NSSM 变 15 个的代价——**而这台机器连「一键回滚」都还没有**。收益为负。 |
| 2 | **不上 K8s / 不引入 Docker** | 单机内网、5 个 NSSM 服务。现在连 Prometheus 都跑不起来（配置全是 Docker 主机名），先解决「看得见」再谈编排。 |
| 3 | **不引入消息队列替代 ARQ** | 备份 / 导入这类任务用 ARQ 够用，且已有 `arq_callbacks` 的死信 + 告警链路。 |
| 4 | **不重写前端** | Vue 3 + TS 分层健康：`views→api` 138 条边、`views` 内 0 处直接 axios。全图只有一个环（`stores/auth.ts ↔ stores/patternRoom.ts`），且已用动态 import 打破。 |
| 5 | **不追 100% 测试覆盖** | 后端 `tests` 144 + `fastapi_app/tests` 151 个文件；前端 115/556 模块。**优先补 0 覆盖的高风险面**：login（0/6）、approval（0/6）——入口与关键业务动作。 |
| 6 | **不动生产迁移历史** | 4 个 root 是历史遗留，合并它们没有任何运行时收益，却要冒改生产迁移的风险。只往前加约束。 |
| 7 | **不做「多地多活 / 双主」** | 在 S1（异地备份）+ S4（成功判据）+ S6（回滚）做完之前，谈高可用是跳过基础。 |

---

## 7. 度量：优化前后对照

| 指标 | 现在 | 目标 | 验证方式 |
|---|---|---|---|
| 备份异地副本数 | 0 | ≥ 1 | robocopy 日志 + 还原演练 |
| 「备份成功」的含义 | 进程未抛异常 | 表数一致才 success，否则 partial | 删表跑增量 → partial |
| 可观测盲区 | 服务存活 / 磁盘水位 / 备份停摆 **全盲** | 3 类事故 15 分钟内告警 | 停 `erp-arq` 验证 |
| `/metrics` 可用性 | 503（无 token） | 200（Bearer） | curl |
| 前端回滚耗时 | **无回滚副本** | < 2 分钟 | rollback 演练 |
| 后端回滚耗时 | 人工数小时（靠 runbook 手记） | < 10 分钟 | rollback 演练 |
| 配置键漂移 | 82 个（含全部 `BACKUP_*`） | 0 | `check_env_drift.py` |
| `core→services` 反向边 | 12 | 3 | AST 扫描 |
| 健康检查端点套数 | 2（其中一套被 JWT 挡住） | 1 | 无 token curl |
| 前端守卫粒度 | path 第一段 | 完整路径 | 单测 |
| BOM 文件数 | 13 | 0 | 全仓 `ast.parse` |
| 跟踪的误提交文件 | 41（backups 17 + uploads 24） | 0 | `git ls-files` |

---

## 8. 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| S1 没有可用的常开内网机 / NAS | 异地备份退化为「搬到独立物理盘」，仍不解决「同一台机器」 | 先确认设备是否存在；若确实没有，把「采购一台 NAS」作为正式诉求上报 |
| S3 严格校验上线即重启失败 | 服务起不来 | **先跑 dry-run 打印校验结果**，确认 `.env` 里加密口令齐备，再开严格模式 |
| S4 改 `records.py:113` 默认值是破坏性 API 变更 | 漏改调用点 → 运行时 TypeError | 一次性搜完所有 records 的 create/update 调用点，先加必填再跑全量测试 |
| S6 依赖 `alembic downgrade` 可用性 | 部分迁移无法降级 → 回滚失败 | 逐个确认 downgrade；不可降级的迁移只能走「还原备份」路径（依赖 S1/S4） |
| S11 第 2 步 force-push | 协作者本地历史分叉 | 独立立项 D1，提前通知全员重新 clone |
| 本地门禁弱于 CI（pre-commit 未安装） | 问题到 CI 才暴露 | S3/S10 顺带把 `check_env_drift.py` 与 BOM 检查挂进 pre-commit 并真正安装 |

---

## 9. 附：本次复核中被证伪 / 已修复的旧结论（避免重复劳动）

| 旧结论 | 复核结果 |
|---|---|
| `backup_schedule.last_status` 恒为 `running` | ❌ **已过时**。`core/arq_callbacks.py:42-46` / `:65-100` 已实现终态落定，`core/arq_app.py:202-203` 已注册钩子 |
| 恢复路径无 partial 语义 | ❌ **已实现**。`json_backup.py:368` / `:484-485` / `:547` / `:552` |
| 行级降级跳过缺失 | ❌ **已实现**。`json_backup.py:237`/`:238`/`:274`/`:283`/`:294` |
| auxiliary 的健康端点「完全无鉴权」 | ⚠️ **不准确**。`api/v1/router.py:186-191` 带 router 级 `Depends(get_current_user_id)`，是**被鉴权挡住**而非裸奔 |
| 仓库有 `alembic.ini` | ❌ **不存在**（本轮实测确认） |
| 根目录有 `ERP_上线前优化方案.md` / `CODE_REVIEW_OPTIMIZATION_PLAN.md` / `ERP_上线前全面代码质量审查报告_2026-09-29.md` | ❌ **三份均不存在**，不要引用 |
| `logs/erp.log` 是生产日志 | ❌ **不是**。格式对应 `utils/logger.py`，唯一导入者是 `tests/test_logger.py` |

---

## 10. 建议的 ADR（Architecture Decision Record）

按 software-architect 技能要求，以下决策值得留档（模板：Status / Context / Decision / Consequences）：

1. **ADR-01 备份异地策略**：robocopy 到 NAS（方案 A）vs 对象存储（方案 B），以及为什么现在不做多地多活。
2. **ADR-02 可观测性路线**：进程内巡检（方案 B）vs 完整 Prometheus 栈（方案 A），以及死配置的处置。
3. **ADR-03 配置单一来源**：`.env` 为唯一权威，`.env.production` 的定位与校验强度。
4. **ADR-04 备份成功判据**：什么条件下允许把一次备份标记为 success（本方案的核心定义）。
5. **ADR-05 API 版本化**：删除 `api/v2` 还是保留——以及未来什么时候才需要版本化。
6. **ADR-06 依赖注入方式**：删除服务定位器（`core/container.py`），统一用 FastAPI `Depends`。
7. **ADR-07 部署与回滚**：不做 CI 自动部署的前提下，人工发布的标准化步骤与 tag 约定。
8. **ADR-08 移动端定位**：数据层统一（A）与功能面收敛（B）的取舍。

---

*本方案基于 2026-09-30 的代码与配置实测，所有 `文件:行号` 引用均来自当轮 AST / 定向读取结果。*
