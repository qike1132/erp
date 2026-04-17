# ERP系统数据库备份与恢复方案

**更新日期**: 2026-04-16
**数据库类型**: MySQL (已统一，不再支持SQLite)

---

## 1. 数据库配置

### 1.1 MySQL数据库配置
```env
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=erp_system
```

### 1.2 数据库路径
- **MySQL服务**: localhost:3306
- **数据库名称**: erp_system
- **备份目录**: `d:\erp_system\backups\`

---

## 2. 数据库备份

### 2.1 备份命令

**使用数据库管理工具（推荐）**：
```bash
python scripts/database/db_manager.py backup
```

**使用快速备份脚本**：
```bash
python scripts/database/quick_backup.py
```

**手动备份**：
```bash
"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe" -u root -p110110 --single-transaction --routines --triggers erp_system > backup.sql
```

### 2.2 备份文件存储

**备份位置**: `d:\erp_system\backups\manual\`

**命名规范**:
```
erp_system_backup_YYYYMMDD_HHmmss.sql
```

### 2.3 备份类型

| 类型 | 目录 | 说明 |
|------|------|------|
| daily | backups/daily/ | 每日备份 |
| weekly | backups/weekly/ | 每周备份 |
| monthly | backups/monthly/ | 每月备份 |
| manual | backups/manual/ | 手动备份 |

---

## 3. 数据库恢复

### 3.1 恢复前准备
1. 确认MySQL服务正在运行
2. 对当前数据库进行最终备份
3. 确认有足够的磁盘空间

### 3.2 恢复命令

**使用Python脚本**：
```bash
python scripts/database/db_manager.py restore --file "backups/manual/erp_system_backup_YYYYMMDD_HHmmss.sql"
```

**手动恢复**：
```bash
"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe" -u root -p110110 erp_system < backup.sql
```

---

## 4. 备份验证

### 4.1 验证备份文件
```bash
python scripts/database/db_manager.py verify --file backups/manual/erp_system_backup_YYYYMMDD_HHmmss.sql
```

### 4.2 恢复到测试库验证
```bash
# 创建测试数据库
mysql -u root -p110110 -e "CREATE DATABASE erp_system_test"

# 恢复到测试数据库
mysql -u root -p110110 erp_system_test < backup.sql

# 验证数据
mysql -u root -p110110 erp_system_test -e "SELECT COUNT(*) FROM product"
```

---

## 5. 安全措施

### 5.1 备份完整性
- 备份后验证文件大小和内容
- 定期进行恢复演练

### 5.2 访问控制
- 限制备份目录访问权限
- 不在代码中硬编码密码

### 5.3 备份管理
- 定期清理过期备份
- 异地存储重要备份

---

## 6. 相关脚本

| 脚本 | 用途 |
|------|------|
| `scripts/database/db_manager.py` | 数据库管理工具（备份/恢复/验证） |
| `scripts/database/quick_backup.py` | 快速备份脚本 |
| `scripts/database/test_connection.py` | 数据库连接测试 |
| `scripts/database/restore_test.py` | 备份恢复测试 |

---

## 7. 快速参考

| 操作 | 命令 |
|------|------|
| 备份 | `python scripts/database/quick_backup.py` |
| 恢复 | `python scripts/database/db_manager.py restore --file <backup_file>` |
| 验证 | `python scripts/database/test_connection.py` |
| 列出备份 | `python scripts/database/db_manager.py list` |

---

**注意**: 本系统已统一使用MySQL，不再支持SQLite。
