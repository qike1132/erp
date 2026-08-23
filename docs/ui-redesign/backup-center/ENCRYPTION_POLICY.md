# 备份加密策略声明（ENCRYPTION_POLICY）

> 适用范围：`d:\erp_system` 生产环境的全部备份产物（`backups/server/` 及手动导出下载）。
> 本文档为 TECHNICAL_PLAN v2 §7 M5 收尾交付物之一，声明当前生效的加密策略、磁盘混存现状的处理决定，以及孤儿 `.enc.meta` 的清理方案与执行结果。

## 1. 密码解析优先级链（fail-safe，禁止随机回退）

所有备份加密入口（`GET /export`、`GET /export-enhanced`、`POST /save`、任务化 `/full`、`/incremental`）统一经由 `endpoints/backup/_deps.py::_resolve_encryption` 解析加密意图：

1. 请求参数 `password`
2. 请求头 `X-Backup-Password`
3. 环境变量 `BACKUP_ENCRYPTION_PASSWORD`
4. 以上均未提供 → **明确降级为不加密**，并记录 WARNING 日志

**红线**：任何情况下都不生成随机密码加密备份（M0 已热修移除该回退分支）。随机密码不可找回，会使备份文件事实上不可还原——宁可明文可还原，不可密文打不开。

## 2. backup_settings.encryption_mode 语义

`backup_settings` 表（M1 新增，单行）的 `encryption_mode` 字段声明系统级加密姿态：

| 取值 | 语义 |
|------|------|
| `off` | 系统声明不加密（明文备份，依赖磁盘/OS 层保护） |
| `password` | 期望密码加密：密码来自第 1 节优先级链（请求参数/请求头/env） |
| `key` | 期望密钥文件加密（当前版本未实现独立密钥文件流，等价 password 链） |
| `env` | 跟随 `BACKUP_ENCRYPTION_PASSWORD` 环境变量（未初始化表时的默认值） |

注意：`encryption_mode` 是声明性配置，实际是否加密仍以每次请求的 `encrypt` 参数 + 第 1 节密码链解析结果为准。

## 3. 算法与文件格式

- 算法：AES-256-GCM（认证加密，篡改可检测）
- 密钥派生：PBKDF2-HMAC-SHA256，600,000 次迭代，128-bit 随机盐
- 每次加密使用独立 96-bit nonce；认证标签 16 字节
- 加密包物理格式：`meta_len(4 字节大端) + meta_json + 密文`，meta 含 `{"encrypted": true, "algorithm": "AES-256-GCM", kdf 参数}`
- 实现位置：`fastapi_app/core/backup_encryption.py`

## 4. 磁盘混存现状与处理决定（2026-08-23 盘点）

`backups/server/` 当前同时存在三类产物：

| 类别 | 数量 | 说明 | 处理决定 |
|------|------|------|----------|
| 明文 `*.zip` | 30 | 定时全量（`erp_auto_daily_*`）、增量（`erp_incremental_*`）、演练物（`erp_m3drill_*`） | **保留**。当前生产未配置 `BACKUP_ENCRYPTION_PASSWORD`，按第 1 节 fail-safe 策略降级明文属预期行为；内网磁盘依赖 OS 权限保护 |
| 加密 `*.zip.enc` | 4 | 2026-07/08 手动加密备份（`erp_backup_*.zip.enc`） | **保留**。还原需当时设置的密码；DR 演练解密需配 `BACKUP_TEST_PASSWORD` |
| 孤儿 `*.enc.meta` | 6 | 2026-06 的 `erp_backup_*.zip.enc.meta`，对应加密包已被保留策略删除 | **清理**（见第 5 节） |

混存判定：磁盘不要求统一加密或统一明文。加密与否以单次备份时密码链是否解析到密码为准；这是显式、可追溯的策略，而非缺陷。

## 5. 孤儿 `.enc.meta` 清理方案与执行结果

**成因**：旧版加密流程在写 `.enc` 之外另落一份 `.enc.meta` 元数据文件；保留策略清理 `.enc` 时未联动清理 meta，遗留 6 个孤儿。

**清理方案**（保守、可审计）：
1. 逐个校验 meta 为纯元数据 JSON（不含任何业务数据）——已抽查确认内容仅为 `{"encrypted": true, "algorithm": "AES-256-GCM"}`
2. 仅删除「同名 `.enc` 不存在」的 meta 文件（孤儿判定）
3. 存在对应 `.enc` 的 meta 一律保留（还原时用于加密探测）

**执行结果（2026-08-23）**：已删除 6 个孤儿 meta：

- `erp_backup_20260606_153623.zip.enc.meta`
- `erp_backup_20260606_153648.zip.enc.meta`
- `erp_backup_20260606_153700.zip.enc.meta`
- `erp_backup_20260606_153752.zip.enc.meta`
- `erp_backup_20260606_161217.zip.enc.meta`
- `erp_backup_20260611_141224.zip.enc.meta`

## 6. 运维要点

- **还原加密包**：DR 演练（`DisasterRecoveryTestService`）解密 `.enc` 需设置 `BACKUP_TEST_PASSWORD` 环境变量；未设置时演练会明确报「已加密但未配置密码」，不会误判为损坏
- **审计**：`GET /export` / `GET /export-enhanced` 下载整库备份自 M5 起写入显式审计记录（action=`EXPORT`，detail 含文件名/是否加密/大小/备注）
- **密钥轮换**：`policy` 中 `key_rotation_days=90` 仅为配置占位，未实现自动轮换（明确不在本轮范围，另立项）
- 新增备份的加密判定日志：请求加密但无密码时后端记 WARNING「将以未加密形式保存」，可在日志中追溯每次降级
