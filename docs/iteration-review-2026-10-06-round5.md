# 迭代审核报告 Round-5 —— 2026-10-06（code-review-excellence 框架）

> 范围：Round-4（2026-10-05）之后备份域的全部迭代——调度 stale-running 补跑上线验证、
> 还原流程重构（去密码框 → 勾选化 → 去差异表）、plan 端点密码兜底链、cron 中文时间标签。
> 退货管理模块（并行会话）不在本轮范围，其状态见 [round-4](iteration-review-2026-10-05-round4.md)。
> 方法：改动文件最终态逐文件通读 + ruff/mypy/quality_gate/定向 pytest 实测 + 生产截图反证。

## Summary

本轮把备份页从「运维向导」收敛为「一键安全还原」：解密密码由服务端环境变量承担（UI 输入框删除），
破坏性确认从「手输确认文本」改为勾选，67 行差异表从预览弹窗移除（保留"覆盖 N 张表 · 加密/明文包"摘要）。
配套修了两个真实缺陷：plan 端点缺密码兜底链（预览必失败 → 确认按钮恒灰，用户实测命中）、
加密包预览成功时误标「明文包」。

## Strengths（值得保留的做法）

- 🎉 **兜底链复用而非另起炉灶**：plan 端点接入 `_get_encryption_password`（body → header → env），
  与 restore-by-name/async-import 完全同范式——不新增密码传递通道，不扩大攻击面。
- 🎉 **安全边界推理成立**：plan 与 restore 要求同一 `backup` 权限且走同一解密兜底，
  「无输入自动解密」不改变信任边界；`EncryptedBackupError` 仍作为独立异常区分「解不开」与「文件损坏」。
- 🎉 **stale-running 补跑语义配套双向测试**（超阈值放行 / 新鲜 running 不双跑 / failed/success 不补跑），
  且生产已验证（16:00 窗口被重启杀死后 16:35 由 ARQ 重试闭环）。
- 🎉 **破坏性确认降级为勾选但未丢语义**：勾选文案保留「覆盖全部数据且无法撤销」，
  切换备份点自动重置勾选，避免「确认 A 点顺手还原 B 点」。

## Findings（按严重度）

### 🟡 已修：加密包预览成功时误标「明文包」（本轮审核发现，当场修复）

- `build_restore_plan` 返回 `encrypted=bool(manifest.get('encrypted'))`，但 manifest 固化发生在
  **加密之前**，该键恒缺 → 成功分支永远 `encrypted=False`；`.enc` 后缀才是权威信号
  （失败分支早已按后缀判定，两条路径口径分叉）。用户截图实测命中（`erp_auto_daily_20261006_*.zip.enc` 显示"明文包"）。
- 修复：成功分支 `plan.pop('encrypted')` 后按 `.enc` 后缀显式传参（`restore.py` restore_plan 端点）。
- **生效条件：需再重启一次 erp-prod**（见文末部署状态）。

### 🟡 建议跟进：plan 端点级测试缺口

M3/加密路径测试（`test_backup_m3.py`、`test_backup_encrypted_restore_path.py`，48 用例全绿）
覆盖服务层，但本轮两处端点层行为变更（兜底链接入、encrypted 按后缀覆盖）无直接端点断言。
建议补一条「无 body 密码 + .enc 文件 → success=True 且 encrypted=True」的端点测试。

### 🟢 nit（不阻塞）

1. `BackupRestorePlanRequest.password` 的 schema 描述仍写着「缺省时加密包只回 encrypted=True」，
   缺省语义已变为「自动用环境变量解密」，描述可顺手更新；
2. `BackupView.previewPlan(filename, password?)` 的 password 参数已无调用方传入，可收窄签名；
3. 差异表删除后，后端 plan 仍对 67 张表逐表 `COUNT(*)`（前端不再展示 tables）。
   当前库量级无感知；若未来表数/行数增长，可给 plan 加 `include_tables=false` 跳过逐表统计。

### 📚 记录：本轮一次编辑事故（已修复）

勾选化改造中一次 Edit 误吞了模板 `</div>` 与进度态开标签，type-check 前已发现并修复，
最终 vue-tsc 通过、结构通读确认无误。教训：多行模板替换的 old_string 边界要含上下文锚点。

## 门禁实测（2026-10-06）

| 项 | 结果 |
|---|---|
| vue-tsc type-check | ✅ 0 错误 |
| ruff（改动后端文件） | ✅ |
| mypy（restore.py / restore_plan.py / schedule_service.py） | ✅ |
| pytest（M2/M3/加密还原路径） | ✅ 48 passed |
| quality_gate.py | ✅ PASS |
| 前端上线 | ✅ live `index-DeC6z8Pv.js`（nginx，dist hash 一致） |

## 部署状态与待办

- **前端**：已上线（差异表移除、勾选确认、无密码框）——强刷即见。
- **后端**：plan 兜底链**已生效**（用户 2026-10-06 上午经 restart_erp_prod.bat 重启，截图预览成功为证）；
  encrypted 后缀修正**待一次重启**生效——需再双击一次 `scripts/restart_erp_prod.bat`。
- 未提交变更持续累积（备份域 + 退货域 + 本轮），建议按域分批提交（备份域可独立成 commit：
  调度补跑 + 还原流程简化 + cron 显示）。

## Verdict

✅ **Approve**（备份域全部改动；encrypted 修复已随审随修，重启后闭环）。
