# /purchase-plan 出货计划页 UI 重设计 —— 方案B 落地记录（2026-11-28）

## 背景与拍板

痛点（owner 原文口径）：打开页面要一眼看清两级信息——①月维度：当月哪些客户、哪些 SKU 有出货计划、各多少数量；②日维度：当月任意一天，哪些客户、哪些 SKU、各多少数量。所有数字都是数量口径。数据已存在（导出 CSV `出货计划_年_月_日汇总.csv` 为证），痛点是屏上呈现不清晰。

流程：erp-ui-design 技能取方法弃其视觉 token（其 Bootstrap/24px 圆角/Plush 配色与全站方角改版冲突）→ 产出 3 案效果图（`docs/ui-mockups/purchase-plan-redesign-{a-matrix,b-calendar,c-dual}-20261128.html`，脱敏数据、可交互下钻）→ **owner 拍板方案B：月历热力 + 当日明细主区**。

## 数据口径结论（盘点取证）

`GET /plans/monthly-aggregated` 一次返回 `rows`（按日聚合，含 `plans` 全明细=客户×产品×数量×工厂）、`sku_summary`（客户×SKU 月汇总）、`sku_date_index`（客户|产品 → 按日数量+出货状态）、`customers`（客户月汇总）——**日×客户×SKU 矩阵现接口完全支撑，本次零后端改动、零新增端点**。移动端 mobileRoutes 无此页（PC-only）。

## 改动清单（纯前端，scoped，不动共享组件与 API 写路径）

| 文件 | 动作 | 内容 |
|---|---|---|
| `PurchasePlanView.vue` | 重写 | 两 Tab 合并为单视图；风险聚合（riskItems）上收至此；kpi 改新口径 |
| `components/PurchasePlanBoard.vue` | 新增 | 单视图主体：左列=月历+风险条+客户 chips+SKU 月度统计；右列=当日明细主区（430px） |
| `components/PlanMonthGrid.vue` | 重写 | 格子新增「N 客户 · M SKU」元信息 + 客户占比条（flex-grow 分配） |
| `components/PlanDayDetail.vue` | 重写 | 客户组加色点+当日占比条；状态标签改出货口径（已出清/部分出/未出） |
| `components/PurchasePlanKpiStrip.vue` | 重写 | 四格大数字 KPI → 约 40px 一行五格信息条：本月计划/客户/SKU/峰值日/风险 |
| `components/PurchasePlanHeader.vue` | 重写 | 去掉视图 Tab 组（两 Tab 已合并），仅剩工厂 Tab 组 |
| `components/PurchasePlanToolbar.vue` | 改 | 去 viewTab prop，搜索占位统一 |
| `composables/useSkuSummary.ts` | 改 | 去 viewTab 参数（搜索现恒过滤 SKU 表） |
| `composables/usePurchasePlanData.ts` | 改 | 去 viewTab 参数 |
| `components/types.ts` | 改 | 新增 `DayCellMeta` |
| 删除 | — | `PurchasePlanDailyTab.vue`、`PurchasePlanMonthlySummary.vue`、`PlanRiskList.vue`、`CustomerDistPanel.vue`、`FactorySummaryCard.vue` |

测试：新增 `purchasePlanBoard.test.ts`（21 用例）；重写 `purchasePlanKpiStrip.test.ts`、`purchasePlanHeader.test.ts`；删除 3 个旧组件测试；2 个降级测试 stub 换 `PurchasePlanBoard`。

## 行为变化（owner 须知）

1. **两 Tab 合一**：原「排产日历」「月度汇总」不再是两个 Tab——月历、风险条、客户 chips、SKU 月度统计、当日明细同屏。客户筛选 chips 现在直接作用于下方 SKU 表。
2. **信息条口径**：顶条从「计划/已生产/完成率/风险」改为「计划/客户/SKU/峰值日/风险」。已生产、待生产、进度仍逐行在 SKU 月度统计表中给出（未丢，只是不在条上重复）。
3. **日明细状态标签**由「已生产/部分生产/待生产」更正为出货口径「已出清/部分出/未出」（后端 `getShipmentStatus` 比对的本来就是出货量）。
4. **风险清单**从右栏卡片列表压成月历下方一行 chips（点条目跳当天）；右栏恒为当日明细，未选日时给引导文案。
5. **SKU 导出**入口移到「SKU 月度统计」区块头（原在顶栏随 Tab 切换）；顶栏「导出」恒为日汇总 CSV。
6. 月历格子新增客户数·SKU数与客户占比条（客户配色按月度计划量降序分配色板，月历/明细/chips 三处同源）。

## 验证与上线证据（2026-11-28 当场跑出）

- 聚焦 vitest 7 文件：**58/58 passed**（Board 21、KpiStrip+MonthNav 9、Header 5、降级 4、dayStatus/monthGrid 纯函数 19）。
- `npm run type-check`（vue-tsc）零错误；`npm run lint` purchase-plan 目录 0 警告（UserView 3 条为存量并发改动，未触碰）；`check:routes` / `check:dto` / `check:types` 全 PASS。
- 构建前核查 3000 端口：为 nginx 双进程（erp-web 正常拓扑），无 dev 会话抢占。
- `npm run build:atomic` 成功（esbuild 外部副本 `D:\esbuild-ext\esbuild.exe` 已同步为依赖同版本 0.28.1；构建前发现 node_modules 缺 `@apideck/better-ajv-errors` 等 826 包，按 lock `npm install` 补齐，package-lock 未变）。
- 线上验证：`https://127.0.0.1/` index 200，`app-entry-DXN0hmXf.js` 与构建一致；`/assets/PurchasePlanView-y8Rj4aIM.js` 线上 sha256 `9605ca887f207126…` 与 dist **字节级一致**，且 chunk 内含方案B新代码标记；`:3000/nginx-health` 探针 200。
- 纯前端改动，无需重启任何 NSSM 服务。

## 回滚路径

- 前端：`swap-dist` 发布前有 dist 备份（见构建日志说明），回滚=换回上一份 dist；或 `git revert` 本提交后重新 build。
- 无后端/数据库改动，无迁移，无服务重启。

## 并发事故补记（2026-11-28 16:49–16:52）

落地期间一个**并发会话正在做「审批系统下线」任务**（15:47–16:16 连续 5 个提交），16:49 其 git 操作（疑似 pre-commit stash 流程）把本任务**未暂存**的全部改动整体退回 HEAD（`git restore`/stash 类操作不进 reflog，无新提交无新 stash 条目可查）；16:52:53 改动随其 stash pop 弹回工作区，内容逐字恢复。全程三个新建未跟踪文件（Board/SummarySection/Board 测试）因 stash 不含 untracked 而幸存。

处置：全面核对标记确认改动集完整 → 手术式暂存（期间发现并发会话自己的 8 个文件也滞留在暂存区，逐个 `restore --staged` 移出，**不夹带提交**）→ 提交 `23524d21` 落盘防再吞 → 复跑全部验证。

教训重申（与 AGENTS §6.1-5、2026-10-21 吞 21 文件同型）：**改动完成即 `git add`，攒够一个任务就提交**——未暂存内容在任何并发 git 操作面前都是裸奔。另：线上 chunk 校验曾被 SPA fallback 假象迷惑（已删 chunk 请求返回 200+index.html），必须同时比对 sha256 与 content-type。
