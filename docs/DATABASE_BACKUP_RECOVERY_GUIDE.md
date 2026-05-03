# ERP系统数据库备份与恢复方案

**更新日期**: 2026-05-01
**数据库类型**: PostgreSQL（兼容 MySQL）
**备份系统版本**: v3.0

---

## 1. 系统概述

ERP 系统采用 **FastAPI + PostgreSQL** 技术栈，备份系统支持两种方式：

| 方式 | 文件 | 适用场景 |
|------|------|----------|
| **Web API** | `fastapi_app/api/v1/endpoints/backup.py` | 通过 HTTP 接口操作，支持 ZIP 全量备份 |
| **CLI 工具** | `scripts/database/db_manager.py` | 命令行操作，支持 pg_dump/mysqldump 原始 SQL |

### 1.1 数据库配置

- **PostgreSQL 服务**: localhost:5432
- **数据库名称**: erp_system
- **API 备份目录**: `backups/server/`（可配置 `BACKUP_DIR` 环境变量）
- **CLI 备份目录**: `backups/` 下的 daily / weekly / monthly / manual 子目录

---

## 2. 全量备份（Full Backup）

### 2.1 Web API 方式

**备份到服务器**：
```bash
curl -X POST "http://localhost:5002/api/v1/backup/save" \
  -H "Authorization: Bearer <token>" \
  -d "remark=手动全量备份"
```

**下载备份文件**：
```bash
curl "http://localhost:5002/api/v1/backup/export?format=zip" \
  -H "Authorization: Bearer <token>" \
  -o erp_backup.zip
```

### 2.2 CLI 方式

```bash
# 手动备份
python scripts/database/db_manager.py backup

# 按类型备份
python scripts/database/db_manager.py backup --type daily
python scripts/database/db_manager.py backup --type weekly
python scripts/database/db_manager.py backup --type monthly
```

### 2.3 备份包结构（ZIP 格式 v2.0）

```
erp_backup_YYYYMMDD_HHMMSS.zip
├── manifest.json              # 元数据清单（版本、表数、行数、SHA256、指纹）
├── database/
│   └── dump.sql.gz           # pg_dump PostgreSQL 导出（gzip 压缩）
├── filestore/                # static/uploads/ 全量附件打包
├── config/                   # 关键配置文件（JWT密钥、.env、nginx等）
└── redis/
    └── dump.rdb              # Redis 快照
```

**manifest.json 关键字段**：
```json
{
  "version": "2.0",
  "type": "full",
  "exported_at": "2026-05-01 12:00:00",
  "exported_by": "admin",
  "table_count": 35,
  "total_rows": 100000,
  "tables": { "order": {"rows": 500}, "product": {"rows": 150}, ... },
  "checksums": { "database/dump.sql.gz": "<SHA256>" },
  "fingerprints": { "order": "<MD5>", "product": "<MD5>", ... }
}
```

---

## 3. 全量恢复与验证（核心）

### 3.1 恢复流程

**Web API 恢复**（从服务器备份文件）：
```bash
curl -X POST "http://localhost:5002/api/v1/backup/restore-by-name/erp_backup_20260501_120000.zip?confirm=true" \
  -H "Authorization: Bearer <token>"
```

**Web API 恢复**（从上传文件）：
```bash
curl -X POST "http://localhost:5002/api/v1/backup/import?confirm=true" \
  -H "Authorization: Bearer <token>" \
  -F "file=@erp_backup.zip"
```

**CLI 恢复**：
```bash
python scripts/database/db_manager.py restore --file backups/manual/erp_system_backup_20260501_120000.sql.gz
```

### 3.2 四层恢复验证机制

恢复完成后，系统自动执行四层数据完整性校验，**杜绝"假恢复"**：

| 层级 | 验证方式 | 验证内容 | 判定标准 |
|------|---------|---------|---------|
| **L0** | 数据库全局 MD5 校验和 | 对所有非空表的完整数据逐行计算 MD5，合并为全局哈希 | 与备份时 manifest 中的 db_checksum 比对 |
| **L1** | 表行数比对 | `SELECT COUNT(*)` 逐个表比对 | 每个表的行数必须与 manifest 中一致 |
| **L2** | 业务表数据指纹 | 对 20+ 个关键业务表的全部数据行做 MD5 聚合 | 指纹必须与备份时 manifest.fingerprints 中一致 |
| **L3** | ID 抽样检查 | 每个表的 top 3 ID 是否存在 | 确认主键数据可正常访问 |

**验证结果返回格式**：
```json
{
  "overall_pass": true,
  "verification_verdict": "通过",
  "l0_global_checksum": {
    "db_checksum": "a1b2c3d4...",
    "tables_contributed": 25
  },
  "l1_row_count": {
    "total_tables": 35,
    "verifiable_tables": 35,
    "match": 35,
    "mismatch": [],
    "pass_rate_pct": 100.0,
    "summary": "行数匹配: 35/35 (100.0%)"
  },
  "l2_fingerprint": {
    "tables_checked": 18,
    "match": 18,
    "mismatch": [],
    "summary": "指纹匹配: 18/18"
  },
  "l3_sampling": {
    "tables_checked": 30,
    "results": [...]
  }
}
```

### 3.3 验证失败处理

- **L1 失败**（行数不匹配）：标记 `overall_pass: false`，列出所有不匹配的表及差异
- **L2 失败**（指纹不匹配）：标记 `overall_pass: false`，意味着数据内容与备份时不一致
- **L0 仅供参考**：全局哈希通常与备份时比对，在恢复验证时计算当前库的全局哈希供人工比对

---

## 4. 备份管理

### 4.1 查看备份列表

**Web API**：
```bash
curl "http://localhost:5002/api/v1/backup/list" -H "Authorization: Bearer <token>"
```

**CLI**：
```bash
python scripts/database/db_manager.py list
```

### 4.2 验证备份文件（不恢复）

```bash
curl -X POST "http://localhost:5002/api/v1/backup/validate" \
  -H "Authorization: Bearer <token>" \
  -F "file=@erp_backup.zip"
```

### 4.3 删除备份

```bash
curl -X DELETE "http://localhost:5002/api/v1/backup/delete-by-name/erp_backup_20260401.zip" \
  -H "Authorization: Bearer <token>"
```

### 4.4 清理过期备份

```bash
# 仅保留最近 7 天
python scripts/database/db_manager.py cleanup --keep 7

# 预览模式（不实际删除）
python scripts/database/db_manager.py cleanup --keep 7 --dry-run
```

### 4.5 备份状态概览

```bash
curl "http://localhost:5002/api/v1/backup/status" -H "Authorization: Bearer <token>"
```

返回最近的全量备份信息、备份总数、总大小、校验和表配置等。

---

## 5. 安全措施

### 5.1 权限控制
- 所有备份/恢复操作需要 `backup_manage` 权限
- 恢复操作需要 `confirm=true` 二次确认

### 5.2 并发保护
- 恢复操作使用 PostgreSQL Advisory Lock（ID: 20240426），防止并发恢复

### 5.3 数据完整性
- SHA256 校验和确保备份文件未被篡改
- 四层恢复验证机制确保数据 100% 恢复
- 恢复前自动创建 pre-restore 备份，防止误操作

### 5.4 性能考虑
- pg_dump 使用 `--no-owner --no-privileges` 减少导出开销
- 备份使用 gzip 快速压缩（level 1）减少 I/O

---

## 6. 相关文件

| 文件 | 用途 |
|------|------|
| `fastapi_app/api/v1/endpoints/backup.py` | Web API 备份/恢复/验证核心实现 |
| `fastapi_app/core/database.py` | 数据库连接管理（PostgreSQL asyncpg） |
| `fastapi_app/core/config.py` | 数据库 URI 配置 |
| `fastapi_app/shared_models/` | 所有数据表模型定义 |
| `scripts/database/db_manager.py` | CLI 数据库管理工具 v3.0 |
| `docs/DATABASE_BACKUP_RECOVERY_GUIDE.md` | 本文档 |

---

## 7. 快速参考

| 操作 | Web API | CLI |
|------|---------|-----|
| 全量备份 | `POST /backup/save` | `python db_manager.py backup` |
| 上传恢复 | `POST /backup/import` | — |
| 服务器恢复 | `POST /backup/restore-by-name/{file}` | `python db_manager.py restore --file <path>` |
| 验证文件 | `POST /backup/validate` | `python db_manager.py verify --file <path>` |
| 列表 | `GET /backup/list` | `python db_manager.py list` |
| 删除 | `DELETE /backup/delete-by-name/{file}` | — |
| 清理 | — | `python db_manager.py cleanup --keep 7` |
| 状态 | `GET /backup/status` | — |
