# 迭代审核记录 #2 —— 2026-10-05 晚（审核时点 20:34–20:55）

> 审核对象：晚间迭代的最终工作区状态（白天两轮见 [iteration-review-2026-10-05.md](iteration-review-2026-10-05.md)）。
> 方法：按 mtime 把改动分为**稳定组**（≥30 分钟无写入）与**在飞行组**（审核期间仍被并行会话实时改写），只对稳定组下逐行结论；一切结论以编译器/测试/哈希复验为准，不采信单次工具输出（本晚多次遭遇工具输出污染，详见 §6）。

## 0. 迭代全景

| 组 | 内容 | 状态 |
|---|---|---|
| 本会话 | production 弹窗 3 组件 v2（1200px/min-height 480/控件 64px + 遮罩去点击关闭） | **已上线**（live 五层 hash 校验一致，erp-web RUNNING） |
| 并行会话已提交 | f2d72fd1（出货页 data 键错配修复，3 文件） | 干净：提交信息写明"为什么"，types 补齐顺带消除退货模块类型错 |
| 稳定未提交 | router.py、nav_context.py、069 迁移、schedule_service.py、inventory_service.py、auxiliary.py、StockOutRecords.vue、备份页 4 组件、3 张表格、2 个既有测试、3 个新脚本、退货前端视图/api/路由接线 | 逐项审核 ✓ |
| 在飞行 | stock_return 后端三件套（service/schema/endpoint，20:32–20:36 仍在写）+ 前端弹窗/composable（20:50–20:51） | 只记客观事实，不下结论 |
| 门禁 | quality_gate / ruff(迭代文件) / vue-tsc / check:api / check:routes | 全 PASS（快照） |
| pytest | **3 failed / 3883 passed / 181 skipped**（10.5 分钟） | 3 失败全部归因飞行组 |

## 1. 已验证结论（稳定组）

**弹窗 v2（本会话）**：三组件 diff 自审 = 纯样式值 + 唯一模板变更（遮罩 `@click.self` 移除并注释原因：防误触丢已录内容，仅 ✕/Esc 关闭，Esc 链路已核实先收菜单再关弹窗）；vue-tsc、quickEntry 16 测全过；上线后 live 链路（index.html → 主 js → 路由 js/css → 全局 css）与 dist 哈希逐层一致。

**退货模块接线（稳定部分）**：
- 迁移 069：单 head ✓、生产库已应用 ✓、幂等 seed（NOT EXISTS 守卫）、downgrade 先清 user_permission 再清 permission；Revises 正确挂 067（068 回滚后），文件头注释交代缘由。
- router.py：`/stock-returns` 带 `get_current_user_id` + 端点级 `require_permission('stock_return_view'|'stock_return_manage')` 双层鉴权。
- nav_context.py：`stock_return_view → [view, manage]` 展开，与迁移"manage 命名继承 view、刻意不反向挂子权限"的模型自洽。
- 依赖存在性：`require_permission` / `db_transaction` / `escape_like` / `UTC` 导入齐全；服务编排函数（防超退、乐观锁写入口、流水、订单重算、领域事件、request_id 幂等令牌）在 `stock_return_service.py` 中分层清晰。

**备份调度补跑修复**：`STALE_RUNNING_AFTER=2h`；仅 `running` 超阈值放行补跑，`failed/success` 终态不重试（防 5 分钟 poller 反复重试）；并发双跑由任务内 advisory lock 兜底。闭环白天"重启杀死定时备份、窗口永久丢失"问题。`test_backup_m2.py` 新增 4 测：超阈值补跑 / 新鲜 running 跳过 / failed、success 不补跑，全绿。

**available-shipment 只读副本修复**：`calculate_available_shipment_quantity` 增 `lock_orders: bool = True` 关键字参数，展示端点传 False 写路径保锁；配套 `tests/test_available_shipment_readonly_session.py`（server_settings 复刻热备）通过。与白天审核 #1 的 Round-1 结论一致。

**行内退货入口（StockOutRecords.vue）**：权限门 `stock_return_manage` 与后端一致；`returned_quantity < quantity` 才显示（防超退入口）；复用退货模块 composable/弹窗不重复实现；提交后手动刷新列表（注释说明 returned_quantity 不归 vue-query 管）。

**test_import_idempotency_constraints.py**：单 head 断言从"head==067"放宽为"067 可从 head 回溯到达"——消除未来迁移前移时的写死误红，前瞻正确。

**存量小改**：备份页时间 slice(0,10) + 状态中文；ScheduleConfig `cronLabel` 仅翻译每天/每周X/每月X日三种本页会产生的形态，步进/区间原样回退，dow 7→周日映射正确，悬停 title 留原文；三张表格去圆角（scoped 覆盖共享组件默认值，未动共享组件）。

**ruff**：迭代六个后端文件 `All checks passed!`；裸 `ruff check .` 的 99 处全在存量基建（server_manager、docs/audit-round2 工具等），非本次迭代引入；门禁口径（ruff.toml scoped）59 处与基线一致。

## 2. 在飞行组（客观事实，不下结论）

- 审核期间 mtime 持续变化：service 20:32、schema 20:34、endpoint 20:36、useStockReturn.ts 20:50、StockReturnCreateDialog.vue 20:51（均距审核动作 <2 分钟）。
- 观察到 `delete_stockreturn → cancel_stockreturn` 改名进行中（P1-① 软取消语义：记录保留 status='cancelled'，库存/流水/订单重算对称回冲），中间态下端点 import 与服务函数名一度不一致。
- pytest 快照 3 失败全部锚定该模块：`test_create_stockreturn_deduction_protected`、`test_delete_stockreturn_core_message_verbatim_then_releases`、`test_every_write_point_calls_unified_entry[stock_return_service.py]`——与改名中间态吻合（旧名测试 + 统一写入口扫描中间态文件），**非稳定范围回归**（稳定范围 3883 测全绿，含弹窗 16 测、调度 4 测、readonly-session 回归）。

## 3. 门禁汇总（审核时点快照）

quality_gate **PASS** · ruff 迭代文件 **0** · vue-tsc **0** · check:api **✓**（移动端共享 API 层）· check:routes **✓** · pytest **3f/3883p/181s**（3f 归因飞行组）

## 4. 发现与建议

- **P2（流程）**：并行会话活动期跑全量门禁只能得快照结论。建议其文件静默 ≥10 分钟后**复跑** pytest + vue-tsc 作收官门禁；届时 3 个失败应随改名收尾消失，若仍在则是该会话必须修的真回归。
- **P3（代码）**：StockOutRecords.vue `openReturn` 用 `row as Parameters<typeof openFromStockout>[0]` 断言绕过结构检查，运行时依赖 `stockout_no/returned_quantity` 字段存在（f2d72fd1 已补类型，但接口再变会静默漏字段）。低风险，建议后续改显式字段挑选。
- **P3（环境）**：本晚多次遭遇工具输出污染（与所执行命令不符的内容混入，含伪造 diff 尾巴——一次伪造恰好把 ScheduleConfig 的 `cronLabel` 扭曲成坏版本，实读无恙）。全部靠"编译器/测试/哈希复验"兜住，未据此下过结论。

## 5. 与审核 #1 的衔接

- 审核 #1 遗留 1（product 20857 负库存 -13001 待对平后 VALIDATE 约束）**仍开放**，本晚 pytest 3883 通过含还原后的 103 个守护测试，约束 NOT VALID 状态未变。
- 审核 #1 提到的 069 改挂 067 的"最小干预"，本晚已验证单 head + 生产库 069 生效，闭环。

## 6. 审核方法备忘

1. 先 `stat` mtime 分层，飞行文件不做逐行审——每次读取都是不同中间态，互相"矛盾"的多次输出多为真实现象。
2. 结论只认：py_compile / ruff / vue-tsc / pytest / curl 哈希。
3. git-bash 管道会吃退出码并夹带 `\r`（`$(grep)` 当路径/URL 用必踩），一律日志文件 + echo $? + 直测。
