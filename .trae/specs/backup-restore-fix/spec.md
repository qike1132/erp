# 数据备份与恢复功能全面修复与验证 Spec

## Why
当前 ERP 系统的数据备份功能可以成功执行备份，但数据恢复操作存在严重问题导致无法恢复。增量备份的前端 API 调用在后端无对应端点，恢复流程存在连接池管理、锁释放、错误处理等多处缺陷，需要全面修复以确保"一键备份与恢复左侧导航栏全部板块数据"的可靠性。

## What Changes
- 修复后端增量备份 API 端点缺失问题（前端调用 `/backup/save-incremental` 和 `/backup/restore-incremental/{filename}`，后端无对应实现）
- 修复 psql 恢复流程中的连接池管理、锁释放和错误处理缺陷
- 修复 Legacy JSON 恢复中的外键约束处理和参数命名冲突问题
- 修复 `restore_db.py` 脚本使用 MySQL 命令而非 PostgreSQL 的问题
- 扩展 `_CHECKSUM_TABLES` 覆盖所有核心业务表
- 增强恢复流程的异常处理和事务安全机制
- 增加恢复前自动备份（安全网）机制
- 增加恢复进度反馈和超时保护
- **BREAKING**: 恢复操作将先自动创建安全备份再执行

## Impact
- Affected specs: 数据备份与恢复功能（`/backup` 页面全部功能）
- Affected code:
  - `fastapi_app/api/v1/endpoints/backup.py` — 核心备份/恢复 API
  - `frontend-vite/src/views/backup/BackupView.vue` — 前端备份页面
  - `frontend-vite/src/api/index.ts` — 前端 API 封装
  - `scripts/database/restore_db.py` — 命令行恢复脚本
  - `scripts/database/db_manager.py` — 数据库管理工具

## 问题分析报告

### 问题 1：增量备份 API 端点缺失（BLOCKER）
前端 `backupApi` 定义了 `saveIncremental` 和 `restoreIncremental` 两个方法，分别调用：
- `POST /backup/save-incremental?remark=...`
- `POST /backup/restore-incremental/{filename}?confirm=true`

但后端 `backup.py` 中**完全没有**这两个端点的实现。用户点击"增量备份"或"增量恢复"按钮时，请求将返回 404 错误。

### 问题 2：psql 恢复流程缺陷（BLOCKER）
`_restore_database_via_psql` 函数存在以下问题：

1. **连接池释放不完整**：在 `db.close()` 和 `_async_engine.dispose()` 后仅等待 0.5 秒，可能不足以让所有连接完全释放，导致 `DROP DATABASE` 失败（"database is being accessed by other users"）
2. **锁未正确释放**：`_restore_from_zip` 的 finally 块中，当 `psql_attempted=True` 时不释放 advisory lock，因为数据库已被重建，但新数据库中可能残留锁状态
3. **`WITH (FORCE)` 不兼容旧版 PostgreSQL**：`DROP DATABASE ... WITH (FORCE)` 需要 PostgreSQL 13+，低版本会报语法错误
4. **psql 恢复后连接池重建可能失败**：`_dispose_and_reinit_pool()` 调用 `_init_async_engine()`，但如果环境变量或配置有问题，重建会失败且无适当回退
5. **验证步骤使用可能无效的数据库会话**：psql 恢复后，原始 `db` 会话已关闭，验证尝试使用 `_AsyncSessionLocal()` 创建新会话，但该变量可能在连接池重建过程中尚未正确初始化

### 问题 3：Legacy JSON 恢复缺陷（HIGH）
`_restore_legacy_json` 函数存在以下问题：

1. **DELETE 操作不处理外键约束**：按 `reversed(Base.metadata.sorted_tables)` 顺序删除，但 SQLAlchemy 的 `sorted_tables` 依赖拓扑排序，反向删除不一定能解决所有外键依赖
2. **参数命名冲突**：使用 `{col}_{inserted}` 格式命名参数，如果列名本身包含数字后缀（如 `field_1`），可能与行号冲突
3. **行级 INSERT 缺少 ON CONFLICT 处理**：如果恢复过程中存在主键冲突，整个表的恢复会失败
4. **双重 advisory lock**：`_restore_legacy_json` 内部也获取了 advisory lock，但 `_restore_from_zip` 在调用前已获取锁，导致嵌套锁

### 问题 4：`restore_db.py` 使用 MySQL 命令（HIGH）
`scripts/database/restore_db.py` 硬编码了 `MYSQL_PATH`，使用 `mysql.exe` 命令恢复，但系统实际使用 PostgreSQL 数据库。该脚本完全不可用。

### 问题 5：`_CHECKSUM_TABLES` 覆盖不全（MEDIUM）
当前 `_CHECKSUM_TABLES` 仅包含 21 个表，缺少以下核心业务表：
- `user`, `permission`, `user_permission`（用户管理/权限管理）
- `app_version`（版本管理）
- `daily_production_record`, `craft_work`, `packaging_record`（生产报表）
- `production_plan`, `production_plan_log`（排产计划）
- `stock_return`（退货管理）
- `order_status_log`, `order_sync_config`, `order_sync_record`（订单同步）
- `customer_access_log`（客户访问日志）
- `staging_order`, `staging_stock_in`, `staging_stock_out`（暂存数据）
- `purchase_plan`, `purchase_plan_detail`（采购计划）
- `product_fabric`, `product_material`, `product_accessory`, `product_packaging`（物料管理）

### 问题 6：异常处理不足（MEDIUM）
1. **无恢复前安全备份**：恢复操作直接 DROP DATABASE，如果恢复失败，原始数据已丢失且无法回滚
2. **无超时保护**：psql 恢复操作无超时限制，大数据库恢复可能无限挂起
3. **无进度反馈**：恢复过程中前端无法获知进度，用户可能误以为卡死而重复操作
4. **网络中断无处理**：大文件上传恢复时网络中断，无断点续传机制

### 问题 7：前端错误信息展示不足（LOW）
恢复失败时，前端仅显示 toast 消息中的 `e?.response?.data?.detail`，但后端返回的详细错误信息（如 `results.database.errors`、`results.warnings`）未在 UI 中完整展示。

## ADDED Requirements

### Requirement: 增量备份与恢复 API
系统 SHALL 提供增量备份和恢复的完整 API 端点实现，与前端 `backupApi` 的调用接口一致。

#### Scenario: 增量备份成功
- **WHEN** 用户点击"增量备份"按钮
- **THEN** 系统仅备份自上次全量备份以来变更的数据，返回备份文件名和变更行数

#### Scenario: 增量恢复成功
- **WHEN** 用户从服务器备份列表选择增量备份并点击恢复
- **THEN** 系统以 UPSERT 模式合并数据，不删除现有数据

### Requirement: 恢复前安全备份
系统 SHALL 在执行任何恢复操作前，自动创建当前数据库的安全备份，确保恢复失败时可回滚。

#### Scenario: 恢复前自动备份
- **WHEN** 用户确认执行恢复操作
- **THEN** 系统先自动创建一个标记为 `pre_restore_` 前缀的安全备份，再执行恢复

#### Scenario: 恢复失败回滚
- **WHEN** 恢复操作失败
- **THEN** 系统自动从安全备份还原数据，并向用户报告失败原因

### Requirement: psql 恢复流程健壮性
系统 SHALL 确保 psql 恢复流程的连接管理、锁处理和错误恢复机制可靠。

#### Scenario: 连接池完全释放
- **WHEN** 执行 DROP DATABASE 前
- **THEN** 系统确保所有数据库连接已完全释放，包括重试机制和连接状态验证

#### Scenario: PostgreSQL 版本兼容
- **WHEN** 数据库版本低于 PostgreSQL 13
- **THEN** 系统使用不带 `WITH (FORCE)` 的 DROP DATABASE 语句，先终止连接再删除

#### Scenario: 恢复超时保护
- **WHEN** psql 恢复执行超过 600 秒
- **THEN** 系统终止恢复进程并报告超时错误

### Requirement: Legacy JSON 恢复修复
系统 SHALL 修复 JSON 格式恢复中的外键约束、参数命名和冲突处理问题。

#### Scenario: 外键约束正确处理
- **WHEN** 恢复包含外键关联的表数据
- **THEN** 系统按正确的依赖顺序先禁用外键约束，恢复数据后重新启用

#### Scenario: 主键冲突处理
- **WHEN** 恢复的数据与现有数据存在主键冲突
- **THEN** 系统使用 UPSERT（ON CONFLICT DO UPDATE）策略处理

### Requirement: 完整的校验表覆盖
系统 SHALL 确保所有核心业务表都包含在恢复验证的校验表列表中。

#### Scenario: 新增表自动纳入校验
- **WHEN** 系统添加新的数据库模型表
- **THEN** 该表自动纳入恢复后的行数和指纹校验

### Requirement: 恢复进度反馈
系统 SHALL 提供恢复操作的进度反馈机制。

#### Scenario: 恢复进度展示
- **WHEN** 恢复操作执行中
- **THEN** 前端显示当前恢复阶段（备份数据库→终止连接→重建数据库→恢复数据→验证完整性）

## MODIFIED Requirements

### Requirement: 数据恢复功能
原恢复功能直接 DROP DATABASE 并从备份恢复，现修改为：
1. 恢复前自动创建安全备份
2. 增加连接释放重试机制（最多 3 次，每次间隔 1 秒）
3. 增加 PostgreSQL 版本检测，兼容 13 以下版本
4. 增加 psql 恢复超时保护（600 秒）
5. 恢复失败时自动从安全备份回滚
6. 正确释放 advisory lock

### Requirement: 增量备份功能
原前端定义了增量备份 API 调用但后端无实现，现补充完整后端实现：
1. 增量备份基于时间戳比对，仅导出变更行
2. 增量恢复使用 UPSERT 模式，不删除现有数据
3. 增量备份文件格式与全量备份一致（ZIP），manifest 中标记 `type: incremental`

## REMOVED Requirements

### Requirement: MySQL 恢复脚本
**Reason**: 系统使用 PostgreSQL 数据库，`restore_db.py` 中的 MySQL 恢复逻辑完全不可用
**Migration**: 将 `restore_db.py` 重写为 PostgreSQL 版本，与 `db_manager.py` 保持一致
