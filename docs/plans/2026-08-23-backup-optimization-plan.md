# 备份中心优化改进方案（2026-08-23）

> 依据：`docs/reports/2026-08-23-backup-benchmark-report.md`（对标审核报告）
> 约束：延续 v2 定案——**演进不重写**、保 ZIP 格式、保 ARQ；每个抽象必须证明其复杂性；优先可逆决策。
> 状态：**用户已确认（2026-08-23）：除 P1-1 异地备份不做外，其余全部实施。**
> 实施记录：分支 fix/backup-p0-hotfix-2 —— P0 提交 5f18610、M6 提交 6c6087a；
> ADR 见 `docs/adr/2026-08-23-backup-adrs.md`；新增测试 test_backup_p0.py(18) + test_backup_m6.py(18)。

---

## 总原则

1. **恢复优先**（学 DBackup）：备份系统的价值在恢复时兑现。P0 全部围绕"备份一定可还原"。
2. **单一真相源**：加密决策、还原锁、还原编排各只允许一个决策点。
3. **3-2-1 落地**（学 OCA/Frappe/DBackup 共识）：备份必须离开本机。本项目开发机即生产服务器，同盘备份是当前最大灾难风险。
4. **不做的事**（rejected alternatives，见第五节）：内容寻址去重存储、WebSocket 替换轮询、备份域微服务化。

---

## P0 批次：正确性与安全（预计 1-2 天，分支 fix/backup-p0-hotfix-2）

### P0-1 加密决策单点化（修复"不可还原备份/双重加密"）

- `create_full_backup` 的 `encrypt=None` 分支**移除随机回退**：无显式密码即不加密并告警；`BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED` 默认值改 `false`（保留 env 开关兼容，加启动告警）。
- 遗留端点 `/save`、`/export`、`/save-incremental`、`/export-chunk` 对齐 M1 任务路径语义（`_resolve_encryption`：参数 > 请求头 > 环境变量，均无则明文+告警），服务层不再自行取环境密码加密。
- 修正 `core.py:323` 误导日志（"密钥已记录在日志中"→ 如实说明）。
- 测试：随机回退禁用回归、无密码→明文落盘、有环境密码→单层加密且可解密还原（test_backup_p0）。
- ADR-001。

### P0-2 敏感配置还原的 confirm_sensitive 透传

- 还原 API（restore-by-name / async 变体 / import）增加 `confirm_sensitive` 请求字段（默认 false，维持 fail-safe）；`restore_from_zip` 透传替代硬编码（`restore.py:197`）。
- 前端还原向导第 3 步（危险确认）增加勾选项"同时还原敏感配置文件（.env.production / jwt 密钥）"。
- ADR 无需（补完 REV-09 既有设计意图）。

### P0-3 分片下载缓存化

- `GET /export-info` 生成一次备份并登记缓存（bundle_id → 临时文件 + SHA-256 + 分片元数据，带 TTL 与后台清理），`/export-chunk/{i}` 改为读该缓存切片。
- 保证整包 checksum 与各分片一致（当前每片重跑全量且内容可能不同）。
- 复用现有 BackgroundTasks 清理机制，不改前端协议。

### P0-4 `.meta` sidecar 落地（或删除）

- 推荐落地：备份任务写盘成功后调用既有 `create_meta_file`（时间戳/大小/checksum/加密标志）；`_backup_created_time` 的 meta 分支即生效，保留策略不再依赖不可靠的 mtime。
- 若用户倾向极简，可反向删除 `.meta` 相关读取代码——二选一，消除半成品状态。

### P0-5 还原路径加固

- `restore-by-name` 增加文件大小上限（与上传一致 500MB，超限走分片/异步路径）。
- psql 还原改 `--single-transaction + ON_ERROR_STOP=1`：失败整回滚（新库未建成前不动旧库的顺序保持），失败自动提示 pre_restore 回滚备份文件名；`partial` 概念保留但必须显式告警+记录。
- 统一还原锁：同步路径也改为 Redis 锁（advisory 仅作备份互斥保留），消除"各持一种锁并发还原"窗口；`_check_task_mutex` 注释降级为 UX 预检（强保证由任务内真锁承担，消除 TOCTOU 争议）。

---

## P1 批次：能力补齐——异地备份 + 架构收敛（预计 1-2 周，M6）

### P1-1 异地备份（对标 OCA SFTP / Frappe offsite / DBackup 适配器）

分两步走（可逆递进）：

- **第一步（零新依赖，先行）**：`backup_settings` 增加"备份完成后推送命令"配置（如 `rsync`/`scp` 到 NAS/异地机，参数模板化，白名单校验可执行文件）；全量/定时任务尾部执行并记录推送结果到 BackupRecord。风险低、当天可用、随时可撤。
- **第二步（原生 SFTP 适配器）**：`BackupStorage` 端口已有，新增 `SftpBackupStorage` 适配器（paramiko，评估依赖后定）+ 远端保留 N 份轮换；backup_settings 增加远端目标字段。对标 OCA 的 days_to_keep 远端清理。
- ADR-002（含"为什么不做完整 S3 适配器"：当前无对象存储基础设施，SFTP/rsync 已满足 3-2-1；端口已留扩展位）。

### P1-2 表级选择性备份（对标 Frappe include/exclude doctypes）

- `BackupFullRequest` 增加 `tables` / `exclude_tables`（表名白名单校验，复用 `quote_table`）；pg_dump 传 `--table`/`--exclude-table-data`；manifest 记录备份范围；还原默认仅 upsert 所选表（JSON 路径天然支持，psql 路径提示改用 JSON）。
- 使用场景：升级前只备份核心业务表、快速热备份。

### P1-3 六边形收敛（接线或删除，二选一——推荐接线）

- **推荐**：`DatabaseRestoreOrchestrator` 接线为 `restore_from_zip` 的内核（阶段生命周期/策略选择已写完，把过程式实现逐段迁入 strategies，端点行为不变），删除重复的解密/校验/验证代码。与 v2"演进不重写"一致，消除双轨漂移。
- 备选：若用户认为不值得，删除未接线半成品（orchestrator/format_strategy/chunks/LocalBackupStorage）+ 对应测试。**不可继续双轨并存**。
- ADR-003。

### P1-4 演练与巡检例行化

- `integrity_check`（已有种子）确认启用；`disaster_recovery_test_task` 加入 backup_schedule 种子（每月 1 次 03:30），结果写 BackupRecord + 告警通道。对标 DBackup"定时重扫"——让"备份可恢复"从假设变成持续验证的事实。

---

## P2 批次：体验与进阶（选做，M7+）

- **P2-1 前端补齐**：记录下载接通（按文件名下载，替代空占位）、删除备份入口恢复、备份加密密码输入（API 已支持 encrypt/password）、ValidationCache 迁 Redis。
- **P2-2 进度阶段对齐**：任务上报补齐 8 阶段全量映射；保持 HTTP 轮询（设计文档已排除 SSE/WS，维持决策）。
- **P2-3 前端遗留链清理**：删除零引用旧 composable/组件（useBackupCenter 链），i18n 预留评估。
- **P2-4 PITR 方向 ADR（仅记录不实施）**：WAL 归档（pgBackRest/WAL-G 托管）与应用级备份解耦共存——应用级保业务粒度，PITR 保 RPO 秒级；待业务对 RPO 有硬要求再启动。

---

## 五、明确不做（rejected alternatives）

| 提案 | 不做理由 |
|---|---|
| restic/Borg 式内容寻址去重 | 单机数据量级下收益低；去重显著复杂化恢复路径（DBackup 明示同样的权衡）。备份域定位是"企业功能完整性"而非存储效率。 |
| WebSocket/SSE 替换轮询 | 800ms 轮询在单管理员场景足够；引入推送层的复杂度不被证明。设计文档已两次排除。 |
| 备份域微服务化 | 单机部署、无独立扩展诉求；违反"没有架构太空人"。 |
| 双写新 ZIP v3 格式 | v2.0 manifest 已满足；格式演进仅在需要 breaking change 时随版本号走。 |

## 六、实施顺序与验收

1. **fix/backup-p0-hotfix-2**（P0 全部）：验收 = 新增 test_backup_p0 通过 + 既有 127 用例全绿 + 一次真实"备份→校验→还原"演练成功（敏感文件含/不含两种）。
2. **M6 分支**（P1）：验收 = 推送到异地成功且远端轮换生效；表级备份/还原往返一致；orchestrator 接线后 restore 端到端等价测试；DR 演练月度任务首跑成功。
3. **M7**（P2 按需）。

每批次独立 PR、独立可回滚；延续里程碑测试文件命名与 AST 导入守卫惯例。

## 七、待用户决策点

1. P0-4：`.meta` **落地** 还是 **删除**？（推荐落地）
2. P1-3：六边形 **接线收敛** 还是 **删除半成品**？（推荐接线）
3. P1-1：异地第一步用 **推送命令模板**（零依赖）还是直接做 **原生 SFTP 适配器**？（推荐先命令模板）
4. P1-2 表级备份是否纳入 M6（可延后）。
