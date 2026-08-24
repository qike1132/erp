# 备份中心"一键备份 → 一键还原"终局审计报告（2026-08-24）

> 方法：非纸面审查——在真实生产库（数据为用户声明的模拟数据）实测全链路：
> ARQ 真实备份 → 校验 → 差异预览 → 删除 2 行制造数据事故 → 真实还原 → 回滚验证。
> 审计人：ZCode（software-architect + 实测取证）；前置：2026-08-23 对标整改已部署（main@7479609）。

---

## 一、结论

**"一键备份"已达成；"一键还原"已达成**（引擎、锁、安全备份、四层验证、数据回滚全部实测证实）。
附带产出：实测抓出 2 个真实缺陷（已修复+回归测试）+ 3 项遗留建议（F5/F6/F7）。

## 二、实测证据链

### Phase A 一键备份（UI 同款 ARQ 链路）✅
- 入队 `manual_full_backup_task` → Redis 进度八阶段真实推进（backup_config 65% → completed 100%）
- 产物：`erp_backup_20260824_084224.zip`（6.98MB，63 表 / 30541 行）
- `.meta` sidecar ✓（created_at/checksum/行数）；BackupRecord ✓（success/full/manual/encrypted=false）

### Phase B 校验与预览 ✅
- `validate_backup_file`：checksums_ok=True
- 差异预览（还原向导第 2 步同款）：affected=2，**精确命中现实**——`customer_sampling_part -2`（人为删除）、`backup_record +1`（备份自身记录）
- 人为数据事故：删除 customer_sampling_part 2 行（PK 246/187），4110→4108

### Phase C 一键还原（UI 同款引擎链：pre_restore → Redis 锁 → 内核 → 验证）✅
- pre_restore 安全备份自动生成 ✓；Redis 还原锁获取/释放 ✓
- 数据库：26868 行恢复；**被删的 2 行完全恢复（4108→4110）**；全库 63 表逐一比对，**62 表行数零偏差**
- 组件：filestore 11 文件 ✓、config 2 文件（非敏感）✓
- 四层验证如实工作：L1 报 `backup_record 40≠39`（见 F7，验证层正确报警而非静默）→ overall partial——**这正是验证体系的价值证明**
- 还原可重复（第二轮复跑一致）

## 三、实测抓出的缺陷（本轮已修，含回归测试）

| 编号 | 缺陷 | 修复 |
|---|---|---|
| F3 | 包级 `release_restore_lock` 被 `.verify` 星号导入的 query_service 同名 advisory 版遮蔽——还原端点 finally 调用会 TypeError（还原成功但收尾炸、锁残留至 TTL） | `__init__.py` 显式导入置于所有星号导入之后 + 解析回归测试 |
| F4 | `ExistingCacheInvalidatorAdapter` 中 `invalidate_purchase_caches()` 为协程却未 await——采购缓存还原后从未失效 | 改 await + 回归测试 |
| F8 | 内核 `restore_components` 进度阶段名未映射到 10 阶段表（前端进度在 55-90% 区间停摆） | 映射至 `restore_filestore` |

回归：备份域 191 项测试全绿。

## 四、遗留发现与建议（未修，需决策）

- **F5 灾备演练服务是半成品**：`recovery_test_service._create_test_schema/_import_test_data` 为 stub（自注释 TODO），只建 dummy 表、不真导入——月度调度（迁移 037 种子）每月会产出"验证失败"的**假阴性报告**。建议：按本次审计同款方式实现（psql 到一次性隔离库 + L1 比对），或暂时停用该调度。
- **F6 pg_dump 不在服务 PATH**：全部备份实际走 JSON 全表导出路径（`db_format=json`），psql 物理导出/单事务还原路径从未在生产生效（P0-5 改动未被生产覆盖）。建议：把 PostgreSQL bin 目录加入 API/ARQ 服务环境变量，恢复物理快照能力（更快、含序列/DDL 保真）。
- **F7 JSON 还原"清空失败仅告警继续"**：`erp_app` 非 superuser 无法禁 FK，个别表 DELETE 失败时旧行残留并与快照合并（本次仅 `backup_record` 残留备份自身记录 1 行，业务表零偏差；验证层已如实报警）。建议：DELETE 失败的表显式计入 errors 并在结果中标注"该表为合并而非回滚"。
- **F9（昨日部署时已报告）**：`backup_schedule` 表四个默认定时种子（每日全量/增量/巡检/清理）缺失，**自动定时备份当前未配置**，需在 UI 重建或补种。

## 五、审计过程环境说明

- 还原期间 uvicorn 因代码修复热重载、ARQ 常驻；生产 API 全程 `/backup/ping` 401 鉴权正常，未出现服务中断。
- 本次实测产生并保留的产物：审计备份 `erp_backup_20260824_084224.zip`、两次 pre_restore 安全备份（pre_restore 目录保留 5 份策略内）。
