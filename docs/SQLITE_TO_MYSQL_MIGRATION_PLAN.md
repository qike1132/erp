# ERP系统 SQLite 到 MySQL 统一迁移方案

**文档版本**: v1.0
**创建日期**: 2026-04-16
**目标**: 统一使用MySQL作为唯一数据库

---

## 1. 现状分析

### 1.1 当前数据库配置

根据分析，项目当前配置：
- **默认类型**: `DB_TYPE=mysql`（已配置）
- **环境变量读取**: Flask和FastAPI都支持通过`DB_TYPE`环境变量切换
- **SQLite fallback**: 部分代码仍保留SQLite作为备用选项

### 1.2 SQLite代码分布

| 序号 | 文件路径 | SQLite相关代码 | 修改方式 |
|------|----------|----------------|----------|
| 1 | `app/__init__.py` | `get_database_uri()` 返回 `sqlite:///erp.db` | 删除SQLite分支 |
| 2 | `fastapi_app/core/config.py` | fallback返回 `sqlite:///:memory:` | 删除fallback |
| 3 | `fastapi_app/core/database.py` | 无直接SQLite | 无需修改 |
| 4 | `scripts/upgrade/backup.py` | SQLite备份逻辑 | 删除SQLite备份 |
| 5 | `scripts/upgrade/rollback.py` | SQLite回滚逻辑 | 删除SQLite回滚 |
| 6 | `scripts/database/db_manager.py` | SQLite备份/恢复/验证 | 删除SQLite相关方法 |
| 7 | `scripts/database/verify_backup.py` | `import sqlite3` | 移除导入 |
| 8 | `docs/DATABASE_BACKUP_RECOVERY_GUIDE.md` | SQLite说明 | 更新文档 |
| 9 | `tests/*.py` | `sqlite:///:memory:` | **保留**（测试用） |

---

## 2. 迁移步骤

### 阶段一：配置统一（高优先级）

#### 步骤1.1: 更新 `app/__init__.py`

**文件**: `d:\erp_system\app\__init__.py`

**当前代码** (行298-318):
```python
def get_database_uri():
    """获取数据库URI"""
    db_type = os.getenv('DB_TYPE', 'sqlite')

    if db_type == 'mysql':
        # ... MySQL逻辑
    else:
        return 'sqlite:///erp.db'  # <-- 删除此分支
```

**修改为**:
```python
def get_database_uri():
    """获取数据库URI - 仅支持MySQL"""
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '3306')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    db_name = os.getenv('DB_NAME', 'erp_system')

    if os.environ.get('FLASK_ENV') == 'production':
        if not db_user or not db_password:
            raise RuntimeError("PRODUCTION ERROR: DB_USER and DB_PASSWORD must be set!")

    db_user = db_user or 'root'
    db_password = db_password or ''

    return f'mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4'
```

#### 步骤1.2: 更新 `fastapi_app/core/config.py`

**文件**: `d:\erp_system\fastapi_app\core\config.py`

**当前代码** (行14-23):
```python
def _build_database_uri() -> str:
    db_type = os.getenv("DB_TYPE", "mysql")
    if db_type == "mysql":
        # ... MySQL逻辑
        return f"mysql+pymysql://..."
    # sqlite fallback  <-- 删除此分支
    return "sqlite:///:memory:"
```

**修改为**:
```python
def _build_database_uri() -> str:
    """构建MySQL数据库URI"""
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "3306")
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "erp_system")
    return f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
```

---

### 阶段二：脚本清理（中优先级）

#### 步骤2.1: 更新 `scripts/upgrade/backup.py`

**文件**: `d:\erp_system\scripts\upgrade\backup.py`

**删除内容**:
- 行102-139: SQLite备份逻辑（`backup_database`方法中的else分支）
- `db_file = PROJECT_ROOT / 'erp.db'` 相关代码

#### 步骤2.2: 更新 `scripts/upgrade/rollback.py`

**文件**: `d:\erp_system\scripts\upgrade\rollback.py`

**删除内容**:
- 行80-158: SQLite回滚逻辑

#### 步骤2.3: 更新 `scripts/database/db_manager.py`

**文件**: `d:\erp_system\scripts\database\db_manager.py`

**删除方法**:
- `get_sqlite_path()` - 行75-77
- `backup_sqlite()` - 行143-164
- `verify_sqlite()` - 行238-279
- `restore_sqlite()` - 行330-351

**修改 `backup()` 方法**: 移除 `db_type == 'sqlite'` 判断分支

**修改 `verify()` 方法**: 移除 `verify_sqlite` 调用

**修改 `restore()` 方法**: 移除 `restore_sqlite` 调用

#### 步骤2.4: 更新 `scripts/database/verify_backup.py`

**文件**: `d:\erp_system\scripts\database\verify_backup.py`

**修改内容**:
- 删除行2: `import sqlite3`
- 整个文件可考虑删除或仅保留MySQL验证逻辑

---

### 阶段三：文档更新（低优先级）

#### 步骤3.1: 更新 `docs/DATABASE_BACKUP_RECOVERY_GUIDE.md`

**删除内容**:
- SQLite相关说明（行15, 18-20, 39-40, 80, 113-126, 155-158, 246）
- 所有对比表格中的SQLite列

**保留内容**:
- MySQL备份/恢复完整说明
- 命令速查表

---

### 阶段四：测试配置（特殊处理）

#### 步骤4.1: 测试文件处理

**重要**: 测试文件中的 `sqlite:///:memory:` **不应删除或修改**

**原因**:
- 测试使用内存数据库可以提高测试速度
- 测试环境与生产环境隔离是正确的实践
- 测试不需要真实的MySQL连接

**建议**: 保留现状，不修改测试文件

---

## 3. 数据迁移

### 3.1 当前数据状态

根据之前的操作：
- ✅ MySQL数据库 `erp_system` 已创建
- ✅ 备份文件 `erp_system_backup_20260416_091519.sql` 已恢复到MySQL
- ✅ 数据完整性已验证（58个表，包含完整业务数据）

### 3.2 如需迁移旧的SQLite数据

如果存在旧的 `erp.db` 文件需要迁移：

```bash
# 1. 备份当前MySQL数据（以防万一）
python scripts/database/quick_backup.py

# 2. 使用Python脚本转换SQLite到MySQL
# (需要开发专门的迁移脚本)
```

---

## 4. 验证清单

### 4.1 配置验证

| 检查项 | 验证方法 | 预期结果 |
|--------|----------|----------|
| MySQL服务运行 | `Get-Service MySQL84` | Status: Running |
| 数据库存在 | `mysql -u root -p -e "SHOW DATABASES LIKE 'erp_system'"` | 显示erp_system |
| 表数据完整 | `python scripts/database/test_connection.py` | 6/6测试通过 |
| Flask连接 | 启动Flask应用 | 无SQLite相关错误 |
| FastAPI连接 | 启动FastAPI应用 | 无SQLite相关错误 |

### 4.2 代码验证

| 检查项 | 验证方法 |
|--------|----------|
| 无硬编码SQLite | `grep -r "sqlite:///" --include="*.py" | grep -v test | grep -v :memory:` |
| 无erp.db引用 | `grep -r "erp.db" --include="*.py" | grep -v test` |
| DB_TYPE已废弃 | 检查代码中无 `DB_TYPE` 环境变量读取 |

---

## 5. 风险评估

### 5.1 高风险项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 测试环境失败 | 测试无法运行 | 保留 `:memory:` SQLite用于测试 |
| 回滚脚本失效 | 升级回滚失败 | 预先完整备份 |

### 5.2 中风险项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 文档不一致 | 用户困惑 | 更新所有相关文档 |

### 5.3 低风险项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 第三方skills提及SQLite | 无实际影响 | 无需处理 |

---

## 6. 实施计划

### 6.1 推荐执行顺序

```
阶段一：配置统一
  ├─ 步骤1.1: app/__init__.py
  └─ 步骤1.2: fastapi_app/core/config.py

阶段二：脚本清理
  ├─ 步骤2.1: scripts/upgrade/backup.py
  ├─ 步骤2.2: scripts/upgrade/rollback.py
  ├─ 步骤2.3: scripts/database/db_manager.py
  └─ 步骤2.4: scripts/database/verify_backup.py

阶段三：文档更新
  └─ 步骤3.1: 更新DATABASE_BACKUP_RECOVERY_GUIDE.md

阶段四：验证
  └─ 执行验证清单
```

### 6.2 预计工作量

| 阶段 | 文件数 | 预计修改行数 |
|------|--------|--------------|
| 阶段一 | 2 | ~30行 |
| 阶段二 | 4 | ~150行 |
| 阶段三 | 1 | ~100行 |
| 阶段四 | - | 验证步骤 |

---

## 7. 后续建议

1. **废弃DB_TYPE环境变量**: 考虑在未来的版本中完全移除`DB_TYPE`变量的支持
2. **更新.env.example**: 移除SQLite相关注释
3. **添加数据库健康检查**: 在应用启动时验证MySQL连接
4. **文档清理**: 移除所有提及SQLite的文档

---

## 8. 附录

### 8.1 关键文件路径

| 文件 | 绝对路径 |
|------|----------|
| Flask配置 | `d:\erp_system\app\__init__.py` |
| FastAPI配置 | `d:\erp_system\fastapi_app\core\config.py` |
| 备份脚本 | `d:\erp_system\scripts\upgrade\backup.py` |
| 回滚脚本 | `d:\erp_system\scripts\upgrade\rollback.py` |
| 数据库管理 | `d:\erp_system\scripts\database\db_manager.py` |
| 备份恢复指南 | `d:\erp_system\docs\DATABASE_BACKUP_RECOVERY_GUIDE.md` |

### 8.2 相关文档

- [数据库连接配置报告](../../docs/DB_CONNECTION_REPORT.md)
- [备份恢复测试报告](../../docs/BACKUP_RESTORE_TEST_REPORT.md)

---

**方案编制完成时间**: 2026-04-16 09:40
