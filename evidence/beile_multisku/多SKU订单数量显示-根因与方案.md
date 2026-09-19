# 湖北订单页（/beile-order）多 SKU 订单数量显示错误 —— 根因分析与修复方案

- 页面：`http://192.168.0.95:3000/beile-order`
- 现象：同一订单、同一下单时间内含约 20 个 SKU 时，列表页无法让每个 SKU 对应展示各自的订单数量
- 分析日期：2026-09-18
- 取证方式：只读。未修改任何业务代码、未写库、未重启服务
- 取证产物：`_qa_tmp/beile_multisku_probe{,2,3,4}.json`、`_qa_tmp/probe3_summary.txt`、`_qa_tmp/probe4_summary.txt`
- 取证脚本：`_beile_multisku_probe.py`、`_beile_multisku_probe2.py`、`_beile_multisku_probe3.py`、`_beile_multisku_probe4.py`

---

## 0. 结论（TL;DR）

这不是一个渲染 Bug，而是**「逐 SKU 下单量在数据模型层就已经不存在」**所导致的连锁缺陷：

> 汇总下单时，**1 个客户订单 = 1 张采购单**，多 SKU 的产品名被 `'、'.join()` 拼成一个字符串、数量被求和成一个合计；
> 于是「每个 SKU 各自下单多少」自落库起即不可还原。
> 下游 `/beile-order` 接口只能给出**订单级标量**（`MAX`），前端也只能在**一个单元格**里画一个数字。

前端在任何筛选状态下都**不存在**「一行列出该订单全部 SKU 及其各自数量」的视图：

| 状态 | 产品名称列 | 订单数量列显示 |
|---|---|---|
| 无产品筛选 | **整列隐藏**（看不到任何 SKU） | 全部 SKU 之和（如 `63791`） |
| 有产品筛选 | 只渲染**匹配关键字的那 1 个 SKU** | 该 SKU 自己的数量（如 `32766`） |
| 已下单行 | 同上 | 订单级合计 `purchase_order_qty`，**不随筛选变化** |

即：**未下单多 SKU 行的「订单数量」会随筛选状态在「订单合计」与「单 SKU 数量」之间静默漂移**；已下单行则永远显示订单合计，与眼前那个 SKU 对不上。

---

## 1. 真实数据基线（取证时点）

| 指标 | 值 |
|---|---|
| 未确认记录数 | 5 |
| 已确认记录数 | 69 |
| `status='completed'` 采购单总数 | 30 |
| 被采购单覆盖的客户订单数 | 42 |
| SKU 数量分布（订单/备货行） | 1 个 SKU：51 行；2 个：16 行；3 个：7 行 |
| 当前最大 SKU 数 | **3**（尚无 20 SKU 的真实订单） |
| 采购单 `source_order_ids` 基数分布 | {1 个订单：26，2 个：2，3 个：1，**15 个：1**} |

> 说明：题面所述「约 20 个 SKU」的订单在当前生产库中尚未出现，缺陷**目前处于潜伏期**（最大 3 SKU 未触发可见裁切）。所有结论均由「机制 + 边界实测 + 外推」三重证据支撑，见 §3。

---

## 2. 五层根因

### RC-1 数据模型层（最上游、最根本）：采购单只存订单级合计，逐 SKU 下单量未持久化

`fastapi_app/services/purchase_order_generate.py::_generate_per_customer`

```python
# 多 SKU 模型：按 SKU 粒度收集产品名与数量，避免使用 Order.product_id
# （仅首个 SKU）和 Order.quantity（所有 SKU 之和）造成统计错误
product_names = sorted({ pid_name_map.get(pid, '未知产品')
                        for r in records for pid, _qty in _iter_source_skus(r) })
total_qty = sum(qty for r in records for _pid, qty in _iter_source_skus(r))

result = await one_click_generate_order(
    db, cust_items,
    customer_name=customer_name,
    source_order_ids=[r.id for r in records],
    product_name='、'.join(product_names) if len(product_names) > 1 else (...),
    product_quantity=total_qty,
)
```

**「1 个客户 = 1 个采购单」**。生成器本身已经做到 SKU 感知（注释明确），但它把 SKU 名**拼接**、把数量**求和**，然后只落一条 `purchase_order` 记录。

真实库证据：

| 客户订单 | 采购单 | `product_name` | `product_quantity` | 该订单 SKU 明细 |
|---|---|---|---|---|
| 65003 | 20381 | `Nommi糯米儿-宝藏收藏家系列毛绒盲盒、妹妹二代、招财猫盲盒毛绒挂件(混4款)` | 30000 | 3 × 10000 = 30000 |
| 64982 | 20346 | `CITYPEN巡游世界系列-9寸女神像企鹅公仔、企鹅、叮咚丛遇系列-企鹅盲盒毛绒挂件(混4款)` | 40000 | 多 SKU 合计 |
| 64997 | 20373 / 20374 / 20375 / 20376 | `妹妹二代`（4 家供应商各 1 张） | 10000 × 4 | 单 SKU 10000 |

⇒ **逐 SKU 下单量在采购单侧没有任何可还原的粒度**（不是「难取」，是「不存在」）。`purchase_order_item` 是 BOM 物料明细（`material_name` / `quantity` / `unit_usage`），与 SKU 订单数量无关。

### RC-2 后端注入口径层：订单级 `MAX` 在多 SKU 下失去语义

`fastapi_app/services/order/beile.py::_apply_ordered_fields`

```python
if pos:
    record['purchase_order_qty'] = max((float(p.product_quantity or 0) for p in pos), default=0)
    record['spare_quantity']     = max((float(p.spare_quantity or 0) for p in pos), default=0)
    record['spare_rate']         = max(rates) if rates else None
    record['is_ordered']         = True
else:
    record['purchase_order_qty'] = record.get('quantity') or 0   # ← 首个 SKU 的数量
    record['spare_quantity'] = 0
    record['is_ordered'] = False
```

`MAX` 的设计意图是「同一订单被拆到多个供应商时去重」（注释与 AC-8 所述）。该意图在两种情形下成立，在第三种情形下失效：

| 情形 | 采购单形态 | `MAX` 结果 | 是否正确 |
|---|---|---|---|
| 单 SKU 拆多供应商 | 4 张单，各 10000 | 10000 | ✅ 正确 |
| 多 SKU 合并成 1 张单 | 1 张单，合计 30000 | 30000 | ⚠️ 等于合计，但**失去逐 SKU 语义** |
| 一张单覆盖多张客户订单 | PO 20342 覆盖 **15** 个订单，`product_quantity=15` | 15 | ❌ **这 15 个订单每行都显示 15** |

`by_order_id` 由 `source_order_ids` 的**元素包含**关系建立，因此「一张采购单覆盖 N 张订单」时，这 N 张订单各自都会被注入同一个合计 → **单订单数量被系统性高估**。基数分布 {1:26, 2:2, 3:1, 15:1} 证明该形态真实存在。

另：未下单分支的 `purchase_order_qty = record['quantity']`，而 `record['quantity'] = first_item.quantity`（`_build_beile_order_record`）—— **只取首个 SKU**。实测订单 65036（3 SKU：13173 / 32766 / 17852）该字段为 `13173`，而实际合计 `63791`。前端当前用 `localQty` 求和恰好遮住了它，但同一反模式（采购单生成器已明确修正）仍留在 beile 侧。

### RC-3 前端展示层：一行只有一个数量单元格，且列语义随筛选漂移

`frontend-vite/src/views/beile-order/components/BeileOrderRow.vue`

```html
<!-- 产品名称列：仅当 showProductColumn 为真时渲染 -->
<div v-if="showProductColumn" class="bo-td ...">
  <div v-for="sku in visibleSkus" :key="sku.id" class="bo-sku-line"> ... </div>
</div>
<!-- 订单数量列：单个单元格 -->
<div class="bo-td ...">
  <span v-if="item.is_ordered === true" class="bo-qty-value--ordered">{{ item.purchase_order_qty ?? 0 }}</span>
  <span v-else class="bo-qty-value">{{ localQty }}</span>
</div>
```

```ts
const showProductColumn = computed(() => appliedProduct.value.trim() !== '')
const visibleSkus = computed(() => {           // 有关键字时只返回命中的 SKU
  const kw = props.keyword.trim().toLowerCase()
  if (!kw) return items
  const matched = items.filter((s) => skuMatchesKeyword(s, kw))
  return matched.length > 0 ? matched : items
})
const localQty = computed(() => {
  if (props.showProductColumn && visibleSkus.value.length > 0)
    return visibleSkus.value.reduce((s, x) => s + (x.quantity || 0), 0)   // 命中 SKU 之和
  if (props.item.items?.length) return props.item.items.reduce(...)       // 全部 SKU 之和
  return props.item.quantity
})
```

真实浏览器实测（已确认 TAB，同一批行）：

| 客户 | SKU 数 | 无筛选时「订单数量」 | 筛选「妹妹二代」后 | API `sku_qty_sum` | 该 SKU 自身数量 |
|---|---|---|---|---|---|
| MINISO国内 | 3 | **63791** | **32766** | 63791 | 32766 |
| MINISO国际 | 3 | **90550** | **48989** | 90550 | 48989 |
| MINISO国际 | 3 | **110496** | **30901** | 110496 | 30901 |
| 名创优品 | 3 | **56276** | （未命中） | 56276 | — |

⇒ 同一行、同一订单、同一份数据，`订单数量` 列的数字在 **63791 → 32766** 之间跳变。**列语义随「是否输入了产品关键字」而静默切换。** 且**任何状态下都看不到该订单的完整 SKU 清单**（无筛选时整列隐藏，有筛选时只显示 1 个）。

已下单行更明确：`purchase_order_qty` 与筛选无关，按 SKU 搜索仍显示订单合计（订单 65003 → 恒为 30000，而 3 个 SKU 各 10000）。

### RC-4 虚拟列表高度层：一旦实现逐 SKU 展开，必被固定高裁剪（修复的前置约束）

`frontend-vite/src/components/ui/VirtualList.vue`

```ts
function measureItems() {
  ...
  const h = el.getBoundingClientRect().height      // ← 量的是「被约束后的盒子」
  if (_heightMap.get(idx) !== h) { _heightMap.set(idx, h); changed = true }
}
function getItemStyle(index: number) {
  const h = _heightMap.get(index) || estimatedH.value
  return { height: `${h}px` }                       // ← 又把它写回固定高
}
```

每个 `.virtual-list-item` 都被赋予 inline 固定高（初值 `estimatedHeight = 54px`），`getBoundingClientRect()` 量到的正是这个固定高 → **测量自相矛盾，永远学不到内容真实高度**；行高恒为 54px，而 `.bo-td { overflow: hidden }` 会直接裁掉超出内容。

真实浏览器实测（`.virtual-list-item` 的 inline height 临时置 `auto` 后测内容自然高，随后立即还原）：

| 行类型 | 强制高（inline） | 内容自然高 | 余量 |
|---|---|---|---|
| 单 SKU | 54px | 46.2px | −7.8px（不裁） |
| 3 SKU（产品名称列隐藏，备注列为 3 个空 `.bo-sku-line`） | 54px | **52.1px** | **−1.9px（临界）** |
| 3 SKU（产品名称列展开，1 行名称） | 54px | 46.2px | −7.8px |

- 全部采样行的 `itemStyleH` 恒为 `"54px"` —— 测量从未产出 > 54 的值。
- 空 `.bo-sku-line` 约 2.95px/行；**第 4 行即 55.06px > 54px → 溢出被裁**。
- 20 个 SKU 且各行有备注（`.bo-sku-line` ≈ 22px/行）时：自然高 ≈ 46.2 + 19 × 22 ≈ **464px**，而强制高 54px ⇒ **裁掉约 410px**。

⇒ 若直接实现「逐 SKU 展开」而不先修此测量缺陷，20 SKU 订单会被裁成 2 行，**症状反而更严重**。这是方案的硬前置项。

### RC-5 筛选作用域层（放大症状）

`useBeileOrders.ts`

```ts
queryFn: () => orderApi.beileList({
  customer: appliedCustomer.value || undefined,
  confirm_status: confirmStatus.value || undefined,
  page: page.value, per_page: perPage.value,
})     // ← 后端已支持 product_kw，前端从不传
```

后端 `get_beile_orders_with_stockins(..., product_kw=...)` 支持按 SKU 名/条码服务端筛选，但前端**从不传入**；`displayOrders` 只在**当前页 18 条**上做客户端过滤。

实测：输入关键字「盲盒」「毛绒」并选中候选项后，当前页无命中 → 列表 0 行 → 展示「当前页未匹配到该订单号」。用户按 SKU 名定位多 SKU 订单时，会被误导为「该订单不存在」。

---

## 3. 修复方案

### 3.1 硬前置项（无论选哪个方案都必须先做）

| 编号 | 内容 | 文件 |
|---|---|---|
| P-0 | 修正 VirtualList 变高测量：量测时临时解除固定高（或用内部包裹层承载内容高度），确保 `_heightMap` 学到真实内容高 | `src/components/ui/VirtualList.vue` |
| P-1 | 消除「订单数量」列语义漂移：明确该列在**任何筛选状态下**都代表同一口径 | `BeileOrderRow.vue` / `useBeileOrders.ts` |
| P-2 | 产品筛选改为服务端生效（传 `product_kw`），客户端过滤仅作二次收窄 | `useBeileOrders.ts` |

### 3.2 主方案（推荐）：行内逐 SKU 展开 + 口径显式分层

**布局**：`产品名称 / 订单数量 / 生产数量 / 备注` 四列按 SKU 逐行渲染；`订单类型 / 下单时间 / 客户名称 / 工厂 / 小义开单 / 确认状态 / 确认操作` 为订单级列，在同一行块内垂直居中（不做 rowspan，保持 flex 结构不变）。

```
订单类型 下单时间 客户 工厂 │ 产品名称      │ 订单数量 │ 生产数量 │ 小义开单 │ 备注
订单    08-09 03:07 MINISO国内 湖北 │ Nommi…盲盒  │ 13173 │   —  │ 未开单 │
                                  │ 妹妹二代     │ 32766 │   —  │        │
                                  │ 企鹅的订单   │ 17852 │   —  │        │
                                  │ ── 合计 ──  │ 63791 │   —  │        │
```

**口径定义（写进列头 tooltip，避免口径歧义）**

| 列 | 未下单行 | 已下单行 |
|---|---|---|
| 订单数量（逐 SKU） | `sku.quantity` —— 该 SKU 客户订单数量，**始终准确、可得** | 同左（`sku.quantity`），逐 SKU 稳定 |
| 订单数量（合计子行） | `Σ sku.quantity` | `purchase_order_qty`（采购单实际下单合计） |
| 生产数量 | `—` | **仅在合计子行**显示 `purchase_order_qty + spare_quantity`；逐 SKU 单元格显示 `—` 并附 tooltip 说明「采购单仅记录订单级合计，无法拆分到 SKU」 |
| 小义开单 | 未开单 | 已开单（订单级事实，随订单） |

**为什么已下单行逐 SKU 生产数量只能是 `—`**：`spare_quantity` 与 `product_quantity` 一样是订单级 `MAX` 标量（RC-1/RC-2），逐 SKU 无法得出，任何拆分都是编造数字。**宁可显示 `—` 并联结解释，也不给出无法追溯的数**。

**密度控制**：SKU 明细行默认折叠，行首加「▸ 3 个 SKU」开关就地展开（无动效，纯展开/收起），避免 20 SKU 订单把列表撑到 460px/行。展开态与详情弹窗口径同源。

### 3.3 备选方案 B：始终展开

多 SKU 行恒定逐 SKU 展示，不做折叠。口径同上。代价：20 SKU 行高约 460px，每页 18 行时页面高度可达 8000px+，列表密度显著下降。适合「一次只看 1–2 单」的使用习惯。

### 3.4 备选方案 C（治本，但改动最大）：后端补逐 SKU 数量快照

才能真正做到「每个 SKU 各自的订单数量 **与** 生产数量」：

1. 新增 `purchase_order_sku`（`po_id` / `product_name` / `order_qty` / `spare_qty`），Alembic 迁移；
2. `_generate_per_customer` 与「保存/编辑数量」写路径同步写入逐 SKU 行；
3. `/beile-list` 按 SKU 注入 `per_sku` 数组；
4. 历史 30 张采购单回填：可用 `_iter_source_skus(order)` + 对应订单的 SKU 数量回填（未编辑时等于客户订单数量），并**明确标注为推算值**。

代价：涉及生产库迁移 + 写路径改造 + 历史回填口径定义。收益：逐 SKU 数量与生产数量全部真实可得，前端不再需要 `—` 兜底。

---

## 4. 本次未改动任何代码

本轮为只读侦察与方案设计。已确认的既有改动仍然有效：`备品数量` 独立列已删除、`生产数量 = 订单数量 + 备品数量` 已上线、`/purchase` 侧数据源未动。

## 5. 待交付（选定方案后）

- P-0 / P-1 / P-2 前置修复
- 主方案（或备选）的列表页与导出/打印同源改造（`buildSummaryTbody` 现用 rowspan 把订单数量并到订单级，需与页面口径同步）
- 单元测试 + Playwright/Edge 真实浏览器端到端断言（含 20 SKU 构造用例）
- 生产构建与部署
