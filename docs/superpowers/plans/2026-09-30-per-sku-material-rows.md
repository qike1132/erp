# 汇总下单「按 SKU 展开物料明细」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/purchase` 汇总下单弹窗「工厂内部订单」页签按 SKU 展开物料明细——每个 SKU 拥有一整块自己的 供应商/布料名称/规格型号/损耗率/数量/单位。

**Architecture:** 后端汇总接口**只增字段** `groups[].skus[].materials[]`（每 SKU 每物料的**基准量** = `BOM 单件用量 × 该 SKU 数量`，纯内存、零新增查询）；前端把「按 SKU 的物料行」映射回**落库明细的坐标 `(si, fi)`**，于是既有的率/数量编辑与联动机制**原样复用**（同一物料 = 同一坐标 = 同一份状态 ⇒ 联动天然的、不需要新代码）；当「各 SKU 推算之和 ≠ 落库真值」时渲染一个浅色对照块。单 SKU 单走同一行模型的退化路径，与今天逐字一致。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 async（后端）；Vue 3 + TypeScript + Vite + vitest（前端）；pytest + sqlite 内存库（后端测试）

**Spec:** `docs/purchase/汇总下单按SKU展开物料明细设计方案.md`（提交 `69a12d29`，用户已确认）

## Global Constraints

- **落库结构零改动**：不加表、不加列、不改列类型、不迁移数据。采购明细仍按 `(物料名, 规格, 单位)` 合并存储。
- **接口只增字段**：`groups[].suppliers[].fabrics[]`（落库真值 + `item_ids`）与 `groups[].skus[].product_name/product_barcode/order_qty` 的**形状与数值逐字不变**（老前端不受影响）。
- **零新增数据库查询**：BOM 已在汇总接口加载（`purchase_order_query.py:344-351`），按 SKU 展开必须是纯内存计算。
- **绝不抛错**：SKU 名解析不出、BOM 缺失、字段缺失一律降级（该 SKU `materials: []`），不得让汇总接口 500。
- **单 SKU 零回归**：单 SKU 单（`skus` ≤ 1 或缺失、或 `materials` 缺失）的屏幕、打印、导出输出与改动前**逐字一致**。
- 前端硬门禁：**单 SFC ≤ 400 行**、单文件 ≤ 1600 行（`pyproject.toml` 的 `[tool.code-quality]`）；`ruff.toml` 对测试文件不豁免 F401。
- 后端测试：`pytest.ini` 的 `asyncio_mode = auto`（async 测试**不加** `@pytest.mark.asyncio`）、`filterwarnings = error`（sqlite 写入**禁用** `Decimal`）。
- 测试/工具：`python -m pytest`；前端 `npx vitest run`、`npm run type-check`、`npm run lint`、`npm run check:api`、`npm run check:routes`。
- **本机 Bash 有 `_lc` 别名故障**：`git`/`npm`/`npx`/`cat`/`head`/`tail`/`grep`/`ruff` 等都要写成 `command X`。
- **提交纪律（重要）**：工作区存在**并发会话的未提交改动**（`frontend-vite/src/views/customer-order/**`、`fastapi_app/services/stock_inventory_service.py` 等）。**只 `git add` 本任务列出的文件**，**严禁** `git add -A` / `git add .` / `git commit -a`；**严禁** `git stash` / `git restore` 任何非本任务文件。
- **提交信息**写「为什么」，结尾附 `Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>`。

## Review Focus

以下输入/失败模式是 spec 隐含但最容易漏的，按可能性排序；每条都要在「拥有该代码的任务」里落到一条测试：

1. **同一物料跨 SKU 时键必须逐字对齐**（供应商+物料名+规格+单位）——新字段与既有 `fabrics` 的键一旦漂移，差异对照块会**全行误报**（Task 1 覆盖）。
2. **SKU 名解析不出产品**（快照里的名字与 `Product.name` 不一致 / 旧数据拼接名）→ 该 SKU `materials: []` 且不得抛错（Task 1 覆盖）。
3. **落库明细里没有的新物料**（BOM 在生成后被新增）→ 该行**无可写目标**，必须只读、不得让率/数量编辑把它写进别的明细（Task 2、Task 3 覆盖）。
4. **差异容差**：`|Σ推算 − 落库| ≤ 0.005` 必须**不**触发对照块（2 位小数落库的浮点尾差误报）（Task 2 覆盖）。
5. **单 SKU 逐字零回归**：屏幕 DOM、打印 HTML、导出行数与列位（Task 5、Task 6 覆盖）。
6. **编辑态的同物料联动**（改动块 A 里某物料 → 块 B 中同物料同步，且**只发一次**保存请求）（Task 3 覆盖）。

---

### Task 1: 后端——按 SKU 展开物料行（只增字段）

**Files:**
- Modify: `fastapi_app/services/purchase/_factory.py`（新增纯函数 + 在 `_build_factory_group_map` 收集、在 `_serialize_factory_groups` 装配）
- Test: `fastapi_app/tests/services/test_factory_summary_multisku.py`（追加用例，复用其现有 `db` fixture 与 `_seed_single_or_multi`）

**Interfaces:**
- Consumes: `bom_data`（`{pid: [{material_name, specification, unit, quantity, supplier_name, category}]}`，来自 `_fetch_bom_data`，其中 `quantity` 是**单件用量**）、`prod_name_map`（`{pid: 产品名}`）、`po_sku_map`（`{po_id: [{product_name, product_barcode, order_qty}]}`）、`_is_filling_category(category)`、`merge_sku_lines(rows)`
- Produces:
  - `def _norm_sku_name(value) -> str` —— SKU 名归一（仅 `strip`，**不** casefold：产品名要逐字匹配 `Product.name`）
  - `def _sku_material_rows(bom_rows: list, sku_qty: float, supplier_fallback: str) -> list[dict]` —— 返回 `[{supplier_name, material_name, specification, unit, quantity}]`（**基准量**，不含损耗加放；按 供应商→物料名→规格→单位 稳定排序）
  - 响应新增字段：`groups[].skus[].materials[]`（同一形状）

- [ ] **Step 1: 写失败测试**

在 `fastapi_app/tests/services/test_factory_summary_multisku.py` 末尾追加：

```python
# ===== skus[].materials[]：按 SKU 展开的物料明细（口径 A：单件用量 × 该 SKU 数量）=====

def _sku_materials(group) -> dict[str, dict[str, float]]:
    """{SKU 名: {物料名: 基准量}}，便于逐 SKU 断言。"""
    return {
        s['product_name']: {m['material_name']: float(m['quantity']) for m in s.get('materials') or []}
        for s in group['skus']
    }


async def test_c8_per_sku_materials_split_by_sku(db):
    """C8：每个 SKU 拿到**自己**那份物料（含跨 SKU 共享的物料，各算各的）。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add_all([
        PurchaseOrderSku(id=1, po_id=po_id, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=po_id, product_name='产品B', product_barcode='bB',
                         order_qty=200, source_order_id=9001, source_record_type='order'),
    ])
    await session.commit()

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    per_sku = _sku_materials(group)

    # 单件用量均为 0.2：A 用 100 件 → SHARED 20 / ONLY_A 20；B 用 200 件 → SHARED 40 / ONLY_B 40
    assert per_sku['产品A'] == {SHARED: 20.0, ONLY_A: 20.0}
    assert per_sku['产品B'] == {SHARED: 40.0, ONLY_B: 40.0}
    # 共享物料**两边都出现**（不合并、不去重——那是采购合计的口径）
    assert SHARED in per_sku['产品A'] and SHARED in per_sku['产品B']


async def test_c9_per_sku_material_keys_match_fabrics(db):
    """C9：新字段的**键**必须与既有 fabrics 的键逐字一致 —— 否则差异对照块会全行误报。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add_all([
        PurchaseOrderSku(id=1, po_id=po_id, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=po_id, product_name='产品B', product_barcode='bB',
                         order_qty=200, source_order_id=9001, source_record_type='order'),
    ])
    await session.commit()

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    per_sku_keys = {
        (m['supplier_name'], m['material_name'], m['specification'], m['unit'])
        for s in group['skus'] for m in (s.get('materials') or [])
    }
    fabric_keys = {
        (f.get('supplier_name') or s['supplier_name'], f['fabric_name'], f['specification'], f['unit'])
        for s in group['suppliers'] for f in s['fabrics']
    }
    assert per_sku_keys <= fabric_keys, '新字段出现了 fabrics 里没有的键（命名口径漂移）'


async def test_c10_per_sku_sum_equals_stored_when_consistent(db):
    """C10：各 SKU 推算之和 == 落库真值（本 fixture 是自洽的）→ 前端不该显示差异块。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add_all([
        PurchaseOrderSku(id=1, po_id=po_id, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=po_id, product_name='产品B', product_barcode='bB',
                         order_qty=200, source_order_id=9001, source_record_type='order'),
    ])
    await session.commit()

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]
    summed: dict[str, float] = {}
    for mats in _sku_materials(group).values():
        for name, qty in mats.items():
            summed[name] = summed.get(name, 0.0) + qty

    assert summed == _fabrics(group)


async def test_c13_unresolvable_sku_name_yields_empty_materials(db):
    """C13：SKU 名解析不出产品（旧数据拼接名 / 名字不一致）→ 该 SKU 的 materials 为空，
    且**不抛错**（前端据此回退订单级单块，绝不编造数字）。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add(PurchaseOrderSku(
        id=7, po_id=po_id, product_name='查无此产品', product_barcode='',
        order_qty=100, source_order_id=9001, source_record_type='order',
    ))
    await session.commit()

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    target = next(s for s in group['skus'] if s['product_name'] == '查无此产品')
    assert target['materials'] == []


async def test_c11_stored_truth_unchanged_when_item_hand_edited(db):
    """C11：明细被手工改过时，**既有字段**仍是真值（对照块的依据），按 SKU 字段照旧按 BOM 算。"""
    session, _ = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add_all([
        PurchaseOrderSku(id=1, po_id=po_id, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=po_id, product_name='产品B', product_barcode='bB',
                         order_qty=200, source_order_id=9001, source_record_type='order'),
        # 手工把 ONLY_A 从 20 改成 25
        PurchaseOrderItem(id=99, order_id=po_id, material_name=ONLY_A, specification='S2', unit='米',
                          quantity=25, supplier_name='供应商甲'),
    ])
    await session.commit()
    # 覆盖原 ONLY_A 行，避免同键两行被累加
    from sqlalchemy import update as _update
    await session.execute(
        _update(PurchaseOrderItem).where(PurchaseOrderItem.id == 2).values(quantity=0)
    )
    await session.commit()

    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    assert _fabrics(group)[ONLY_A] == 25.0, '落库真值必须原样反映手工修改'
    assert _sku_materials(group)['产品A'][ONLY_A] == 20.0, '按 SKU 字段仍按 BOM 推算'
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest fastapi_app/tests/services/test_factory_summary_multisku.py -k "c8 or c9 or c10 or c11" -v`
Expected: FAIL —— `materials` 键不存在 ⇒ `KeyError`/`TypeError`（`s.get('materials') or []` 会得到 `[]`，故 c8/c10/c11 断言在**数值**上失败；c9 会因空集而通过——**注意 c9 在实现前是「假绿」**，Step 4 之后才是真验证）

- [ ] **Step 3: 写最小实现**

在 `fastapi_app/services/purchase/_factory.py` 中，`_is_filling_category` 的 import 已存在（`:11`）。追加两个纯函数（放在 `_accumulate_factory_po_items` 之后、`_build_factory_group_map` 之前）：

```python
def _norm_sku_name(value) -> str:
    """SKU 名归一：仅 strip。**不** casefold —— 产品名要逐字匹配 `Product.name`（全局唯一）。"""
    return str(value or '').strip()


def _sku_material_rows(bom_rows: list, sku_qty: float, supplier_fallback: str) -> list[dict]:
    """把某个 SKU 的 BOM 行展开为「该 SKU 自己的物料行」（口径 A）。

    `quantity` = ``单件用量 × 该 SKU 数量``（**基准量**，不含损耗加放 —— 加放由前端按该
    物料的行损耗率实时做，故这里必须给基准值）。

    口径要点：
    - 过滤填充类（与工厂汇总既有展示口径一致）；
    - **同一 SKU 内多作用域（角色）重复行累加** —— 与生成路径一致；
    - **不同 SKU 之间不合并、不去重** —— 那是采购合计的口径（见
      `_build_factory_group_map` 的 `seen_materials`），本函数只服务「某一个 SKU 要多少料」。

    不查库、不抛错；`bom_rows` 为空时返回 `[]`。
    """
    buckets: dict[tuple, dict] = {}
    for bom in bom_rows or []:
        if _is_filling_category(bom.get('category')):
            continue
        sup = bom.get('supplier_name') or supplier_fallback
        key = (sup, bom['material_name'], bom['specification'], bom['unit'])
        amount = float(bom.get('quantity') or 0) * float(sku_qty or 0)
        if key in buckets:
            buckets[key]['quantity'] += amount
        else:
            buckets[key] = {
                'supplier_name': sup,
                'material_name': bom['material_name'],
                'specification': bom['specification'],
                'unit': bom['unit'],
                'quantity': amount,
            }
    # 稳定顺序：与既有 fabrics 的排序口径一致（供应商 → 物料名 → 规格 → 单位）
    return sorted(
        buckets.values(),
        key=lambda r: (r['supplier_name'], r['material_name'], r['specification'], r['unit']),
    )
```

在 `_build_factory_group_map` 里：分组字典初始化时加一个 `'_sku_materials': {}`（紧跟 `'_sku_lines': []` 之后），并在**逐 SKU 展示明细**那段之后加入按 SKU 的物料收集。找到这段现有代码：

```python
        # 逐 SKU 展示明细：优先取逐 SKU 快照，缺失时回退订单级单行
        sku_lines = (po_sku_map or {}).get(po.id) or []
        if sku_lines:
            group['_sku_lines'].extend(sku_lines)
        else:
            group['_sku_lines'].append({
                'product_name': prod, 'product_barcode': '', 'order_qty': order_qty,
            })
```

改为（**只增加最后一段**）：

```python
        # 逐 SKU 展示明细：优先取逐 SKU 快照，缺失时回退订单级单行
        sku_lines = (po_sku_map or {}).get(po.id) or []
        if sku_lines:
            group['_sku_lines'].extend(sku_lines)
        else:
            group['_sku_lines'].append({
                'product_name': prod, 'product_barcode': '', 'order_qty': order_qty,
            })

        # 按 SKU 展开的物料（口径 A）：纯内存，BOM 已随请求加载，零新增查询。
        # 键用 SKU 名（Product.name 全局唯一）；解析不出产品的 SKU 留空 →
        # 前端据此回退订单级单块，绝不编造。
        name_to_pid = {name: pid for pid, name in (prod_name_map or {}).items()}
        for sku in sku_lines:
            sku_pid = name_to_pid.get(_norm_sku_name(sku.get('product_name')))
            group['_sku_materials'][_norm_sku_name(sku.get('product_name'))] = (
                _sku_material_rows(
                    bom_data.get(sku_pid) or [], float(sku.get('order_qty') or 0),
                    po.supplier_name or '未指定供应商',
                )
                if sku_pid else []
            )
```

在 `_serialize_factory_groups` 里装配（找到现有 `'skus': merge_sku_lines(group.get('_sku_lines') or []),`）：

```python
            # 逐 SKU 展示明细（前端逐 SKU 分行 + 合计子行）。新增 `materials`：
            # 该 SKU 自己的物料基准量（口径 A）；解析不出 / 无 BOM 时为空数组，前端回退。
            'skus': [
                {
                    **line,
                    'materials': (group.get('_sku_materials') or {}).get(
                        _norm_sku_name(line.get('product_name'))
                    ) or [],
                }
                for line in merge_sku_lines(group.get('_sku_lines') or [])
            ],
```

同时把该函数里 `groups.append({...})` 上方的注释「物料数量在采购单侧是跨 SKU 合并值，无法拆分到 SKU，故物料仍按订单级展示」**改为如实描述新形态**：

```python
            # 注意：既有 `suppliers/fabrics` 仍是**跨 SKU 合并的落库真值**（含手工编辑），
            # 前端用它做「实际下单」差异对照与编辑态定位；`skus[].materials` 才是按 SKU
            # 推算的展示口径（BOM 单件用量 × 该 SKU 数量）。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/services/test_factory_summary_multisku.py -v`
Expected: PASS（**含既有 c1–c7**——它们断言 `suppliers/fabrics` 与 `skus` 的既有键，必须全绿）

- [ ] **Step 5: 零新增查询护栏**

在 `test_factory_summary_multisku.py` 末尾追加（复用 fixture 的 `statements` 记录器）：

```python
async def test_c12_per_sku_materials_add_no_db_queries(db):
    """C12：新增 materials 不得引入任何额外 DB 往返（BOM 已随请求加载）。"""
    session, statements = db
    po_id = await _seed_single_or_multi(session, multi=True)
    session.add_all([
        PurchaseOrderSku(id=1, po_id=po_id, product_name='产品A', product_barcode='bA',
                         order_qty=100, source_order_id=9001, source_record_type='order'),
        PurchaseOrderSku(id=2, po_id=po_id, product_name='产品B', product_barcode='bB',
                         order_qty=200, source_order_id=9001, source_record_type='order'),
    ])
    await session.commit()

    statements.clear()
    group = (await get_factory_order_summary(session, [po_id]))['groups'][0]

    reads = [s for s in statements if s.lstrip().lower().startswith('select')]
    assert group['skus'][0].get('materials') is not None
    # BOM/产品/明细/快照 ≈ 8 条定点读；给到 14 条上限，超了说明有人在循环里查库
    assert len(reads) <= 14, f'汇总读查询数异常偏多（{len(reads)} 条），疑似在按 SKU 展开时查库'
```

Run: `python -m pytest fastapi_app/tests/services/test_factory_summary_multisku.py -k c12 -v`
Expected: PASS

- [ ] **Step 6: 跑门禁并提交**

Run: `python scripts/quality_gate.py && command ruff check fastapi_app/services/purchase/_factory.py fastapi_app/tests/services/test_factory_summary_multisku.py`
Expected: 无新增违规

```bash
command git add fastapi_app/services/purchase/_factory.py fastapi_app/tests/services/test_factory_summary_multisku.py
command git commit -m "feat(purchase): 汇总接口按 SKU 展开物料明细（只增字段，零新增查询）" -m "前端要按 SKU 展示物料，而后端此前只给跨 SKU 合并的物料（明细按「物料名+规格+单位」合并落库、且不带 SKU 身份），无从拆开。改为在既有 suppliers/fabrics（落库真值，原样保留）之外，新增 skus[].materials[]：每 SKU 每物料的**基准量** = BOM 单件用量 × 该 SKU 数量。BOM 本就随请求加载（po_pids_map + bom_data），故纯内存、零新增 DB 查询（有用例护栏）。SKU 名解析不出产品的（旧数据拼接名）留空数组，不编造。" -m "Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 前端——按 SKU 行模型与差异计算（纯函数模块）

**Files:**
- Create: `frontend-vite/src/views/purchase/composables/perSkuRows.ts`
- Modify: `frontend-vite/src/views/purchase/composables/useSummaryModal.ts`（`SkuLine` 增加可选 `materials`）
- Test: `frontend-vite/src/test/perSkuRows.test.ts`

**Interfaces:**
- Consumes: **仅类型**（`FactoryGroup` / `FabricItem`，用 `import type`）——**不得**从 `useSummaryModal.ts` 引入任何**值**，否则与它对本模块 `buildPerSkuRows` 的依赖构成**循环导入**（Vite/vitest 下会得到 `undefined` 绑定）
- **本任务同时搬迁两个纯函数**：把 `calcSpareQuantity` 与 `summaryMaterialKey` 从 `useSummaryModal.ts` **移入** `perSkuRows.ts`（它们本就是无依赖的纯函数），并在 `useSummaryModal.ts` 里用 `export { calcSpareQuantity, summaryMaterialKey } from './perSkuRows'` **反向重导出** —— 依赖方向从此单向（`useSummaryModal` → `perSkuRows`），且既有测试从 `useSummaryModal` 导入这两个函数的写法**不受影响**
- Produces（后续 Task 3/5 依赖，签名冻结）:
  ```ts
  export interface SkuMaterial { supplier_name: string; material_name: string; specification: string; unit: string; quantity: number }
  export interface PerSkuRow {
    skuIdx: number
    /** 该 SKU 块在左侧「产品名称/订单数量/备品数量」三列里要显示的文本行（per-SKU 模式恒 1 行） */
    cellLines: { name: string; qty: number; spare: number; isTotal: boolean }[]
    isFirstSkuRow: boolean
    skuRowSpan: number
    isFirstSupplierRow: boolean
    supplierRowSpan: number
    supplierName: string
    materialName: string
    specification: string
    unit: string
    baseQuantity: number
    /** 该物料在落库明细中的坐标；无对应明细时为 null（只读行） */
    coord: { si: number; fi: number } | null
    itemIds: number[]
    /** 该 SKU 无 BOM 明细时的占位行（保留块结构，不隐藏该 SKU） */
    noBom: boolean
  }
  export function materialKeyOf(m: { supplier_name?: string; material_name?: string; specification?: string; unit?: string }): string
  export function buildPerSkuRows(group: FactoryGroup, groupRate: number): PerSkuRow[]
  export function computeQuantityDiff(group: FactoryGroup, rows: PerSkuRow[]): { materialName: string; perSku: number; stored: number }[]
  ```

- [ ] **Step 1: 写失败测试**

创建 `frontend-vite/src/test/perSkuRows.test.ts`：

```ts
/**
 * 按 SKU 行模型（perSkuRows）单测（2026-09-30）。
 *
 * 锁定：
 *   R1 每个 SKU 一块：skuIdx / skuRowSpan / supplierRowSpan 正确；
 *   R2 每行映射回落库坐标 (si, fi) 与 itemIds —— 这是「同物料率/数量联动」的实现基础；
 *   R3 落库明细里没有的物料 → coord=null（只读行，不得写库）；
 *   R4 差异判定：|Σ推算 − 落库| ≤ 0.005 不算差异（浮点尾差不得误报）；
 *   R5 无 materials（旧后端 / 无 BOM）→ 返回 []，调用方据此回退现状。
 */
import { describe, it, expect } from 'vitest'
import { buildPerSkuRows, computeQuantityDiff, materialKeyOf } from '@/views/purchase/composables/perSkuRows'
import type { FactoryGroup } from '@/views/purchase/composables/useSummaryModal'

/** 2 SKU × 同供应商；共享布跨 SKU 各算各的；另有一条「只出现在 BOM、落库里没有」的新物料 */
function twoSkuGroup(): FactoryGroup {
  return {
    customer_name: '客户甲',
    product_name: '产品A、产品B',
    product_quantity: 300,
    spare_rate: 10,
    skus: [
      {
        product_name: '产品A', product_barcode: 'bA', order_qty: 100,
        materials: [
          { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20 },
          { supplier_name: '供应商甲', material_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20 },
        ],
      },
      {
        product_name: '产品B', product_barcode: 'bB', order_qty: 200,
        materials: [
          { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40 },
          { supplier_name: '供应商甲', material_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40 },
          { supplier_name: '供应商甲', material_name: '新加布', specification: 'S9', unit: '米', quantity: 5 },
        ],
      },
    ],
    suppliers: [
      {
        supplier_name: '供应商甲',
        fabrics: [
          { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 60, item_ids: [1] },
          { fabric_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20, item_ids: [2] },
          { fabric_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40, item_ids: [3] },
        ],
      },
    ],
  }
}

describe('materialKeyOf', () => {
  it('与 summaryMaterialKey 同口径：供应商+物料名+规格+单位', () => {
    expect(materialKeyOf({ supplier_name: '甲', material_name: '布', specification: 'S1', unit: '米' }))
      .toBe(materialKeyOf({ supplier_name: '甲', material_name: '布', specification: 'S1', unit: '米' }))
    expect(materialKeyOf({ supplier_name: '甲', material_name: '布' }))
      .not.toBe(materialKeyOf({ supplier_name: '乙', material_name: '布' }))
  })
})

describe('buildPerSkuRows', () => {
  it('R1 每 SKU 一块：块内行数 = 该 SKU 的物料数；供应商在块内合并', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)

    expect(rows).toHaveLength(5) // A 2 行 + B 3 行
    expect(rows.filter((r) => r.isFirstSkuRow).map((r) => r.skuIdx)).toEqual([0, 1])
    expect(rows[0]!.skuRowSpan).toBe(2)
    expect(rows[2]!.skuRowSpan).toBe(3)
    // 供应商在 A 块 2 行合并、B 块 3 行合并
    expect(rows[0]!.isFirstSupplierRow).toBe(true)
    expect(rows[0]!.supplierRowSpan).toBe(2)
    expect(rows[2]!.supplierRowSpan).toBe(3)
    expect(rows[1]!.isFirstSupplierRow).toBe(false)
  })

  it('R1 左侧三列文本行：per-SKU 模式恒 1 行，数量取该 SKU 的 order_qty、备品按订单级率算', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)

    expect(rows[0]!.cellLines).toEqual([{ name: '产品A', qty: 100, spare: 1, isTotal: false }])
    expect(rows[2]!.cellLines).toEqual([{ name: '产品B', qty: 200, spare: 2, isTotal: false }])
  })

  it('R2 每行映射回落库坐标与 itemIds（共享布在两个 SKU 块里指向同一坐标 → 联动天然成立）', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)

    expect(rows[0]!.coord).toEqual({ si: 0, fi: 0 })   // A 块 · 共享布
    expect(rows[2]!.coord).toEqual({ si: 0, fi: 0 })   // B 块 · 共享布 → 同一坐标
    expect(rows[0]!.itemIds).toEqual([1])
    expect(rows[1]!.itemIds).toEqual([2])
    expect(rows[3]!.itemIds).toEqual([3])
  })

  it('R3 落库明细里没有的物料 → coord=null、itemIds 为空（只读行）', () => {
    const rows = buildPerSkuRows(twoSkuGroup(), 10)
    const newFabric = rows.find((r) => r.materialName === '新加布')!

    expect(newFabric.coord).toBeNull()
    expect(newFabric.itemIds).toEqual([])
  })

  it('R5 无 materials（旧后端 / 无 BOM）→ 返回空数组，调用方回退现状', () => {
    const group = twoSkuGroup()
    group.skus = [{ product_name: '产品A', product_barcode: 'bA', order_qty: 100 }]

    expect(buildPerSkuRows(group, 10)).toEqual([])
  })

  it('R6 个别 SKU 无 BOM → 保留块结构并产出占位行（不隐藏该 SKU）', () => {
    const group = twoSkuGroup()
    group.skus![1]!.materials = []

    const rows = buildPerSkuRows(group, 10)

    const placeholder = rows.find((r) => r.noBom)
    expect(placeholder).toBeDefined()
    expect(placeholder!.skuIdx).toBe(1)
    expect(placeholder!.cellLines[0]!.name).toBe('产品B')
    // 占位行没有可写目标
    expect(placeholder!.coord).toBeNull()
    expect(placeholder!.itemIds).toEqual([])
  })
})

describe('computeQuantityDiff', () => {
  it('R4 一致时不报差异（含浮点尾差 ≤0.005）', () => {
    const group = twoSkuGroup()
    // 让「新加布」也出现在落库明细里，且数值完全一致
    group.suppliers![0]!.fabrics.push({ fabric_name: '新加布', specification: 'S9', unit: '米', quantity: 5, item_ids: [9] })
    const rows = buildPerSkuRows(group, 10)

    expect(computeQuantityDiff(group, rows)).toEqual([])
  })

  it('R4 尾差 ≤0.005 不报；超过才报（并给出推算值与落库值）', () => {
    const group = twoSkuGroup()
    group.suppliers![0]!.fabrics[0]!.quantity = 60.004 // Σ推算 60 → 差 0.004，不报
    expect(computeQuantityDiff(group, buildPerSkuRows(group, 10))).toEqual([])

    group.suppliers![0]!.fabrics[0]!.quantity = 65 // 差 5 → 报
    expect(computeQuantityDiff(group, buildPerSkuRows(group, 10))).toEqual([
      { materialName: '共享布', perSku: 60, stored: 65 },
    ])
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command npx vitest run src/test/perSkuRows.test.ts`
Expected: FAIL —— `Failed to resolve import '@/views/purchase/composables/perSkuRows'`

- [ ] **Step 3: 实现**

**3a. 先把两个纯函数搬进 `perSkuRows.ts`（消解循环导入）**

把 `useSummaryModal.ts` 里 `calcSpareQuantity` 与 `summaryMaterialKey` 两个函数的**定义**（连同 docstring）整段**移入** `perSkuRows.ts`；并在 `useSummaryModal.ts` 的 import 区之后加一行**重导出**，保住既有导入路径：

```ts
// 这两个纯函数已移入 perSkuRows.ts —— 本模块要用它的 buildPerSkuRows，
// 若此处再定义它们就构成互相 import（Vite/vitest 下会拿到 undefined 绑定）。
// 重导出仅为兼容既有导入路径，行为逐字不变。
export { calcSpareQuantity, summaryMaterialKey } from './perSkuRows'
```

同时 `useSummaryModal.ts` 内部要用到它们的地方（`buildSkuDisplayLines`、`supplierGroups`、`printFactory`/`exportFactory` 等）改从 `./perSkuRows` 引入：

```ts
import { calcSpareQuantity, summaryMaterialKey } from './perSkuRows'
```

**3b. 再给 `SkuLine` 加上可选 `materials`**

先给 `useSummaryModal.ts` 的 `SkuLine` 加上可选 `materials`：

```ts
/** 汇总分组的逐 SKU 展示明细（后端 factory-summary 返回） */
export interface SkuLine {
  product_name: string
  product_barcode?: string
  order_qty: number
  /**
   * 该 SKU 自己的物料明细（后端按 SKU 展开的**基准量** = BOM 单件用量 × 该 SKU 数量）。
   * 缺省/为空表示后端未提供（旧后端、无 BOM、SKU 名解析不出）→ 前端回退订单级单块。
   */
  materials?: { supplier_name: string; material_name: string; specification: string; unit: string; quantity: number }[]
}
```

创建 `frontend-vite/src/views/purchase/composables/perSkuRows.ts`：

```ts
/**
 * 汇总下单「按 SKU 展开物料明细」的行模型（纯函数，可独立测试）。
 *
 * 设计要点：**每个按 SKU 的物料行都映射回落库明细的坐标 `(si, fi)`** ——
 * 因为同一物料在库里只有一行（跨 SKU 共用），于是：
 *   - 损耗率、编辑态数量这些既有机制（都按坐标寻址）**原样复用**；
 *   - 「同物料跨 SKU 联动」天然成立（同一坐标 = 同一份状态），无需新增联动代码。
 *
 * 落库明细里找不到对应的物料（BOM 在生成后被新增）时 `coord = null` —— 该行只读，
 * 绝不允许把编辑写进别的明细。
 */
import type { FactoryGroup } from './useSummaryModal'
import { calcSpareQuantity, getGroupOrderQty, summaryMaterialKey } from './useSummaryModal'

export interface SkuMaterial {
  supplier_name: string
  material_name: string
  specification: string
  unit: string
  quantity: number
}

export interface PerSkuRow {
  skuIdx: number
  cellLines: { name: string; qty: number; spare: number; isTotal: boolean }[]
  isFirstSkuRow: boolean
  skuRowSpan: number
  isFirstSupplierRow: boolean
  supplierRowSpan: number
  supplierName: string
  materialName: string
  specification: string
  unit: string
  baseQuantity: number
  coord: { si: number; fi: number } | null
  itemIds: number[]
}

/** 物料键：与工厂页/供应商页同源（复用 summaryMaterialKey，不另造一套）。 */
export function materialKeyOf(m: {
  supplier_name?: string; material_name?: string; specification?: string; unit?: string
}): string {
  return summaryMaterialKey(m.supplier_name, m.material_name, m.specification, m.unit)
}

/** 落库明细索引：物料键 → 坐标 / item_ids / 落库数量。 */
function buildStoredIndex(group: FactoryGroup) {
  const index = new Map<string, { coord: { si: number; fi: number }; itemIds: number[]; storedQuantity: number }>()
  ;(group.suppliers || []).forEach((supplier, si) => {
    ;(supplier.fabrics || []).forEach((fabric, fi) => {
      const key = materialKeyOf({
        supplier_name: supplier.supplier_name,
        material_name: fabric.fabric_name,
        specification: fabric.specification,
        unit: fabric.unit,
      })
      const itemIds = fabric.item_ids || (fabric.item_id ? [fabric.item_id] : [])
      index.set(key, {
        coord: { si, fi },
        itemIds,
        storedQuantity: parseFloat(String(fabric.quantity)) || 0,
      })
    })
  })
  return index
}

/** 是否具备「按 SKU 展开」的数据（否则调用方回退现状）。 */
function hasPerSkuMaterials(group: FactoryGroup): boolean {
  const skus = group.skus || []
  return skus.length > 0 && skus.some((s) => (s.materials?.length || 0) > 0)
}

/**
 * 构建「每个 SKU 一块」的扁平行列表。
 *
 * 返回 `[]` 表示数据不足（旧后端 / 无 BOM / SKU 名解析不出）→ 调用方回退订单级单块，
 * 与改动前逐字一致（单 SKU 单因此天然零回归）。
 */
export function buildPerSkuRows(group: FactoryGroup, groupRate: number): PerSkuRow[] {
  if (!hasPerSkuMaterials(group)) return []
  const stored = buildStoredIndex(group)
  const rows: PerSkuRow[] = []

  ;(group.skus || []).forEach((sku, skuIdx) => {
    const materials = (sku.materials || []) as SkuMaterial[]
    if (materials.length === 0) {
      // 该 SKU 没有 BOM 明细（或后端解析不出产品）：**保留块结构**渲染一条占位行，
      // 不隐藏该 SKU —— 否则用户会以为它被漏掉了。整组都无 materials 时上层
      // hasPerSkuMaterials 已判否、根本走不到这里（那种情况回退订单级单块）。
      const skuQty = parseFloat(String(sku.order_qty ?? 0)) || 0
      rows.push({
        skuIdx,
        cellLines: [{ name: sku.product_name || '', qty: skuQty, spare: calcSpareQuantity(skuQty, groupRate), isTotal: false }],
        isFirstSkuRow: true,
        skuRowSpan: 1,
        isFirstSupplierRow: false,
        supplierRowSpan: 0,
        supplierName: '',
        materialName: '',
        specification: '',
        unit: '',
        baseQuantity: 0,
        coord: null,
        itemIds: [],
        noBom: true,
      })
      return
    }
    // 块内按 供应商 → 物料名 → 规格 → 单位 排序（与后端稳定序一致，避免视觉跳动）
    const sorted = [...materials].sort((a, b) =>
      a.supplier_name.localeCompare(b.supplier_name)
      || a.material_name.localeCompare(b.material_name)
      || a.specification.localeCompare(b.specification)
      || a.unit.localeCompare(b.unit),
    )
    const skuQty = parseFloat(String(sku.order_qty ?? 0)) || 0
    const supplierCounts = new Map<string, number>()
    sorted.forEach((m) => supplierCounts.set(m.supplier_name, (supplierCounts.get(m.supplier_name) || 0) + 1))
    const seenSupplier = new Set<string>()

    sorted.forEach((m, i) => {
      const key = materialKeyOf(m)
      const hit = stored.get(key)
      const isFirstSupplierRow = !seenSupplier.has(m.supplier_name)
      seenSupplier.add(m.supplier_name)
      rows.push({
        skuIdx,
        cellLines: [{
          name: sku.product_name || '',
          qty: skuQty,
          spare: calcSpareQuantity(skuQty, groupRate),
          isTotal: false,
        }],
        isFirstSkuRow: i === 0,
        skuRowSpan: sorted.length,
        isFirstSupplierRow,
        supplierRowSpan: supplierCounts.get(m.supplier_name) || 0,
        supplierName: m.supplier_name,
        materialName: m.material_name,
        specification: m.specification,
        unit: m.unit,
        baseQuantity: parseFloat(String(m.quantity)) || 0,
        coord: hit?.coord ?? null,
        itemIds: hit?.itemIds ?? [],
        noBom: false,
      })
    })
  })
  return rows
}

/**
 * 数量差异：各 SKU 推算之和 vs 落库真值（按物料键）。
 * 容差 0.005 —— 数量落库为 2 位小数，避免浮点尾差误报。返回空数组表示无差异。
 */
export function computeQuantityDiff(
  group: FactoryGroup, rows: PerSkuRow[],
): { materialName: string; perSku: number; stored: number }[] {
  if (rows.length === 0) return []
  const stored = buildStoredIndex(group)
  const summed = new Map<string, number>()
  rows.forEach((r) => {
    const key = materialKeyOf({
      supplier_name: r.supplierName, material_name: r.materialName,
      specification: r.specification, unit: r.unit,
    })
    summed.set(key, (summed.get(key) ?? 0) + r.baseQuantity)
  })

  const diffs: { materialName: string; perSku: number; stored: number }[] = []
  summed.forEach((perSku, key) => {
    const hit = stored.get(key)
    if (!hit) return                       // 只出现在 BOM、落库里没有 → 不是「差异」，是新增物料
    const perSkuRounded = Math.round(perSku * 100) / 100
    if (Math.abs(perSkuRounded - hit.storedQuantity) > 0.005) {
      diffs.push({ materialName: key.split('\u0000')[1] || '', perSku: perSkuRounded, stored: hit.storedQuantity })
    }
  })
  return diffs
}
```

> **注意**：`getGroupOrderQty` 在本模块中未使用（备品取 SKU 自己的 `order_qty`），**不要 import 它**，否则触发 `F401`/eslint 未使用告警。

- [ ] **Step 4: 跑测试确认通过**

Run: `command npx vitest run src/test/perSkuRows.test.ts`
Expected: PASS（5 个 describe 全绿）

- [ ] **Step 5: 提交**

```bash
command git add frontend-vite/src/views/purchase/composables/perSkuRows.ts frontend-vite/src/views/purchase/composables/useSummaryModal.ts frontend-vite/src/test/perSkuRows.test.ts
command git commit -m "feat(purchase): 按 SKU 展开的行模型（把每行映射回落库坐标，联动天然成立）" -m "前端要按 SKU 展示物料。关键设计：每个按 SKU 的物料行都映射回落库明细坐标 (si,fi) —— 同一物料在库里只有一行（跨 SKU 共用），于是既有的损耗率/数量编辑机制（都按坐标寻址）原样复用，「同物料跨 SKU 联动」不需要任何新代码。落库明细里没有的物料（BOM 生成后新增）置 coord=null，行只读，避免编辑写错明细。数据不足时返回空数组，调用方回退现状（单 SKU 零回归）。" -m "Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 前端——表格改为按 SKU 块渲染（含只读行与编辑态提示）

**Files:**
- Modify: `frontend-vite/src/views/purchase/components/SummaryFactoryTab.vue`（模板 + `flatFactoryRows` 替换）
- Test: `frontend-vite/src/test/SummaryFactoryTab.perSku.test.ts`（新建）

**Interfaces:**
- Consumes: `buildPerSkuRows(group, groupRate): PerSkuRow[]`、`materialKeyOf`（Task 2）；组件既有 props（`groupSpareRates`、`lossRate`、`fabricLossRates`、`editMode`）与既有 `rateForFabric(gi, si, fi)` / `spareRateForGroup(gi)` / `displayFabricQty` / `editFabricQty`
- Produces: 无新对外接口（组件内部行模型替换）

- [ ] **Step 1: 写失败测试**

创建 `frontend-vite/src/test/SummaryFactoryTab.perSku.test.ts`：

```ts
/**
 * 工厂页签「按 SKU 展开物料明细」渲染测试（2026-09-30）。
 *
 * 锁定：
 *   P1 每个 SKU 一块：块内物料行独立，供应商在块内合并；
 *   P2 左侧三列（产品名称/订单数量/备品数量）按 SKU 各一行；
 *   P3 **同物料跨 SKU 联动**：同一物料在两块里的损耗率输入显示同值（同一坐标）；
 *   P4 落库明细里没有的物料 → 该行**只读**（无输入框）；
 *   P5 数据不足（旧后端 / 无 materials）→ 回退现状形态（逐 SKU 名堆叠 + 订单级物料）。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(), unprocessedOrders: vi.fn(), factorySummary: vi.fn(),
    supplierSummary: vi.fn(), saveFactoryEdits: vi.fn(), supplierSummaryExport: vi.fn(),
  },
}))

import SummaryFactoryTab from '@/views/purchase/components/SummaryFactoryTab.vue'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

const stubs = { FontAwesomeIcon: true }

function group(): FactoryGroup {
  return {
    customer_name: '客户甲', product_name: '产品A、产品B', product_quantity: 300, spare_rate: 10,
    skus: [
      { product_name: '产品A', product_barcode: 'bA', order_qty: 100, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20 },
        { supplier_name: '供应商甲', material_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20 },
      ] },
      { product_name: '产品B', product_barcode: 'bB', order_qty: 200, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40 },
        { supplier_name: '供应商甲', material_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40 },
        { supplier_name: '供应商甲', material_name: '新加布', specification: 'S9', unit: '米', quantity: 5 },
      ] },
    ],
    suppliers: [{
      supplier_name: '供应商甲',
      fabrics: [
        { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 60, item_ids: [1] },
        { fabric_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20, item_ids: [2] },
        { fabric_name: 'B专有布', specification: 'S3', unit: '米', quantity: 40, item_ids: [3] },
      ],
    }],
  }
}

function dataOf(g: FactoryGroup): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: 10, groups: [g] }
}

function mountTab(g: FactoryGroup, opts: { editMode?: boolean } = {}) {
  return mount(SummaryFactoryTab, {
    props: {
      factoryData: dataOf(g), editMode: opts.editMode ?? false, lossRate: 10, orderCount: 1,
      groupSpareRates: [10],
      fabricLossRates: [[[5, 0], [0, 0, 0]]],  // [供应商][布料]：共享布 5‰、A/B专有 0、新加布 0
    },
    global: { stubs },
  })
}

const bodyRows = (w: ReturnType<typeof mountTab>) => w.findAll('tbody tr')

describe('P1/P2 按 SKU 分块', () => {
  it('P1 共 5 个数据行（A 块 2 + B 块 3）；供应商单元格在每块内合并', () => {
    const rows = bodyRows(mountTab(group()))
    expect(rows).toHaveLength(5)
    // 每块第一行含供应商单元格，块内第二/三行不再有
    expect(rows[0]!.text()).toContain('供应商甲')
    expect(rows[1]!.text()).not.toContain('供应商甲')
    expect(rows[2]!.text()).toContain('供应商甲')
  })

  it('P2 产品名称 / 订单数量 / 备品数量 各块一行，值为该 SKU 自己的', () => {
    const rows = bodyRows(mountTab(group()))
    expect(rows[0]!.findAll('td')[1]!.text()).toBe('产品A')
    expect(rows[0]!.findAll('td')[2]!.text()).toBe('100.0')
    expect(rows[0]!.findAll('td')[3]!.text()).toBe('1.0')
    expect(rows[2]!.findAll('td')[0]!.text()).toBe('产品B')
    expect(rows[2]!.findAll('td')[1]!.text()).toBe('200.0')
    expect(rows[2]!.findAll('td')[2]!.text()).toBe('2.0')
  })
})

describe('P3 同物料跨 SKU 联动', () => {
  it('共享布在两块里的损耗率输入显示同一个值（同一坐标）', () => {
    const rows = bodyRows(mountTab(group()))
    const rateA = rows[0]!.find('input[type="number"]')
    const rateB = rows[2]!.find('input[type="number"]')
    expect((rateA.element as HTMLInputElement).value).toBe('5')
    expect((rateB.element as HTMLInputElement).value).toBe('5')
  })
})

describe('P4 只读行', () => {
  it('落库明细里没有的「新加布」不渲染损耗率输入框，并给出说明', () => {
    const rows = bodyRows(mountTab(group()))
    const newRow = rows[4]!
    expect(newRow.text()).toContain('新加布')
    expect(newRow.find('input[type="number"]').exists()).toBe(false)
    // 必须有可解释的提示（title 或文案），否则用户不知道为什么改不了
    expect(newRow.html()).toContain('title')
  })
})

describe('P5 数据不足回退现状', () => {
  it('无 materials → 退回「逐 SKU 名堆叠 + 订单级物料」的旧形态', () => {
    const g = group()
    g.skus = [
      { product_name: '产品A', product_barcode: 'bA', order_qty: 100 },
      { product_name: '产品B', product_barcode: 'bB', order_qty: 200 },
    ]
    const rows = bodyRows(mountTab(g))

    expect(rows).toHaveLength(3)                       // 订单级 3 条落库物料
    expect(rows[0]!.text()).toContain('产品A')          // 名称仍逐 SKU 堆叠在一格
    expect(rows[0]!.text()).toContain('产品B')
    expect(rows[0]!.text()).toContain('合计')
  })
})

describe('P6 编辑态提示（跨 SKU 共用同一行明细）', () => {
  it('共享布的数量输入带「共用」提示；仅单个 SKU 出现的 A专有布不带', () => {
    const rows = bodyRows(mountTab(group(), { editMode: true }))

    // 编辑态每行只有「数量」一个输入框（率列在编辑态为只读文本）
    const sharedQty = rows[0]!.find('input[type="number"]')   // A 块 · 共享布
    expect(sharedQty.attributes('title')).toContain('共用')

    const ownQty = rows[1]!.find('input[type="number"]')      // A 块 · A专有布
    expect(ownQty.attributes('title') || '').not.toContain('共用')
  })

  it('非编辑态的率输入在共享物料上带提示（改率同样跨 SKU 生效）', () => {
    const rows = bodyRows(mountTab(group()))

    expect(rows[0]!.find('input[type="number"]').attributes('title')).toContain('共用')
    expect(rows[1]!.find('input[type="number"]').attributes('title') || '').not.toContain('共用')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command npx vitest run src/test/SummaryFactoryTab.perSku.test.ts`
Expected: FAIL —— P1/P2/P3/P4 失败（当前仍是订单级合并渲染，共 3 行、无 per-SKU 块）；P5 应**已经通过**（现状即回退形态）

- [ ] **Step 3: 实现**

修改 `SummaryFactoryTab.vue`：

**3a. script：引入行模型并替换 `flatFactoryRows`**。找到现有 `flatFactoryRows` computed（连同其上方注释），替换为：

```ts
/**
 * 行模型：优先「按 SKU 展开」（每个 SKU 一块物料）；数据不足时回退「订单级单块」——
 * 两条路径产出**同一形状**的行，模板只有一套（零回归靠回退路径保证）。
 *
 * 按 SKU 模式下每行携带落库坐标 coord，率/数量的读写仍走既有按坐标的机制，
 * 因此「同物料跨 SKU 联动」天然成立（同一坐标 = 同一份状态）。
 */
const flatRows = computed(() => {
  const groups = props.factoryData?.groups || []
  const out: {
    gi: number; row: PerSkuRow; group: FactoryGroup
    /** 回退模式下由订单级物料合成的行；按 SKU 模式下恒为 null */
    legacy: { si: number; fi: number; fabric: FabricItem; supplierName: string } | null
  }[] = []

  groups.forEach((group, gi) => {
    const perSku = buildPerSkuRows(group, spareRateForGroup(gi))
    if (perSku.length > 0) {
      perSku.forEach((row) => out.push({ gi, row, group, legacy: null }))
      return
    }
    // 回退：订单级物料 + 逐 SKU 名堆叠（与改动前逐字一致）
    const suppliers = group.suppliers || []
    const totalRows = suppliers.reduce((s, sup) => s + (sup.fabrics?.length || 0), 0)
    let index = 0
    suppliers.forEach((supplier, si) => {
      ;(supplier.fabrics || []).forEach((fabric, fi) => {
        const lines = groupSkuLines.value[gi] || []
        out.push({
          gi, group, legacy: { si, fi, fabric, supplierName: supplier.supplier_name },
          row: {
            skuIdx: 0,
            cellLines: lines,
            isFirstSkuRow: index === 0,
            skuRowSpan: totalRows,
            isFirstSupplierRow: fi === 0,
            supplierRowSpan: supplier.fabrics?.length || 0,
            supplierName: supplier.supplier_name,
            materialName: fabric.fabric_name,
            specification: fabric.specification || '',
            unit: fabric.unit || '',
            baseQuantity: parseFloat(String(fabric.quantity)) || 0,
            coord: { si, fi },
            itemIds: fabric.item_ids || (fabric.item_id ? [fabric.item_id] : []),
          },
        })
        index++
      })
    })
  })
  return out
})
```

**3b. script：率读写统一**（新增两个薄封装，按 SKU 与回退模式共用）：

```ts
/** 该行的落库坐标：按 SKU 模式下取 row.coord；回退模式取 legacy 坐标。 */
function rowCoord(r: { row: PerSkuRow; legacy: { si: number; fi: number } | null }) {
  return r.legacy ? { si: r.legacy.si, fi: r.legacy.fi } : r.row.coord
}

/** 该行的行损耗率（只读行无坐标 → 显示 0，且模板不给输入框）。 */
function rowRate(r: { row: PerSkuRow; legacy: { si: number; fi: number } | null; gi: number }): number {
  const c = rowCoord(r)
  if (!c) return 0
  return rateForFabric(r.gi, c.si, c.fi)
}
```

**3c. 模板：替换 `<tbody>`**。把现有 `flatFactoryRows` 循环整段替换为（列顺序：客户 / 产品名称 / 订单数量 / 备品数量 / 供应商 / 布料名称 / 规格型号 / 损耗率 / 数量 / 单位）：

```html
      <tbody>
        <template v-for="(item, ri) in flatRows" :key="`${item.gi}-${ri}`">
          <tr>
            <!-- 客户：该组第一行，rowspan = 该组总行数（两种模式同一算法） -->
            <td v-if="isGroupFirstRow(item.gi, ri)" :rowspan="groupRowCounts[item.gi]" class="font-bold">
              {{ item.group.customer_name }}
            </td>

            <!-- 产品名称 / 订单数量 / 备品数量：该 SKU 块首行，rowspan = 该块行数。
                 cellLines 在 per-SKU 模式恒 1 行；回退模式为逐 SKU 名堆叠（与改动前逐字一致）。 -->
            <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
              <div v-for="(line, li) in item.row.cellLines" :key="`n-${li}`"
                   :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]">{{ line.name }}</div>
            </td>
            <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
              <div v-for="(line, li) in item.row.cellLines" :key="`q-${li}`"
                   :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]">{{ formatQty(line.qty) }}</div>
            </td>
            <td v-if="item.row.isFirstSkuRow" :rowspan="item.row.skuRowSpan">
              <div v-for="(line, li) in item.row.cellLines" :key="`sp-${li}`"
                   :class="['sm-sku-line', { 'sm-sku-line--total': line.isTotal }]">{{ formatQty(line.spare) }}</div>
            </td>

            <!-- 该 SKU 无 BOM：占位行（保留块结构，不隐藏该 SKU） -->
            <td v-if="item.row.noBom" colspan="6" class="text-text-muted">无 BOM 明细</td>

            <template v-else>
              <!-- 供应商：块内首行 -->
              <td v-if="item.row.isFirstSupplierRow" :rowspan="item.row.supplierRowSpan">{{ item.row.supplierName }}</td>
              <td>{{ item.row.materialName }}</td>
              <td>{{ item.row.specification || '' }}</td>
              <!-- 损耗率：有落库坐标才可编辑；无坐标 → 只读并说明原因 -->
              <td>
                <template v-if="rowCoord(item)">
                  <input
                    v-if="!editMode"
                    type="number" class="w-14 text-right py-1 px-1 text-[13px] border border-border rounded"
                    :value="rowRate(item)" min="0" max="1000" step="any"
                    :title="sharedMaterialTitle(item)"
                    @input="onRowRateInput(item, $event)"
                  />
                  <template v-else>{{ formatQty(rowRate(item)) }}</template>
                </template>
                <span v-else class="text-text-muted" title="该物料不在采购明细中（BOM 生成后新增），无法在此修改">—</span>
              </td>
              <!-- 数量：编辑态可改（同物料跨 SKU 联动，故给出提示）；否则取派生展示值 -->
              <td>
                <input
                  v-if="rowCoord(item) && editMode"
                  type="number" class="w-20 text-right py-1 px-1.5 text-[13px] inline-block border border-border rounded"
                  :value="editRowQty(item)" min="0"
                  :title="sharedMaterialTitle(item)"
                  @change="onRowQtyChange(item, $event)"
                  @focus="($event.target as HTMLInputElement).select()"
                />
                <template v-else>{{ displayRowQty(item) }}</template>
              </td>
              <td>{{ item.row.unit || '' }}</td>
            </template>
          </tr>
        </template>
      </tbody>
```

> **本任务不包含差异对照块**：`<SummaryDiffBlock>` 及其三个胶水函数（`rowDiffMap` / `storedFabricsOf` / `isLastRowOfGroup`）由 **Task 4** 创建并接线——若在这里引用，T3 提交时该组件尚不存在，渲染会报「Failed to resolve component」且用例会挂。

**3e. 模板用到的其余胶水函数**（补进 script，与 3b、3d 一起，全部是薄封装）。先定义一次行项类型再复用：

```ts
type RowItem = {
  gi: number
  row: PerSkuRow
  group: FactoryGroup
  legacy: { si: number; fi: number; fabric: FabricItem; supplierName: string } | null
}
```
（`flatRows` 的 `out` 数组即声明为 `RowItem[]`。）

```ts
/** 该组第一行？（客户列 rowspan 的锚点） */
const groupFirstRowIndex = computed<Record<number, number>>(() => {
  const first: Record<number, number> = {}
  flatRows.value.forEach((r, ri) => { if (first[r.gi] === undefined) first[r.gi] = ri })
  return first
})
function isGroupFirstRow(gi: number, ri: number): boolean {
  return ri === groupFirstRowIndex.value[gi]
}

/** 该行的率：按坐标取（只读行 → 0，模板不会给输入框） */
function rowRate(item: RowItem): number {
  const c = rowCoord(item)
  return c ? rateForFabric(item.gi, c.si, c.fi) : 0
}

/** 该行的基准数量：回退模式取落库布料数量；按 SKU 模式取后端给的基准量 */
function rowBaseQty(item: RowItem): number {
  return item.legacy
    ? parseFloat(String(item.legacy.fabric.quantity)) || 0
    : item.row.baseQuantity
}

/** 编辑态数量输入框值（精确加放值，保存时由 updateFactoryQty 反推真值） */
function editRowQty(item: RowItem): number {
  const c = rowCoord(item)
  return c ? factoryQtyDisplayValue(rowBaseQty(item), rateForFabric(item.gi, c.si, c.fi), true) : rowBaseQty(item)
}

/** 非编辑态数量展示值（加放后向上取整） */
function displayRowQty(item: RowItem): number {
  const c = rowCoord(item)
  return c ? factoryQtyDisplayValue(rowBaseQty(item), rateForFabric(item.gi, c.si, c.fi), false) : rowBaseQty(item)
}

/** 每个物料键在多少个行里出现（>1 ⇒ 跨 SKU 共用同一行明细，编辑会联动）。 */
const sharedMaterialKeys = computed<Set<string>>(() => {
  const counts = new Map<string, number>()
  flatRows.value.forEach((r) => {
    if (r.legacy || r.row.noBom) return
    const k = materialKeyOf({
      supplier_name: r.row.supplierName, material_name: r.row.materialName,
      specification: r.row.specification, unit: r.row.unit,
    })
    counts.set(k, (counts.get(k) || 0) + 1)
  })
  const shared = new Set<string>()
  counts.forEach((n, k) => { if (n > 1) shared.add(k) })
  return shared
})

/** 编辑态提示文案：该物料跨 SKU 共用一行 ⇒ 明示改动会影响所有 SKU（spec §4.3 的可见性要求）。 */
function sharedMaterialTitle(item: RowItem): string {
  if (item.legacy || item.row.noBom) return ''
  const k = materialKeyOf({
    supplier_name: item.row.supplierName, material_name: item.row.materialName,
    specification: item.row.specification, unit: item.row.unit,
  })
  return sharedMaterialKeys.value.has(k)
    ? '该物料各 SKU 共用采购明细中的同一行，改动会影响所有 SKU'
    : ''
}

/** 率输入：按坐标提交（沿用既有 emit，不新增契约） */
function onRowRateInput(item: RowItem, e: Event): void {
  const c = rowCoord(item)
  if (!c) return
  const val = parseFloat((e.target as HTMLInputElement).value)
  emit('fabricLossRateInput', item.gi, c.si, c.fi, Number.isNaN(val) || val < 0 ? 0 : Math.min(val, 1000))
}

/** 数量提交：按坐标提交 —— 同一物料的多行共享同一坐标，故联动天然成立 */
function onRowQtyChange(item: RowItem, e: Event): void {
  const c = rowCoord(item)
  if (!c) return
  emit('updateQty', item.gi, c.si, c.fi, (e.target as HTMLInputElement).value)
}
```

**P6（编辑态提示）必须在 Step 1 有用例**：编辑态下，跨 SKU 共用的物料（如「共享布」）的**率输入与数量输入**都带 `title` 且文案含「共用」；只在单个 SKU 出现的物料（如「A专有布」）**不带**该提示。

**3d. 组级别的行统计**（供客户列 rowspan）在组件内计算：

```ts
/** 每个组的总行数（客户列 rowspan）；两种模式同一算法。 */
const groupRowCounts = computed<number[]>(() => {
  const counts: number[] = []
  flatRows.value.forEach((r) => { counts[r.gi] = (counts[r.gi] || 0) + 1 })
  return counts
})
```

并在模板里用 `v-if="ri === groupFirstRowIndex[item.gi]"` 控制客户单元格（同理加一个 `groupFirstRowIndex` computed）。

- [ ] **Step 4: 跑测试确认通过**

Run: `command npx vitest run src/test/SummaryFactoryTab.perSku.test.ts`
Expected: PASS（P1–P5）

- [ ] **Step 5: 守门禁并跑既有回归**

Run: `command wc -l frontend-vite/src/views/purchase/components/SummaryFactoryTab.vue && python scripts/quality_gate.py`
Expected: **行数 ≤ 400**；门禁 PASS。若超 400 —— **把「差异对照块」与只读行的提示渲染拆成子组件**（见 Task 4），不要压注释换行数。

Run: `command npx vitest run src/test/SummaryModal.multisku.test.ts src/test/useSummaryModal.test.ts src/test/QaAdversarial.beileSync.test.ts src/test/SummaryFactoryTab.spareColumn.test.ts`
Expected: 全绿（这几条锁定回退模式与列位，**不得回归**）

- [ ] **Step 6: 提交**

```bash
command git add frontend-vite/src/views/purchase/components/SummaryFactoryTab.vue frontend-vite/src/test/SummaryFactoryTab.perSku.test.ts
command git commit -m "feat(purchase): 工厂页签按 SKU 展开物料明细（每 SKU 一块，行只读兜底）" -m "物料原先跨 SKU 合并成一份，看不出每个 SKU 要多少料。改为每个 SKU 一块：左侧产品名称/订单数量/备品数量按 SKU 各一行，右侧是该 SKU 自己的物料行（供应商在块内合并）。率与数量的读写仍走既有的按坐标机制 —— 同一物料在各块里映射到同一坐标，故「同物料联动」不需要新代码。落库明细里没有的物料（BOM 生成后新增）渲染为只读行并给出原因，避免编辑写错明细。数据不足时整体回退订单级单块，与改动前逐字一致。" -m "Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 前端——数量差异对照块（仅差异时渲染）

**Files:**
- Create: `frontend-vite/src/views/purchase/components/SummaryDiffBlock.vue`
- Modify: `frontend-vite/src/views/purchase/components/SummaryFactoryTab.vue`（在组末尾插入该块）
- Test: `frontend-vite/src/test/SummaryDiffBlock.test.ts`

**Interfaces:**
- Consumes: `computeQuantityDiff(group, rows): { materialName; perSku; stored }[]`（Task 2）、`PerSkuRow`、既有 `formatQty`
- Produces: `SummaryDiffBlock.vue` 的 props —— `{ diffs: { materialName: string; perSku: number; stored: number }[]; storedFabrics: FabricItem[] }`（`storedFabrics` = 该组落库真值，用于列出全部「实际下单」行）

- [ ] **Step 1: 写失败测试**

创建 `frontend-vite/src/test/SummaryDiffBlock.test.ts`：

```ts
/**
 * 数量差异对照块（2026-09-30）。
 *   D1 无差异 → 组件不渲染任何内容（父组件据此不占高度）
 *   D2 有差异 → 渲染横幅（列出不一致的物料与两个数值）+ 落库真值行，不一致者描红
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryDiffBlock from '@/views/purchase/components/SummaryDiffBlock.vue'

const stored = [
  { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 65 },
  { fabric_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20 },
]

describe('SummaryDiffBlock', () => {
  it('D1 无差异 → 不渲染', () => {
    const w = mount(SummaryDiffBlock, { props: { diffs: [], storedFabrics: stored } })
    expect(w.text()).toBe('')
  })

  it('D2 有差异 → 横幅点名物料与数值，真值行渲染且不一致者描红', () => {
    const w = mount(SummaryDiffBlock, {
      props: { diffs: [{ materialName: '共享布', perSku: 60, stored: 65 }], storedFabrics: stored },
    })

    expect(w.text()).toContain('共享布')
    expect(w.text()).toContain('60')
    expect(w.text()).toContain('65')
    expect(w.text()).toContain('实际下单')
    // 不一致的那一行有描红标记
    expect(w.find('[data-diff="true"]').exists()).toBe(true)
    expect(w.findAll('[data-diff="true"]')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command npx vitest run src/test/SummaryDiffBlock.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 实现**

创建 `frontend-vite/src/views/purchase/components/SummaryDiffBlock.vue`：

```vue
<template>
  <template v-if="diffs.length > 0">
    <!-- 差异横幅：说明「实际下单含手工调整」并点名不一致的物料 -->
    <tr class="sm-diff-banner">
      <td :colspan="10">
        ⚠ 本条「实际下单」含手工调整，与上方按 BOM 推算的明细不一致：
        <span v-for="(d, i) in diffs" :key="d.materialName">{{ i > 0 ? '、' : '' }}{{ d.materialName }}（推算 {{ formatQty(d.perSku) }} / 实际 {{ formatQty(d.stored) }}）</span>
      </td>
    </tr>
    <!-- 落库真值：该组全部物料（与采购单明细一致） -->
    <tr
      v-for="(f, i) in storedFabrics"
      :key="`diff-${i}`"
      class="sm-diff-row"
      :data-diff="isDiff(f) ? 'true' : 'false'"
    >
      <td v-if="i === 0" :rowspan="storedFabrics.length" class="sm-diff-label">实际下单（含手工调整）</td>
      <td>{{ f.fabric_name }}</td>
      <td>{{ f.specification || '' }}</td>
      <td>{{ f.unit || '' }}</td>
      <td class="sm-diff-qty">{{ formatQty(f.quantity) }}</td>
    </tr>
  </template>
</template>

<script setup lang="ts">
/**
 * SummaryDiffBlock.vue — 「数量差异对照块」（2026-09-30）。
 *
 * 按 SKU 展开的物料行是**算出来的**（BOM 单件用量 × 该 SKU 数量）；若某单用过
 * 「自定义编辑」手改过数量，各 SKU 之和会与库里存的合并真值对不上。此处把差异
 * **显式化**：横幅点名不一致的物料与两个数值，其下列出该组全部落库行并对不一致者描红。
 *
 * 无差异时整块不渲染（`diffs` 为空 ⇒ 模板无输出），不占用表格高度。
 */
import { fmtQty as formatQty } from '@/utils/formatQty'
import type { FabricItem } from '../composables/useSummaryModal'

const props = defineProps<{
  diffs: { materialName: string; perSku: number; stored: number }[]
  /** 该组落库真值（既有 suppliers[].fabrics 汇总而来） */
  storedFabrics: FabricItem[]
}>()

/** 该落库行是否属于「不一致」的物料（横幅点名的那些） */
function isDiff(fabric: FabricItem): boolean {
  return props.diffs.some((d) => d.materialName === fabric.fabric_name)
}
</script>

<style scoped lang="scss">
.sm-diff-banner > td {
  background: #fffaf0;
  color: #7a4a00;
  font-size: 12px;
  text-align: left;
}
.sm-diff-row > td {
  background: #fffaf0;
}
.sm-diff-label {
  font-weight: 700;
  color: #7a4a00;
}
.sm-diff-row[data-diff='true'] .sm-diff-qty {
  color: #c22;
  font-weight: 700;
}
</style>
```

在 `SummaryFactoryTab.vue` 中接线（三处）：**① script 顶部 import 该组件**：

```ts
import SummaryDiffBlock from './SummaryDiffBlock.vue'
import { computeQuantityDiff } from '../composables/perSkuRows'
```

**② 在 `tbody` 内、每组的行之后插入对照块**：

```html
        <SummaryDiffBlock
          v-if="rowDiffMap[item.gi] && rowDiffMap[item.gi]!.length > 0 && isLastRowOfGroup(item.gi, ri)"
          :diffs="rowDiffMap[item.gi]!"
          :stored-fabrics="storedFabricsOf(item.group)"
        />
```

并在 script 中补三个小工具（**注意它们是渲染层胶水，保持简短以守住 400 行**）：

```ts
/** 每组的差异列表（按 SKU 模式下才有；回退模式恒为空 ⇒ 不渲染对照块）。 */
const rowDiffMap = computed<Record<number, { materialName: string; perSku: number; stored: number }[]>>(() => {
  const map: Record<number, { materialName: string; perSku: number; stored: number }[]> = {}
  ;(props.factoryData?.groups || []).forEach((group, gi) => {
    const rows = buildPerSkuRows(group, spareRateForGroup(gi))
    map[gi] = rows.length > 0 ? computeQuantityDiff(group, rows) : []
  })
  return map
})

/** 该组的全部落库物料（压平供应商维度，供对照块列出） */
function storedFabricsOf(group: FactoryGroup) {
  return (group.suppliers || []).flatMap((s) => s.fabrics || [])
}

/** 是否该组最后一行（对照块挂在组末尾） */
function isLastRowOfGroup(gi: number, ri: number): boolean {
  return ri === flatRows.value.length - 1 || flatRows.value[ri + 1]!.gi !== gi
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `command npx vitest run src/test/SummaryDiffBlock.test.ts src/test/SummaryFactoryTab.perSku.test.ts`
Expected: PASS

- [ ] **Step 5: 守门禁并提交**

Run: `command wc -l frontend-vite/src/views/purchase/components/SummaryFactoryTab.vue frontend-vite/src/views/purchase/components/SummaryDiffBlock.vue && python scripts/quality_gate.py`
Expected: `SummaryFactoryTab.vue` ≤ 400；门禁 PASS

```bash
command git add frontend-vite/src/views/purchase/components/SummaryDiffBlock.vue frontend-vite/src/views/purchase/components/SummaryFactoryTab.vue frontend-vite/src/test/SummaryDiffBlock.test.ts
command git commit -m "feat(purchase): 按 SKU 明细与落库真值的差异对照块（仅差异时渲染）" -m "按 SKU 的物料量是 BOM 推算值；若某单用过自定义编辑手改数量，各 SKU 之和会与库里合并真值对不上。此时在组末尾追加浅色对照块：横幅点名不一致的物料与两个数值，其下列出该组全部落库行并对不一致者描红。无差异整块不渲染（不占高度）。" -m "Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 打印 / Excel 导出与屏幕同源

**Files:**
- Modify: `frontend-vite/src/views/purchase/composables/useSummaryModal.ts`（`buildFactoryHtml` 按 SKU 分支）
- Test: `frontend-vite/src/test/useSummaryModal.perSkuPrint.test.ts`（新建）

**Interfaces:**
- Consumes: `buildPerSkuRows(group, rate)`、`computeQuantityDiff`（Task 2）；既有 `FACTORY_TABLE_HEAD`（10 列，含备品数量）、`escapeHtml`、`fmtQty`、`ceilMagnifiedByLossRate`
- Produces: `buildFactoryHtml(data, lossRate, fabricRates?, groupRates?)` **签名不变**；行为新增——当某组有 `materials` 时按 SKU 块输出（每块左侧三列合并、右侧物料行）；无 `materials` 时输出与改动前**逐字一致**

- [ ] **Step 1: 写失败测试**

创建 `frontend-vite/src/test/useSummaryModal.perSkuPrint.test.ts`：

```ts
/**
 * 打印 / 导出「按 SKU 展开」回归（2026-09-30）。
 *   E1 有 materials → 每 SKU 一块；左侧三列按 SKU 一行；物料行数 = Σ 各 SKU 物料数
 *   E2 差异存在时，对照块一并输出（打印件必须与屏幕同源，否则等于隐瞒差异）
 *   E3 无 materials → 输出与改动前逐字一致（零回归）
 */
import { describe, it, expect } from 'vitest'
import { buildFactoryHtml } from '@/views/purchase/composables/useSummaryModal'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

function perSkuGroup(): FactoryGroup {
  return {
    customer_name: '客户甲', product_name: '产品A、产品B', product_quantity: 300,
    skus: [
      { product_name: '产品A', product_barcode: 'bA', order_qty: 100, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20 },
      ] },
      { product_name: '产品B', product_barcode: 'bB', order_qty: 200, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40 },
      ] },
    ],
    suppliers: [{ supplier_name: '供应商甲', fabrics: [
      { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 60, item_ids: [1] },
    ] }],
  }
}

function legacyGroup(): FactoryGroup {
  return {
    customer_name: '客户甲', product_name: '产品A', product_quantity: 100,
    suppliers: [{ supplier_name: '供应商甲', fabrics: [
      { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 20, item_ids: [1] },
    ] }],
  }
}

const dataOf = (g: FactoryGroup): FactorySummaryData => ({ success: true, order_count: 1, groups: [g] })

function tbodyText(html: string): string[] {
  const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
  return [...doc.querySelectorAll('tbody tr')].map((tr) => tr.textContent || '')
}

describe('E1 有 materials → 按 SKU 块', () => {
  it('每 SKU 一行（左侧三列），物料行数 = Σ 各 SKU 物料数', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(perSkuGroup()), 10))

    expect(rows).toHaveLength(2)                    // A 一块 1 行 + B 一块 1 行
    expect(rows[0]).toContain('产品A')
    expect(rows[1]).toContain('产品B')
    // 数量列按该物料行率加放（率未给 ⇒ 回退统一率 10‰）：20 × 1.01 = 20.2 → ceil 21
    expect(rows[0]).toContain('21')
    expect(rows[1]).toContain('41')                 // 40 × 1.01 = 40.4 → ceil 41
  })
})

describe('E2 差异 → 对照块同源输出', () => {
  it('落库 65 ≠ 推算 60 → 输出「实际下单」行', () => {
    const g = perSkuGroup()
    g.suppliers![0]!.fabrics[0]!.quantity = 65
    const rows = tbodyText(buildFactoryHtml(dataOf(g), 10))

    expect(rows.some((t) => t.includes('实际下单'))).toBe(true)
    expect(rows.some((t) => t.includes('65'))).toBe(true)
  })
})

describe('E3 无 materials → 零回归', () => {
  it('单块、订单级物料，与改动前逐字一致', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(legacyGroup()), 10))

    expect(rows).toHaveLength(1)
    expect(rows[0]).toContain('产品A')
    expect(rows[0]).toContain('共享布')
    expect(rows[0]).not.toContain('实际下单')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `command npx vitest run src/test/useSummaryModal.perSkuPrint.test.ts`
Expected: FAIL —— E1 目前只有 1 行（订单级单块）；E2 无「实际下单」行

- [ ] **Step 3: 实现**

在 `buildFactoryHtml` 内、`data.groups?.forEach((group, gi) => {` 之后、现有订单级分支之前插入按 SKU 分支。**先在本文件顶部补两处导入**：

```ts
import { buildPerSkuRows, computeQuantityDiff } from './perSkuRows'
import type { PerSkuRow } from './perSkuRows'
```
（`FACTORY_TABLE_HEAD` / `buildFactoryHtml` 等既有导出与签名**保持不变**。）

```ts
    const perSkuRows = buildPerSkuRows(group, spareRate)
    if (perSkuRows.length > 0) {
      // 按 SKU 一块：客户列跨整组合并；左侧三列按 SKU 块合并；右侧是该 SKU 自己的物料行
      let cursor = 0
      let blockNo = 0
      while (cursor < perSkuRows.length) {
        const skuIdx = perSkuRows[cursor]!.skuIdx
        const block: PerSkuRow[] = []
        while (cursor < perSkuRows.length && perSkuRows[cursor]!.skuIdx === skuIdx) {
          block.push(perSkuRows[cursor]!)
          cursor++
        }
        block.forEach((row, i) => {
          tableHtml += '<tr>'
          if (i === 0) {
            // 客户列：整组只出现一次（rowspan = 该组全部行数）
            if (blockNo === 0) {
              tableHtml += `<td rowspan="${perSkuRows.length}" style="font-weight:bold;">${escapeHtml(group.customer_name)}</td>`
            }
            const line = row.cellLines[0]
            tableHtml += `<td rowspan="${block.length}">${escapeHtml(line?.name || '')}</td>`
            tableHtml += `<td rowspan="${block.length}">${escapeHtml(fmtQty(line?.qty ?? 0))}</td>`
            tableHtml += `<td rowspan="${block.length}">${escapeHtml(fmtQty(line?.spare ?? 0))}</td>`
          }
          if (row.noBom) {
            tableHtml += '<td colspan="6" style="color:#8e8e93;">无 BOM 明细</td>'
            tableHtml += '</tr>'
            return
          }
          const rowRate = row.coord
            ? (fabricRates?.[gi]?.[row.coord.si]?.[row.coord.fi] ?? lossRate)
            : lossRate
          if (row.isFirstSupplierRow) {
            tableHtml += `<td rowspan="${row.supplierRowSpan}" style="font-weight:bold;">${escapeHtml(row.supplierName)}</td>`
          }
          tableHtml += `<td>${escapeHtml(row.materialName)}</td>`
          tableHtml += `<td>${escapeHtml(row.specification)}</td>`
          tableHtml += `<td>${escapeHtml(String(rowRate))}</td>`
          tableHtml += `<td>${ceilMagnifiedByLossRate(row.baseQuantity, rowRate)}</td>`
          tableHtml += `<td>${escapeHtml(row.unit)}</td>`
          tableHtml += '</tr>'
        })
        blockNo++
      }

      // 差异对照块：与屏幕同源（打印件不能对差异保持沉默）。
      // 列数必须仍是 10：标签跨「客户/产品名称/订单数量/备品数量」4 列 + 供应商 + 物料 5 列。
      const diffs = computeQuantityDiff(group, perSkuRows)
      if (diffs.length > 0) {
        const detail = diffs
          .map((d) => `${d.materialName}（推算 ${d.perSku} / 实际 ${d.stored}）`)
          .join('、')
        tableHtml += `<tr><td colspan="10" style="background:#fffaf0;color:#7a4a00;">⚠ 本条「实际下单」含手工调整，与上方按 BOM 推算不一致：${escapeHtml(detail)}</td></tr>`
        const storedRowCount = (group.suppliers || []).reduce((n, s) => n + (s.fabrics?.length || 0), 0)
        ;(group.suppliers || []).forEach((supplier, si) => {
          const fabrics = supplier.fabrics || []
          fabrics.forEach((fabric, fi) => {
            const fRate = fabricRates?.[gi]?.[si]?.[fi] ?? lossRate
            tableHtml += '<tr>'
            if (si === 0 && fi === 0) {
              tableHtml += `<td colspan="4" rowspan="${storedRowCount}" style="font-weight:bold;background:#fffaf0;color:#7a4a00;">实际下单（含手工调整）</td>`
            }
            if (fi === 0) {
              tableHtml += `<td rowspan="${fabrics.length}" style="background:#fffaf0;">${escapeHtml(supplier.supplier_name)}</td>`
            }
            tableHtml += `<td style="background:#fffaf0;">${escapeHtml(fabric.fabric_name)}</td>`
            tableHtml += `<td style="background:#fffaf0;">${escapeHtml(fabric.specification || '')}</td>`
            tableHtml += `<td style="background:#fffaf0;">${escapeHtml(String(fRate))}</td>`
            tableHtml += `<td style="background:#fffaf0;">${ceilMagnifiedByLossRate(parseFloat(String(fabric.quantity)) || 0, fRate)}</td>`
            tableHtml += `<td style="background:#fffaf0;">${escapeHtml(fabric.unit || '')}</td>`
            tableHtml += '</tr>'
          })
        })
      }
      return   // 该组已处理完，跳过订单级分支
    }
```

> **实现要点**（上面的代码已完整，照抄即可）：
> ① 每行都以 `tableHtml += '<tr>'` 开头、`+= '</tr>'` 收尾，**不要**在半途拼接闭合标签；
> ② 客户列只在**第一块的 i===0** 渲染（`blockNo === 0`），rowspan = 整组行数——若误写成「每块都渲染」，表头会与数据错位；
> ③ 差异行的列数必须凑满 **10 列**：标签 `colspan="4"` + 供应商(块内 rowspan) + 物料/规格/损耗率/数量/单位；
> ④ `noBom` 占位行 `colspan="6"`（供应商 + 之后 5 列）。

- [ ] **Step 4: 跑测试确认通过**

Run: `command npx vitest run src/test/useSummaryModal.perSkuPrint.test.ts src/test/useSummaryModal.test.ts src/test/SummaryModal.multisku.test.ts`
Expected: PASS（含既有打印/导出用例——**E3 的零回归在这里被真实校验**）

- [ ] **Step 5: 提交**

```bash
command git add frontend-vite/src/views/purchase/composables/useSummaryModal.ts frontend-vite/src/test/useSummaryModal.perSkuPrint.test.ts
command git commit -m "feat(purchase): 打印/导出按 SKU 展开，并与屏幕同源（含差异对照块）" -m "屏幕按 SKU 展开展示后，打印与导出必须同结构，否则会出现「屏幕上有、打印没有」——差异对照块尤其不能只在屏幕出现（那等于对打印件隐瞒差异）。无 materials 的单据走原路径，输出逐字不变（零回归）。" -m "Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 全量门禁与零回归验证

**Files:**
- Modify: `docs/purchase/汇总下单按SKU展开物料明细设计方案.md`（追加「实施状态」小节）
- 不改任何代码

- [ ] **Step 1: 前端全量**

Run: `command npx vitest run`
Expected: 全绿（既有 1069 + 本计划新增用例）。**特别注意**：`SummaryModal.multisku`、`QaAdversarial.beileSync`、`useSummaryModal`、`SummaryFactoryTab.spareColumn` 这几条锁定列位与回退形态，必须全绿。

- [ ] **Step 2: 前端其它门禁**

Run: `command npm run type-check && command npm run lint && command npm run check:api && command npm run check:routes`
Expected: type-check 无错；lint 0 error（既有 warning 不计）；两条检查通过

- [ ] **Step 3: 后端相关回归 + 门禁**

Run: `python -m pytest fastapi_app/tests/services/test_factory_summary_multisku.py fastapi_app/tests/services/test_factory_order_summary_spare_rate.py fastapi_app/tests/test_purchase_center.py -q`
Expected: 全绿

Run: `python scripts/quality_gate.py && command ruff check . && mypy`
Expected: 门禁 PASS；ruff 无新增（全仓存量告警不计）；mypy Success（本机 `mypy` 可能需 `PYTHONUTF8=1`）

- [ ] **Step 4: 文档同步**

在 `docs/purchase/汇总下单按SKU展开物料明细设计方案.md` 的 `> 性质：**纯设计文档，不修改任何代码**` 一行之后插入：

```markdown
> **实施状态（2026-09-30）**：已实施。后端见 `fastapi_app/services/purchase/_factory.py`
> （`_sku_material_rows` + 装配）；前端见 `composables/perSkuRows.ts` 与
> `components/SummaryFactoryTab.vue`、`SummaryDiffBlock.vue`。落库结构与迁移零改动。
```

- [ ] **Step 5: 提交**

```bash
command git add "docs/purchase/汇总下单按SKU展开物料明细设计方案.md"
command git commit -m "docs(purchase): 标记按 SKU 展开物料明细方案已实施" -m "方案文档补实施状态与代码落点，便于后续追溯「设计 → 实现」对应关系。" -m "Co-Authored-By: Claude Sonnet 5 (1M context) <noreply@anthropic.com>"
```

---

## 附录：本计划的关键判断与理由

| 判断 | 理由 |
| --- | --- |
| 按 SKU 的物料行映射回**落库坐标**，而不是另起一套按 SKU 的状态 | 同一物料在库里只有一行（跨 SKU 共用）⇒ 率/数量编辑、自动落库、串行化队列**全部原样复用**；「同物料跨 SKU 联动」成为坐标的必然结果，不需要任何联动代码 |
| 后端只给**基准量**（不含损耗加放） | 加放必须随用户改率**实时**变化，只有前端能做；与今天订单级行的做法同源 |
| 既有 `suppliers/fabrics` 一个字段不动 | 它同时是「实际下单」对照的数据源与编辑态的定位键（`item_ids`）；动它会同时破坏对照与保存 |
| 差异用**基准量**比（不是加放后） | 加放依赖前端实时率，把它带进比对会让「差异」随改率抖动；基准量的差异只可能来自手工改数量——正是要暴露的东西 |
| 客户列 rowspan 在组件内统计、不改 Task 2 的接口 | Task 2 的接口已被 Task 3/5 消费并冻结；组级统计是纯展示关注点，放组件里最小 |
| 只读行（`coord=null`）必须带 `title` 说明 | 否则用户看到「改了没反应」会当成 bug；这是 spec §4.3/§5 的可见性要求 |
| 不做落库结构改造 | 会波及供应商汇总、来料登记、导出与全部历史数据；本方案用「推算 + 差异对照」在零迁移下达成同一目标 |

## 范围边界（本计划只做 P0）

spec §7 的分期里，**P0 = 本计划的 Task 1–5 + Task 6 的验证**；以下**不在本计划内**（需要时另开计划）：

- **P1**：编辑态提示文案打磨、极端多 SKU 单的打印版面优化（横向 / 缩字号）——待实测后再定；
- spec 明确排除项：落库结构改造、按 SKU 的率/数量存储、供应商页签改造。

本计划**不包含**任何生产部署动作（构建 dist、重启服务）——那是用户侧的独立决定（见 spec §7 与仓库 AGENTS.md 的生产纪律）。
