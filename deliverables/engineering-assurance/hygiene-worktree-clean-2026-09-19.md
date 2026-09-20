# 工作区卫生整治与未提交变更收口报告（hygiene-worktree-clean）

- **日期**：2026-09-19
- **工作流**：技术债评估（工作区卫生执行）
- **对象仓库**：`D:\erp_system`（内网生产机本机）
- **行动编号**：engineering-worktree-hygiene（L2）
- **报告编号**：hygiene-worktree-clean-2026-09-19

---

## 📌 TL;DR

工作区卫生 L2 行动当日完成：Rex（SRE）迁出 97 项 / 171 文件 / 2,996,265B（≈2.86MB）至归档区，零锁失败、零硬失败、零 tracked 误碰、零 git 写。Cody（Code Reviewer）全量比对复核给出 **🟡 有条件通过**，唯一问题（8 份被入库交付物点名的报告正文被 `_` 前缀规则误归档）已由 Rex 定向恢复闭环。.gitignore 棘轮 4 条 glob 经 9 例正反验证零误伤面，并已随 22f8ce9a 提交入库。当日诊断的四条根因中 C1/C2/C3 均已闭合，仅 C4（远端推送滞后）仍开放。

**整体评级 🟢 通过（条件项已闭合）/ 阻塞 0 / 关键行动 6 条**。

---

## 🎯 核心结论卡片

| 维度 | 结论 |
|------|------|
| 整体评级 | 🟢 通过（条件项已闭合） |
| 归档规模 | 97 项 / 171 文件 / 2,996,265B（≈2.86MB），执行者初报 2,999,792B 经复核修正 |
| 安全边界 | 零锁失败 / 零硬失败 / 零 tracked 误碰 / 零删除原语 / 零 git 写；同卷 os.rename 迁移 |
| 复核结论 | 🟡 有条件通过 → 唯一条件项（8 份误归档报告）已定向恢复闭环 |
| tracked 保护 | MANIFEST 97 项 × git ls-files(2185) 全量比对：0 项被动；payload 逐项字节吻合 |
| .gitignore 棘轮 | 4 条 glob × 9 例 check-ignore 正反验证：作用域严格锚定 /deliverables/，全仓零误伤面；已随 22f8ce9a 入库 |
| 根因闭合 | C1 ✅ / C2 ✅ / C3 ✅ / C4 ❌ 仍开放（远端 erp/main=351c822a 落后本地） |
| 阻塞项 | 0 |
| 关键行动 | 6 条（P1×3 / P2×2 / P3×1） |

---

## 正文

### 1. 背景与行动定位

2026-09-19 上午，督导（Zhen · Engineering Director）在团队组建前完成垃圾审计（报告：`deliverables/junk-audit-20260919.html`）与绿区回收：225 项 / 33.66MB / 1418 文件，归档于 `D:\erp_ws_archive\20260919_junk_reclaim`。随后用户下达「执行」工作区卫生 L2 指令，督导按团队 SOP 立项 **engineering-worktree-hygiene**，由 Rex（SRE）执行、Cody（Code Reviewer）对抗复核、Docu（Tech Writer）落盘本报告。

当日仓库为并行会话活跃环境，HEAD 属移动靶：行动期间 HEAD 两次被并行会话前移，SRE 均如实记录，并以「自身操作零痕迹」作为终验标准。

### 2. 当天 HEAD 演变

| 提交 | 时间 | 内容 | 备注 |
|------|------|------|------|
| 36cb1a76 | — | 行动起点基线 | — |
| f8c61b41 | 10:54 | 移除 AI 工具目录与 v8 原型跟踪（D=289 / M=6） | 并行会话推进 |
| 920ea54b | 11:11 | 提交此前 staged 的 272 项（A=165 / M=107） | 并行会话自行闭合 C1 |
| 51b71920 | 11:13 | fix(beile-order) 8 文件（M=6 / A=1 / D=1） | D 恰为 `pattern-room/components/VersionCreateDialog.vue`，tracked 删除悬空（C3）由此闭合 |
| **22f8ce9a** | 11:23 | chore(gitignore)：SRE 棘轮块 + `/_qa_tmp*` + `/_dsh_research*` 忽略规则入库 | 现 .gitignore 共 321 行 |

### 3. L2 执行结果（Rex · SRE）

- **迁出规模**：97 项 / 171 文件 / **2,996,265B（≈2.86MB）**。执行者初报 2,999,792B，经对抗复核比对修正为当前值。
- **归档位置**：`D:\erp_ws_archive\20260919_worktree_hygiene_20260919\{payload, MANIFEST.json, restore.py, EXECUTION_LOG.txt, tools}`。
- **构成**：deliverables 过程件 95（engineering-assurance 44 + gstack 51）+ `_qa_tmp2`（57 文件 / 1.63MB）+ `_qa_tmp3`（19 文件 / 0.41MB）。
- **安全机制**：同卷 `os.rename`、零删除原语、零 git 写操作；含 `restore.py` 一键回滚脚本。
- **终验标准**：执行期间 HEAD 两次被并行会话前移，SRE 均如实记录，以「自身操作零痕迹」为终验标准。

### 4. 对抗复核（Cody · Code Reviewer）：🟡 有条件通过

**全量比对（非抽样）结论**：

- MANIFEST 97 项 × `git ls-files`（2185 项）：**0 项 tracked 被动**；归档后 src 目录全消失。
- payload 逐项字节吻合；dist=193 文件、node_modules=39056 文件复测吻合。
- 两笔新提交（920ea54b、22f8ce9a）中无凭据类文件名。

**🟠 唯一问题及闭环**：8 份被已入库交付物点名的报告正文被 `_` 前缀忽略规则误归档——

- `_member-*.md` ×5 被 `full-audit-and-incident-2026-09-17.md` 第 362-366 行附录表引用；
- `_raw-*.md` ×3 被 `gstack/overview.md` 第 22-24 行与 `perf-debugmode-vs-production-2026-09-17.md` 第 551-553 行引用。

**处置**：督导令 Rex 定向恢复，**已闭环**——8/8 回到原位、字节与 MANIFEST 一致、归档原件保留（复制式恢复）；恢复后它们以 untracked 可见状态待处置（见行动清单 #1）。约 30 份 `.py/.out/.txt` 证据过程件维持归档，此为棘轮规则的明确意图。

**🟢 棘轮规则验证**：.gitignore 棘轮 4 条 glob 经 9 例 `check-ignore` 正反验证，作用域严格锚定 `/deliverables/`，全仓零误伤面；且已被 22f8ce9a 提交入库。

### 5. 行动后 git 实况（Rex 恢复后实测，HEAD=22f8ce9a）

| 状态 | 数量 | 明细 |
|------|------|------|
| staged | 0 | — |
| untracked | 9 | 8 份恢复的报告正文 + 1 个并行会话新测试 `BeileOrderRow.searchName.test.ts` |
| modified | 5 | `fastapi_app/services/order/beile.py`、`tests/services/test_beile_orders.py`、`BeileOrderTab.vue`、`BeileOrderRow.vue`、`useBeileOrders.ts`——均为并行会话在研工作，本行动零触碰 |
| `_dsh_research*` | 退出 status | 因 22f8ce9a 忽略规则生效（文件本体在位） |

### 6. 根因回顾与闭合情况

| 编号 | 根因 | 闭合情况 |
|------|------|---------|
| C1 | 暂存区积压 272 项 | ✅ 并行会话自行提交闭合（920ea54b） |
| C2 | 忽略规则缺口（`_qa_tmp2/3`、`_dsh_research*`、deliverables 过程件） | ✅ 归档 + 棘轮入库（22f8ce9a）闭合 |
| C3 | tracked 删除悬空（`VersionCreateDialog.vue`） | ✅ 随 51b71920 正常提交闭合 |
| C4 | 上游/推送滞后（远端 erp/main=351c822a 落后本地；`erp/main [gone]` 为未 fetch 假象） | ❌ **仍开放**，见行动清单 #2、#3 |

### 7. 验证恢复正常的标准步骤（供后续复用）

1. 复跑分类统计：staged / modified / deleted / untracked 各归零或等于白名单。
2. `git ls-files --others --exclude-standard` 精确等于刻意保留清单。
3. `git diff HEAD --stat` 与 `git diff --cached` 均为空。
4. `git log -S` 反查无旧版洗回。
5. `git rev-parse HEAD` + `git fsck --connectivity-only` rc=0。
6. `git ls-remote erp refs/heads/main` 对 sha 确认推送（**不信 refs/remotes**）。
7. vitest / vue-tsc / quality_gate 回归保险。
8. 每次清理后重跑诊断脚本对比前后差异。

---

## ✅ 行动清单

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 处置 8 份恢复的报告正文（随下一批 deliverables 提交入库或明确归档） | 用户/文档负责人 | P1 | 下一交付批次 |
| 2 | `git fetch erp` 建立上游跟踪消除 `[gone]`，`git ls-remote erp` 对 sha 确认 | 用户（普通终端） | P1 | 即时 |
| 3 | 推送本地领先提交（远端 main=351c822a 落后） | 用户（普通终端） | P1 | 即时 |
| 4 | 人工删除设备名残留：`del \\?\D:\erp_system\nul` | 用户 | P2 | 本周 |
| 5 | 回归脚本固化进 tracked 目录；找回/重建 6 个失踪的 `*_check.py` | 工程 | P2 | 本周 |
| 6 | 灰区大件决策：backups/version-prune-20260916（119.32MB）、dist-v533-sentinel（18.58MB）、AI 工具目录 8 处（36.2MB） | 用户 | P3 | 择期 |

---

## ⚠️ 待完善与已知局限

1. **并行会话移动靶**：行动全程 HEAD 两次被并行会话前移，本报告的 git 实况快照仅代表 HEAD=22f8ce9a 时点；后续并行会话继续变更后需重跑第 7 节标准步骤复核。
2. **C4 上游/推送滞后仍开放**：远端 `erp/main=351c822a` 落后本地，`erp/main [gone]` 仅为未 fetch 假象。在推送完成前，本地领先提交存在单点丢失风险（生产机本机）。
3. **8 份恢复的报告正文处于悬置态**：untracked 可见但未入库，依赖行动清单 #1 在下一交付批次正式处置；处置前若再次触发清理，需注意勿重复归档。
4. **执行者初报字节数已修正**：2,999,792B → 2,996,265B，本报告以复核修正值为准；下游文档如引用旧值需同步更正。
5. **灰区大件未决**：约 174MB 灰区大件（行动清单 #6）尚无处置决策，占用磁盘但不影响 git 卫生。
6. **6 个失踪的 `*_check.py` 未找回**：仅列入行动清单，本轮未执行找回/重建。

---

## 📚 数据来源与成员产出索引

**Rex 执行产物**：

- `D:\erp_ws_archive\20260919_worktree_hygiene_20260919\MANIFEST.json`
- `D:\erp_ws_archive\20260919_worktree_hygiene_20260919\EXECUTION_LOG.txt`
- `D:\erp_ws_archive\20260919_worktree_hygiene_20260919\restore.py`
- `D:\erp_ws_archive\20260919_worktree_hygiene_20260919\tools\_restore_verify_out.json`

**Cody 复核产物**：

- 同目录 `tools\_cody_review.out`、`_cody_review2.out`、`_cody_review3.out`、`_cody_review4.out`
- 同目录 `tools\_cody_manifest_dump.txt`、`_cody_tracked.txt`、`_cody_commit_ns.txt`、`_cody_920_ns.txt`

**督导诊断与绿区回收**：

- `D:\erp_ws_archive\20260919_junk_reclaim\tools\_diag_worktree_20260919.py` / `_diag_worktree_20260919.out`
- `D:\erp_ws_archive\20260919_junk_reclaim\tools\_diag_worktree2_20260919.py` / `_diag_worktree2_20260919.out`
- `D:\erp_ws_archive\20260919_junk_reclaim\MANIFEST.json`、`EXECUTION_LOG.txt`（绿区回收：225 项 / 33.66MB / 1418 文件）
- 督导垃圾审计报告：`deliverables/junk-audit-20260919.html`

**参与成员**：

| 成员 | 角色 | 职责 |
|------|------|------|
| Rex | SRE | L2 执行 |
| Cody | Code Reviewer | 对抗复核 |
| Docu | Tech Writer | 本报告落盘 |
| Zhen | Engineering Director | 编排汇编 |

---

> **免责声明**：本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
