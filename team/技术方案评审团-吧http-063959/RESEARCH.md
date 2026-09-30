# 调研报告（RESEARCH）—— customer-order 页面「记录查询/订单/备货」合并 + 新筛选

> 目标页面 http://192.168.0.95:3000/customer-order（前端路由 /customer-order）。
> 需求：把「记录查询 / 订单 / 备货」三部分数据合并展示；删除现有筛选，重写一个能按「订单/备货」类型筛选、并能按「产品名称」搜索的新筛选。
> 口径：以代码为准（REPOWIKI 可能过期）。前端 Vue 3 + TS；后端 FastAPI + SQLAlchemy async。

---

## 一、定位结果

1. 路由：frontend-vite/src/router/index.ts:40-44
   path:'customer-order' -> name:'CustomerOrder' -> component: @/views/customer-order/CustomerOrderView.vue，meta.hideHeader:true。
   另有 router/index.ts:98 移动端 mobile/views/customer-order/MCustomerOrderView.vue（本次不动）。
   历史路径 order、order/:id 重定向到 /customer-order（router/index.ts:27-28）。

2. 「记录查询 / 订单 / 备货」不是三个独立路由/组件，而是：
   - 记录查询 = 顶层 tab（与「录入」并列）。主视图 CustomerOrderView.vue 顶部 co-tab-bar 只有两个按钮：录入 / 记录查询（CustomerOrderView.vue:8-15，activeTab: 'input' | 'records'）。
   - 订单 / 备货 = 「记录查询」tab 内部的一个 recordType 二态切换（'order' | 'stockin'），由 OrderRecordFilter.vue 的 co-record-type-switch 按钮组渲染（OrderRecordFilter.vue:6-12）。当前是二选一切换展示，不是同一列表合并展示。

3. 记录查询 tab 的组件链：
   CustomerOrderView.vue:58-81 -> OrderRecordQuery.vue（组合器）-> OrderRecordFilter.vue（筛选）+ OrderRecordTable.vue（表格）。
   数据逻辑在 composables/useOrderList.ts（recordType / 筛选状态 / fetchOrders 分派）。

4. 文件清单（全路径）：
   - frontend-vite/src/views/customer-order/CustomerOrderView.vue（11322 B，主视图）
   - frontend-vite/src/views/customer-order/components/OrderRecordQuery.vue（3770 B）
   - frontend-vite/src/views/customer-order/components/OrderRecordFilter.vue（6105 B，现有筛选，本次要删/重写）
   - frontend-vite/src/views/customer-order/components/OrderRecordTable.vue（8829 B，列表表格）
   - frontend-vite/src/views/customer-order/components/OrderTypeSwitch.vue（1639 B，录入 tab 用的订单/备货切换，与记录查询无关）
   - frontend-vite/src/views/customer-order/composables/useOrderList.ts（5996 B，数据源+筛选状态）
   - frontend-vite/src/views/customer-order/composables/types.ts（OrderRecord 归一化类型）
   - 其余 components（OrderInputPanel / StagingArea / EditOrderModal / EditStagedModal / OcrPreviewModal / OrderDeductControl / OrderExcelImport / OrderOcrPaste）与 composables（useOrderForm / useOrderActions / useOrderDelete / useOrderDetailEdit / useOrderImport / useOrderOcr / useStagedEdit / useStagedItems）属于「录入」链路，本次筛选/合并基本不涉及（仅 fetchOrders 回调签名共用）。

---

## 二、现状梳理（现有筛选）

现有筛选代码集中在 OrderRecordFilter.vue（UI）+ useOrderList.ts（状态与查询参数拼装）。

筛选字段（OrderRecordFilter.vue:21-65）：
| 字段 | 状态 | 后端参数 | 显示条件 |
|---|---|---|---|
| 客户 | filterCustomer | customer | 始终显示 |
| 状态 | filterStatus | status | 仅 recordType==='order' |
| 工厂 | filterFactory | factory | 仅 recordType==='order' |
| 开始日期 | filterStart | start_date | 始终显示 |
| 结束日期 | filterEnd | end_date | 始终显示 |
| 查询/重置 | - | - | 始终显示 |

- 没有任何「产品名称」搜索。现有筛选字段：客户、状态、工厂、开始/结束日期。
- 类型切换是筛选器标题栏里的 recordTypeOptions（useOrderList.ts:40-44）：{value:'order',label:'订单'}, {value:'stockin',label:'备货'}。
- statusOptions 硬编码 7 态（useOrderList.ts:47-56）：待备货/已备货/部分备货/待出货/已出货/已取消/批次已完成。
- factoryOptions 硬编码（useOrderList.ts:10-13）：东莞/湖北。factoryDisabled 由 authStore.user?.factory 决定（绑定工厂用户锁定本厂，权限隔离）。
- resetFilter（useOrderList.ts:141-151）：清客户/状态，工厂按 userFactory 复位，清日期，回第 1 页。

表格列（OrderRecordTable.vue:88-105）：时间（订单时间/备货时间）、编号（带「订单/备货」badge）、客户、工厂（仅订单）、SKU数量（仅订单）、产品（product?.name + barcode）、数量、抵扣备货、操作（仅订单，删除按钮 canDelete 且 isOrder）。
产品列读 row.product?.name（OrderRecordTable.vue:56-59），不是扁平 product_name。

---

## 三、数据来源与 API（三部分是否不同接口/表）

结论：是的，订单与备货来自不同接口、不同表，当前前端按 recordType 二选一请求。

### 3.1 前端 API 调用点
- frontend-vite/src/api/order.ts:40 -> orderApi.list = get('/orders/list', params)
- frontend-vite/src/api/stock.ts:34 -> stockApi.stockins = get('/stock/in/list', params)

### 3.2 前端数据分派（useOrderList.ts）
- fetchOrders（useOrderList.ts:68-100）：按 recordType 分派 -> fetchOrderRecords 或 fetchStockins。
- fetchOrderRecords（useOrderList.ts:102-119）params：page, per_page, customer, status, factory, start_date, end_date；响应 res.data 映射 record_type:'order'。
- fetchStockins（useOrderList.ts:121-139）params：page, per_page, customer, start_date, end_date；响应 res.data ?? res.items，映射 record_type:'stockin'、order_date=stockin_date、order_no=stockin_no、deduct_quantity=deducted。

### 3.3 后端端点 + service + 表/模型
订单：
- 端点 fastapi_app/api/v1/endpoints/order.py:42-95 list_orders。Query 参数：page, per_page, customer, product_id, status, start_date, end_date, factory。权限 order_manage。
  - 注意：只有 product_id（整数），没有产品名称关键字。
  - 工厂隔离：order.py:78-79 绑定工厂非超管强制本厂。
- service：order_service.get_orders -> fastapi_app/services/order/queries.py:201-243 get_orders（_build_order_filters queries.py:101-118）。
- 表/模型：fastapi_app/shared_models/order.py（order 表，customer/order_date/product_id/quantity/status/batch_no/is_deleted，无 product_name 列，产品名经 product 关系）+ order_item.py（order_item 表，多 SKU，冗余 product_name/product_barcode）。
- 序列化：fastapi_app/services/serializers/order_serializer.py LIST_CONFIG 输出 product:{id,name,barcode,image} + items[] + factories[]。

备货：
- 端点 fastapi_app/api/v1/endpoints/stock.py:42-73 list_stockins。Query 参数：page, per_page, customer, start_date, end_date。权限 stockin_manage。
  - 无产品名、无 status、无 factory 筛选。
- service：stock_service.get_stockins -> fastapi_app/services/stock_inventory_service.py:63-128 get_stockins。输出 product:{id,name,barcode,image} + deducted。
- 表/模型：fastapi_app/shared_models/stock_in.py（stock_in 表，stockin_no/stockin_date/customer/product_id/quantity/note/is_deleted，无 status 列、无 factory 列、无 product_name 列）。

产品：fastapi_app/shared_models/product.py（product 表，name(unique)/barcode/factory/image 等；name 有 gin trgm 索引 idx_product_name_trgm，barcode 有 idx_product_barcode_trgm）。

---

## 四、「产品名称」字段确切命名 + 现有是否支持按产品名搜索

- 前端：类型里叫 product_name（types/index.ts 的 OrderItem.product_name、StockInRecord.product_name、OrderSKU.product_name；composables/types.ts 的 OrderRecord.product_name）。但实际接口返回是嵌套 product.name（订单经 OrderSerializer、备货经 get_stockins 均返回 product:{name,...}），表格也读 row.product?.name。
- 后端：产品名真源是 Product.name（product 表列，unique）。Order/StockIn 表本身没有 product_name 列（经 product 关系取）；仅 OrderItem 有冗余 product_name/product_barcode 列（shared_models/order_item.py）。
- 现有是否支持按产品名搜索：
  - /orders/list：不支持（只有 product_id）。
  - /stock/in/list：不支持。
  - 已有现成实现：/orders/beile-list（湖北订单合并列表）支持 product 关键字（匹配产品名称或条码）。端点 order.py:98-124（product: str | None = Query(None, 产品关键字筛选) 匹配产品名称或条码，order.py:104）。

---

## 五、关键代码片段（带路径+行号）

### 5.1 现有筛选 UI（OrderRecordFilter.vue）
- 类型切换按钮组：OrderRecordFilter.vue:6-12
- 筛选面板字段：客户 :25，状态 :29（v-if recordType==='order'），工厂 :34（v-if recordType==='order'），开始日期 :39，结束日期 :45，查询/重置 :48-55。

### 5.2 现有数据分派（useOrderList.ts）
- recordTypeOptions = [{value:'order',label:'订单'},{value:'stockin',label:'备货'}] -> useOrderList.ts:40-44
- fetchOrders 按 recordType 分派 -> useOrderList.ts:68-100（关键：if (recordType.value === 'stockin') await fetchStockins(seq) else await fetchOrderRecords(seq)，第 80-85 行）
- fetchOrderRecords 拼 params -> useOrderList.ts:102-119
- fetchStockins 拼 params -> useOrderList.ts:121-139

### 5.3 后端订单筛选（services/order/queries.py）
- _build_order_filters -> queries.py:101-118（Order.customer.like(...)、Order.product_id == product_id、Order.status == status、日期条件）
- get_orders -> queries.py:201-243，缓存 @cache_result(key_prefix='orders:list', ttl=60, local_ttl=0)，key_builder 不含产品关键字（queries.py:199）。

### 5.4 后端备货筛选（services/stock_inventory_service.py）
- get_stockins -> stock_inventory_service.py:63-128，缓存 @cache_result(key_prefix='stockins:list', ttl=30, local_ttl=10)，key_builder 仅 page/per_page/customer/start_date/end_date（:61）。

### 5.5 现成的「订单+备货合并 + 产品名搜索」参考实现（可直接借鉴）
文件 fastapi_app/services/order/beile.py（湖北订单合并列表）：
- _build_beile_unified_query -> beile.py:57-113：用 union_all 合并 Order 子查询 + StockIn 子查询，literal('order'/'stockin').label('record_type')。
  - 订单侧产品关键字：beile.py:81-86 -> Order.items.any(or_(OrderItem.product_name.ilike(kw), OrderItem.product_barcode.ilike(kw)))
  - 备货侧产品关键字：beile.py:105-110 -> StockIn.product.has(or_(Product.name.ilike(kw), Product.barcode.ilike(kw)))
  - kw 转义：kw = f'%{escape_like(product_kw)}%'（escape_like 真源 fastapi_app/core/sanitizer.py，经 services/__init__.py:5 re-export）。
- get_beile_orders_with_stockins -> beile.py:408-530：UNION 分页（窗口 func.count().over()），按 record_type 分桶取 id，再批量 _fetch_beile_records_by_ids 回填完整行，保持排序。
- 行构建：_build_beile_order_record beile.py:533-595（含搜索态 items 收窄为命中 SKU）、_build_beile_stockin_record beile.py:598-641。
- 端点入口：order.py:98-124 beile-list（product 关键字 -> product_kw）。

注意：beile-list 是湖北专用（强制 factory='湖北'、权限 beile_order_view、注入湖北确认流程与采购下单字段），不能直接改前端指向它，但「UNION ALL 合并 + ilike 产品名搜索 + record_type 区分」这套思路可直接移植到 customer-order。

---

## 六、依赖（共享组件 / store / API 层封装）

- API 层：frontend-vite/src/api/request.ts 提供 get/post/put/del/upload/download（axios 封装）；页面不直调 axios，统一走 orderApi / stockApi（api/index.ts re-export）。
- Pinia store：useAuthStore（stores/auth）——取 user.factory（工厂隔离）、hasPermission('order_manage')（canDelete，CustomerOrderView.vue:198-199）。
- 共享 UI 组件：UiSelect / UiDatePicker / UiButton（@/components/ui/）、UiDataTable（@/components/ui/UiDataTable.vue，表格+分页）、UiConfirmDialog。
- 类型：OrderRecord（composables/types.ts）已归一化订单/备货（record_type:'order'|'stockin'，含 order_no/stockin_no/order_date/stockin_date/product/items/factories/deduct_quantity）。
- 缓存失效：useOrderDelete 用 invalidateOrderDerivedQueries（utils/queryKeys.ts）失效派生查询。
- 未使用 TanStack Query（useOrderList 是手写 ref + requestSeq 防脏数据），仅 useOrderDelete 用 useQueryClient 做派生失效。

---

## 七、风险与约束

1. 删除语义不对称：当前删除按钮仅对「订单」显示（OrderRecordTable.vue 列定义 isOrder 才 push actions；handleDeleteOrder 在 useOrderDelete.ts 固定调 orderApi.delete）。合并展示后若备货也要删除，需另接 stockApi.deleteStockin（/stock/in/delete/{id}）；否则合并列表里备货行不能放删除按钮（现状如此）。
2. 权限口径不同：订单 order_manage、备货 stockin_manage（两个 endpoint 各自 require_permission）。合并为单一端点时需选一个权限并确认用户均具备，或端点内分别校验。前端 canDelete 目前只判 order_manage。
3. 后端字段能力不对称：stock_in 表无 status/factory 列（备货只有 customer/date/product/quantity/note），所以现有筛选里 status/factory 对备货 v-if 隐藏。合并后端筛选字段时，「状态/工厂」只能作用于订单侧（或备货侧按 Product.factory 过滤，beile 就是这么做的：StockIn.product.has(Product.factory==factory)）。
4. 产品名搜索落点不同：订单侧在 OrderItem.product_name/product_barcode（多 SKU，需 any）；备货侧在 Product.name/barcode（has）。这是 beile 已验证的写法，需照搬并注意 escape_like 转义 + ilike（不区分大小写，依赖 pg_trgm gin 索引）。
5. 缓存 key 需扩展：get_orders/get_stockins 的 key_builder 均不含产品关键字/类型字段，新增按产品名搜索必须把新参数纳入缓存键，否则不同关键字命中同一缓存（beile 的 key_builder 已含 pk，见 beile.py:406）。
6. 复用面（避免误伤）：
   - OrderRecordFilter.vue / OrderRecordQuery.vue / OrderRecordTable.vue / useOrderList.ts 是本页面私有组件，仅 customer-order 使用（未发现其他页面 import）。
   - OrderTypeSwitch.vue 是录入 tab 的订单/备货类型切换，不要在重写筛选时误删/误改。
   - OrderRecord 类型（composables/types.ts）已具备合并展示所需的归一化字段，合并列表可直接复用。
   - get_stockins/get_orders 是 stock/order 域的公共服务，被库存页/批次页等其他调用方复用，改 service 签名要向后兼容（新增可选参数，不改既有行为）。
7. 合并展示方案选择（供 architect 决策，两种路线）：
   - A（后端合并，推荐）：仿 beile 新增一个「订单+备货 UNION ALL + product 关键字」端点/service（或扩展 /orders/list 支持 record_type=all 与 product 关键字），前端改单次请求。数据一致性最好、分页最稳。
   - B（前端合并）：前端并发请求两个接口再本地 merge/sort，受分页与总数口径影响，跨表排序分页易错位，不推荐。
8. 改动波及文件清单（合并+重写筛选的最小集）：
   - 前端必改：useOrderList.ts（新增 filterProduct/filterType，改 fetch 逻辑）、OrderRecordFilter.vue（删除旧字段，重写为「类型 + 产品名称」）、CustomerOrderView.vue / OrderRecordQuery.vue（props 透传）、OrderRecordTable.vue（合并态列显示）。
   - 后端可能改：endpoints/order.py 或新增端点、services/order/queries.py（_build_order_filters 加 product 关键字）或新增 service、schemas/order.py（响应类型）。备货侧 stock_inventory_service.py 若走 A 路线可能复用 beile 的 StockIn 过滤写法。
9. 质量门禁：改动 .vue 触发 quality_gate.py（max_vue_component_length=400、max_file_size=1600）；后端 max_function_length=80。合并列表的 service 函数体较大时需拆分（beile 已拆成多个小函数可作范本）。

---

## 附：关键文件索引（全路径）

- frontend-vite/src/router/index.ts（路由 :40-44）
- frontend-vite/src/views/customer-order/CustomerOrderView.vue
- frontend-vite/src/views/customer-order/components/OrderRecordFilter.vue（现有筛选）
- frontend-vite/src/views/customer-order/components/OrderRecordQuery.vue
- frontend-vite/src/views/customer-order/components/OrderRecordTable.vue
- frontend-vite/src/views/customer-order/components/OrderTypeSwitch.vue（录入 tab，勿动）
- frontend-vite/src/views/customer-order/composables/useOrderList.ts
- frontend-vite/src/views/customer-order/composables/types.ts
- frontend-vite/src/api/order.ts / frontend-vite/src/api/stock.ts / frontend-vite/src/api/index.ts
- fastapi_app/api/v1/endpoints/order.py（list :42-95，beile-list :98-124）
- fastapi_app/api/v1/endpoints/stock.py（in/list :42-73）
- fastapi_app/services/order/queries.py（get_orders :201-243，_build_order_filters :101-118）
- fastapi_app/services/order/beile.py（合并+产品名搜索参考：_build_beile_unified_query :57-113，get_beile_orders_with_stockins :408-530）
- fastapi_app/services/stock_inventory_service.py（get_stockins :63-128）
- fastapi_app/services/serializers/order_serializer.py
- fastapi_app/shared_models/order.py / order_item.py / stock_in.py / product.py
