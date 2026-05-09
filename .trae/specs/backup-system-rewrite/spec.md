# 数据备份与恢复系统全面重构 Spec

## Why
当前 ERP 备份系统经过多次打补丁式修复，代码复杂度高、进度展示有缺陷、定时备份未真正启用、缺少备份记录管理与容量控制、前端交互体验不足。需要对备份/恢复功能进行全面重构，构建一个健壮、可维护、用户体验优秀的备份系统。

## What Changes
- **BREAKING**: 彻底删除现有 `backup.py` 中备份/恢复相关代码，重新开发
- **BREAKING**: 删除现有 `backup_tasks.py` 任务实现，重新设计定时任务体系
- **BREAKING**: 重构前端 `BackupView.vue` 和 `RestoreProgressBar.vue`，统一交互模式
- 新增 `BackupRecord` 数据库模型，记录所有备份/恢复操作历史
- 新增备份文件容量管理与自动清理策略
- 新增备份加密支持（AES-256-GCM）
- 新增定时全量备份 + 定时增量备份的完整调度体系
- 新增 WebSocket 实时进度推送，替代轮询机制
- 新增备份/恢复操作的审计日志

## Impact
- Affected specs: 数据备份与恢复（完全替代 `backup-restore-fix`）
- Affected code:
  - `fastapi_app/api/v1/endpoints/backup.py` — 完全重写
  - `fastapi_app/core/restore_progress.py` — 删除，合并到新模块
  - `fastapi_app/tasks/backup_tasks.py` — 完全重写
  - `fastapi_app/core/celery_app.py` — 更新 beat_schedule
  - `fastapi_app/models/backup_record.py` — 新增
  - `fastapi_app/services/backup_service.py` — 新增（核心业务逻辑）
  - `frontend-vite/src/views/backup/BackupView.vue` — 重构
  - `frontend-vite/src/components/backup/RestoreProgressBar.vue` — 重构为通用 ProgressPanel
  - `frontend-vite/src/api/index.ts` — 更新 backupApi
  - `scripts/database/restore_db.py` — 重写

---

## 功能需求分析

### 数据范围
备份系统 SHALL 覆盖系统中**所有路由板块**对应的全部数据：

| 板块 | 数据类型 | 备份内容 |
|------|---------|---------|
| 核心业务/客户订单 | PostgreSQL 表 | orders, order_items, order_batch_logs 等 |
| 产品清单 | PostgreSQL 表 | products, product_bom_items, product_fabric 等 |
| 出库管理 | PostgreSQL 表 | stock_out_records, stock_out_items |
| 库存管理 | PostgreSQL 表 | stock_in_records, inventory, stock_return |
| 出货计划 | PostgreSQL 表 | production_plans, plan_details, shipment_records |
| 采购中心 | PostgreSQL 表 | purchase_orders, purchase_order_items |
| 供应商管理 | PostgreSQL 表 | suppliers |
| 来料登记 | PostgreSQL 表 | material_registrations |
| 生产报表 | PostgreSQL 表 | daily_production_records, craft_works, packaging_records |
| 客户管理 | PostgreSQL 表 | customers, customer_access_logs |
| 用户/权限管理 | PostgreSQL 表 | users, permissions, user_permissions |
| 审批管理 | PostgreSQL 表 | approvals, approval_items |
| 系统配置 | 文件系统 | .env, JWT密钥, nginx配置, Redis配置 |
| 附件文件 | 文件系统 | static/uploads/ 全部文件 |
| Redis 缓存 | Redis | dump.rdb 快照 |
| 搜索索引 | MeiliSearch | 全部索引文档与设置 |
| 版本管理 | PostgreSQL 表 | app_versions |

### 用户操作流程

**全量备份流程**：
```
用户进入备份页 → 查看数据库概览 → 填写备注 → 选择存储位置(服务器/下载)
→ 点击「一键备份」→ 实时进度条展示 → 备份完成 → 追加到备份列表
```

**全量恢复流程**：
```
用户选择备份文件(上传/服务器列表) → 系统验证文件完整性 → 展示备份摘要
→ 用户确认恢复 → 系统创建安全备份 → 实时进度条展示 → 恢复完成 → 展示验证报告
```

**增量备份流程**：
```
系统自动计算上次全量备份时间 → 用户点击「增量备份」→ 仅导出变更数据
→ 进度条展示 → 生成增量备份文件(标记父备份)
```

---

## ADDED Requirements

### Requirement: 备份服务核心模块
系统 SHALL 提供独立的 `BackupService` 服务类，封装所有备份/恢复业务逻辑，与 API 层解耦。

#### Scenario: BackupService 创建全量备份
- **WHEN** 调用 `BackupService.create_full_backup(user, remark)`
- **THEN** 返回 `(zip_bytes, manifest, BackupRecord)`，manifest 包含完整的表统计、校验和、指纹

#### Scenario: BackupService 执行恢复
- **WHEN** 调用 `BackupService.restore_from_zip(zip_bytes, user)`
- **THEN** 创建安全备份 → 获取锁 → 恢复数据库/文件/配置/Redis/MeiliSearch → 验证 → 释放锁 → 返回结果

### Requirement: 备份记录管理
系统 SHALL 使用 `BackupRecord` 数据库模型记录所有备份和恢复操作。

#### Scenario: 备份成功后记录
- **WHEN** 全量/增量备份成功完成
- **THEN** 创建 BackupRecord，包含：类型、文件名、大小、表数、行数、操作人、时间、备注、状态

#### Scenario: 恢复操作记录
- **WHEN** 恢复操作完成（无论成功/失败）
- **THEN** 创建 BackupRecord，包含：恢复源、验证结果、是否回滚、错误信息

### Requirement: WebSocket 实时进度推送
系统 SHALL 通过 WebSocket 向前端推送备份/恢复的实时进度，替代当前的 HTTP 轮询。

#### Scenario: 备份进度实时推送
- **WHEN** 备份任务执行中
- **THEN** 每完成一个阶段（数据库导出/文件打包/配置备份/Redis/MeiliSearch），通过 WebSocket 推送 `{phase, progress, detail}`

#### Scenario: 恢复进度实时推送
- **WHEN** 恢复任务执行中
- **THEN** 实时推送阶段进度，包括 psql 导入期间的 heartbeat 更新

#### Scenario: WebSocket 连接断开重连
- **WHEN** WebSocket 意外断开
- **THEN** 前端自动重连，并从 Redis 获取最后一次进度状态恢复显示

### Requirement: 定时备份调度体系
系统 SHALL 通过 Celery Beat 实现完整的定时备份调度。

#### Scenario: 每日全量备份
- **WHEN** 每日凌晨 2:00（可配置）
- **THEN** 自动执行全量 ZIP 备份到服务器默认路径

#### Scenario: 定时增量备份
- **WHEN** 每 4 小时（可配置：02:00, 06:00, 10:00, 14:00, 18:00, 22:00）
- **THEN** 自动执行增量备份，仅导出自上次全量备份以来的变更行

#### Scenario: 备份完整性巡检
- **WHEN** 每日凌晨 3:00
- **THEN** 检查最新备份文件的校验和、文件存在性、备份时效性（超过 48h 告警）

### Requirement: 备份加密
系统 SHALL 支持对敏感备份文件进行 AES-256-GCM 加密。

#### Scenario: 加密备份下载
- **WHEN** 用户在备份时启用加密选项
- **THEN** 备份 ZIP 文件使用用户提供的密码进行 AES-256-GCM 加密

#### Scenario: 加密备份恢复
- **WHEN** 用户上传加密的备份文件
- **THEN** 系统要求输入解密密码，验证后解密再执行恢复

### Requirement: 备份容量管理
系统 SHALL 管理备份文件的存储容量，防止磁盘写满。

#### Scenario: 自动清理旧备份
- **WHEN** 备份目录总大小超过配置阈值（默认 10GB）或文件数量超过上限（默认 30 个）
- **THEN** 自动删除最旧的备份文件，优先删除增量备份，保留最近 N 个全量备份

#### Scenario: 容量告警
- **WHEN** 备份目录使用率达到 80%
- **THEN** 在管理面板显示警告，并通过通知服务发送告警

### Requirement: 审计日志
系统 SHALL 为所有备份/恢复操作记录完整的审计日志。

#### Scenario: 操作审计
- **WHEN** 任何备份/恢复操作发生
- **THEN** 记录：操作人 IP、User-Agent、操作类型、文件名、大小、耗时、结果状态

---

## MODIFIED Requirements

### Requirement: 数据备份功能（替代现有）
原备份功能直接在 API 端点中实现，现修改为：
1. 业务逻辑集中在 `BackupService` 中
2. 备份进度通过 WebSocket 实时推送
3. 备份记录写入 BackupRecord 表
4. 支持加密选项
5. 由统一的容量管理策略控制存储

### Requirement: 数据恢复功能（替代现有）
原恢复功能为同步阻塞 + 异步轮询，现修改为：
1. 恢复始终为异步模式（返回 task_id）
2. 进度通过 WebSocket 推送
3. 安全备份 + 自动回滚机制保留
4. 恢复成功后自动清除相关缓存
5. 完整的验证报告在 WebSocket 推送中返回

### Requirement: 进度展示（替代现有）
原进度通过 800ms HTTP 轮询实现，现修改为：
1. WebSocket 双向通信，服务端主动推送
2. 前端 WebSocket hook 自动管理连接和重连
3. 进度条支持阶段标签、百分比、剩余时间估算

## REMOVED Requirements

### Requirement: HTTP 轮询进度查询
**Reason**: 被 WebSocket 实时推送替代，减少服务端负载和延迟
**Migration**: 前端移除 `setTimeout(poll, 800)` 轮询逻辑，改用 `useWebSocket` composable

###