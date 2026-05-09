# Tasks

- [x] Task 1: 实现增量备份与恢复 API 端点（BLOCKER）
  - [x] SubTask 1.1: 在 `backup.py` 中实现 `POST /save-incremental` 端点，基于时间戳比对导出变更行，生成 ZIP 格式增量备份（manifest 中 `type: incremental`）
  - [x] SubTask 1.2: 在 `backup.py` 中实现 `POST /restore-incremental/{filename}` 端点，使用 UPSERT 模式合并增量数据
  - [x] SubTask 1.3: 验证前端 `backupApi.saveIncremental` 和 `backupApi.restoreIncremental` 调用与后端端点匹配

- [x] Task 2: 修复 psql 恢复流程的连接池与锁管理（BLOCKER）
  - [x] SubTask 2.1: 增加连接释放重试机制：在 `_restore_database_via_psql` 中，dispose 后重试最多 3 次检查活跃连接数，每次间隔 1 秒
  - [x] SubTask 2.2: 增加 PostgreSQL 版本检测：获取 PG 版本号，低于 13 时先 `pg_terminate_backend` 终止连接再 `DROP DATABASE`，不使用 `WITH (FORCE)`
  - [x] SubTask 2.3: 修复 advisory lock 释放：psql 恢复后在新数据库会话中显式释放锁
  - [x] SubTask 2.4: 增加 psql 恢复超时保护：为 `proc.communicate` 设置 600 秒超时
  - [x] SubTask 2.5: 增强 `_dispose_and_reinit_pool` 的错误处理和日志记录，确保重建失败时有明确错误信息

- [x] Task 3: 修复 Legacy JSON 恢复缺陷（HIGH）
  - [x] SubTask 3.1: 在 `_restore_legacy_json` 中添加外键约束禁用/启用逻辑：恢复前 `SET session_replication_role = 'replica'`，恢复后 `SET session_replication_role = 'origin'`
  - [x] SubTask 3.2: 修复参数命名冲突：将 `{col}_{inserted}` 改为 `{col}__row{inserted}` 格式，避免与列名数字后缀冲突
  - [x] SubTask 3.3: 将行级 INSERT 改为批量 INSERT 并添加 ON CONFLICT 处理
  - [x] SubTask 3.4: 移除 `_restore_legacy_json` 中的双重 advisory lock（外层 `_restore_from_zip` 已获取锁）

- [x] Task 4: 增加恢复前安全备份机制（HIGH）
  - [x] SubTask 4.1: 在 `_restore_from_zip` 和 `import_backup` 中，恢复前自动调用 `_execute_backup_to_zip` 创建 `pre_restore_` 前缀的安全备份
  - [x] SubTask 4.2: 恢复失败时自动从安全备份回滚
  - [x] SubTask 4.3: 安全备份保存到 `BACKUP_DIR / 'pre_restore'` 目录

- [x] Task 5: 扩展 `_CHECKSUM_TABLES` 覆盖所有核心业务表（MEDIUM）
  - [x] SubTask 5.1: 将所有 `Base.metadata.sorted_tables` 中的表名自动纳入校验范围，替代硬编码的 `_CHECKSUM_TABLES`
  - [x] SubTask 5.2: 确保新增模型表自动纳入恢复验证

- [x] Task 6: 修复 `restore_db.py` 脚本（HIGH）
  - [x] SubTask 6.1: 将 `restore_db.py` 从 MySQL 实现改为 PostgreSQL 实现，使用 `psql` 命令
  - [x] SubTask 6.2: 支持 .sql.gz 压缩文件的自动解压恢复
  - [x] SubTask 6.3: 支持 ZIP 格式备份文件的恢复

- [x] Task 7: 增强前端错误信息展示与恢复进度（MEDIUM）
  - [x] SubTask 7.1: 在恢复结果区域完整展示后端返回的 `results.database.errors`、`results.warnings` 等详细信息
  - [x] SubTask 7.2: 增加恢复阶段进度指示（备份数据库→终止连接→重建数据库→恢复数据→验证完整性）
  - [x] SubTask 7.3: 增量备份/恢复按钮增加加载状态和错误提示

- [x] Task 8: 端到端功能验证测试
  - [x] SubTask 8.1: 验证全量备份（ZIP 格式）创建成功，包含所有板块数据
  - [x] SubTask 8.2: 验证全量恢复（从 ZIP 文件）成功，数据完整一致
  - [x] SubTask 8.3: 验证增量备份创建成功
  - [x] SubTask 8.4: 验证增量恢复（UPSERT 模式）成功
  - [x] SubTask 8.5: 验证恢复前安全备份自动创建
  - [x] SubTask 8.6: 验证恢复后数据一致性（L1 行数 + L2 指纹 + L3 抽样）
  - [x] SubTask 8.7: 验证 Legacy JSON 格式备份的恢复
  - [x] SubTask 8.8: 验证异常场景（恢复中断电/网络异常后的系统状态）

# Task Dependencies
- [Task 2] depends on [Task 4] (安全备份应先于恢复流程修复实现)
- [Task 3] depends on [Task 4] (安全备份应先于 JSON 恢复修复实现)
- [Task 8] depends on [Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7]
- [Task 1] and [Task 6] can be parallelized
- [Task 5] and [Task 7] can be parallelized
