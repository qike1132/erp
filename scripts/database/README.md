# 数据库管理工具使用说明

## 概述

本目录包含ERP系统的数据库管理工具，支持数据库备份、验证、恢复等功能。

> **生产环境的备份与恢复不走这里。** 应用内「备份中心」由 `fastapi_app/services/backup/`
> 实现（`pg_dump` + 分片加密 + 增量），设计说明见 `docs/backup-restore/备份与恢复模块设计方案.md`。
> 本目录脚本仅用于人工排障、只读副本搭建与切换演练。

## 文件说明

| 文件 | 说明 |
|------|------|
| `db_manager.py` | 手动备份/恢复/校验脚本（PostgreSQL 优先，保留 MySQL 兼容分支） |
| `db_backup.bat` | Windows 手动备份入口，内部调用 `db_manager.py backup --type manual` |
| `restore_core.py` | **恢复逻辑的唯一实现**（恢复前备份 / DROP+CREATE / psql 导入 / 落地校验） |
| `restore_db.py` | 由备份产物恢复的 CLI（薄封装：取参数 → 取写库授权 → 调 `restore_core`） |
| `failover_drill.sh` | 主备切换演练 |
| `setup_read_replica.sh` | 只读副本搭建 |
| `setup_replication.sql` | 流复制初始化 SQL |
| `pg_stat_statements_setup.sql` | 慢查询统计扩展启用 |
| `README.md` | 本使用说明 |

## 恢复：唯一实现与不可协商的四条（审计 F1-7）

`restore_db.py` 与 `db_manager.py restore` 走的是**同一份**恢复实现
（`restore_core.py`）。恢复行为只允许改 `restore_core.py`；两个入口只负责
「准备输入 → 调用 → 汇报结果」。收敛前两边各持一套且互不调用，任何修复只会落在
一侧、漏到另一侧没人发现（P1-34「恢复假成功 + 无恢复前备份」就是这么漏的）。

`restore_core.py` 的四条硬约束：

1. **恢复前备份 fail-closed** —— DROP DATABASE 之前必须先有一份非空 `pg_dump`
   产物，否则中止（这是唯一的回退手段）。确实没有备份时要继续，必须显式加
   `--allow-missing-pre-restore-backup`。
2. **psql 一律 `ON_ERROR_STOP=1`** —— 该选项为 0 时 SQL 错误不会让 psql 返回
   非零退出码，失败判定会假绿。
3. **恢复后校验落地** —— psql 退出码为 0 不代表数据真的进去了（dump 本身可能是
   空的），必须查 `public` schema 的表数，为 0 判失败。
4. **写生产库需显式授权** —— 走 `scripts/_prod_write_guard`：
   `ERP_ALLOW_PROD_WRITE=1` 或命令行 `--allow-prod-write`，二者缺一即拒绝执行。

```bash
# 恢复（需显式授权写库）
python scripts/database/restore_db.py --allow-prod-write <备份文件路径>
```

支持格式：`.sql`（流式导入）、`.sql.gz`、`.zip`（内含 `database/dump.sql.gz`）。
ZIP 内若是 JSON 格式导出会明确报错——那种只能用 Web 界面恢复。

## 功能特性

- ✅ 支持 PostgreSQL（生产使用）；MySQL 分支仅为历史兼容
- ✅ 自动压缩备份文件（gzip格式）
- ✅ 备份文件完整性验证
- ✅ SHA-256校验和生成
- ✅ 备份清单管理
- ✅ 多类型备份（每日/每周/每月/手动）
- ✅ 数据库恢复功能
- ✅ 备份文件列表查看

## 使用方法

### 前置要求

1. Python 3.7+
2. 项目虚拟环境已激活或已安装依赖

### 命令说明

#### 1. 数据库备份

```bash
# 基本备份（手动类型，自动压缩）
python scripts/database/db_manager.py backup

# 指定备份类型
python scripts/database/db_manager.py backup --type daily
python scripts/database/db_manager.py backup --type weekly
python scripts/database/db_manager.py backup --type monthly
python scripts/database/db_manager.py backup --type manual

# 不压缩备份
python scripts/database/db_manager.py backup --no-compress
```

**备份类型说明**：
- `daily`: 每日备份（存储在 `backups/daily/`）
- `weekly`: 每周备份（存储在 `backups/weekly/`）
- `monthly`: 每月备份（存储在 `backups/monthly/`）
- `manual`: 手动备份（存储在 `backups/manual/`）

#### 2. 验证备份文件

```bash
python scripts/database/db_manager.py verify --file <备份文件路径>
```

示例：
```bash
python scripts/database/db_manager.py verify --file backups/manual/erp_backup_20260416_120000.db.gz
```

#### 3. 恢复数据库

```bash
python scripts/database/db_manager.py restore --file <备份文件路径>
```

示例：
```bash
python scripts/database/db_manager.py restore --file backups/manual/erp_backup_20260416_120000.db.gz
```

**重要提示**：
- 恢复前会自动备份当前数据库
- 恢复操作会覆盖当前数据，请谨慎操作

#### 4. 列出所有备份

```bash
python scripts/database/db_manager.py list
```

### Windows快速备份

双击运行 `db_backup.bat` 即可快速执行手动备份。

## 备份目录结构

```
backups/
├── daily/          # 每日备份
├── weekly/         # 每周备份
├── monthly/        # 每月备份
├── manual/         # 手动备份
├── db_manager.log  # 操作日志
└── manifest_*.json # 备份清单文件
```

## 备份文件命名规则

**PostgreSQL 备份**：
```
erp_system_backup_YYYYMMDD_HHmmss.sql
erp_system_backup_YYYYMMDD_HHmmss.sql.gz (压缩后)
```

## 备份清单

每次备份会生成一个 `manifest_YYYYMMDD_HHmmss.json` 文件，包含：
- 备份时间戳
- 数据库类型
- 文件列表及大小
- SHA-256校验和

## 自动化备份建议

### Windows任务计划程序

1. 打开"任务计划程序"
2. 创建基本任务
3. 设置触发器（例如：每天凌晨2点）
4. 操作选择"启动程序"
5. 程序/脚本：`python.exe`
6. 添加参数：`scripts\database\db_manager.py backup --type daily`
7. 起始于：`d:\erp_system`

### 使用批处理脚本

创建 `daily_backup_task.bat`:
```batch
@echo off
cd /d d:\erp_system
call venv\Scripts\activate.bat
python scripts\database\db_manager.py backup --type daily
```

## 故障排除

### 问题：找不到Python虚拟环境

**解决方案**：
- 确保虚拟环境在 `venv/` 或 `.venv/` 目录
- 或者手动激活虚拟环境后运行

### 问题：备份失败（找不到 pg_dump / psql）

**解决方案**：
- 确认 PostgreSQL 客户端工具 `pg_dump` / `psql` 已安装且已在 PATH 中
- 检查 `.env` 中的 `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME`
- 确认数据库用户有 `CONNECT` 权限及目标表的读取权限

### 问题：备份文件损坏

**解决方案**：
- 使用 `verify` 命令验证备份文件
- 尝试使用更早的备份文件
- 检查磁盘空间和文件系统

## 安全建议

1. **定期验证备份**：每周至少验证一次备份文件的可用性
2. **异地备份**：将重要备份复制到其他位置或云存储
3. **访问控制**：限制备份目录的访问权限
4. **加密敏感数据**：对包含敏感信息的备份进行加密

## 更多信息

详细的备份与恢复方案请参考：

- [备份与恢复模块设计方案](../../docs/backup-restore/备份与恢复模块设计方案.md)
- [备份相关架构决策记录](../../docs/adr/2026-08-23-backup-adrs.md)
