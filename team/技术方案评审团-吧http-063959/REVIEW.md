# 评审（REVIEW）

## 结论

**已返工修订（第二轮 spec-review 前）**：12 条 findings 已全部回填——5 P1（F1 权限放宽记录 / F2 备货侧 is_deleted+日期400 / A1 recordType 删除责任落 F2 inScope / A2 SPEC 日期残留 / A3 AUTHORITY 纳入 SPEC）与 7 P2（A4 status 可空 / A5 行号 / A6 术语 / F3 工厂粒度 / F4 Literal / F5 price / F6 备货无快照）均已在 SPEC/PLAN/TASKS/AUTHORITY 定点修订。待 implement 后做代码级 review。

## 问题清单

| 严重级 | 位置 | 原因 | 建议 |
|---|---|---|---|

## 安全审查（Ivy · spec-review 安全面门禁）

> verdict：**needs_revision**（无 P0 阻断；2 条 P1 需修 + 4 条 P2 建议，须在实现前回填 SPEC/PLAN 与 B1 契约）

### 逐条核查结论

**1. SQL 注入 / 通配符逃逸 —— [P1 需修]**
- `escape_like` 实现正确：`fastapi_app/core/sanitizer.py:36`，先 replace 反斜杠、再 replace `%` 与 `_`（顺序正确，防 LIKE 通配符逃逸）。
- 参照实现 `beile.py` 对 customer/product 两侧均转义：`beile.py:80` `Order.customer.like(f'%{escape_like(customer)}%')`、`:84-85` `Order.items.any(or_(OrderItem.product_name.ilike(kw), OrderItem.product_barcode.ilike(kw)))`、`:104-110` 备货侧同款。**无裸拼 SQL，全部走绑定参数 + escape_like，无注入风险。**
- 但新增 `order_no` 关键字无既有先例，须在 B1 强制同样 `escape_like` 转义（PLAN 已声明，实现需确认）。
- `status` 非枚举白名单：`queries.py:110-111` `Order.status == status`（裸字符串等值，绑定参数无注入，但非法值静默返回空而非 422）；`record_type` 契约已声明 Literal（PLAN.md），须实现落实。

**2. 权限模型 —— [P1 需修]**
- 越权方向（stockin_manage 看订单）：**安全**。合并端点仅 `order_manage`，`stockin_manage`-only 账号缺 order_manage → 403，看不到订单（`stock.py:50` /stock/in/list 仍要求 stockin_manage，新端点不认它）。
- **反向放宽（order_manage 看备货）**：合并端点仅 `order_manage`，使「有 order_manage 无 stockin_manage」的账号**首次可读备货数据**（此前 /stock/in/list 需 stockin_manage）。属权限边界放宽，SPEC/PLAN 未把此决策记为已接受风险（见 F1）。
- 401/403 语义与现有端点一致：`deps.py:288-291` `require_permission` 无权限抛 403「权限不足」；未认证由 `_authenticate_user_id` 抛 401（`deps.py:202/214/217`）。
- 备货只读前后端一致：后端仅新增 GET 只读端点，无备货写端点（order_manage 无法调 /stock/in/edit，`stock.py:101-106` 要求 stockin_manage）；前端 F2「删除按钮仅 record_type==='order'」。（TASKS.json F2.acceptance）

**3. 工厂隔离（数据泄露）—— [P2 建议]**
- 订单侧沿用 `list_orders`：端点层 `order.py:78-79` `if user.factory and not user.is_super: factory = user.factory`（忽略前端传参），service 层 `queries.py:224-225` `Order.items.any(OrderItem.product.has(Product.factory == factory))`。**factory 参数不可被前端伪造绕过。**
- 备货侧 PLAN 新增 `StockIn.product.has(Product.factory == factory)`（`beile.py:97` 同款）。`.has()` 生成 EXISTS，`stock_in.product_id` NOT NULL + ondelete RESTRICT（`stock_in.py:30`），正常路径无 null 行；脏数据/工厂为 NULL 的行被**排除（fail-safe，非跨厂泄露）**，不会「漏过滤泄露他厂」。
- 遗漏点：多工厂订单按订单粒度隔离，绑定工厂用户看到含他厂 SKU 的**整单**，`items[]`/`factories[]` 暴露他厂 SKU 名称/条码/数量（`queries.py:225` 继承自 list_orders，非本任务新增）→ F3。

**4. 软删 / 权限升降级 —— [P1 需修]**
- 软删两侧恒加：`beile.py:72` `Order.is_deleted.isnot(True)`、`:96` `StockIn.is_deleted.isnot(True)`；但 **`get_stockins` 反例未加 is_deleted**（`stock_inventory_service.py:63-128` 无该条件），B1 复用其 deducted_sub 时若照抄会漏备货软删排除 → F2。
- 产品软删：`Product` 无 is_deleted 列（`product.py:26-51`），无软删机制；订单侧有 `OrderItem.product_name/product_barcode` 快照回退（`order_item.py:33-34`），**备货侧无快照列**，依赖 live Product，product 缺失行被 `.has()` 静默排除（与 SPEC「软删产品行仍展示」承诺不一致）→ F6。
- 权限回收收敛：`deps.py:70` `_PERMISSION_CACHE = _TTLCache(ttl=5)`，回收后 ≤5s 收敛，与现有端点一致（非回归）。

**5. 信息泄露面 —— [P2 建议]**
- 响应 schema（PLAN.md UnifiedRecord）无 price/cost/profit；但 `Product.to_dict()` 含 `price`（`product.py:87`），实现若误用整体序列化 Product 会泄露价格 → F5。
- `note`（备注）已暴露于既有端点（`stock_inventory_service.py:126`、`beile.py:569/623`），合并端点暴露 note 非新增泄露，但需确认 note 内容无成本/利润等内部敏感信息。
- `total` 探测闭合：窗口 `func.count().over()` 在**同一已按工厂过滤的 unified 子查询**上执行（`beile.py:463-468`），total 即工厂隔离后的命中数，无法探测他厂数据量；实现须确保 count 窗口在工厂/关键字过滤**之后**（在子查询内，而非仅页查询）。

### findings

| # | severity | problem | requiredFix |
|---|---|---|---|
| F1 | P1 | 合并端点 GET /orders/records 仅要求 order_manage（PLAN.md 接口契约），使仅有 order_manage 而无 stockin_manage 的账号首次可读备货数据（此前 /stock/in/list 要求 stockin_manage，`stock.py:50`）。权限边界放宽未被 SPEC/PLAN 记为已接受决策。 | 在 SPEC/PLAN 显式记录「order_manage 现覆盖备货读权限」为已拍板接受项；确认组织权限矩阵中 order_manage 角色可见备货无异议；若不可接受，改 `require_any_permission("order_manage","stockin_manage")` 并评估其反向后果。 |
| F2 | P1 | 现有 `get_stockins`（`stock_inventory_service.py:63-128`）无 is_deleted 过滤、非法日期静默忽略（`:75-76`/`:82-83` `except ValueError: pass`），与 PLAN「两侧恒加 is_deleted、日期非法 400」相悖；B1 复用其 deducted_sub（`:99-107`）时若照抄条件会退化为静默忽略/漏软删排除。 | B1 acceptance 明确：备货侧 `StockIn.is_deleted.isnot(True)`；start/end 走 `_parse_date_condition`（`queries.py:84-99`，非法抛 BusinessError→400）；禁止复制 get_stockins 的日期静默忽略与无软删过滤。 |
| F3 | P2 | 工厂隔离为订单粒度：`Order.items.any(OrderItem.product.has(Product.factory==factory))`（`queries.py:225`）使绑定工厂用户看到含他厂 SKU 的整单，`items[]`/`factories[]` 暴露他厂 SKU 名称/条码/数量。继承自 list_orders，非本任务新增。 | 记录为已知取舍；或后续按 item 粒度过滤/收窄 items 与 factories 仅保留本厂 SKU。 |
| F4 | P2 | `status` 为裸字符串等值（`queries.py:110-111`），非法值静默空结果非 422；`record_type` 已声明 Literal 但需实现确认。无注入风险（绑定参数）。 | status 校验 `VALID_ORDER_STATUSES`（`order.py:30-38`）或文档化非法→空；record_type 用 `Literal["all","order","stockin"]` 强制 422。 |
| F5 | P2 | `Product.to_dict()` 含 `price`（`product.py:87`）；UnifiedRecord 的 product 字段须严格按 PLAN schema 构造 `{id,name,barcode,image}`，不得整体序列化 Product 或调 to_dict()。 | 实现时手工构造 product 对象，排除 price/current_stock 等字段；review 时检查无整体序列化泄露。 |
| F6 | P2 | 备货侧 `StockIn.product.has(Product.factory==factory)`（`beile.py:97` 同款）对 product 缺失或 factory=NULL 的备货行生成 EXISTS=false → 整行不展示，与 SPEC「软删产品行仍展示、回退快照」承诺不一致；且 StockIn 无 product_name 快照列（对比 `order_item.py:33-34`）。正常路径 product_id NOT NULL+ondelete RESTRICT（`stock_in.py:30`）不产生 null 行，属 over-restrictive 非越权泄露。 | 明确备货侧无快照、product 缺失/工厂 NULL 行将被排除的行为口径；必要时 LEFT JOIN + COALESCE 保留行，避免整行消失。 |

### 结论

无 P0 阻断：SQL 注入/通配符逃逸正确、工厂隔离备货侧新增过滤且强于现有 /stock/in/list、total 探测闭合、备货只读前后端一致。**verdict = needs_revision**：需回填 F1（权限边界放宽记录）、F2（B1 备货侧 is_deleted/日期契约）两条 P1 后方可进入实现。

## 功能/一致性审查（Alex · spec-review 门禁）

> verdict：**needs_revision**（无 P0 阻断；3 条 P1 需修 + 3 条 P2 建议，须在实现前回填 SPEC/PLAN 与 TASKS 契约）
> 范围：边界十问口径、接口契约完整性、SPEC/PLAN 一致性、AUTHORITY 单源化、TASKS 依赖/边界、锚点抽查。安全面由 Ivy 节覆盖，本节不重复。

### 逐条核查结论

**1. 边界十问覆盖与三处口径 —— [通过，1 条 P2 观察]**
- 边界表 11 行（自反关系/归属跨父级/备货只读/终态不可变/越权/幂等/基数上限/级联计数/并发同键/权限升降级/可见性），每行「规则、期望行为/拒绝、验收方式」三列齐全，无空跳。
- 「备货只读」「record_type+id 二元组路由」「越权 order_manage 单权限」三条在 SPEC/PLAN/TASKS **三处口径一致**（见 SPEC 边界族+A9、PLAN 接口契约、TASKS B1/F2）。
- P2 观察：标题「边界十问」但表列 11 行（多「可见性」），超覆盖非缺失。

**2. 接口契约完整性（GET /orders/records）—— [通过，1 条 P2]**
- Query 8 筛选字段（record_type/product/order_no/customer/status/factory/start_date/end_date）在 PLAN 契约表与 B1.acceptance 齐备，另有 page(ge=1)/per_page(ge=1,le=500)。响应 UnifiedRecord 与 types.ts OrderRecord 可逐字段对齐。
- 错误语义 401/403/400/422/500 闭合，400(非法日期)、403(require_permission)、500(SQLAlchemyError/OSError) 沿用 order.py list_orders 既有实现。
- P2：types.ts 的 status 为必填非空 string vs PLAN「备货 status 恒 null」，见 A4。

**3. SPEC 与 PLAN 一致性 —— [1 条 P1 + 2 条 P2]**
- 筛选字段范围（8 字段）、权限口径（仅 order_manage）、备货状态列「—」、产品名搜索 name+barcode 四处一致。
- 残留：「两维/删除五维」旧口径在 SPEC 仍有 1 处未清理（A2「日期参数本需求已移除」）；PLAN 头部注释「SPEC §8 的『两维/删除五维』」引用已过期（A6）。

**4. AUTHORITY 单源化（5 条校验规则）—— [规则 1-4 通过；规则 5 违反 = P1]**
- 规则 1 格式 4 列非空、规则 2 文件真实（PLAN.md 存在）、规则 3 写者合法且唯一（architect）、规则 4 无自相矛盾（3 行同指 PLAN.md）均通过。
- 规则 5「纳入治理」违反：SPEC.md 未出现在任何一行（A3）。

**5. TASKS.json 三条任务 —— [依赖/可测/verify 通过；1 条 P1 边界矛盾]**
- 依赖图 B1->F1→F2 线性合理；acceptance 可测；verify 命令真实存在（frontend-vite package.json 的 type-check/lint/test/check:api/check:routes 全定义；B1 的 ruff/mypy/pytest 存在）。
- inScope/outOfScope 无重叠；B1 复用 escape_like(sanitizer.py:34)、_batch_deduct_quantities(order_utils.py:8/21/35/36)、_batch_item_factories(order/queries.py:157/240)、StockOut deducted(stock_inventory_service.py get_stockins@63, deducted@99-125) 均为只读复用，不冲突；types.ts 仅 F1 改、F2 只读，边界干净。
- P1 矛盾：F1 描述「recordType/recordTypeOptions 由 F2 删除」但 F2 outOfScope 含 useOrderList.ts（A1）。

**6. 文件清单锚点抽查 —— [通过，1 条 P2]**
- useOrderList.ts fetchOrders@68、OrderRecordFilter.vue co-record-type-switch 互斥切换@4-11 与源码相符；后端复用符号全部命中。
- P2：SPEC §0 行号漂移 order.py:26（实为 order.py:43）、order.py:59-85（beile-list 端点在 order.py:98-124），见 A5。

### findings

| # | severity | problem | requiredFix |
|---|---|---|---|
| A1 | P1 | F1 描述承诺 recordType/recordTypeOptions 由 F2 删除，但 F2 outOfScope 含 frontend-vite/src/views/customer-order/composables/useOrderList.ts 且 inScope 不含该文件，@deprecated 导出无任务清理，「废除 recordType 互斥切换」不彻底。 | 将 useOrderList.ts 加入 F2 inScope（并从 outOfScope 移除），由 F2 在移除组件引用后删除 recordType/recordTypeOptions；或改由 F1 直接删除并声明 F1 阶段组件编译兼容方式。 |
| A2 | P1 | SPEC「边界 Case」写「日期参数本需求已移除，不再有非法日期输入」，与功能目标 #2 / 业务规则 R1c / 验收 A7 / PLAN 契约「全保留 start_date/end_date」自相矛盾，属「删除五维」旧口径残留，会误导实现漏做日期校验（与 Ivy F2 同源）。 | 删除该句，替换为「start_date/end_date 非法格式=400（BusinessError，沿用 order/list _parse_date_condition）」，与 PLAN 契约一致。 |
| A3 | P1 | AUTHORITY.md 表仅 3 行且全部指向 PLAN.md §设计·接口契约，SPEC.md 未出现在任何一行，违反其自带校验规则 #5「纳入治理」；SPEC 同时另写定义「筛选字段清单/合并端点权限/记录类型枚举」三个已单源化事实。 | 为 SPEC.md 增至少一行声明唯一权威文件与唯一写者；并明确 SPEC 中三事实与 PLAN 的引用关系（只许指针，删除或标注另写定义）。 |
| A4 | P2 | types.ts OrderRecord.status 为必填 string，但合并端点备货行 status 返回 null（PLAN 契约），F1 仅写「必要时微调 types.ts」未显式覆盖。 | F1 acceptance 明确将 status 改为 string 或 null（备货 status=null），并同步 order_no/order_date 归一化。 |
| A5 | P2 | SPEC §0 现状依据表 order.py:26(list_orders) 实际在 order.py:43（26 行为 ApprovalCancelResponse, 导入项）；order.py:59-85 实指 list_orders 函数体，beile-list 端点在 order.py:98-124。 | 修正为 order.py:43、order.py:98-124（锚点以字符串为准，不阻塞实现）。 |
| A6 | P2 | PLAN 契约仅写 status 备货恒 null 未声明 null 到「—」渲染映射；SPEC 假设 #3/澄清点 Q2 用「四维」（客户/状态/工厂/日期）而功能目标 #2 用五字段（客户/状态/工厂/开始日期/结束日期），术语漂移；PLAN 头部「SPEC §8 两维/删除五维」引用已过期。 | PLAN 契约 status 补「备货 status=null，前端渲染「—」」；统一五字段表述；清理 PLAN 头部过期引用。 |

### 结论

无 P0 阻断：核心契约（8 筛选字段、order_manage 单权限、备货只读、record_type+id 二元组路由、产品名 name+barcode）在 SPEC/PLAN/TASKS 三处口径一致，依赖图与 verify 命令真实可用。**verdict = needs_revision**：须先修 A1（F1/F2 删除责任悬空）、A2（SPEC 日期残留）、A3（AUTHORITY 未纳入 SPEC）三条 P1 后方可进入实现。
