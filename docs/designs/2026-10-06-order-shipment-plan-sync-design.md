---
design_type: feature
created_at: 2026-10-06
---

# 订单备货录入：出货计划标记与采购计划同步

> 状态：**设计稿待评审**
> 日期：2026-10-06
> 关联页面：/customer-order（录入）→ /purchase-plan（消费）

## Intent Contract

```yaml
intent: 订单备货录入的「订单」条目支持标记"是否有出货计划"并选择出货日期；提交订单时在同一数据库事务内，把有计划的条目同步为采购计划系统对应客户当月（按出货日期所在月）的计划明细，日期/数量/产品与订单一致
constraints:
  - "无出货计划"路径零改动：选项默认为"无"，默认提交行为、payload 结构（对后端为新增可选字段）、权限要求与改动前完全一致
  - 订单与其采购计划明细原子：某客户的计划同步失败时，该客户的订单整组（主单+明细+抵扣）随 savepoint 回滚并报错，绝不出现"订单在、计划丢"的中间态
  - 落库复用 purchase_plan_crud_ops 的 create_plan / add_details，不新写计划写入逻辑
  - 不新增数据库表、不加列、不出 Alembic 迁移；同步溯源记在计划明细 remark（来源订单号），弱关联
  - 录单员不需要 production_plan_manage 权限：同步在服务层直调，绕过 /plans/create 端点的权限检查（有意为之，审计靠 plan.created_by 记录单人）
  - Excel 导入与 OCR 条目默认"无出货计划"，不改造这两条链路（可通过暂存编辑弹窗补设）
success_criteria:
  - 选"有"+日期提交后，/purchase-plan 对应客户月历出现该明细，日期=所选出货日、数量=订单数量
  - 同客户两条不同月的出货日期 → 生成/追加到两个月的计划主单
  - 该客户当月已有计划时 → 明细追加到既有计划，不报 409
  - 选"无"提交行为与改动前逐字节一致
  - 计划写入失败（如客户不存在）时该客户订单不落库，错误信息用户可见
  - 后端新增单测/集成测试通过；前端 vitest 全量不回归；quality_gate.py PASS
risk_level: medium
```

## Verification Contract

```yaml
verify_steps:
  - run tests: python -m pytest fastapi_app/tests/test_shipment_plan_sync.py -v （新增：月分组/追加已有计划/客户不存在/订单余量准入在事务内可见）
  - run tests: python -m pytest fastapi_app/tests -q （后端全量回归）
  - run tests: npm test --prefix frontend-vite （现有 717 用例不回归 + 新增断言）
  - check: python scripts/quality_gate.py PASS（新增 .vue ≤ 400 行、函数 ≤ 80 行）
  - check: npm run type-check --prefix frontend-vite 通过
  - confirm: 浏览器实测 /customer-order 提交带计划的订单 → /purchase-plan 月历可见；再提交一条"无计划"订单确认原流程无感知
```

**边界条件测试矩阵**（需求明确要求覆盖网络异常与数据格式错误）：

| 边界场景 | 预期行为 |
|---|---|
| 计划写入时数据库连接中断（网络异常在单体同库下的形态） | savepoint 回滚，该客户组报"数据库异常"，订单不落库；其他客户组不受影响 |
| shipment_plan_date 格式非法（绕过前端手改请求） | 后端校验拒绝，该组失败并返回明确文案，不产生半截数据 |
| has_shipment_plan=true 但日期为空 | 前端 missingFields 拦截（"还需填写：出货日期"）；后端 422 兜底 |
| 出货日期为过去日期 | 允许（计划补录场景），与采购计划页现有行为一致，不做拦截 |
| 同批同客户同产品多条带计划条目 | 各自成明细行、数量独立，与采购计划导入行为一致 |
| 同批同客户跨月出货日期 | 按月分组，分别 find-or-create 两个月的主单 |
| 客户名不在客户档案 | 该组失败，error 注明"客户档案中无此客户"，订单回滚 |
| 计划主单创建成功后明细写入失败 | 整组回滚（同一 savepoint），无孤儿计划主单 |
| 并发：两人同时为首建同客户同月计划 | 后到者唯一约束冲突回滚报错，重试自动转追加路径 |

## Governance Contract

```yaml
approval_gates:
  - 设计稿评审（本稿，用户拍板后进入 writing-plans）
  - 实施完成后 code-review（hotl:code-review）
rollback: 全部改动单分支单提交序列，git revert 即可完整回退；无迁移、无存量数据变更，回滚零残留
ownership: 设计由用户拍板；实施由 AI 执行；业务验收（页面实测）由用户完成
```

## Scope

| 范围 | 内容 |
|---|---|
| In（前端） | types.ts 的 FormState/StagedItem 增加出货计划两字段；新组件 ShipmentPlanControl.vue（单选开关+日期选择器，仿 OrderDeductControl 的挂载模式）；OrderInputPanel 订单模式挂载；useOrderForm 校验（选"有"缺日期→missingFields 提示"出货日期"）；useStagedItems 暂存与 payload 携带字段；StagingArea 条目卡片显示出货日期徽标；EditStagedModal 支持查看/修改两字段 |
| In（后端） | auxiliary.py 的 BatchOrderItem 增加可选字段 has_shipment_plan / shipment_plan_date；新服务 shipment_plan_sync.py（客户名→Customer.id 解析、按月分组、find-or-create 计划主单、明细 remark 写来源订单号）；order_batch_create.py 在每客户 savepoint 内订单创建成功后调用同步，并顺带修正"同步至采购中心"过期注释 |
| Out | 订单删除时联动删计划明细（与现状一致，不联动）；Excel 导入模板增加出货日期列；OCR 识别出货日期；记录查询页显示计划同步状态；采购计划页对"来源订单"的反查界面；订单表存储计划标记（溯源走明细 remark）；ARQ 异步重试（用户已选同事务策略） |
| Out（说明） | "备货"类型条目不显示该选项——备货是内部库存行为，不产生订单余量，同步到采购计划会与"订单余量>0"准入校验冲突（用户已裁决仅订单类型） |

## Decisions

| # | 决策 | 选择 | 否决的备选与理由 |
|---|---|---|---|
| 1 | 出货日期设置粒度 | 每条暂存条目单独设置（用户拍板） | 整批统一一个日期：同批不同产品无法有不同交期；ERPNext 的行级 delivery_date 模式佐证行级更通用 |
| 2 | 一致性策略 | 同数据库事务同步（用户拍板） | 事后同步+重试队列：存在"订单在、计划未同步"中间态窗口，需 ARQ worker 与幂等去重，复杂度高；调研结论：单体+同库场景同事务是首选，Outbox/重试仅适用跨系统 |
| 3 | 适用条目类型 | 仅订单（用户拍板） | 订单+备货都支持：备货不产生订单余量，会被计划准入校验拦截，语义说不通 |
| 4 | 已有计划的合并 | 追加明细到已有计划（用户拍板） | 合并同产品同日期数量：破坏与订单的行级对应，需额外合并逻辑，且与现有导入行为（并存多行）不一致 |
| 5 | 溯源方式 | 计划明细 remark 写来源订单号 | 订单表加列存储计划标记：需迁移且无功能消费方（YAGNI）；Odoo 用 origin 字段弱关联佐证此模式 |
| 6 | 权限边界 | 服务层直调，不检查 production_plan_manage | 前端双调用（batch-submit + plans/create）：有权限墙（录单员无计划管理权限）、两次 HTTP 无原子性、计划端点的订单余量校验会因订单未提交而误报 |
| 7 | 同步落点 | 每客户 savepoint 内、订单创建后调用 | 事务最外层统一调用：某客户计划失败会污染整批（现有批量语义是按客户部分成功，组内原子即可满足"订单+计划原子"约束） |
| 8 | UI 组件形态 | 独立 ShipmentPlanControl.vue 子组件 | 直接内联进 OrderInputPanel：该文件已 311 行，内联有撞 400 行门禁的风险；OrderDeductControl 已确立子控件模式 |

## Surface

**API**：`POST /api/v1/aux/batch-submit-orders` 请求体 `BatchOrderItem` 增加两个可选字段：`has_shipment_plan`（布尔，缺省 false）与 `shipment_plan_date`（`YYYY-MM-DD` 字符串，has_shipment_plan 为真时必填，后端校验）。响应结构不变；同步失败以现有"按客户失败"的 results[].error 形态返回，文案含失败原因（如"客户不存在于客户档案"）。

**存储**：零 schema 变更。写入发生在既有 purchase_plans / purchase_plan_details 两表；计划主单按（customer_id, plan_month）唯一约束 find-or-create；明细行 plan_date=出货日期、quantity=订单数量、remark=`来源订单:{order_no}`；plan.created_by=提交订单的用户名；upload_batch 留空。

**组件与交互设计**（设计基调：在既有 ocean 色系与圆角语言内做"有意图的克制"，让新控件成为表单中可记忆的视觉锚点，而非又一组灰框）：

- **无打扰原则**：未勾选时新增内容占零像素——复选框是唯一的可见增量，原有表单节奏完全不动。
- **检查态即锚点**：勾选「有出货计划」后，整行浮出 primary-50 底色与 primary-200 描边（复用 co-tab-btn.active 的既有视觉语言），成为表单中唯一的彩色区域——扫视即知"这条订单带计划"。
- **揭示动效**：出货日期行以 grid-rows 0fr→1fr 加 160ms ease 展开（与全局 hover transition 同节奏），展开后自动聚焦日期输入，省一次点击；prefers-reduced-motion 下退化为直接显示。
- **出货 chip 的唯一彩色信号**：暂存卡片上以卡车图标 + primary 色调呈现"出货: MM-DD"，在抵扣/备注等中性 chip 群中形成唯一的彩色点，视觉搜索成本最低。
- **提交反馈**：toast 措辞在存在同步时扩展为"已提交：订单 N 条（其中 M 条已同步出货计划）"；同步失败跟随现有"按客户报错"文案，不新造错误形态。
- **可复用技术方案（GitHub 调研沉淀）**：ERPNext 行级 delivery_date → 每条目独立日期；Odoo origin 弱关联 → 明细 remark 记来源单号；OCA 模块"开关+日期"组合控件 → 复选框+日期选择器；单体同库同事务写入 → 无需 Outbox/重试队列。
- **关于"与 purchase-plan 系统接口对接"的澄清**：两个 URL 实为同一 FastAPI 应用的两个前端路由（同一 nginx、同一数据库），因此"接口对接"落地为**模块间服务层调用**（订单域调用计划域的 create_plan/add_details 服务函数），而非跨进程 HTTP 自调用——后者会在事务内制造自我 HTTP 依赖，破坏同事务原子性且无任何架构收益。对接边界与契约 = BatchOrderItem 的两个新增可选字段 + 计划明细的落库形状。

**改动文件清单**：前端新增 1 个组件（ShipmentPlanControl.vue，封装复选框+日期选择器组合）、修改 6 个文件（types/useOrderForm/useStagedItems/OrderInputPanel/StagingArea/EditStagedModal）；后端修改 2 个文件（auxiliary.py 请求 schema、order_batch_create.py 组内编排）、新增 1 个服务文件（shipment_plan_sync.py）与 1 个测试文件（test_shipment_plan_sync.py）。

**数据流不变量**：无计划条目 → 后端两字段缺省 false/None → 同步函数对空集合短路返回，与现状路径完全一致；有计划条目 → 计划明细必须与订单同事务可见（savepoint 内自见），"订单余量>0"准入校验天然通过。

## Risks & Open Questions

- **客户名无法解析**：order.customer 是自由文本（历史数据可能不在 customer 表）。同步前按名称精确查 Customer，查不到 → 该客户组整体失败并在 results[].error 说明。开放问题：是否需要"自动创建客户档案"兜底？现按"报错人工处理"设计（保守，避免脏档案）。
- **并发竞态**：两人同时为同一客户首次创建同月计划 → 唯一约束冲突，PlanExistsError 使后到组回滚报错，用户重试即走追加路径。内网低频，接受。
- **savepoint 嵌套**：create_plan 内部的 begin_nested 会嵌套在订单组的 begin_nested 内，PostgreSQL 支持多层 savepoint，但需集成测试实机验证（列入 verify_steps）。
- **订单后续删除不联动**：删单后计划明细仍在（数量已计入月历）。与两模块现状一致（本就互不感知），明细 remark 可人工溯源。若业务后续要联动，属独立需求。
- **数量口径**：同步数量=订单条目数量（含抵扣关系不管控——计划是"要出多少货"，与备货抵扣进度正交）。若业务希望扣掉已备货量，需再裁决。
