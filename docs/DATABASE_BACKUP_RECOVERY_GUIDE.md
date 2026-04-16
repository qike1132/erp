# ERP系统数据库备份与恢复方案

## 目录
1. [数据库路径信息](#1-数据库路径信息)
2. [数据库备份方案](#2-数据库备份方案)
3. [数据库恢复流程](#3-数据库恢复流程)
4. [安全与完整性措施](#4-安全与完整性措施)

---

## 1. 数据库路径信息

### 1.1 数据库类型
本系统支持两种数据库类型：
- **SQLite**（默认开发环境）
- **MySQL**（推荐生产环境）

### 1.2 SQLite数据库路径
- **完整路径**: `d:\erp_system\erp.db`
- **相对路径**: `./erp.db`

### 1.3 MySQL数据库配置
MySQL配置通过环境变量或`.env`文件设置：
```env
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=erp_system
```

---

## 2. 数据库备份方案

### 2.1 备份工具与命令

#### 2.1.1 SQLite备份
由于SQLite是文件型数据库，备份非常简单：

**Python脚本备份**（推荐）：
```bash
python scripts/upgrade/backup.py --db-only
```

**手动备份**：
```powershell
# Windows
Copy-Item "d:\erp_system\erp.db" "d:\erp_system\backups\erp_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
```

#### 2.1.2 MySQL备份
使用`mysqldump`工具：

**完整备份命令**：
```bash
mysqldump -h localhost -P 3306 -u root -p --single-transaction --routines --triggers erp_system > erp_system_backup_$(date +%Y%m%d_%H%M%S).sql
```

**参数说明**：
- `--single-transaction`: 使用事务确保一致性
- `--routines`: 备份存储过程和函数
- `--triggers`: 备份触发器
- `-p`: 提示输入密码（推荐，避免密码暴露在命令历史中）

### 2.2 备份文件存储位置与命名规范

#### 2.2.1 存储目录结构
```
d:\erp_system\
├── backups\
│   ├── daily\          # 每日备份
│   ├── weekly\         # 每周备份
│   ├── monthly\        # 每月备份
│   └── manual\         # 手动备份
```

#### 2.2.2 命名规范
**SQLite备份文件命名**：
```
erp_backup_YYYYMMDD_HHmmss.db
```

**MySQL备份文件命名**：
```
erp_system_backup_YYYYMMDD_HHmmss.sql
```

**压缩备份文件命名**：
```
erp_backup_YYYYMMDD_HHmmss.db.gz
erp_system_backup_YYYYMMDD_HHmmss.sql.gz
```

### 2.3 备份策略建议

#### 2.3.1 开发环境
- **频率**: 每次重要更改前手动备份
- **保留**: 最近5个备份

#### 2.3.2 测试环境
- **频率**: 每日自动备份
- **保留**: 最近7天备份

#### 2.3.3 生产环境
- **每日备份**: 保留最近30天
- **每周备份**: 保留最近8周
- **每月备份**: 保留最近12个月

### 2.4 备份数据验证方法

#### 2.4.1 SQLite验证
1. **文件完整性检查**：
```python
import sqlite3
def verify_sqlite_backup(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        conn.close()
        return len(tables) > 0, f"验证成功，找到 {len(tables)} 个表"
    except Exception as e:
        return False, f"验证失败: {str(e)}"
```

2. **记录数验证**：对比关键表的记录数与源数据库

#### 2.4.2 MySQL验证
1. **SQL语法检查**：
```bash
mysql -u root -p --force --verbose < backup_file.sql
```

2. **恢复到临时数据库验证**：
```bash
mysql -u root -p -e "CREATE DATABASE erp_system_test;"
mysql -u root -p erp_system_test < backup_file.sql
mysql -u root -p -e "DROP DATABASE erp_system_test;"
```

---

## 3. 数据库恢复流程

### 3.1 恢复前检查清单
- [ ] 确认备份文件的完整性和有效性
- [ ] 停止所有应用服务
- [ ] 对当前数据库进行最终备份（以防万一）
- [ ] 确认有足够的磁盘空间
- [ ] 记录恢复开始时间

### 3.2 SQLite恢复流程

#### 步骤1：停止应用服务
```powershell
# 停止所有相关进程
Get-Process | Where-Object {$_.Path -like "*erp_system*"} | Stop-Process -Force
```

#### 步骤2：备份当前数据库
```powershell
Copy-Item "d:\erp_system\erp.db" "d:\erp_system\backups\erp_pre_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
```

#### 步骤3：恢复备份文件
```powershell
Copy-Item "d:\erp_system\backups\manual\erp_backup_20260416_120000.db" "d:\erp_system\erp.db"
```

#### 步骤4：验证恢复
```python
# 运行验证脚本
python scripts/database/verify_db.py
```

#### 步骤5：启动应用服务

### 3.3 MySQL恢复流程

#### 步骤1：停止应用服务
同上

#### 步骤2：备份当前数据库
```bash
mysqldump -u root -p --single-transaction erp_system > pre_restore_backup.sql
```

#### 步骤3：删除并重建数据库
```bash
mysql -u root -p -e "DROP DATABASE IF EXISTS erp_system; CREATE DATABASE erp_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

#### 步骤4：恢复备份
```bash
mysql -u root -p erp_system < erp_system_backup_20260416_120000.sql
```

#### 步骤5：验证恢复
```bash
mysql -u root -p erp_system -e "SHOW TABLES; SELECT COUNT(*) FROM users;"
```

#### 步骤6：启动应用服务

---

## 4. 安全与完整性措施

### 4.1 备份完整性保障
1. **校验和验证**：为每个备份文件生成SHA-256校验和
   ```powershell
   Get-FileHash -Algorithm SHA256 "erp_backup.db" | Format-List
   ```

2. **备份加密**：对敏感数据的备份进行加密
   ```powershell
   # 使用7-Zip加密
   7z a -p"your_secure_password" erp_backup_encrypted.7z erp_backup.db
   ```

### 4.2 备份安全措施
1. **访问控制**：限制备份目录的访问权限
2. **异地备份**：定期将备份复制到远程存储或云存储
3. **备份生命周期管理**：自动清理过期备份
4. **日志记录**：记录所有备份和恢复操作

### 4.3 自动化备份
可以使用Windows任务计划程序或cron实现自动化备份：

**Windows任务计划程序示例**：
```powershell
# 创建每日备份任务
$action = New-ScheduledTaskAction -Execute "python.exe" -Argument "scripts/upgrade/backup.py --db-only"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "ERP_DB_Daily_Backup" -Description "ERP系统数据库每日备份"
```

---

## 附录：快速参考

### 常用命令速查
| 操作 | SQLite | MySQL |
|------|--------|-------|
| 备份 | `python scripts/upgrade/backup.py --db-only` | `mysqldump -u root -p erp_system > backup.sql` |
| 恢复 | 直接复制文件 | `mysql -u root -p erp_system < backup.sql` |
| 验证 | 检查文件完整性 | 恢复到测试库 |

### 故障排除
- **备份失败**: 检查磁盘空间、文件权限、数据库连接
- **恢复失败**: 验证备份文件完整性、检查数据库版本兼容性
- **数据损坏**: 使用更早的备份文件，或尝试数据库修复工具

---

**文档版本**: v1.0
**创建日期**: 2026-04-16
**最后更新**: 2026-04-16
