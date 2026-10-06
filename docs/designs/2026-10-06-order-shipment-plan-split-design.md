---
design_type: feature
created_at: 2026-10-06
---

# 订单出货计划 v2：单订单多批次分批计划

> 状态：**口径已获用户裁决**（必须排满 + 每批独立备注），按当日先例直接进入实施
> 关系：2026-10-06-order-shipment-plan-sync-design.md（v1 单日期版）的行为修订，部署数小时后升级，无持久化耦合

## Intent Contract

```yaml
intent: 订单备货录入的一条订单条目支持拆分多个出货计划批次，每批独立设置出货日期、数量与备注；提交时同事务同步为多条采购计划明细
constraints:
  - 数量口径（用户裁决）：各批数量之和必须等于订单数量，不等则拦截（前端暂存前 + 后端逐条校验双层）
  - 每批独立备注落入明细 remark（与「来源订单:{order_no}」并存）
  - 同事务原子性不变：任一批落库失败 → 该客户订单组整体回滚
  - 「无计划」路径零改动：shipmentPlans 为空 = 原流程
  - 字段替换而非并存：v1 的 has_shipment_plan/shipment_plan_date 移除，新 shipment_plans 列表；v1 前端与 v2 后端同发，无外部消费方
  - 跨月分批天然支持（沿用按月分组 find-or-create）
success_criteria:
  - 一条订单（如 500 件）拆 10-10×200 + 10-20×300 提交后，采购计划出现两条明细，数量/日期/备注各自正确
  - 分批之和 ≠ 订单量时前端拦截且后端兜底拒绝
  - 无计划条目提交行为与 v1 完全一致
  - 后端/前端新旧测试全绿；quality_gate 无本功能新增违规
risk_level: medium
```

## Verification Contract

```yaml
verify_steps:
  - run tests: python -m pytest fastapi_app/tests/test_shipment_plan_sync.py -v（扩充排满校验/多批次落库用例）
  - run tests: npm test --prefix frontend-vite（全量不回归 + 新用例）
  - check: python scripts/quality_gate.py 无本功能新增违规；vue-tsc 零错误
  - confirm: 部署后页面实测——单条 500 件订单拆两批提交，采购计划月历两日各见明细；无计划订单原流程无感
```

## Governance Contract

```yaml
approval_gates:
  - 口径裁决（已完成：必须排满 + 每批备注）
  - 实施后 code-review + 页面人工验收（同 v1 流程）
rollback: 单提交序列 git revert；无迁移无存量数据变更
ownership: 口径用户裁决，AI 实施与自验，页面验收用户完成
```

## Scope

| 范围 | 内容 |
|---|---|
| In（前端） | FormState/StagedItem 以 `shipmentPlans: {date, quantity, note}[]` 替换两旧字段；ShipmentPlanControl 升级为多行编辑器（日期+数量+备注+增删行，底部已分配/剩余统计）；useOrderForm 校验（每行完整 + 排满，排满属"值错误"走 quantityOutOfRange 同款拦截而非 missingFields）；useStagedItems payload 改发 shipment_plans；StagingArea 每批一枚 chip（超 2 批折叠 +N）；EditStagedModal 同款多行编辑器与保存校验 |
| In（后端） | BatchOrderItem 以 `shipment_plans: list[BatchShipmentPlanSplit]` 替换两旧字段（每项 plan_date/quantity/note）；_validate_one_item 逐项校验日期格式与数量 ≥1、总和必须等于订单数量；sync 函数每个 split 落一条明细，remark 拼接批次备注 |
| Out | 计划明细与订单行的强外键（仍走 remark 弱关联）；未排满场景（口径已否决）；Excel/OCR 导入的分批识别（默认无计划，编辑弹窗可补）；v1 字段兼容层（部署即切换） |

## Decisions

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| 1 | 分批总和口径 | 必须排满订单量（用户裁决） | 保证计划总量与订单量自洽；"先定首批后排补批"场景由采购计划页的订单余量机制承接 |
| 2 | 批次备注 | 每批独立（用户裁决） | 分批发货的运办差异（急发/拼车）需要批级说明 |
| 3 | 字段演进 | 直接替换 v1 两字段 | v1 部署数小时、无外部消费方、无持久化耦合；旧前端提交的未知字段被 Pydantic 静默忽略，切换窗口影响可忽略 |
| 4 | 排满校验的交互归属 | 走「值错误」通道（实时标红 + addStaged 拦截），不进 missingFields | 与 quantityOutOfRange 既有模式一致：缺项与值错误分开表达，避免长句误读 |
| 5 | 勾选即建首行 | 勾选「有出货计划」自动生成一行（日期空、数量=订单全量） | 减少一次点击；单批用户改个日期即可提交，多批用户加行拆分 |

## Surface

**API**：`BatchOrderItem.shipment_plans`，每项 `{plan_date: 'YYYY-MM-DD', quantity: int(≥1), note: str}`；校验失败文案区分「分批数量之和(X)必须等于订单数量(Y)」「出货日期格式错误」「分批数量必须大于 0」。

**存储**：零 schema 变更；一个 split = 一条 purchase_plan_details 行；remark 形如 `来源订单:PO-xxx；首批急发`。

**组件**：ShipmentPlanControl 内聚多行编辑器（含已分配/剩余统计），EditStagedModal 复用同一交互模式（独立实现，避免为两处抽公共组件引入耦合——两处行数均远低于门禁）。

**数据流不变量**：plans 空 → 同步短路（不变）；plans 非空 → 明细行数 = 批次数，逐批日期/数量落库。
