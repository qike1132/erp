# 来料进度页：开源 ERP 的做法对照与我们的问题

日期：2026-11-08
触发：owner 反馈「UI 逻辑完全不行」，要求参考 GitHub 上开源 ERP 的同类功能。

本文只做取证与方案，不涉及代码改动。所有结论都来自**源码/视图定义**，不是截图印象。

---

## 一、先说我错在哪

对着已上线的截图，逐条对照成熟 ERP：

| # | 我这版的做法 | 为什么错 |
|---|---|---|
| 1 | 订单卡 → 供应商块 → 物料行，**三层内联嵌套** | 一屏只放得下 3 个订单 / 约 12 行，其中只有 6 行需要行动。成熟 ERP 不会把三层塞进一屏 |
| 2 | **三条进度条**（订单头、供应商头、物料行）同时出现 | 同一种视觉语言用了三次，权重没差别；订单 5% 与物料 50%/100%/0% 口径不同、互不同约，用户无法互推 |
| 3 | **没有时间维度** | 整屏唯一的日期是下单日。「逾期」是个孤零零的标签，看不到晚了多久、还剩几天 |
| 4 | 「逾期」标签泛滥 | 一张卡里 4 个物料全带逾期、组头带、卡边框也红 —— 红色失去指向性，等于没标 |
| 5 | **没有表头** | 每行是「名称 + 一堆数字」，用户靠猜哪列是采购量、哪列是已到量 |
| 6 | 状态用 4 桶（逾期/已到齐/进行中/未开始）**混合了两种语义** | 「逾期」是时间风险，「已到齐/进行中」是数量进度。混在一列，既不能排序也不能筛选 |

---

## 二、四家开源 ERP 到底怎么做的

### 1. ERPNext（frappe/erpnext）

**列表就是答案**：采购订单列表里，`% Received` 是一个 `Percent` 字段，`in_list_view: 1`。

`erpnext/buying/doctype/purchase_order/purchase_order.json`：

```json
{ "fieldtype": "Percent", "in_list_view": 1, "label": "% Received", "read_only": 1 },
{ "fieldtype": "Percent", "in_list_view": 1, "label": "% Billed",   "read_only": 1 }
```

Frappe 对 `Percent` 列的原生渲染就是**一条细进度条 + 百分比**（社区还在问「怎么关掉这个条、只显示数字」），
即：进度是**一列**，不是主角。

状态是一组离散词，由两个百分比组合推出（`purchase_order_list.js`）：

```js
get_indicator(doc) {
  if (doc.status === "Closed")        return [__("Closed"), "green", ...];
  if (doc.status === "On Hold")       return [__("On Hold"), "orange", ...];
  if (flt(doc.per_received) < 100 && doc.status !== "Closed") {
    if (flt(doc.per_billed) < 100) return [__("To Receive and Bill"), "orange", ...];
    else                           return [__("To Receive"), "orange", ...];
  }
  if (flt(doc.per_received) >= 100 && flt(doc.per_billed) < 100) return [__("To Bill"), "orange", ...];
  if (flt(doc.per_received) >= 100 && flt(doc.per_billed) == 100) return [__("Completed"), "green", ...];
}
```

**「哪批晚了」靠单独一张报表**：`Procurement Tracker`，一行 = 一条采购订单行，
列里成对出现 `Expected Delivery Date`（要求到货）与 `Actual Delivery Date`（实际到货）。
「追踪单个物料到货」是一张**独立的下钻视图**，不是主列表的内联展开。

- 列表源码：`github.com/frappe/erpnext/blob/develop/erpnext/buying/doctype/purchase_order/purchase_order_list.js`
- 字段定义：同目录 `purchase_order.json`
- 报表文档：`docs.erpnext.com/docs/v14/user/manual/en/buying/articles/procurement-tracker-report`

### 2. Odoo（odoo/odoo）—— 最值得抄的一家

`receipt_status` 是**三值**枚举，不是四桶：

`addons/purchase_stock/models/purchase_order.py`

```python
receipt_status = fields.Selection([
    ('pending', 'Not Received'),
    ('partial', 'Partially Received'),
    ('full',    'Fully Received'),
], string='Receipt Status', compute='_compute_receipt_status', store=True)
```

列表视图里它是**默认隐藏的可选列**，并且**颜色只表达时间风险**：

`addons/purchase_stock/views/purchase_views.xml`

```xml
<field name="receipt_status" optional="hide" widget="badge"
  decoration-success="date_planned and (date_planned > 今天23:59 或 (receipt_status=='full' and effective_date <= date_planned))"
  decoration-danger ="date_planned and (date_planned < effective_date 或 (date_planned < 今天00:00 and receipt_status!='full' ...))"
  decoration-warning="date_planned and (今天00:00 <= date_planned <= 今天23:59 且 receipt_status!='full')"/>
```

翻译成人话：

| 颜色 | 含义 |
|---|---|
| 绿 | 还没到应到日，或已收齐且**准时** |
| 黄 | **应到日就是今天**、还没收齐 |
| 红 | **应到日晚于实际到货**，或应到日已过仍未收齐 |

注意两点：
1. **进度百分比不进这个徽标**。徽标只说「到没到」，颜色只说「急不急」。
2. **必填的时间锚点是 `date_planned`（应到日）**；`effective_date`（首次收货完成时间）用来判「准时/迟到」。

其余三个配套设计：

- 单据页有 `Receipt` 智能按钮，角标是 `incoming_picking_count`（`widget="statinfo"`，图标 `fa-truck`）——「这个订单有几张收货单」一眼可见，点击才进详情。
- 列表支持 **Group By → Vendor**（`context="{'group_by': 'partner_id'}"`，见 `purchase_views.xml:462/500/802`）——**「按供应商分组」是一种视图模式，不是页面的默认结构**。
- 供应商档案上有 `on_time_rate`（准时交货率），在采购单上以链接形式露出 —— 把「这家供应商靠不靠谱」变成可查的数字。

### 3. Dolibarr

采购订单是一个明确的状态机，到货是状态迁到 `Received partially (4)` / `Received completely (5)`；
收货动作走**独立单据 `Reception`**，进去逐行填本次收货量。

即：**列表上只留状态词，「收多少」是另一个界面的动作**。

- `wiki.dolibarr.org/index.php?title=Module_Purchase_Orders`
- `wiki.dolibarr.org/index.php/Module_Reception`

### 4. metasfresh

把「待收货」显式建模成一种单据：**Material Receipt Schedule**，一行 = 一条待收货行，
列固定为 `QtyOrdered / QtyDelivered / QtyToDeliver`（`QtyToDeliver` 还会用颜色标红/橙表示缺料程度）。
这是「等到货清单」这一独立工作台的做法，跟采购单列表分开。

- `docs.metasfresh.org/appdictionary_collection/EN/column_descriptions.html`

---

## 三、提炼出来的 7 条共同模式

| 模式 | 内容 |
|---|---|
| P1 | **单位是「行」，不是「卡」**：一行 = 一个可行动的到货单元（订单行/物料行），不是把三层塞进卡片 |
| P2 | **状态是有限离散值**（3 个），而且**到货状态与时间风险分属两个通道**（词 vs 颜色），不混在一列 |
| P3 | **进度只占一列**：细条 + 数字，宽度固定，不抢名称的横向空间 |
| P4 | **时间才是主角**：应到日/账龄是排序键，逾期是派生结果，不是独立状态 |
| P5 | **分组是视图模式**（Group By），不是默认结构；分组后组头给计数与聚合 |
| P6 | **详情靠下钻**（独立单据 / 右侧抽屉 / 报表），不靠内联展开三层 |
| P7 | **顶部是 KPI + 筛选**，不是图例；图例只在颜色真的承载语义时才出现 |

---

## 四、一个绕不开的数据约束

ERP 的「逾期」全部建立在**约定/计划到货日**上。本系统没有：

```
purchase_order:        order_date（下单日期）
material_registration: registration_date（登记日期）
                       —— 没有 expected_date / delivery_date / 交期
```

所以「逾期 30 天」其实是**账龄**，却挂了「逾期」的名 —— 名不副实，而且 30 天阈值写死在代码里。

两条路：

- **A（不改数据，马上能做）**：把这一列诚实地叫「账龄」，显示 `已登记 N 天`，超过阈值（默认 30 天，可配）标红。
  这是 ERP 里通用的 Aging 口径（应收账龄、库存账龄都这么算），不虚构承诺日期。
- **B（要动业务）**：给登记/采购单加 `expected_date`（约定到货日，可默认 = 登记日 + 供应商交期天数），
  之后才能真正做 Odoo 那种「应到日 vs 实际到货」的准时/迟到判断，也能算供应商准时率。

建议先 A，把 B 作为后续增强 —— A 已经能解决「谁压了最久」这个真问题。

---

## 五、据此提出的新结构

### 5.1 主视图：到货行列表（一行 = 一条物料的到货任务）

| 列 | 内容 | 说明 |
|---|---|---|
| 状态 | `待到货` / `部分到货` / `已到齐` | 三值徽标，中性色底；**不含逾期** |
| 订单 / 客户 | `PO-20261105-0018` + `华美玩具` | 订单号为主，客户为辅 |
| 产品 | 12 寸毛绒兔 | 单 SKU 时直显 |
| 物料 / 规格 | `1.0超柔` · `A126#` | 主体列，允许两行 |
| 供应商 | 佳宝纺织 | 可点 → 供应商档案 |
| 采购 | `1,200 码` | 数字右对齐 + 单位 |
| 已到 | `600 码` | 数字右对齐 + 单位 |
| 到货 | 60px 细条 + `50%` | **封顶 60px**，不参与分配剩余宽度 |
| 账龄 | `已登记 12 天` / 超阈值 `38 天`（红） | 排序键，默认降序 |
| 操作 | 收货 | 行内唯一主动作 |

行高 ~40px，1440 宽一屏约 15–18 行（现在是 12 行里 6 行可行动）。

### 5.2 排序与筛选

- **默认排序：账龄降序**（压得最久的在最上面），同账龄按订单号。
- 筛选：`全部` / `待到货` / `部分到货` / `已到齐` / `超 30 天`（带计数）。
- 顶部 KPI 三格：`待到货 N 项` / `部分到货 N 项` / `超 30 天 N 项` —— 点击即筛选。

### 5.3 分组是开关，不是结构

工具条一个 `分组：不分组 / 按供应商 / 按订单` 切换：

- **不分组（默认）**：纯列表，适合「今天该催谁」。
- **按供应商**：组头一行 `佳宝纺织 · 4 项 · 待到货 2 · 超 30 天 1`，可折叠。
  组头只给计数与「最长账龄」，**不给跨单位求和的百分比**（码/只/张 不能相加）。
- **按订单**：组头 `PO-…-0018 · 华美玩具 · 2 家供应商 · 6 项 · 3 项未齐`。

### 5.4 下钻

点行 → 右侧抽屉：该物料的到货流水（哪天登记、每次收多少、谁操作的、备注），底部「去收货」。
不再有「查看明细」这种含糊入口。

### 5.5 手机/窄屏

≤720px 时列收敛为两行式：
第一行 `状态 · 物料名 · 账龄`，第二行 `订单/供应商 · 已到/采购 · 细条%`。
不横向滚动、不隐藏关键数字。

---

## 六、改动成本

| 项 | 影响 |
|---|---|
| `useMaterialRegistrations.ts` | 需要多产出一层**物料行扁平数组**（现有 `ProgressOrderRow` 是订单+分组结构，可复用其内部数据，纯前端派生，不动接口） |
| `ProgressTab.vue` / `OrderCard.vue` / `SupplierGroupCard.vue` | 前两个改写成列表 + 分组开关；`SupplierGroupCard` 可退役 |
| 后端 | **不需要改** |
| 测试 | 现有 37 条按卡片结构写，需重写为列表结构断言 |
| 风险 | 低。数据与接口不变，纯视图重组 |

---

## 七、待 owner 决策

1. 逾期口径：先做**账龄（A）**，还是同时加 `expected_date` 字段做真交期（B）？
2. 默认视图：**不分组**（推荐，找异常最快）还是**按供应商**？
3. 是否保留「一单一卡」作为可选视图，还是彻底改成列表？
