# 计划（PLAN）

> pm 起草骨架 · 模块边界/接口契约/技术选型留空给 architect（见「设计」节）
> 筛选字段范围与权限口径已按拍板值修订（本节为冻结依据；与 SPEC 一致：全保留 + 新增 类型/产品名称/单号）

## 目标

把 /customer-order「记录查询」的订单(Order)+备货(StockIn)合并为单列表；重写筛选为「类型 + 产品名称 + 单号/编号」并**全保留**既有「客户 / 状态 / 工厂 / 开始日期 / 结束日期」字段（验收/边界详见 SPEC.md，筛选字段范围与权限口径以本节拍板值为准）。

## 需求要点与约束

- 合并展示：订单+备货单列表，类型徽章区分，废除 recordType 互斥切换。
- 新筛选字段（全保留+新增）：类型(全部/订单/备货，默认全部) + 产品名称(模糊，匹配 name 或 barcode，服务端过滤分页前) + 单号/编号(模糊，order_no 或 stockin_no) + 客户 + 状态(仅订单) + 工厂(仅订单) + 开始日期 + 结束日期。
- 权限：合并端点仅要求 order_manage；备货行只读（不可删/不可编辑，删除按钮仅订单行显示）。
- 后端实现路线：新增一个合并查询端点（不改 /orders/list、/stock/in/list 行为）；复用并泛化 beile.py 的 UNION ALL 合并 + ilike 产品关键字思路（去湖北硬编码与确认/采购单注入），落成新 service 函数。
- 软删排除 is_deleted；稳定排序 sort_date 倒序 + (record_type, source_id) 兜底；分页 per_page 上限 500；工厂隔离沿用 order/list 现逻辑（非超管绑定工厂强制本厂）。
- 约束：只动「记录查询」读路径；不改录入/暂存/提交链路；不改 beile-order 行为；无 DDL/迁移；不动 vite.config.js、根 utils/、fastapi_app/utils/。
- 门禁：quality_gate / ruff / mypy / pytest / vue-tsc / eslint / vitest / check:api / check:routes 全绿，不新增基线违规（vue_component_length 基线 7、function_length 基线 52）。

## 里程碑

1. 澄清点拍板（SPEC §8 Q1–Q5）。
2. architect 出模块边界 + 接口契约。
3. backend 实现合并端点（新 service 函数 + 端点）+ product / order_no 关键字过滤。
4. frontend 重写筛选组件 + useOrderList 重构 + 类型/API 对齐。
5. qa 测试 + reviewer 审查 + 门禁全绿。

## 设计（architect 填写）

### 模块边界

**后端（新增，不改既有行为）**

- 新文件 fastapi_app/services/order/unified.py：落一个只读合并查询 service 函数 get_unified_records(db, *, page, per_page, record_type, product_kw, order_no_kw, customer, status, factory, start_date, end_date) -> dict。泛化 beile.py 的 UNION ALL + ilike 思路：去掉湖北硬编码（factory 参数化）、去掉 confirm_status、去掉采购单/确认注入（purchase_order_qty / spare_quantity / is_ordered / confirmed 等 beile 专属字段一律不产出）。
- fastapi_app/api/v1/endpoints/order.py：新增 GET /orders/records，**必须声明在 GET /{order_id} 之前**（否则 /records 会被 int 路径参数转换拦截成 422，参照 beile-list @98 先于 /{order_id} 的先例）。
- 复用（不复制）：escape_like（fastapi_app/core/sanitizer.py，经 services/__init__.py re-export）；订单抵扣量 _batch_deduct_quantities（fastapi_app/services/order_utils.py）；订单工厂聚合 _batch_item_factories（fastapi_app/services/order/queries.py）；备货已抵扣量 StockOut 聚合子查询（fastapi_app/services/stock_inventory_service.py get_stockins 内 deducted_sub @80-88 同款写法）。
- 不改：fastapi_app/services/order/queries.py::get_orders、fastapi_app/services/stock_inventory_service.py::get_stockins、fastapi_app/services/order/beile.py、fastapi_app/api/v1/endpoints/stock.py。既有 /orders/list、/stock/in/list、/orders/beile-list 行为零变化。

**前端（只动「记录查询」读路径）**

- frontend-vite/src/api/order.ts：新增 orderApi.records（指向 GET /orders/records）。
- frontend-vite/src/views/customer-order/composables/useOrderList.ts：新增 filterType/filterProduct/filterNo 三态，fetch 单端点化。
- frontend-vite/src/views/customer-order/composables/types.ts：OrderRecord 承载合并行（record_type 已具备）。
- frontend-vite/src/views/customer-order/components/OrderRecordFilter.vue：重写筛选。
- frontend-vite/src/views/customer-order/components/OrderRecordQuery.vue、CustomerOrderView.vue：管道透传。
- frontend-vite/src/views/customer-order/components/OrderRecordTable.vue：合并态渲染（按行 record_type）。

### 接口契约（I/O 用 JSON Schema，精确到字段/类型/错误语义）

**合并端点**

- 方法/路径：GET /orders/records（挂载前缀 /api/v1/orders，见 router.py）。
- **合并端点权限**：require_permission("order_manage")（仅此一权；不再要求 stockin_manage）。无权限 -> 401（未认证）/ 403（无 order_manage）。**已接受决策（权限边界放宽）**：合并端点仅 order_manage，使有 order_manage 无 stockin_manage 的账号首次可读备货数据（此前 /stock/in/list 要求 stockin_manage）；此为合并展示必然结果，用户已拍板接受，不追加 stockin_manage 门控。
- 工厂隔离（沿用 order/list 现逻辑）：端点层 if user.factory and not user.is_super: factory = user.factory（忽略前端传参）。

**Query 参数（全部可选，除 page/per_page 有默认值）**

| 参数 | 类型 | 默认 | 枚举/约束 | 说明 |
|---|---|---|---|---|
| page | int | 1 | ge=1 | 页码 |
| per_page | int | 50 | ge=1, le=500 | 每页数量；>500 -> 422 |
| record_type | str | "all" | "all" | "order" | "stockin" | 类型筛选；非法值 -> 422（用 Literal/枚举校验） |
| product | str | None | None | 任意 | 产品名称/条码关键字（模糊，服务端过滤分页前，escape_like 转义） |
| order_no | str | None | None | 任意 | 单号/编号关键字（模糊匹配 Order.order_no 或 StockIn.stockin_no） |
| customer | str | None | None | 任意 | 客户名（模糊，escape_like 转义） |
| status | str | None | None | 7 态枚举 | 仅订单侧生效（Order.status） |
| factory | str | None | None | 东莞/湖北 | 仅订单侧筛选 + 隔离（见下） |
| start_date | str | None | None | YYYY-MM-DD | 非法格式 -> 400（BusinessError） |
| end_date | str | None | None | YYYY-MM-DD | 非法格式 -> 400 |

**筛选字段清单**：类型(record_type: all/order/stockin，默认 all) + 产品名称(product) + 单号/编号(order_no) + 客户(customer) + 状态(status，仅订单) + 工厂(factory，仅订单) + 开始日期(start_date) + 结束日期(end_date)。

**记录类型枚举**：order（订单，源表 order，主键 Order.id）+ stockin（备货，源表 stock_in，主键 StockIn.id）。筛选哨兵值 all 仅存在于查询参数，不落库、不进入数据行。

**过滤语义（逐字段）**

- record_type=all：订单子查询 ∪ 备货子查询；order：仅订单子查询；stockin：仅备货子查询。
- product（产品名称/条码）：订单侧 Order.items.any(or_(OrderItem.product_name.ilike(kw), OrderItem.product_barcode.ilike(kw)))；备货侧 StockIn.product.has(or_(Product.name.ilike(kw), Product.barcode.ilike(kw)))；kw = '%' + escape_like(product) + '%'（ilike 不区分大小写，命中 pg_trgm gin 索引）。
- order_no（单号/编号）：订单侧 Order.order_no.ilike(kw)；备货侧 StockIn.stockin_no.ilike(kw)；kw 同 escape_like。
- customer：两侧均 customer.ilike('%'+escape_like(customer)+'%')。
- status：仅订单侧 Order.status == status（备货无 status 列，恒不加）。
- factory：非空时订单侧 Order.items.any(OrderItem.product.has(Product.factory == factory))；备货侧 StockIn.product.has(Product.factory == factory)。备货侧同样过滤是「工厂隔离」的安全必需（A9：绑定工厂用户合并列表与搜索均只返回本厂数据），与 beile.py:107 同款。前端「工厂」下拉仅订单上下文显示（仅订单语义落在 UI 层）。
- start_date/end_date：订单侧作用于 Order.order_date；备货侧作用于 StockIn.stockin_date（均为 timestamptz，ISO 语义一致）。
- 软删：两侧恒加 is_deleted.isnot(True)。
- 排序：ORDER BY sort_date DESC NULLS LAST, record_type, source_id（sort_date = order_date / stockin_date；record_type/source_id 兜底保证同秒跨页稳定，沿用 beile.py 分页窗口写法）。
- total = 订单命中数 + 备货命中数（窗口 func.count().over() 单次执行）。

**响应 JSON Schema（200）**

响应复用 OrderListResponse（success/data/total/page/per_page，data 为 list[dict]；unconfirmed_count 默认 0，本端点不赋值）。

data 每行（UnifiedRecord）：

```json
{
  "id": 0,                          // int，源表主键；Order.id 与 StockIn.id 可重复，路由必须带 record_type
  "record_type": "order",           // "order" | "stockin"
  "order_no": "PO-...",             // string；Order.order_no 或 StockIn.stockin_no
  "customer": "客户",               // string | null
  "order_date": "2026-09-18 10:20", // string；订单=order_date、备货=stockin_date（北京时间格式化）
  "status": "待备货",               // string | null；仅订单非空（7 态）；备货恒 null（前端渲染「—」）
  "product_id": 0,                  // int | null
  "product": { "id": 0, "name": "产品", "barcode": "69码", "image": "" },  // object | null
  "quantity": 0,                    // int
  "deduct_quantity": 0,             // int；订单=抵扣备货净量；备货=已抵扣净量(deducted)
  "factories": ["东莞"],            // string[]；订单=SKU 工厂聚合去重；备货=[product.factory]（可空）
  "note": "",                       // string；空串兜底
  "items": [                        // 订单=多 SKU；备货=单元素
    { "id": 0, "product_id": 0, "product_name": "产品", "product_barcode": "69码",
      "quantity": 0, "deduct_quantity": 0, "note": "" }
  ]
}
```

顶层：```json { "success": true, "data": [ <UnifiedRecord> ], "total": 0, "page": 1, "per_page": 50 } ```

**错误语义**

| 状态码 | 场景 | 语义 |
|---|---|---|
| 401 | 未认证 | 全局 handler |
| 403 | 无 order_manage | require_permission 拒绝 |
| 400 | start_date/end_date 非法格式 | BusinessError（沿用 order/list _parse_date_condition） |
| 422 | per_page>500 / record_type 非法 / page<1 | FastAPI 参数校验 |
| 500 | DB 异常 | 端点捕获 (SQLAlchemyError, OSError) 转 500（沿用 list_orders） |

### 数据流

1. 前端筛选态（filterType/filterProduct/filterNo/customer/status/factory/start/end + page/per_page）-> GET /orders/records。
2. 端点层：order_manage 校验 -> 工厂隔离（绑定工厂强制）-> 调 get_unified_records。
3. service：构建两个 UNION ALL 子查询（订单侧 + 备货侧，各自套用类型/关键字/日期/软删/工厂条件）-> 窗口 count 单次分页 -> 按 (record_type, source_id) 分桶取 id -> 批量回填订单（含 items/factories/deduct）与备货（含 product/deducted）-> 序列化统一行 -> 保持 SQL 排序返回。
4. 前端：单次响应写入 orderRecords，表格按行 record_type 渲染徽章/状态列/工厂列/操作列（删除仅订单行）。

### 技术选型与理由

- 后端 UNION ALL 合并（而非前端并发两接口再本地 merge）：数据一致性最好、total 与分页最稳，跨表排序分页不错位（RESEARCH §7 路线 A）。
- ilike + escape_like 转义：防 LIKE 注入/通配符逃逸；product.name/barcode、order.customer 已有 pg_trgm gin 索引，模糊搜索走索引。
- 窗口 count（func.count().over()）单次执行分页+总数，避免双次 UNION（beile.py 已验证）。
- 批量 id 回填（selectinload/joinedload）替代逐行懒加载，避免 MissingGreenlet 与 N+1（beile.py 同款）。
- 稳定排序 sort_date DESC NULLS LAST + (record_type, source_id)：翻页不丢行/重行（拍板 #5）。
- 新 service 函数 + 新端点，不复用/扩展 get_orders、get_stockins：二者被库存/批次等页复用，扩展签名有回归风险（拍板 #4）。

### 风险与取舍

- 备货侧工厂过滤（隔离需要）vs「工厂(仅订单)」字面：取「两侧都过滤」的安全口径；「仅订单」只体现在 UI 下拉显示，已在此节单源声明，避免前端误把工厂筛选当全局。
- OrderItem.product_name/product_barcode 是快照冗余列，产品改名后搜索按快照命中（与 beile 一致）；备货侧按 Product.name/barcode 实值命中，两侧存在轻微口径差，属既定取舍（快照列是历史查询安全回退）。备货侧无 product_name 快照列，product 缺失/工厂 NULL 的备货行被 `.has()` 排除（正常路径 product_id NOT NULL + ondelete RESTRICT 不产生 null 行），口径已记录于 SPEC 可见性边界。
- 备货行「查看详情/编辑」路由超出本拍板范围：本次底线是备货行不可删、不可编辑；订单详情仍走 EditOrderModal。若后续要备货详情，需新增只读详情端点（不在本任务）。
- 合并 service 函数体偏大，需拆分小函数（参照 beile.py 已拆 _build_unified_query / _fetch_records_by_ids / _build_*_record），否则触发 function_length 门禁（80）。
- OrderRecordTable.vue 合并态按行渲染会增加模板复杂度，注意 max_vue_component_length=400。
- 工厂隔离为订单粒度（Order.items.any(OrderItem.product.has(Product.factory==factory))，继承 list_orders）：绑定工厂用户看到含他厂 SKU 的整单，items[]/factories[] 暴露他厂 SKU 名称/条码/数量——**记录为已知取舍**（非本任务新增），后续可考虑按 item 粒度收窄。

## 计划改动文件清单（交付物三件套：全路径 + 关键行号 + 依据）

| 文件（全路径） | 关键改动位置（行号锚点） | 依据 |
|---|---|---|
| fastapi_app/services/order/unified.py | 新文件：get_unified_records + _build_unified_query（泛化 beile.py:57-113 的 union_all + ilike，去湖北/确认/采购注入） | 拍板 #4 复用并泛化 beile 合并思路 |
| fastapi_app/api/v1/endpoints/order.py | 新增 GET /records，声明在 GET /{order_id}（@~200）之前；参考 list_orders @42-95、beile-list @98-124 | 拍板 #1/#3/#4；权限 order_manage |
| fastapi_app/schemas/order.py | 可选：新增 UnifiedRecordListResponse 或复用 OrderListResponse（data: list[dict]） | 响应 schema 精确化 |
| frontend-vite/src/api/order.ts | 新增 orderApi.records（get('/orders/records', params)），参考 list @40 | F1 接口对齐 |
| frontend-vite/src/views/customer-order/composables/useOrderList.ts | recordTypeOptions @40-44、fetchOrders @68-100、fetchOrderRecords @102-119、fetchStockins @121-139 全部改：三态 filterType + filterProduct/filterNo + 单端点 fetch | 拍板 #1 废除互斥切换、#2 新字段 |
| frontend-vite/src/views/customer-order/composables/types.ts | OrderRecord（已含 record_type）承载合并行；备货 deduct_quantity 语义明确 | 合并行 record_type 语义 |
| frontend-vite/src/views/customer-order/components/OrderRecordFilter.vue | 删除 co-record-type-switch @6-12；五维面板 @15-52 改为「类型+产品名称+单号/编号」+保留客户/状态/工厂/日期 | 拍板 #1/#2 全保留+新增 |
| frontend-vite/src/views/customer-order/components/OrderRecordQuery.vue | props/emits 管道：删除 recordType 二态、新增 filterType/filterProduct/filterNo | 同上 |
| frontend-vite/src/views/customer-order/CustomerOrderView.vue | OrderRecordQuery 绑定 @58-81、handleChangeRecordType @252-256 -> handleChangeFilterType | 同上 |
| frontend-vite/src/views/customer-order/components/OrderRecordTable.vue | orderColumns @88-105 改为按行 record_type；空态 @20-24 改「暂无记录」；操作列 @65-78 删除仅订单行 | 拍板 #1/#3 备货只读 |