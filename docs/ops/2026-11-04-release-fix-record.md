# 2026-11-04 上线阻断项修复记录

> 范围：2026-11-04 上线验收发现的问题逐项修复
>
> 证据截止：2026-11-04 17:25（北京时间）
>
> 代码基线：`main@d030db24`（修复提交 `74acd748` / `28440211` / `d030db24`）
>
> CI：run `41805537090` 四 job 全绿；CodeQL run `41805536420` success
>
> 生产操作边界：归档一个测试残留的恢复标记；通过提权验证并更新 `.env` 的备份加密开关；**未重启服务、未恢复数据库**

## 1. 结论摘要

| 状态 | 数量 | 说明 |
|---|---|---|
| 已修复并有测试证据 | 7 | 恢复标记作用域、测试污染、FK 元数据查询、事务污染、行数口径、watchdog 冷却、readiness 契约 |
| 已执行且可复核的生产处置 | 2 | 恢复标记可逆归档；`.env` 已置加密开关并通过生产环境自检（未重启） |
| 仍需授权/外部信息 | 3 | 告警通道、新备份上的恢复演练、生产重启部署 |

当前 `readiness` 已恢复，但**仍不能据此宣布上线就绪**：最新备份仍为明文（加密开关要重启后才生效），告警仍无实际投递通道，最近一次成功恢复演练尚未产生；代码已通过 CI，但尚未部署到生产进程。

## 2. 已修复问题

### 2.1 恢复标记把生产 readiness 打成 503

**根因**：恢复中断标记是全局单文件，不区分目标库；`test_restore_refuses_without_createdb` 在 scratch 库 `erp_system_restore_test` 上真跑 `restore_database_via_psql`，把标记写进生产备份目录且未清理。readiness 原先只看“有没有标记”，不看标记目标库。

**证据**：

- `backups/server/.restore_in_progress.json`：目标 `erp_system_restore_test`，`failed_stage=rebuild_db`；
- `logs/fastapi_20261103.log:11946`：`建库权限预检未通过，恢复中止（未删除任何数据库）`；
- 预检在 DROP 之前（`fastapi_app/services/backup/dump.py:279-283`），生产库未被删除；
- 11-03 备份 315,222 行 → 11-04 备份 316,567 行，生产数据继续正常增长。

**修复**：

- `restore_guard.restore_readiness(current_db_name_override=None)`：仅当标记目标库 == 当前运行库时阻断；异库标记返回 `ok=True` 并保留 `db_name/current_db_name/warning`；
- 标记不可读、缺 `db_name`、当前库名解析不出时继续 fail-closed；
- `check_interrupted_restore()` 对异库标记降级为 WARNING；
- `health.py` 保持 `restore_pending` 旧契约（是否阻断本库），新增 `restore_marker_present`（磁盘上是否存在标记）；
- `test_restore_real_roundtrip.py` 将 `BACKUP_DIR` / `PRE_RESTORE_DIR` 隔离到 `tmp_path`，演练不再触碰生产备份目录。

**生产处置**：

```text
backups/server/.restore_in_progress.json
  → backups/server/restore_marker_archive/20261103T143523Z_erp_system_restore_test.json
```

标记未删除，原内容与 mtime 保留，附 `*.reason.txt`；回滚方式为移回原路径。

**复验**：

```json
{"status":"ready","database":true,"redis":true,"restore_pending":false,"restore":{"ok":true,"state":"absent"}}
```

### 2.2 恢复约束校验引用不存在的列

**根因**：`drill_validator._load_fk_groups` 查询 `information_schema.constraint_column_usage.ordinal_position`，该视图无此列，约束验证必然 `UndefinedColumnError`。

**修复**：

- 改用 `pg_constraint` 的 `conkey/confkey` 同下标配对 + `pg_attribute` 还原列名；
- 聚合键改为 `schema.table.constraint_name`，避免同一 schema 不同表的同名外键被合并；
- 唯一约束同步改为 `pg_constraint(contype='u')`，并 schema 限定；
- `zip(..., strict=True)`，列数不一致显式失败；
- 真库测试覆盖复合外键、同 schema 同名 FK、跨 schema 同名 UNIQUE。

### 2.3 单个验证族失败污染后续验证

**根因**：四族验证共用一个隐式事务；约束族 SQL 失败后 PostgreSQL 将事务标记 aborted，性能族全部 `InFailedSQLTransactionError`。

**修复**：

- 验证引擎使用 `AUTOCOMMIT`（只读元数据/COUNT 查询，无跨语句原子性要求）；
- 新增逐族兜底，单族异常不丢其他族结果；
- 连接阶段异常统一返回结构化失败结果；
- `test_engine.dispose()` 放入 `finally`；
- 验证连接设置 `statement_timeout=30s`。

### 2.4 manifest 行数用估算值，恢复校验必然误判

**根因**：`_count_tables` 对 `reltuples >= 100000` 的表返回估算值；`DrillValidator` 将其当作精确期望行数做全等比较。真实报告 `audit_log expected=256824 / actual=260880`，恢复本身正确，错在 manifest 口径。

**修复**：

- 新增 SQL dump COPY 区流式计数（空表计 0，不把“空表”误判为“未导出”）；
- JSON 降级备份从 `tables[*].count/rows` 计数；
- manifest 新增 `rows_source=dump`；只有解析失败才回退 `exact_count_fallback` 并显式标记；
- 不再依赖导出后的独立 `COUNT(*)`，避免与 dump 快照漂移。

**真实备份复核**：

```text
71 张 ORM 表全部映射，missing=0
rows_source=dump
total_rows=321615
audit_log=261872（与 dump COPY 区一致）
```

> 旧备份（2026-11-04 08:45 及更早）的 manifest 仍为旧口径，不能靠本次代码回溯修正；必须在新备份生成后重跑演练。

### 2.5 watchdog 告警冷却误记账

**根因**：`select_alerts()` 在投递前写 `last_sent=now`，没有通道或投递失败也会进入 30 分钟冷却，日志出现“告警 1 项，通道 无”后不再重试。

**修复**：

- `select_alerts()` 只读冷却状态；
- 新增 `record_alerts_sent()`，仅在实际成功通道非空时推进冷却；
- 未投递时累加 `undelivered_attempts` / `undelivered_since`，日志与 stderr 显式输出“告警未投递，下一轮重试”。

## 3. 验证证据

| 检查 | 结果 |
|---|---|
| `ruff check`（全部修改文件） | All checks passed |
| `compileall`（全部修改文件） | COMPILE_OK |
| 非真库单测（`test_recovery_validation_fixes.py -k "not real_pg"`） | 21 passed |
| 真库约束测试（3 个 real_pg 用例） | 3 passed |
| 修复聚焦四文件（恢复/守卫/演练/watchdog） | 61 passed |
| 备份/恢复/健康/看门狗相关回归（`fastapi_app/tests` + `tests`） | 850 passed, 4662 deselected |
| 真实备份行数解析 | 71 表全映射，`audit_log=261872`，`total_rows=321615` |
| `/api/health/ready` | 200，`restore_pending=false` |
| `watchdog.log` 最新轮次 | 7 项全 ok，`backend_ready=ok` |
| `quality_gate.py --report` | 与基线一致；无新增违规 |

## 4. 修改文件

| 文件 | 变更 |
|---|---|
| `fastapi_app/services/backup/restore_guard.py` | 目标库作用域、异库告警降级、fail-closed |
| `fastapi_app/core/health.py` | readiness 字段契约、标记可见性 |
| `fastapi_app/services/backup/orchestration/drill_validator.py` | FK/UNIQUE 元数据查询、事务隔离、超时、异常收敛 |
| `fastapi_app/services/backup/orchestration/core.py` | dump 行数解析、manifest `rows_source` |
| `scripts/ops/watchdog.py` | 告警冷却只在成功投递后记账 |
| `fastapi_app/tests/test_restore_guard_fail_closed.py` | 异库/同库/未知标记契约 |
| `fastapi_app/tests/test_restore_real_roundtrip.py` | 标记目录隔离 |
| `fastapi_app/tests/test_recovery_validation_fixes.py` | 24 个恢复校验回归用例 |
| `fastapi_app/tests/test_watchdog_alert_cooldown.py` | 10 个冷却/投递回归用例 |

## 5. 仍需授权或外部信息

### 5.1 备份加密（配置已就绪，待重启生效）

- 已通过提权执行验证：现有 `BACKUP_ENCRYPTION_PASSWORD` 存在，加密/解密往返成功；
- `.env` 已置 `BACKUP_ENCRYPTION_ENABLED=true`、`BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED=false`；修改前快照为 `_ops/credentials/env_snapshots/.env.20261104_171530.bak`；
- `python -m fastapi_app.core.prod_runner --check` 在提权环境返回 0；
- **仍未生效**：`erp-arq` / `erp-prod` 未重启，最新备份仍是明文；
- 重启后必须生成新 `.zip.enc`、确认 `encrypted=true`，并做一次隔离恢复，才算关闭。

### 5.2 告警通道

- 现状：`watchdog.log` 仍“通道 无”；代码冷却缺陷已修，但没有 webhook/SMTP 配置；
- 需要提供企业微信/钉钉 webhook 或 SMTP 收件人；
- 配置后用本地 sink 验证首次投递、冷却和恢复通知，不得直接打真实值班群做首次测试。

### 5.3 新备份上的恢复演练

- 现状：最近成功演练尚未产生；旧报告仍为 `overall_success=false`；
- 代码已修，但旧包 manifest 是估算口径，不能作为修复后的验收样本；
- 需在代码生效后生成新备份，再在独立 scratch 库完成恢复，要求：
  - `overall_success=true`；
  - `constraint_validation.passed=true`；
  - `data_validation` 无差异；
  - 清理成功；
  - 记录实际耗时（RTO）。

### 5.4 发布冻结与 CI

- 当前 `main@4049ab1e19`，本轮改动未提交；
- 另有 2 个他人未跟踪 `deliverables/` 目录，未处置；
- 需 owner 确认后提交本轮修复、冻结目标 SHA、跑 CI 四 job；
- 生产重启会把当前工作区源码加载进生产，必须在干净工作区和维护窗口执行。

## 6. 生产变更与回滚

| 变更 | 回滚 |
|---|---|
| 恢复标记归档 | 将 `backups/server/restore_marker_archive/20261103T143523Z_erp_system_restore_test.json` 移回 `backups/server/.restore_in_progress.json` |
| `.env` 加密开关 | 用 `_ops/credentials/env_snapshots/.env.20261104_171530.bak` 覆盖 `.env`（保留原 ACL），再按需重启 |
| 代码修复（已提交未部署） | `git revert 74acd748 28440211 d030db24` 或按提交回退 |
| watchdog 源码修复 | 已由计划任务按新进程生效；回滚为 `git checkout -- scripts/ops/watchdog.py` |

## 7. 当前上线判定

**仍为 No-Go，但阻断范围已收窄：**

- 已关闭：readiness 503、测试污染、FK SQL 错误、事务污染、行数估算误判、watchdog 冷却误记账、目标 SHA CI；
- 配置已就绪但未生效：备份加密（重启后生效）；
- 未关闭：告警投递（按用户决定暂不配置）、新备份恢复演练、生产重启部署、他人未跟踪目录处置；
- 下一步顺序：**维护窗口重启 erp-arq/erp-prod → 生成新加密备份 → 新备份恢复演练 → 业务验收 → 更新风险登记册**。
