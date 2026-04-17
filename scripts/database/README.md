# 数据库管理工具使用说明

## 概述

本目录包含ERP系统的数据库管理工具，支持数据库备份、验证、恢复等功能。

## 文件说明

| 文件 | 说明 |
|------|------|
| `db_manager.py` | 主数据库管理脚本（Python） |
| `db_backup.bat` | Windows快速备份脚本 |
| `README.md` | 本使用说明 |

## 功能特性

- ✅ 支持 MySQL 数据库
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

**MySQL备份**：
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

### 问题：MySQL备份失败

**解决方案**：
- 确保MySQL已安装并在PATH中
- 检查 `.env` 文件中的数据库配置
- 确认数据库用户有足够权限

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
[数据库备份与恢复指南](../../docs/DATABASE_BACKUP_RECOVERY_GUIDE.md)
