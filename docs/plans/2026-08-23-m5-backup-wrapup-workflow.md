---
intent: M5 收尾——GET /export 下载补显式审计、备份加密策略声明与孤儿 .enc.meta 清理、历史备份还原演练补跑并产出演练报告（TECHNICAL_PLAN.md v2 §7 M5）
success_criteria: ① /export 与 /export-enhanced 下载写入 audit_log（action=EXPORT，单测验证）② ENCRYPTION_POLICY.md 完整声明加密策略且 backups/server 无孤儿 .enc.meta ③ 真实历史备份在隔离测试库 psql 还原+校验通过，DRILL_REPORT 产出 ④ 全部备份域单测绿
risk_level: medium
auto_approve: false
---

## Steps

- [ ] **Step 1: /export 下载显式审计（代码+单测）**
action: 在 fastapi_app/api/v1/endpoints/backup/export.py 新增 `_audit_export_download`（复用 audit_middleware._buffer_audit_entry，action='EXPORT'、resource_type='backup'、detail 含 filename/format/encrypted/size/remark），在 `_export_backup_to_response` 成功返回前调用（同时覆盖 GET /export 与 GET /export-enhanced），端点签名注入 Request 取 IP/UA；新增 fastapi_app/tests/test_backup_m5.py，mock 备份服务后经 client 调 GET /api/v1/backup/export，断言审计条目字段正确（明文/加密两分支）
loop: until pytest 通过
max_iterations: 3
verify: python -m pytest fastapi_app/tests/test_backup_m5.py -q

- [ ] **Step 2: 加密策略声明文档**
action: 创建 docs/ui-redesign/backup-center/ENCRYPTION_POLICY.md：密码优先级链（password 参数 > X-Backup-Password 头 > BACKUP_ENCRYPTION_PASSWORD env > 明文+告警，永不随机回退）、backup_settings.encryption_mode 语义（off/password/key/env）、算法（AES-256-GCM + PBKDF2 600k）、磁盘混存现状盘点（30 明文 zip / 4 enc / 6 孤儿 .enc.meta）、保留策略行为、孤儿 .enc.meta 清理方案与执行结果、加密包还原需 BACKUP_TEST_PASSWORD 的运维说明
verify: shell: PowerShell Select-String 断言文件包含 优先级链/encryption_mode/孤儿 四个关键节

- [ ] **Step 3: 孤儿 .enc.meta 清理**
action: 抽查 1 个 .enc.meta 确认为纯元数据后，删除 backups/server 下 6 个无对应 .enc 的孤儿 meta（对应加密包已被保留策略删除），清理结果记入 ENCRYPTION_POLICY.md
verify: shell: PowerShell 断言 backups/server 下每个 *.enc.meta 均存在同名 .enc（无孤儿）

- [ ] **Step 4: 历史备份演练补跑（live drill）**
action: ① 从 .env 读 DB 超级用户凭据，连续 3 次简单查询探测 DB 稳定性 ② DROP 残留演练库 erp_backup_drill_20260823_005946（若存在）③ 重建隔离库 erp_backup_test ④ 解包真实历史备份 erp_auto_daily_20260820_020004.zip，用 D:\PostgreSQL\bin\psql.exe 将 database/dump.sql.gz 还原进测试库 ⑤ 校验：还原后表清单 vs manifest.includes、抽样表行数 vs manifest 计数 ⑥ 产出 docs/ui-redesign/backup-center/DRILL_REPORT_2026-08-23.md（含结论 PASS/FAIL 与耗时）⑦ 演练后 DROP erp_backup_test 收尾
loop: until 还原+校验通过；若 DB 持续不可用则在报告中记录阻塞项后停止
max_iterations: 3
verify: shell: PowerShell 断言 DRILL_REPORT_2026-08-23.md 存在且含 "结论: PASS"

- [ ] **Step 5: 全量备份域单测绿**
action: 运行全部备份域测试（m0/m1/m2/m3/m5 + test_backup + validation_helpers）
verify: python -m pytest fastapi_app/tests/test_backup_m0_hotfix.py fastapi_app/tests/test_backup_m1.py fastapi_app/tests/test_backup_m2.py fastapi_app/tests/test_backup_m3.py fastapi_app/tests/test_backup_m5.py fastapi_app/tests/test_backup.py fastapi_app/tests/test_backup_validation_helpers.py -q

- [ ] **Step 6: 里程碑提交**
action: 显式路径白名单 git add（export.py、test_backup_m5.py、ENCRYPTION_POLICY.md、DRILL_REPORT、本工作流文件），提交 M5 收尾里程碑 commit
gate: human
