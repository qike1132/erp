---
design_type: feature
created_at: 2026-09-10
---

# 库存多年期出入库模拟测试（生产 API）设计

## Intent Contract

```
intent: 在生产 API（http://192.168.0.95:3000）上以 SIMTEST- 前缀隔离数据，完成 3 年跨度
        （2026-09 → 2029-09、约 1095 天、日级推进）的出入库全生命周期模拟，验证库存余量、
        出入库流水、账目汇总三账一致性与边界约束正确性。
constraints: 生产服务不中断；SIMTEST- 前缀以外的数据零影响；不改动任何现有 API/服务代码。
success_criteria: 37 个检查点（36 月末 + 最终）三账全部一致；全部边界探针被正确拒绝且
                  状态零变化；预期成功操作 100% 成功（无意外失败）。
risk_level: high（生产数据库写入）
```

## Verification Contract

```
verify_steps:
  - run: python scripts/stock_sim/simulator.py --seed 20260910 --dry-run
    check: 干跑生成的操作序列逻辑合法（出库量始终 ≤ 可出货量、无负库存路径）
    confirm: dry-run 汇总显示 0 个非法操作
  - run: python scripts/stock_sim/simulator.py --seed 20260910 --live   # 需人工放行（gate②）
    check: journal 落盘完整（ops.jsonl 逐条含请求/预期/实际），中断可 --resume 续跑
    confirm: 全部预期操作执行完成，journal 记录数 == 计划操作数
  - run: python scripts/stock_sim/verifier.py --journal <journal目录>
    check: 独立拉取 API 全量数据，对 journal 预期账本做三账核对（A1-A6）
    confirm: 报告 37 检查点全 PASS、边界探针全 PASS、差异数 = 0
  - run: python scripts/stock_sim/cleanup.py --confirm                 # 需人工放行（gate③）
    check: 清理后 SIMTEST- 客户在 in/out/inventory 列表中零残留，测试产品已删除或库存归零
    confirm: 复跑 cleanup 输出 "无待清理项"（幂等验证）
```

## Governance Contract

```
approval_gates:
  ① 设计批准（已通过：方案 B + 三年跨度 + 完整生命周期 + 正常流与边界校验）
  ② dry-run 通过后、live 执行前的人工放行（含确认生产服务健康 + 触发一次全量备份）
  ③ 报告产出后的人工确认，放行 cleanup 清理
rollback: cleanup.py 删除全部 SIMTEST- 订单/入库/出库记录并删除（或清零）测试产品；
          异常场景可回滚至 gate② 前的全量备份（复用现有备份模块）。
ownership: 用户拥有生产放行权（gate②③）；模拟器/校验器/清理器由本任务交付并落库。
```

## Scope

### In（范围内）

| 项 | 说明 |
|---|---|
| 时间跨度 | 2026-09-01 → 2029-09-01，约 1095 天，以日为单位推进，通过日期字段模拟未来时间（已验证 API 接受未来日期） |
| 操作频次 | 每日 10 次，混合节奏：订单创建 + 入库 + 出库 + 低频偶发编辑/删除，合计约 10950 次操作（3年×365×10） |
| 操作顺序 | 每日固定节奏：先订单创建（保证出库有订单支撑）→ 后入库/出库（出库受可出货量 FIFO 约束）→ 偶发穿插编辑/删除；订单耗尽时补单；固定随机种子保证可复现 |
| 生命周期操作 | 入库创建/编辑/删除、出库创建/编辑/删除、订单创建（支撑出库，FIFO 按 order_date 抵扣） |
| 三账校验 | A1 实时余额账、A2 流水账、A3 视图账、A4 流水明细、A5 汇总账、A6 不变量（见 Decisions） |
| 边界探针 | 每 6 个月 1 组（共 6 组）：超卖、超可出货量、零数量、负数量、非法日期——全部预期被拒绝且状态零变化 |
| 交付物 | simulator / verifier / cleanup 三脚本 + journal 落盘 + JSON 与 Markdown 测试报告 |
| 数据隔离 | 专用产品（SIMTEST-PROD-时间戳）+ 专用客户（SIMTEST-CUST-时间戳），所有变动封闭其上 |

### Out（范围外）

| 项 | 排除原因 |
|---|---|
| 退货（StockReturn） | 服务层存在 create_stockreturn 但未暴露 HTTP 路由，生产 API 模拟无法覆盖 |
| 订单编辑/删除（业务场景中） | 订单仅作支撑条件；订单 edit 可能触发审批流变化、delete 语义待考（视图 CTE 无 is_deleted 过滤），控制复杂度 |
| 订单抵扣路径（orders/deduct、订单转备货） | 独立业务链路，超出"多次出货与入库"的核心诉求 |
| 皮套出入库（case_stock_in/out） | 独立库存域 |
| 并发竞态 | 已有 test_stock_concurrency.py 覆盖，本任务聚焦时序一致性 |
| 性能压测 | 串行执行的时序一致性验证（达 ~1.1 万次），并发竞态交由已有 test_stock_concurrency.py；性能仅顺带观察聚合查询在 1.1 万记录下的响应 |
| 前端 UI 校验 | 纯 API 层验证，UI 展示不在本任务 |

## Decisions

| # | 决策 | 选择 | 否决的替代方案 |
|---|------|------|----------------|
| 1 | 执行器形态 | 方案 B：模拟器/校验器/清理器三件分离，journal 落盘 | A 单脚本一体化（中断不可恢复、校验不可独立重跑）；C pytest 直连生产（CI 误跑生产风险） |
| 2 | 时间模拟方式 | 通过 stockin_date/stockout_date 指定未来日期 | 真实等待 3 年（不可行）；改系统时钟（影响生产） |
| 3 | 随机性 | 固定种子（默认 20260910），dry-run 与 live 序列完全一致 | 纯随机（不可复现、不可断点对照） |
| 4 | 数据隔离粒度 | 专用产品 + 专用客户 | 复用现有产品（出库扣减全局 Product.current_stock，污染真实库存）；仅前缀标记客户（不隔离余额账） |
| 5 | 三账锚点 | A1 `/aux/product-available-stock`（实时余额）；A2 `/aux/inventory-logs/{pid}` Σ变动 == 余额；A3 `/stock/inventory` total_stock == 预期；A4 in/out list 逐条对照 journal；A5 列表Σquantity 与 stats 增量；A6 余额非负 + 出库前 available-shipment 预检 | 仅校验最终态（丢失月度漂移检测）；仅 A1（单一锚点可信度不足） |
| 6 | 边界探针预期 | 全部被 API 拒绝（4xx 或 success=false）且三账状态零变化 | 跳过边界（用户已确认要含边界） |
| 7 | 缓存时滞处理 | verifier 检出差异时先等待 local TTL（60s）复检一次再判失败 | 直接判失败（生产多进程 local 缓存可能造成误报） |
| 8 | 限速策略 | 操作间 80-100ms 间隔，429/5xx 指数退避重试（上限 3 次） | 无限速（触发限流器导致操作意外失败） |
| 9 | 凭据供给 | 环境变量 ERP_SIM_USER/ERP_SIM_PASSWORD，不硬编码 | 写入脚本（凭据泄漏） |
| 10 | 报告产出 | docs/reports/2026-09-10-stock-multiyear-simulation-report.md + 同目录 JSON | 仅控制台输出（不可审计） |

## Surface

**新增文件**（scripts/stock_sim/ 目录，全新目录，不触碰现有代码）：

- `simulator.py`：登录建权 → 数据准备（建产品/客户）→ 按种子生成约 1095 天 × 每日 10 次操作序列 → 日级顺序执行并逐次维护预期账本 → journal 落盘（ops.jsonl / checkpoints.json / summary.json）。支持 `--dry-run`（只生成与校验序列，不调写接口）与 `--resume`。
- `verifier.py`：独立登录 → 分页拉取 in/out list、inventory 视图、inventory-logs、product-available-stock、stats → 对 journal 做三账核对（含差异复检机制）→ 输出报告。
- `cleanup.py`：幂等清理——删除 SIMTEST- 全部出库/入库/订单记录 → 删除测试产品；可独立先跑，重复执行输出"无待清理项"。

**依赖的生产 API**（只读 + 写入，全部为现有端点）：

- 认证：`POST /api/v1/auth/login`（JWT Bearer，需 stockin_manage / stockout_manage 及订单创建、aux 查询权限）
- 写操作：`/stock/in/create|edit|delete`、`/stock/out/create|edit|delete`、`/orders/create`、`/products/create|delete`
- 读校验：`/stock/in/list`、`/stock/out/list`、`/stock/inventory`、`/stock/stats`、`/aux/inventory-logs/{pid}`、`/aux/product-available-stock`、`/aux/available-shipment`

**journal 落盘**：`scripts/stock_sim/journal/<时间戳>/`，每行一条操作（序号/月份阶段/操作类型/请求体/预期效果/实际响应），为事后审计与断点恢复的依据。

## Risks & Open Questions

| 风险 | 等级 | 缓解 |
|------|------|------|
| 生产数据库写入污染 | 高 | SIMTEST- 前缀全隔离；gate② 前强制全量备份；cleanup 幂等且可先跑 |
| 多进程 local 缓存导致校验误报 | 中 | verifier 差异复检机制（等 local TTL 后重查一次） |
| 测试产品删除失败（被历史数据关联） | 中 | 兜底策略：记录清零 + 产品遗留（SIMTEST 前缀可辨识，无害）；报告中标注 |
| 限流器触发导致操作意外失败 | 中 | 80-100ms 限速 + 指数退避；意外失败计入报告差异项而非静默重试 |
| 凭据权限不足（aux 端点权限名未逐一确认） | 低 | dry-run 阶段首个动作即探测全部依赖端点可达性，快速失败 |
| 订单删除语义（视图 CTE 无 is_deleted 过滤）与预期不符 | 低 | 订单删除仅在 cleanup 中使用，业务模拟不含订单删除；如 cleanup 后视图异常，单独记录为发现项 |
| 开放问题：stats 为全局口径，仅能以"执行前后增量"校验 A5 | 低 | 模拟开始前快照 baseline，结束后对比 Δ |
