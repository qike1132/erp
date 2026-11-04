# 2026-11-04 上线阻断项修复记录

> 范围：2026-11-04 上线验收发现的问题逐项修复
>
> 证据截止：2026-11-04 18:30（北京时间）
>
> 代码基线：`main@200364fb`（修复提交 `74acd748` / `28440211` / `d030db24` / `200364fb`）
>
> CI：`d030db24` 的 run `41805537090`、`200364fb` 的 run `41813809003` 均四 job 全绿；CodeQL 同步 success
>
> 生产操作边界：归档一个测试残留的恢复标记；通过提权更新 `.env` 的备份加密开关与看门狗新鲜度阈值；**未重启服务、未恢复数据库**

## 1. 结论摘要

| 状态 | 数量 | 说明 |
|---|---|---|
| 已修复并有测试证据 | 9 | 恢复标记作用域、测试污染、FK 元数据查询、事务污染、行数口径、watchdog 冷却、readiness 契约、备份新鲜度阈值、演练调度状态 |
| 已执行且可复核的生产处置 | 3 | 恢复标记可逆归档；`.env` 加密开关；`.env` 新鲜度阈值 540→1500（均已留快照） |
| 仍需授权/外部信息 | 3 | 告警通道、新备份上的恢复演练、生产重启部署 |

当前 `readiness` 已恢复、看门狗 7 项全绿，但**仍不能据此宣布上线就绪**：最新备份仍为明文（加密开关要重启后才生效），告警仍无实际投递通道，最近一次成功恢复演练尚未产生；代码已通过 CI，但尚未部署到生产进程。

补充的只读结论（2026-11-04 18:16 提权查询生产库）：

- **生产库迁移版本 = `pg_standalone_109_add_user_token_version`，与源码单 head 一致（149 revisions / 1 head）** —— 此前“生产落后 109/110”的猜测不成立，重启不涉及待执行迁移；
- 生产 `backup_schedule` 只有每日全量 + 每日清理/完整性检查 + **每月 1 日 03:30 的灾备演练**，没有小时级增量；演练“停摆”实为月频正常间隔，但失败状态被记成 success（见 2.7）。

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

### 2.6 备份新鲜度阈值与真实调度不匹配（恒红 15–22 小时/天）

**根因**：`WATCHDOG_BACKUP_MAX_AGE_MINUTES` 默认 90 分钟，生产 `.env` 实际配的是 540（9 小时），但生产 `backup_schedule` 只有**每日一次全量**：

```text
id=32 full             42 8 * * *    last_run 2026-11-04 08:45  success
id=33 cleanup           0 4 * * *
id=35 integrity_check   0 3 * * *
id=36 disaster_recovery_test  30 3 1 * *   last_run 2026-11-01 04:10  success
```

没有任何小时级增量产物。于是 `backup_freshness` 每天 17:45（配 540 时）或 10:12（配 90 时）起必然 fail，直到次日 08:45。恒红信号与真正的备份停摆长得一模一样，值班人只能选择忽略。

**修复**：

- `scripts/ops/watchdog.py` 新增 `DEFAULT_BACKUP_MAX_AGE_MINUTES = 1500.0`（25h），与 `fastapi_app/services/backup/freshness.py` 的 `BACKUP_STALE_HOURS=25.0` 同口径；
- 显式 `.env` 配置仍优先（将来启用小时级增量可调回 90 量级）；
- fail 的 detail 改为同时给出“真实年龄 + 阈值”，并统一按小时展示，便于区分“漏跑”与“阈值配错”；
- `.env.example` 与 `docs/runbooks/watchdog.md` 同步到 1500 并写明理由；
- `freshness.py` 模块 docstring 里“增量 06-22 每小时”的表述与实际调度不符，已按实测校正。

**生产处置**：`.env` 的 `WATCHDOG_BACKUP_MAX_AGE_MINUTES` 由 540 改为 1500（改前快照 `_ops/credentials/env_snapshots/.env.20261104_181646.bak`）。看门狗每轮新起进程，**不需要重启服务**。

**复验**（提权跑 `watchdog.py --no-alert --verbose`）：

```text
RC=0
[OK] backend_health / backend_ready / arq_worker / web_entry
[OK] backup_freshness: 最新 erp_auto_daily_20261104_084509196.zip（9.5 小时前，共 17 个归档）
[OK] disk_free: C: 59.2GB; D: 472.8GB
[OK] services: 五个 NSSM 服务 RUNNING
```

### 2.7 灾备演练失败在调度表里被记成“成功”

**根因**：`disaster_recovery_test_task` 在 `overall_success=false` 时只发告警然后 `return result`；而 `_tracked_job` 判定失败的依据只有“抛异常”或“返回 dict 且 `status=='error'`”。演练服务返回的是 `{'overall_success': False, ...}`，不带 `status`，于是 `on_job_end` 走成功分支，把 `backup_schedule.last_status` 写成 `success`。

**证据**：`backup_schedule` id=36 的 `last_status=success`，而 `backups/server/recovery_tests/recovery_test_20261101_041001_fbf72c.json` 的 `overall_success=false`。也就是说“灾备到底能不能用”这个最关键信号，在调度表里被完全掩盖——与 2.5、2.6 属同一类“监控说谎”缺陷。

**修复**：演练失败时把返回值补上 `status='error'` 与失败原因（保留 `overall_success`/`test_id` 等原始字段），复用既有的 `_tracked_job` 约定，使调度终态如实记为 `failed`，同时进入死信与 critical 告警链路。

**副作用说明**：失败演练现在会同时产生“业务级 error 告警”和“ARQ critical 告警”两条，属有意为之（月度演练失败值得两条），但需在告警通道启用后观察是否过噪。

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
| 新增回归：`test_watchdog_backup_freshness.py` + `test_backup_drill_status.py` | 9 passed |
| 变异验证（移除演练 status 修复） | 2 failed（`status` 缺失、`_job_outcome=success`）→ 证明测试能抓错 |
| 提权跑 `watchdog.py --no-alert --verbose` | RC=0，7 项全 ok，`backup_freshness` 显示“9.5 小时前”判 OK |
| 生产库只读查询 | `alembic_version=pg_standalone_109_add_user_token_version`；`backup_schedule` 4 行均为日/月频 |
| `/api/health/ready` | 200，`restore_pending=false` |
| `watchdog.log` 最新轮次 | 7 项全 ok，`backend_ready=ok` |
| `quality_gate.py --report` | 与基线一致；无新增违规 |
| CI（`200364fb`） | run `41813809003`：test / lint / frontend / build 四 job 全绿 |

## 4. 修改文件

| 文件 | 变更 |
|---|---|
| `fastapi_app/services/backup/restore_guard.py` | 目标库作用域、异库告警降级、fail-closed |
| `fastapi_app/core/health.py` | readiness 字段契约、标记可见性 |
| `fastapi_app/services/backup/orchestration/drill_validator.py` | FK/UNIQUE 元数据查询、事务隔离、超时、异常收敛 |
| `fastapi_app/services/backup/orchestration/core.py` | dump 行数解析、manifest `rows_source` |
| `scripts/ops/watchdog.py` | 告警冷却只在成功投递后记账；备份新鲜度默认阈值 90→1500 分钟，detail 改为“小时/分钟”自适应 |
| `fastapi_app/tasks/backup_tasks.py` | 演练失败时返回 `status='error'`，让调度终态如实记 failed |
| `fastapi_app/services/backup/freshness.py` | 校正“增量 06-22 每小时”的失效表述，写明 25h 的调度依据 |
| `.env.example` / `docs/runbooks/watchdog.md` | 备份新鲜度阈值与真实调度对齐，写明何时该调回 90 |
| `fastapi_app/tests/test_restore_guard_fail_closed.py` | 异库/同库/未知标记契约 |
| `fastapi_app/tests/test_restore_real_roundtrip.py` | 标记目录隔离 |
| `fastapi_app/tests/test_recovery_validation_fixes.py` | 24 个恢复校验回归用例 |
| `fastapi_app/tests/test_watchdog_alert_cooldown.py` | 10 个冷却/投递回归用例 |
| `fastapi_app/tests/test_watchdog_backup_freshness.py` | 6 个新鲜度阈值/归档白名单用例 |
| `fastapi_app/tests/test_backup_drill_status.py` | 3 个演练失败状态用例（含 `_tracked_job` 联通性） |

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
| `.env` 看门狗阈值 540→1500 | 用 `_ops/credentials/env_snapshots/.env.20261104_181646.bak` 覆盖 `.env`；看门狗每轮新进程，无需重启 |
| 代码修复（已提交未部署） | `git revert 200364fb d030db24 28440211 74acd748` 或按提交回退 |
| watchdog 源码修复 | 已由计划任务按新进程生效；回滚为 `git checkout -- scripts/ops/watchdog.py` |

## 7. 当前上线判定

**仍为 No-Go，但阻断范围已收窄：**

- 已关闭：readiness 503、测试污染、FK SQL 错误、事务污染、行数估算误判、watchdog 冷却误记账、备份新鲜度恒红、演练状态掩盖、目标 SHA CI；
- 配置已就绪但未生效：备份加密（重启后生效）；
- 未关闭：告警投递（按用户决定暂不配置）、新备份恢复演练、生产重启部署、他人未跟踪目录处置；
- 下一步顺序：**维护窗口重启 erp-arq/erp-prod → 生成新加密备份 → 新备份恢复演练 → 业务验收 → 更新风险登记册**。

重启前必须确认：生产库已在迁移 head（本次已核实为 109，与源码单 head 一致，无待执行迁移）；工作区只剩他人 2 个未跟踪目录，重启会加载当前工作区源码，需 owner 确认这些目录不影响运行（它们是纯交付文档，不参与 import，但仍应记录在发布单上）。

## 8. 环境修复：本机 SSH 推送恢复（2026-11-04 19:00）

**现象**：`git push erp main` 报 `git@github.com: Permission denied (publickey)`；`ssh-add -l` 无可用 agent。

**根因**：本机 `~/.ssh/id_ed25519`（`SHA256:RjM3rn6Z…`）在 GitHub 上处于“已被占用但不被接受”的状态——尝试登记为部署密钥返回 `key is already in use`，而 SSH 认证却返回 `USERAUTH_FAILURE`。该公钥应挂在其他账号或其他仓库下，本机无权认领。`gh` token 仅有 `gist/read:org/repo`，无 `admin:public_key`，无法查看或新增账号级 key。

**处置**（选择仓库级部署密钥，权限面最小）：

| 项 | 值 |
|---|---|
| 新私钥 | `~/.ssh/id_ed25519_erp`（无口令；ACL 仅 SYSTEM / Administrators / Administrator） |
| 公钥指纹 | `SHA256:L8U/3RypvdHb2z34FOlOxWmI6GKzJ3zjGhfV+q+HH9Q` |
| GitHub 登记 | 仓库部署密钥 id `168729137`，`read_only=false`（写权限）、`verified=true` |
| 仓库级配置 | `core.sshCommand = ssh -i /c/Users/Administrator/.ssh/id_ed25519_erp -o IdentitiesOnly=yes`（仅本 clone，不入库、不改全局、不改 remote URL） |

**验证**：

```text
ssh -T git@github.com        → Hi qike1132/erp! You've successfully authenticated...
git ls-remote erp main       → 98a688447e26c8079d5f6c111671753db5e65d31
git push erp <临时 tag>       → * [new tag]（写权限确认）
git push erp :<临时 tag>      → - [deleted]（清理，远端 404）
```

**已知抖动（重要）**：同一 IP、同一把 key，GitHub 有时回 `SSH2_MSG_USERAUTH_PK_OK`（type 60）、有时回 `USERAUTH_FAILURE`（type 51）。密集重试几十次后几乎全部失败，冷却约 4 分钟后单次必然成功。**排障时不要用循环狂刷**，失败就等几分钟再试一次；自动化脚本应允许一次重试而不是无限重试。已排除中间人（`ssh-keyscan` 的 ED25519 指纹与 GitHub 官方 `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` 一致）与端口因素（22 与 `ssh.github.com:443` 成功率相同）。

**回滚**：删除仓库部署密钥 id `168729137`，并 `git config --unset core.sshCommand`；原 `~/.ssh/id_ed25519` 未被修改。

**遗留**：原 `id_ed25519` 究竟挂在哪个账号/仓库仍未知，若后续要恢复“一把 key 通吃所有仓库”，需在 GitHub 账号设置里找到并删除旧登记，再把它加为账号级 key（需要 `admin:public_key` 授权）。
