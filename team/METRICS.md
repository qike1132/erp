# 团队指标（METRICS）

> 由 `/team learn` 自动聚合，最后更新：2026-09-30T06:39:59.258Z

## 总览

- 总 run 数：1
- 非 run 条目（文件 / 无 STATE.json·TASK.md·RUN.log.md 的目录，未计入）：1 个
- 已完成：0
- 有日志的 run：1
- 返工/失败率：100%（= 1/1，分母是「有日志的 run」而非全部 run）
- 返工判定口径（多源，可审计）：log:error×1 · tasks:verdict|status×1
  · 旧实现只统计 RUN.log 的 role:result 与 error 事件，而 LOGGING 约定从不写 role:result ⇒ 恒 0；
    现改由 TASKS.json 的 repair 任务 / round>1 / verdict / rounds 与日志共同判定。
- 返工性质分解（分母同上，**不改上面那个率**）：仅环境/平台 **0** 个 · 仅过程（质量环/角色/台账） **1** 个 · 两者都有 **0** 个 · 无返工证据 0 个
  · 「环境/平台类」判定族（换环境或没有并发就不会发生）：error:external-write / error:stale-runtime / error:platform / error:dispatch / error:timeout
  · **未列出的错误族一律算过程类**（宁可算过程，不放过 —— 把未知当环境类会系统性美化指标）。
  · ⚠️ 「**用户新需求导致的重做**」**无法自动识别**，本分解不覆盖它；需要人工登记或在 RETRO 里说明。

## 阶段覆盖

- `research`: 1 次
- `design`: 1 次
- `spec-review`: 1 次

## 首产物（首个可运行产物耗时）

- （暂无 first-runnable 登记：有日志的 run 共 1 个，但没有一个算得出「首个可运行产物耗时」—— **这不等于"首产物很快"**）
  · 「未登记」1 个 run = 该 run 没有可运行产物 **或** lead 没写 `first-runnable` 事件 —— 日志**无法区分**这两种情况

## 收尾预算（实现期 = 首产物→冻结 · 收尾 = 冻结→交付）

- （暂无收尾预算可算：有日志的 run 共 1 个，但没有一个同时算得出「实现期」与「收尾期」—— 缺的是 `phase:review`/`phase:test` 记账，不是"没有收尾"）
  · ⚠️ 1 个 run **既无 `first-runnable` 也无 `phase:implement`** ⇒ **实现期起点缺失**（这跟"没有收尾"是两回事；SKILL §7.33 ⓿ 要求开工时就登记首产物）

## 角色结果（pass=交付 / rework=返工件 / fail=失败）

- reviewer: pass 0 / rework 0 / fail 1
- researcher: pass 1 / rework 0 / fail 0
- pm: pass 1 / rework 0 / fail 0
- architect: pass 2 / rework 0 / fail 0
- （未参与：backend、dba、devops、docs、frontend、qa、sec、ui）

## 未闭环（不计入返工率，但必须可见）

- 未终态任务（pending / claimed / in_progress / rework / blocked）：**15** 个（完整的审核一下我这个项目-060103: T06/T07/T08/T09/T10/T11/T12/T13/T14/T18/T19/T21/T15/T16/T17）
- 已取消任务：**1** 个（完整的审核一下我这个项目-060103: T20）
    · 完整的审核一下我这个项目-060103：⚠️ **未记录取消原因**（值得看一眼）
- 有修复但**无独立复验**（该修复之后没有已完成的质量任务覆盖到它的轮次）：无
  · 本节数字**不进返工率分子**：它们记的是"**没交付完**"，不是"返工"。两者必须分开读。
  · 依据：一次真实会话结束时仍有 3 项被审查标为「必修」的缺陷未闭环，而这类"跑完但没收口"完全不计入返工率。

## 高频卡点（error / 返工，去重）

- `error:spec-conflict` × 1 — Q1（只读）与 Q5（含修复后验证）互相冲突，lead 已升级用户裁定（未获裁定前按 Q1 冻结）
- `error:architect` × 1 — 架构师实例异常中断（failed before it finished，无收尾消息，未落盘）→ 已重派
- `error:pm` × 1 — pm 修订实例异常中断一次（SPEC.md 未改动）→ 已重派并追加第二批修订
- `error:agent-failed` × 1 — pm(e0e29e6d) 与 architect(58f64316) 在收到 14:25:09 修复派工后均 failed before it finished、未留收尾消息；实测 SPEC.md 仍 14:17:47 / PLAN.md 

## 用户高频提问（ask，去重）

- `ask:clarify` × 5 — Q1 变更权限（只读审计 / 修 P0·P1 不提交 / 修复并推送）

## 决策记录（decision，去重）

- `decision:user` × 2 — 澄清 5 问已答：Q1=只读审计（不动业务代码）· Q2=允许跑质量门禁命令 · Q3=全维度平均覆盖 · Q4=总报告+分角色报告+可执行 backlog · Q5=深度（含修复后验证）
- `decision:标准档` × 1 — 用户在浮层拍板（2026-09-30T06:01:25.525Z）
- `decision:lead` × 1 — Q1/Q5 冲突按 Q1（只读）冻结，裁定提交方案确认门，不再单独阻塞等待

## 单源化总扫（见一个，扫全部）

- （无单源化总扫登记：`scan:single-source` 事件一个都还没写过）
- 返工成因：单源化类占比 —— **暂无返工可算**（没有 `kind=repair` 的任务；这不等于 0%）

## 评审效率（轮次 / 撤销率）

- 评审轮次：review 1 轮 · test 0 轮
- （暂无撤销登记：质量任务 findings 未标记 reverted）

## token 成本与上下文峰值

- **无 token 记账**：没有任何 run 有可用的 token 数据（会话遥测读不到，且日志里没有 `tokens:<scope>` 事件）。
  · ⚠️ 这一行**不代表消耗低** —— 它只说明"没测到"。本包实测过的真实 run 里，单条 lead 会话累计 prompt 达 **9.7 亿**、
    每步 prompt 中位数 **426K**；**没有数就没有刹车**，这正是本小节存在的原因。
  · 数据来源：DSH 会话遥测（`~/.dsh/sessions/<workspace-slug>/...`）或 `RUN.log.md` 的 `tokens:<scope>` 事件（见 LOGGING.md）。
