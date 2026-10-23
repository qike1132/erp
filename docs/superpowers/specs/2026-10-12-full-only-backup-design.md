# 备份只保留全量 + 7 天保留策略 — 设计

**日期**：2026-10-12
**状态**：待用户审阅（brainstorming 阶段产出）
**范围**：`/backup` 备份子系统
**相关**：本文件与 `2026-10-04-erp-incremental-path-decision.md` **无关**——那份讲的是"ERP 增量改造路线"（放弃重写），不是增量备份。

---

## 1. 目标与验收

把备份模型收敛为**单一全量**，并给出确定性的保留策略。

**目标**

1. **删除增量备份的全部代码**（后端服务/任务/调度/端点 + 前端入口 + 配置 + 相关测试），全栈彻底移除。
2. **全量备份每天一次**（保留现有每日全量调度）。
3. **保留策略唯一规则**：全量备份文件（手动 + 自动，**一视同仁**）年龄 > 7 天即删；任何情况下**至少保留最新 1 个**。
4. 清理生产库与磁盘上的历史增量残留（调度行、记录、文件）。

**验收（可判定）**

- 全仓 grep `incremental`（备份语义）在非测试代码中零命中。
- `/backup` 页面无"增量备份"选项/按钮/还原入口；调度类型下拉无 incremental。
- 新写一条回归测试：**超 7 天删、7 天内留、删到只剩 1 个时停手**——且该测试在把阈值改坏时**会红**（变异检查）。
- 迁移后 `alembic heads` 单 head；空库 `upgrade head` 通过。
- CI 三个 job（test / lint / frontend）全绿。

**非目标（明确不做）**

- 不重写 `/backup` 前端界面；只删增量相关入口。
- 不动加密、恢复向导、组件（filestore/config/redis/meili）备份。
- 不引入"合成全量"/增量合并（已论证：本库体量下收益为零，且增量无删除信息、合并会复活已删行）。
- 不改已应用迁移（036/056/057）；不动 RBAC 种子（权限码无独立码，见 §7）。

---

## 2. 现状（评审取证）

| 概念 | 现状 | 证据 |
|---|---|---|
| 全量包 | 自包含；还原 = 先 DELETE 包里各表再插入 | `json_backup.py:396 _clear_tables_for_restore` |
| 增量包 | 自上次**全量**以来、时间戳列 ≥ since 的行；不记录删除 | `verify/core.py:81 query_table_rows`；`incremental.py:64` |
| 增量还原 | `POST /restore-incremental` → upsert（不清表）；UI **不暴露** | `incremental.py:341`；`api/backup.ts:116`（无组件调用） |
| 增量误用风险 | 普通还原向导不查 `manifest.type`，增量包走 JSON 策略 → 清表+插 delta | `orchestrator.py:499 StrategySelector.select` |
| 保留策略 | env `BACKUP_RETENTION_DAYS`（运行时 `.env` = 7）单一真源 | `_constants.py:188-201` |
| 清理任务 | ARQ `backup_cleanup_task` → `smart_cleanup()`，由 `backup_schedule` task_type='cleanup' 驱动 | `backup_tasks.py:601`；`schedule_service.py:23` |
| 第二套清理 | `records.cleanup_old_backups`（天数+份数+增量级联），**生产无调用方**，仅测试调 | `records.py:644` |
| 界面保留天数 | **不存在**——设置页只有备份路径 | `PathSettings.vue`（全文 101 行） |
| `backup_settings.retention_days/max_count` | 死列：清理不读它，UI 不显示不传 | `settings_service.py:67-96`；`backup.ts:150`（仅类型） |

---

## 3. 保留策略（唯一规则）

**机制**：保留现有清理基础设施（ARQ `backup_cleanup_task` + `backup_schedule` 的 cleanup 行，cron `0 4 * * *`），把 `smart_cleanup` 重写为单规则。

**规则**

1. 扫描 `BACKUP_DIR` 下**全量**文件：前缀 `erp_backup_`（手动）/ `erp_auto_daily_`（自动）；后缀 `.zip` / `.zip.enc`。**不再扫 `erp_incremental_`**。
2. 文件年龄取 `.meta` 的 `created_at`，无则文件 mtime（沿用 `_backup_created_time`）。
3. 年龄 > `retention_days()` 天 → 标记删除。**手动、自动一视同仁**（去掉 `keep_manual` 豁免）。
4. 兜底：`_enforce_keep_floor` 保留——任何情况下至少留最新 1 个（含"全被判损坏"时仍留 1）。
5. 跳过 120 秒内仍在写入的文件（防误删半截 zip）。
6. 删除主文件时同步删 `.meta` / `.record` 伴生文件 + `backup_record` 记录（沿用 `_delete_backup_sidecars` 与批量 DELETE）。

**删除的旧逻辑**（`cleanup/service.py`）

- `_mark_incremental_chains`、`_extract_timestamp`（增量链）
- `_calculate_importance_scores`（重要性评分 / 磁盘压力裁剪）
- `_test_backup_files`（恢复测试抽样）
- `_load_cleanup_config` 里 `retention_count` / `disk_space_threshold` / `min_free_space_gb` / `keep_manual_backups` / `keep_failed_backups` / `smart_cleanup_enabled` / `recovery_test_before_delete` / `test_sample_rate` 等分支
- 报告生成里增量/份数/健康度相关字段（保留：时间戳、删除数、保留数、磁盘信息、错误）

**保留的旧逻辑**：`_get_backup_files_info`（扫描，收窄前缀）、`_backup_created_time`、`_enforce_keep_floor`、`_execute_cleanup`（删除+伴生+DB 记录）、`_send_cleanup_notification`（简化）、`_save_cleanup_report`。

**配置口径**

- `BACKUP_RETENTION_DAYS`：运行时 `.env` 已是 7。**把代码默认值 `RETENTION_DAYS_DEFAULT` 由 30 改为 7**（`_constants.py:190`），使无 `.env` 的新装环境也是 7 天。
- `BACKUP_RETENTION_COUNT` / `retention_count()` / `BACKUP_MAX_COUNT`：保留策略不再用份数。**仅在确认无其余消费者后删除**（`policy_service` 重写后、`records.cleanup_old_backups` 删除后、`__init__.py` 导出与相关测试清理后）。否则保留函数、仅从清理路径移除。
- `backup_settings.retention_days/max_count` 死列：**不动**（无 UI、无消费；删列属破坏性 DDL，需动 `destructive_ddl_baseline.json`，收益为零）。可选小改：让 `settings_service.get_settings` 回显 env 真值，避免 API 说谎——**列为可选，默认不做**。

---

## 4. 删除清单（含评审定位）

### 4.1 后端

| 文件 | 删除内容 |
|---|---|
| `services/backup/incremental.py` | 整文件删除（`create_incremental_backup` / `restore_incremental`） |
| `services/backup/__init__.py` | star import（`:105` 附近）+ `__all__` 的 `create_incremental_backup`/`restore_incremental`/`find_last_backup_timestamp`（`:237-239, 246, 276`）；**必须同删，否则 ruff F401 / `__all__` 悬挂** |
| `services/backup/cleanup/service.py` | 见 §3 删除项 |
| `services/backup/records.py` | **整个 `cleanup_old_backups`（`:644-754`）+ `_retention_thresholds`** 及其 `__init__.py:227` 导出（生产无调用方，仅测试） |
| `services/backup/verify/core.py` | `find_last_backup_timestamp`（`:163`）——唯一非测试调用方是 `incremental.py` |
| `services/backup/orchestration/policy_service.py` | **整体重写为 full+retention 两块**（非逐条抠）：`:58 incremental_backup_cron`、`:122-124` 默认策略块、**`:218 required_fields` 强制要求 `incremental_backup` 键**、`:226` 校验、`:346-348` update、`:392` 禁用判断、`:488`、`:669-672`（`type=='incremental'` 查询）、`:691-693` compliance 报告键 |
| `services/backup/snapshot.py` | 增量相关分支（若有） |
| `tasks/backup_tasks.py` | `manual_incremental_backup_task`（`:173-246`）、`auto_incremental_backup_task`（`:481-538`）、**`_do_auto_backup` 的 else 增量分支（`:725-746`）**——后者与全量共用 `_do_auto_backup_with_metrics`（`:441`），重写时勿伤全量 |
| `core/arq_app.py` | `auto_incremental_backup_task`/`manual_incremental_backup_task` 的 import（`:217, 224`）与 functions 注册（`:371, 373`） |
| `services/backup/schedule_service.py` | `TASK_TYPE_TO_FUNC` 去掉 `'incremental'`（`:25`） |
| `api/v1/endpoints/backup/restore.py` | `POST /restore-incremental/{filename}`（`:377-420`） |
| `api/v1/endpoints/backup/export.py` | 增量创建分支（`:353`） |
| `api/v1/endpoints/backup/actions.py` | 手动增量触发（`:174, 187`） |
| `api/v1/endpoints/backup/_deps.py` | `restore_incremental_backup` 权限映射（`:65`）；`save/trigger_incremental` 映射（`:50, 55`） |
| `api/v1/endpoints/backup/validation.py` | 增量相关分支（`:856`，注释级） |
| `schemas/backup.py` | `IncrementalBackupResponse`（`:211`）、`IncrementalRestoreResponse`（`:224`）、`BackupIncrementalRequest`（`:359`） |
| `shared_models/backup_schedule.py` | 模型默认 `task_type='incremental'`（`:22`）改为 `'full'` |
| `core/config.py` | `BACKUP_INCREMENTAL_CRON` 告警条目（`:254`）——**与 policy_service/env 同批删**（env_drift 门禁） |

### 4.2 前端

| 文件 | 删除/改动 |
|---|---|
| `components/backup/ScheduleConfig.vue` | 删 `<option value="incremental">`（`:10`）+ `TASK_TYPE_LABELS` 里的增量项（`:68`）；**默认 `taskType` 由 `'incremental'` 改 `'full'`（`:64`）**（否则默认值非法 → 保存 400） |
| `views/backup/BackupView.vue` | 删 `triggerIncremental()`（`:213-225`）；**`triggerScheduleNow()` 的回退逻辑重设计（`:246-253`）**：无启用定时任务时改为 toast 提示，不再回退触发增量 |
| `api/backup.ts` | 删 `saveIncremental`/`restoreIncremental`/`triggerIncremental`（`:114-117, 139-140`）、`last_incremental` 字段（`:141`） |
| `components/backup/BackupActions.vue` | 删增量按钮（`:8`） |
| `components/backup/BackupRecordTable.vue` | 删增量类型筛选/标签分支（`:5, 22, 99`）——历史记录已随 §5 一并清除，无残留展示问题 |
| `types/api.d.ts` | **生成物**，不手改；由 `npm run gen:api` 重生成 |

### 4.3 配置

- `.env.example`：删 `BACKUP_INCREMENTAL_CRON`（`:263`）——**与 `core/config.py:254`、`policy_service.py:58` 同一提交一起删**（`check_env_drift.py` 会命中 `os.environ.get`）。
- 运维项（未入库）：`.env.production:134`、`config/.env.production:125` 的该键在同步 `.env` 时一并去掉。

### 4.4 测试

- **重新盘点**（评审实测：后端 `fastapi_app/tests/` 14 个 + 根 `tests/` 5 个 = **19 个**文件含 `incremental`，非 17）。逐文件甄别：
  - 纯增量用例：删（如 `test_backup_m1.py::test_incremental_returns_202`）。
  - 共享夹具：改（`test_backup.py`、`test_backup_retention_policy.py`、`test_backup_policy_service.py` 约 20 处增量断言、`test_backup_m2.py`、`test_backup_restore_lock_ownership.py`、`test_arq_worker_health.py`、`test_backup_completeness.py`、`tests/test_health_backup_signal.py` 的 `erp_incremental_*.zip` 夹具）。
  - **不动**：`tests/test_migration_056/057/058*.py`（测已应用迁移，保留）。
  - 前端：`frontend-vite/src/test/backupRecordTablePaging.test.ts:56-58` 用增量行做夹具 → 改夹具。
  - 新增：§1 的 7 天保留回归测试。

### 4.5 门禁联动（必跑）

- openapi 快照：`python scripts/check_openapi_frontend_alignment.py --export frontend-vite/openapi.json` → `cd frontend-vite && npm run gen:api`。拦快照过期的是 **CI test job 的 `check_openapi_frontend_alignment.py`**（`ci-cd.yml:120`），**不是** `check:api`。
- `check:api` / `check:routes` / `check:dto` / `check:types` / `check:api:pc`：mobile 目录无增量引用、无专属权限码/路由 → 预期不受影响，但仍跑确认。
- `quality_gate.py`：删代码只会让基线可收紧（`--update-baseline` 可选，非必须）。
- `check_orphan_modules.py`：删干净后 `incremental.py` 不存在、不构成孤儿；但 `__init__.py`/`arq_app.py`/`tasks` 的悬挂引用必须同删，否则报错。

---

## 5. 生产数据清理

**同批完成**（顺序敏感）：

1. **删磁盘增量文件**：`BACKUP_DIR/erp_incremental_*.zip`（及 `.meta`）。现存 `erp_incremental_20261012_022000.zip` + `.meta`。
2. **删 DB 记录**：`DELETE FROM backup_record WHERE type='incremental'`（全部历史，含文件已删的）。
3. **删调度行**：`DELETE FROM backup_schedule WHERE task_type='incremental'`（现存 `id=34`）。

**顺序理由**：启动时 `sync_backup_records()` 会"补录文件存在但无记录的项"——若先删记录、后留文件，会把增量记录**重新补回来**。故**文件必须先删**；记录删除在文件之后（或由启动同步自动完成）。

**执行方式**：文件删除走运维脚本（迁移不碰文件系统）；DB 两处删除写进迁移 §6。

---

## 6. 迁移

- **新迁移编号 `pg_standalone_092`**（**不是 068**；当前最高是 `pg_standalone_091_report_row_action_per_tab`）。
- `down_revision = 'pg_standalone_091_report_row_action_per_tab'`，**保持单一 head**（`gate_baseline` `alembic_heads: 0`）。
- 内容（幂等、数据变更、**不 autogenerate**）：
  ```sql
  DELETE FROM backup_schedule WHERE task_type = 'incremental';
  DELETE FROM backup_record   WHERE type = 'incremental';
  ```
- **合规性**：`DELETE` 不触发 `destructive_ddl_baseline.json` 扫描（`_destructive_scan.py:42-57` 只认 `drop_*` 调用与 `DROP` 开头 SQL），`test_migration_autogenerate_safety.py` 不会红。空库链 `036 种 → 056 修 → 092 删` 自洽。
- 不修改已应用迁移（036/056/057）。

---

## 7. 风险与回滚

| 风险 | 处置 |
|---|---|
| 删 `incremental.py` 后残留调用点（如 `_do_auto_backup` else 分支）→ `AttributeError` | 按 §4.1 全量清单逐点删；`__init__.py` 导出与 import 同删 |
| 误删共享 helper | **保留** `normalize_backup_ts`、`_delete_backup_sidecars`、`quote_table`（另有活跃调用方）；只删增量专用。（注：`normalize_backup_ts` 已于 2026-10-23 P2-26 删除——复核确认生产零调用，真正的毫秒容忍在 `verify/query_service` 正则） |
| 权限码 `restore_incremental_backup` | 实为通用码映射（`_deps.py:65`→`backup_restore`），**无独立权限码**，前端无 navAccess/路由引用 → **保留 RBAC 不动** |
| 历史 `backup_record.type='incremental'` | 已决定随 §5 删除（保留无用：列表以文件系统为准、启动同步会自动清、metrics 反而更干净） |
| 7 天误删过多 | `_enforce_keep_floor` 兜底至少留 1；回归测试钉住 |
| 回滚 | 代码：`git revert`。数据：增量文件与记录**不可恢复**（本就是要删的）；调度行可由 /backup 重建或迁移回滚重插 |

---

## 8. 验证计划

1. **TDD**：先写"超 7 天删 / 7 天内留 / 至少留 1 个"回归测试 → 看红 → 实现 → 看绿。
2. 聚焦：`pytest` 备份域 + 清理域；`npx vitest run -t "<相关>"`。
3. 门禁：`ruff check .` / `mypy` / `python scripts/quality_gate.py`；前端 `npm run type-check` / `lint` / 各 `check:*`。
4. 迁移：空库 `upgrade head` + `alembic heads`（单 head）+ `alembic check`。
5. 生产（提权）：跑一次清理，确认只按 7 天删、且增量调度行已消失；`/backup` 页面无增量入口。
6. 变异检查：把 7 改坏 → 回归测试必须红。

---

## 9. 待办清单（实施顺序建议）

1. 后端删除（§4.1）+ `__init__` 导出清理。
2. 清理服务重写（§3）。
3. 配置三处同删（§4.3）。
4. 前端删除（§4.2）。
5. openapi 重导 + `gen:api`（§4.5）。
6. 测试盘点/删改 + 新增回归测试（§4.4）。
7. 迁移 092（§6）。
8. 生产数据清理（§5）。
9. 跑门禁（§8）。
