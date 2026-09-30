# 规格说明（SPEC / Ultra Spec）

> pm 起草 · runId：技术方案评审团-吧http-063959 · 页面：`/customer-order`
> 状态：初稿，待 spec-review 门禁与澄清点拍板（见 §8 澄清点）
> 只读依据：REPOWIKI.md + 目标仓库代码实测（行号为只读实测值，锚点以字符串为准）

## 0. 需求原文与依据

**需求原文（编排者转述）**：
> 页面 /customer-order 的「记录查询 / 订单 / 备货」三部分数据合并展示；删除现有筛选代码，重写一个能按「订单 / 备货」类型筛选、并能按「产品名称」搜索的新筛选。

**TASK.md 原始口径**：
> 技术方案评审团 吧http://192.168.0.95:3000/customer-order的记录查询 订单 备货 的数据合并在一起、然后吧现在的筛选代码删除 重新写一个 可以筛选 订单和备货 搜产品名称

**现状代码依据（REPOWIKI + 只读实测）**：

| 锚点 | 说明 |
|---|---|
| `frontend-vite/src/views/customer-order/CustomerOrderView.vue:5-12` | 页面仅「录入 / 记录查询」两个 Tab |
| `frontend-vite/src/views/customer-order/components/OrderRecordFilter.vue:3-12` | 记录查询头部有「订单/备货」**互斥切换**（recordType），是切换不是筛选 |
| `frontend-vite/src/views/customer-order/components/OrderRecordFilter.vue:15-52` | 现有筛选面板五维：客户 / 状态(仅订单) / 工厂(仅订单) / 开始日期 / 结束日期 |
| `frontend-vite/src/views/customer-order/composables/useOrderList.ts:63-113` | `fetchOrders()` 按 recordType 分支请求两个**独立**端点：订单 `GET /orders/list`、备货 `GET /stock/in/list`，两表数据从未合并 |
| 后端 `fastapi_app/api/v1/endpoints/order.py:43`（`list_orders`） | 订单列表仅 `product_id` 精确筛选，**无产品名称搜索** |
| 后端 `fastapi_app/api/v1/endpoints/stock.py:42-73`（`list_stockins`） | 备货列表仅 customer/start_date/end_date，**无产品名称搜索** |
| 后端 `fastapi_app/api/v1/endpoints/order.py:98-124` → `fastapi_app/services/order/beile.py:408`（`get_beile_orders_with_stockins`） | **合并先例**：已用 UNION ALL 合并订单+备货，支持 `product` 关键字（名称/条码）服务端过滤；但硬编码 factory='湖北' 且夹带湖北确认/采购单注入逻辑 |

**结论**：本需求本质是把「湖北订单页已有的合并列表能力」泛化到全工厂的 /customer-order，并把筛选重写为「保留既有筛选 + 新增 类型/产品名称/单号」。

## 功能目标

1. 「记录查询」Tab 内，订单（Order）与备货（StockIn）合并为**单一张列表**展示，用「类型」徽章/列区分；废除 recordType 互斥切换。
2. 重写筛选为**全保留 + 新增**：保留 客户 / 状态(仅订单) / 工厂(仅订单) / 开始日期 / 结束日期；新增 **类型**(全部/订单/备货，默认全部) + **产品名称**(模糊，名称或条码) + **单号/编号**(order_no 或 stockin_no 关键字)。
3. 产品名称搜索**服务端过滤**（分页前），禁止前端「先分页后过滤」漏命中（沿用 beile-list 既有结论）。
4. 分页、排序、加载/空/错误态、查看详情/删除等既有能力不退化。
5. 工厂权限隔离不退化：非超管且绑定工厂的用户，只能看到本厂数据（沿用 order/list 现逻辑）。

## 验收标准（逐条、可测）

- [ ] A1 进入「记录查询」，默认展示**订单+备货合并**的同一张列表，单页内两类记录按时间倒序统一排序，各有类型徽章区分。
- [ ] A2 类型筛选提供「全部 / 订单 / 备货」三态（默认「全部」）：选「订单」仅显示订单、选「备货」仅显示备货、选「全部」两者兼有。
- [ ] A3 输入产品名称关键字点查询后，仅返回名称或条码命中的记录，且命中判断发生在**分页之前**（翻页不漏）。
- [ ] A4 输入单号/编号关键字点查询后，仅返回 order_no 或 stockin_no 命中的记录（模糊包含，服务端过滤）。
- [ ] A5 产品名称关键字为空白或全空格时，等价于不筛选（返回全部）。
- [ ] A6 类型筛选与产品名称搜索可组合：先选「订单」再搜「苹果」→ 仅返回名称含「苹果」的订单；先选「备货」再搜「苹果」→ 仅返回名称含「苹果」的备货。
- [ ] A7 保留字段与新增字段可组合：客户 + 状态 + 工厂 + 日期区间 + 类型 + 产品名称 + 单号 任意组合生效，交集取数。
- [ ] A8 重置（如有）清空类型回「全部」、清空产品名称/单号，并回到第 1 页。
- [ ] A9 删除/查看详情操作在合并列表上仍可用，且能按 record_type 正确路由（订单→订单详情/删除，备货行只读、不显示删除，见 §4 边界十问·归属）。
- [ ] A10 空态文案与错误态文案区分：无数据显示「暂无记录」，接口失败显示可重试的错误态（沿用 OrderRecordTable.vue 既有语义）。
- [ ] A11 工厂隔离：非超管绑定「东莞」的用户，合并列表与搜索均只返回东莞工厂数据。
- [ ] A12 后端门禁：quality_gate / ruff / mypy / pytest / vue-tsc / eslint / vitest / check:api / check:routes 全部通过，不新增基线违规（vue_component_length 基线 7、function_length 基线 52）。

## 业务规则（输入 → 输出，把隐性规则显式化）

| 规则 | 输入 | 输出/行为 |
|---|---|---|
| R1 类型筛选 | type ∈ {all, order, stockin}（缺省 all） | all→订单∪备货；order→仅 Order；stockin→仅 StockIn |
| R1b 单号搜索 | order_no_keyword / stockin_no_keyword | order_no / stockin_no ILIKE '%kw%'（escape_like 转义后）命中即返回 |
| R1c 保留字段 | customer / status / factory / start_date / end_date | 沿用现状语义：status 仅订单、factory 仅订单（非超管强制本厂） |
| R2 产品搜索（订单侧） | keyword | 任一 SKU 的 product_name / product_barcode ILIKE '%kw%'（escape_like 转义后）命中即整单返回；命中 SKU 收窄展示（复用 beile.py 搜索语义） |
| R3 产品搜索（备货侧） | keyword | product.name / product.barcode ILIKE '%kw%' 命中即返回该备货行 |
| R4 时间排序 | 合并集合 | 按 sort_date（order_date / stockin_date）倒序；同秒按 (record_type, source_id) 稳定排序，避免翻页丢行/重行（沿用 beile.py:547 口径） |
| R5 软删排除 | 数据行 is_deleted | 软删记录（is_deleted=True）一律不进入合并列表 |
| R6 工厂过滤 | user.factory / factory 参数 | 非超管绑定工厂时强制本厂；超管可全量 |
| R7 状态列（订单） | 订单 status | 沿用 7 态（待备货/已备货/部分备货/待出货/已出货/已取消/批次已完成） |
| R8 分页 | page≥1, per_page∈[1,500] | total = 合并后总数（订单命中数 + 备货命中数） |

## 边界与禁止项（强制 · 沉默 ≠ 允许）

> 规格没写的行为默认视为「允许」并被实现。每条边界必须「禁止什么 → 期望行为/拒绝 → 验收方式」。
> 本功能为**只读列表**，边界十问中「自反关系 / 幂等 / 并发同键」不直接适用，但逐条给出结论，不跳空。

| 边界族 | 规则（禁止什么） | 期望行为/拒绝 | 验收方式 |
|---|---|---|---|
| 自反关系 | 无自反关系概念（只读列表，不产生关联） | 不适用，标注即可 | 代码评审确认无关系写入 |
| 归属 / 跨父级 | 合并行 `id` 跨表冲突（Order.id 与 StockIn.id 可相同）；禁止仅凭 `id` 路由删除/详情 | 路由必须以 `record_type + id` 二元组定位；错误路由拒绝并报错 | 构造同 id 的订单+备货，分别点详情，确认不串表 |
| 备货只读 | 合并列表中备货行禁止删除/编辑（现状备货本就不可删） | 备货行不渲染删除/编辑操作，仅订单行可删；后端合并端点只读 | 备货行无删除按钮，删除仅订单行生效 |
| 终态不可变 | 已删除（is_deleted）记录不得出现在列表 | is_deleted 排除；已取消订单默认**仍展示**（沿用现状，状态列可辨识） | 软删一条后刷新列表不可见 |
| 越权 | 无 order_manage 权限的用户不得读取合并列表；跨厂数据不得泄露 | 端点仅要求 order_manage + 工厂隔离，越权返回 401/403 | 用无权限账号请求接口应 401/403 |
| 幂等 | GET 天然幂等；禁止搜索触发任何写操作 | 只读，重复请求返回一致结果 | 连点查询不产生副作用 |
| 基数上限 | per_page 上限 500（沿用现有 Query 约束） | per_page>500 返回 422 | 传 per_page=501 应 422 |
| 级联与计数 | 删除订单/备货后 total 与分页一致，不出现脏页/负数 | 删除后失效缓存并重取，total 重新计算（沿用 useOrderDelete.ts 失效派生查询） | 删除末页最后一条后回退上一页，total 减一 |
| 并发同键 | 合并列表分页在并发写入下不得丢行/重行 | UNION ALL 稳定排序（R4）保证翻页稳定 | 压测下翻页无重复行 |
| 权限升降级 | 用户工厂绑定变化/权限回收后，合并列表可见性即时收敛 | 工厂隔离随 user.factory 实时生效 | 改绑工厂后刷新列表范围变化 |
| 可见性 | 产品被软删时，关联订单/备货行的展示策略 | 订单侧：行仍展示、产品名回退快照 order_item.product_name；备货侧：无 product_name 快照列，product 缺失/工厂 NULL 行被 `.has()` 排除（正常路径 product_id NOT NULL + ondelete RESTRICT 不产生 null 行），依赖 live Product | 软删产品后刷新列表：订单行不消失、不报 500；备货依赖 live Product |

**禁止项（明确不做）**：

- 禁止改动「录入」Tab 与暂存/提交链路（OrderInputPanel / StagingArea / useOrderForm / useOrderActions 等），本需求只动「记录查询」读路径。
- 禁止前端「先取全量再本地过滤/分页」实现产品搜索（会漏命中 + 分页错乱）。
- 禁止破坏 beile-order（湖北订单页）现有合并逻辑：复用其能力而非修改其行为。
- 禁止改权限体系、新增迁移、改数据库结构（本需求纯查询+前端，不涉及 DDL）。
- 禁止删 `frontend-vite/vite.config.js`、根 `utils/`、`fastapi_app/utils/`（红线，见 REPOWIKI §6.2）。

## 边界 Case

- 空输入 / 非法输入：产品名称为空→不筛选；关键字含 `%`/`_`/`\`→经 `escape_like` 转义后按字面匹配；start_date/end_date 非法格式→400（BusinessError，沿用 order/list _parse_date_condition）。
- 权限边界：无权限访问合并端点→401/403；绑定工厂用户看不到他厂数据。
- 并发 / 竞态：快速切换类型/翻页时旧响应丢弃（沿用 useOrderList.ts:60 requestSeq 机制）。
- 历史脏数据 / 向前兼容：product 外键缺失或产品已软删的历史订单/备货行不 500、不整行消失（回退快照值）。

## 安全边界（三级权限）

- **必须做**：合并端点仅要求 `order_manage` 权限（用户已拍板）；备货行在合并列表只读；工厂隔离沿用 order/list 现有逻辑（非超管绑定工厂强制本厂）；产品/单号搜索关键字转义（`escape_like`）防 LIKE 注入/通配符逃逸；只读端点不落任何写操作。**已接受决策（权限边界放宽）**：合并端点仅 `order_manage`，使「有 order_manage 无 stockin_manage」的账号首次可读备货数据（此前 `/stock/in/list` 要求 stockin_manage）——此为合并展示的必然结果，用户已拍板接受，不追加 stockin_manage 门控。
- **严禁做**：不做任何 DDL/迁移；不降低现有权限（不得把 order_manage 降为匿名可见）；不绕过工厂隔离；不改 beile-order 权限（beile_order_view）。

## 测试计划

- 单元 / 集成（后端）：合并查询——type=all/order/stockin 各自返回集正确；product_kw 命中订单 SKU 与备货名称/条码；escape_like 转义；分页 total 与稳定排序；软删排除；工厂过滤。
- 前端：新筛选组件——类型切换、产品名称输入、组合筛选、重置、空/错误态、分页回退；useOrderList 重构后 fetch 行为等价。
- 对存量功能的回归：录入/暂存/提交链路不受影响；beile-order 页回归不回归（复用点改动须跑其测试）；删除后派生查询失效仍生效。
- 端到端（如 UI）：进入记录查询默认合并列表→按类型筛选→搜产品名称→翻页→删除→刷新。

## 假设（不阻塞的小决策，标注即可）

1. 「全部」作为类型筛选默认值（合并展示的前提）。
2. 产品名称搜索沿用 beile-list 语义：名称**或条码**匹配（澄清 Q3 确认）。
3. 新筛选为「全保留 + 新增」：保留 客户/状态/工厂/开始日期/结束日期 五字段，新增 类型/产品名称/单号 三字段（澄清已拍板）。

## 澄清点（已拍板，见下）

- Q1 类型筛选形态：**三态「全部/订单/备货」默认「全部」**。
- Q2 旧筛选四维：**全保留**（客户/状态/工厂/日期），与新增字段并存。
- Q3 产品名称搜索：**同时匹配条码 barcode**（名称或条码）。
- Q4 合并端点权限：**仅 order_manage**；备货行只读、不可删/编辑。
- Q5 备货行「状态」列：**显示「—」**（备货无同款状态机，不引入新状态）。