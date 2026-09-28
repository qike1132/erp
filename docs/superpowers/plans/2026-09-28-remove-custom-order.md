# 移除定制订单与国家功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「定制订单」订单类型与「国家」维度从 `/customer-order`、`/stock` 及其后端与数据库中彻底移除。

**Architecture:** 自底向上按层剥离。先改后端 schema / service / endpoint（此时模型字段仍在，行为已无定制分支），再删 ORM 模型字段，最后单独一个迁移 commit 删除 DB 列与 `country` 表。前端在后端稳定后同步删除。改动一次性落地、按层分 commit，使代码问题与迁移问题可分别回滚。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Alembic + PostgreSQL（asyncpg）；Vue 3 + TypeScript + Pinia + Vue Query + Vitest + vue-tsc。

**Spec:** `docs/superpowers/specs/2026-09-28-remove-custom-order-design.md`

## Global Constraints

- 不新增订单类型抽象，不保留「类型」字段作为未来扩展点。
- 不做历史 custom 数据迁移（实测为 0 条）。
- 不顺带重构 purchase、pattern-room、supplier、case、shipment 等无关模块。
- Excel 批量导入若仍带「国家」列：**静默忽略**，不解析、不报错。
- 迁移沿用本仓库空库守卫约定：`upgrade()` / `downgrade()` 开头调用 `migrations._legacy_base_guard.base_schema_absent()`，基础 schema 缺失时直接 `return`。
- 迁移 `revision = 'pg_standalone_055_remove_custom_order_country'`，`down_revision = 'pg_standalone_054'`。
- 工作区存在与本任务无关的未提交改动（`frontend-vite/src/views/purchase/*`、`pattern-room/*`、`supplier/*`、`server_manager.py`、`tests/test_server_manager_*`、`sentry.ts` 等）。全程**不得** add / commit / stash / revert 这些文件；每次 `git add` 只列本任务改动的文件。
- 环境说明：本机 shell 中 `git` / `npm` / `cat` / `head` / `curl` 等命令被 `_lc` 别名破坏，需写成 `command git`、`command npm`、`command cat` 形式。下文命令均按此写。
- 提交信息末尾附 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`。

## Review Focus

Spec 已声明要求但需要额外测试钉住的行为，按最可能出问题的顺序：

1. **Excel 导入含「国家」列** → 必须静默忽略、导入成功，绝不报错或中断（Task 5）。
2. **`/aux/available-shipment` 不带 `order_type`/`country` 调用** → 返回总可出货量且 HTTP 200，不得 422/500（Task 4）。
3. **`/aux/countries` 已删除** → 调用返回 404（Task 4）。
4. **库存页 `总订单` 口径** → 在「有订单 + 有备货」数据下，`总订单 = 订单余量 + 备货量`（Task 6）。
5. **历史 regular 订单在删列后可正常列表查询**（Task 8 + Task 9 联合验证）。

---

### Task 1: 后端 schema 去除 order_type / country

**Files:**
- Modify: `fastapi_app/schemas/order.py`
- Modify: `fastapi_app/schemas/stock.py`
- Modify: `fastapi_app/schemas/staging.py`
- Test: `fastapi_app/tests/` 与 `tests/` 下断言 schema 字段的用例

**Interfaces:**
- Consumes: 无
- Produces: `OrderCreate` / `OrderUpdate` / `OrderResponse` 等不再含 `order_type`、`country`；`StockItemBase` 不再含 `order_type`、`country`；staging schema 不再含同名两字段。后续 Task 4 的 `AvailableShipmentResponse` 仍含 `regular_available`，本任务**不**动它。

- [ ] **Step 1: 写失败测试**

在 `fastapi_app/tests/schemas/test_order_schema.py`（不存在则新建）加：

```python
import pytest
from pydantic import ValidationError

from fastapi_app.schemas.order import OrderCreate


def test_order_create_has_no_order_type_field():
    assert 'order_type' not in OrderCreate.model_fields


def test_order_create_has_no_country_field():
    assert 'country' not in OrderCreate.model_fields


def test_order_create_ignores_legacy_custom_payload():
    # 旧客户端仍可能传这两个字段：Pydantic 默认忽略未知字段，不应报错
    payload = {'product_id': 1, 'customer': '客户A', 'quantity': 5,
               'order_type': 'custom', 'country': '日本'}
    obj = OrderCreate(**payload)
    assert obj.quantity == 5
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest fastapi_app/tests/schemas/test_order_schema.py -v`
Expected: FAIL（`'order_type' in OrderCreate.model_fields` 为真）

- [ ] **Step 3: 删除字段与校验**

`fastapi_app/schemas/order.py`：删除以下内容（`command grep -n "order_type\|country" fastapi_app/schemas/order.py` 定位）

- `OrderCreate` 中 `order_type` 字段定义（约 L15）与 `country` 字段定义（约 L16）
- `OrderCreate` 的 `@model_validator` 中 `if self.order_type == 'custom' and not self.country: raise ValueError('定制订单必须填写国家名称')`（约 L20）
- `OrderUpdate` 中 `order_type`（约 L30）、`country`（约 L31）字段与对应 validator（约 L35）
- `OrderResponse` 中 `order_type = "regular"`（约 L48）、`country: str | None = None`（约 L49）
- 另一处 create/response 模型中的 `order_type`（约 L59）、`country`（约 L60）与 validator（约 L67）
- `order_type`（约 L83）、`country`（约 L84）

`fastapi_app/schemas/stock.py`：删除 `StockItemBase` 的 `order_type`（约 L56）、`country`（约 L57）字段；删掉 L68 附近关于「order_type/country 不可编辑」的注释段落。

`fastapi_app/schemas/staging.py`：删除 `order_type`（约 L89）、`country`（约 L90）字段。

- [ ] **Step 4: 运行确认通过**

Run: `command python -m pytest fastapi_app/tests/schemas/test_order_schema.py -v`
Expected: PASS

- [ ] **Step 5: 跑相关既有测试**

Run: `command python -m pytest tests/test_order.py fastapi_app/tests/ -x -q`
Expected: 断言「定制订单必须填写国家名称」的用例 FAIL——这是预期的，在 Task 3 处理。本步骤只记录失败清单。

- [ ] **Step 6: Commit**

```bash
command git add fastapi_app/schemas/order.py fastapi_app/schemas/stock.py fastapi_app/schemas/staging.py fastapi_app/tests/schemas/test_order_schema.py
command git commit -m "refactor(order): schema 层移除 order_type/country 字段与定制订单校验"
```

---

### Task 2: 可出货量计算去除类型分支

**Files:**
- Modify: `fastapi_app/shared/shipment_calc.py`
- Modify: `fastapi_app/services/inventory_service.py`
- Test: `tests/test_shipment_limit.py`

**Interfaces:**
- Consumes: Task 1 的 schema（不直接依赖）
- Produces: `build_shipment_summary(orders, shipped_map) -> dict` 返回键变为
  `{order_quantity, shipped_quantity, available_quantity, orders}`（去掉 `regular_available`、`custom_available`；`orders` 明细项去掉 `order_type`、`country`）。
  `calculate_available_shipment_quantity(db, product_id, customer) -> dict` 去掉 `order_type`、`country` 参数。

- [ ] **Step 1: 写失败测试**

在 `tests/test_shipment_calc.py`（不存在则新建）加：

```python
from types import SimpleNamespace

from fastapi_app.shared.shipment_calc import build_shipment_summary


def _order(oid, qty):
    return SimpleNamespace(id=oid, order_no=f'NO{oid}', quantity=qty)


def test_summary_has_no_regular_custom_split():
    result = build_shipment_summary([_order(1, 10)], {1: 3})
    assert result['order_quantity'] == 10
    assert result['available_quantity'] == 7
    assert 'regular_available' not in result
    assert 'custom_available' not in result


def test_order_detail_has_no_type_or_country():
    result = build_shipment_summary([_order(1, 10)], {})
    assert result['orders'][0] == {
        'order_id': 1, 'order_no': 'NO1', 'quantity': 10,
        'shipped': 0, 'available': 10,
    }


def test_empty_orders_shape():
    assert build_shipment_summary([], {}) == {
        'order_quantity': 0, 'shipped_quantity': 0,
        'available_quantity': 0, 'orders': [],
    }
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_shipment_calc.py -v`
Expected: FAIL（`regular_available` 仍在返回字典中）

- [ ] **Step 3: 改写 shipment_calc**

用以下内容整体替换 `fastapi_app/shared/shipment_calc.py` 的函数体（保留文件头 docstring 与 import）：

```python
def build_shipment_summary(orders: Sequence[Order], shipped_map: dict[int, int]) -> dict:
    """根据订单列表与已出货映射，组装可出货量汇总与订单明细。

    Args:
        orders: 已按 order_date 升序的订单列表（可能为空）
        shipped_map: {order_id: 净出货量}（已扣除退货，且排除入库抵扣）

    Returns:
        dict: { order_quantity, shipped_quantity, available_quantity, orders }
    """
    if not orders:
        return {
            'order_quantity': 0,
            'shipped_quantity': 0,
            'available_quantity': 0,
            'orders': [],
        }

    total_order_quantity = 0
    order_details = []

    for order in orders:
        # TODO(multi-sku-order): 遍历累加 order.quantity 在多 SKU 下语义变更，
        # 待后续 spec 改造为遍历 order.items；当前依赖兼容值。
        total_order_quantity += order.quantity
        non_deduction_shipped = shipped_map.get(order.id, 0)

        order_details.append({
            'order_id': order.id,
            'order_no': order.order_no,
            'quantity': order.quantity,
            'shipped': non_deduction_shipped,
            'available': order.quantity - non_deduction_shipped,
        })

    total_shipped = sum(shipped_map.values())
    available_quantity = max(0, total_order_quantity - total_shipped)

    return {
        'order_quantity': total_order_quantity,
        'shipped_quantity': total_shipped,
        'available_quantity': available_quantity,
        'orders': order_details,
    }
```

- [ ] **Step 4: 改写 inventory_service**

`fastapi_app/services/inventory_service.py`：

- 删除 `REGULAR_ORDER_TYPE_ALIASES`（L24）与 `normalize_order_type()`（L27-31）
- 删除文件头 docstring 中提及 `Order.order_type/Order.country` 的 TODO 段落（L7-10）
- `calculate_available_shipment_quantity` 签名改为：

```python
async def calculate_available_shipment_quantity(
    db: AsyncSession, product_id: int, customer: str
) -> dict:
```

- 删除函数体内 `order_type = normalize_order_type(order_type)` 一行
- `where_clause` 中删除 `if order_type:` 整个条件块（L56-62），保留 `product_id`/`customer`/`is_deleted` 三个条件

- [ ] **Step 5: 运行确认通过**

Run: `command python -m pytest tests/test_shipment_calc.py tests/test_shipment_limit.py -v`
Expected: PASS（`test_shipment_limit.py` 中若有用例传 `order_type`/`country`，同步骤删除这些实参）

- [ ] **Step 6: Commit**

```bash
command git add fastapi_app/shared/shipment_calc.py fastapi_app/services/inventory_service.py tests/test_shipment_calc.py tests/test_shipment_limit.py
command git commit -m "refactor(stock): 可出货量计算移除订单类型与国家维度"
```

---

### Task 3: 出库 / 订单 / 审批服务去除定制校验

**Files:**
- Modify: `fastapi_app/services/stock_out_service.py`
- Modify: `fastapi_app/services/order/commands.py`
- Modify: `fastapi_app/services/staging/stockout.py`
- Modify: `fastapi_app/services/approval_service.py`
- Test: `tests/test_order.py`、`tests/test_stock.py`、`fastapi_app/tests/test_batch_stockout.py`

**Interfaces:**
- Consumes: Task 2 的 `calculate_available_shipment_quantity(db, product_id, customer)`
- Produces: `create_stockout(...)` 等不再接受/透传 `order_type`、`country`；`order/commands.py` 不再抛「定制订单必须填写国家名称」。

- [ ] **Step 1: 写失败测试**

在 `tests/test_custom_order_removed.py`（新建）加：

```python
import pytest


def test_no_service_raises_custom_country_error():
    """全量源码中不应再出现定制订单国家校验文案。"""
    import pathlib

    root = pathlib.Path('fastapi_app')
    hits = []
    for path in root.rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        if '定制订单必须填写国家名称' in text:
            hits.append(str(path))
    assert hits == [], f'仍存在定制订单校验: {hits}'
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_custom_order_removed.py -v`
Expected: FAIL，列出仍含该文案的文件（预期含 `stock_out_service.py`、`order/commands.py`）

- [ ] **Step 3: 删除校验与参数**

`fastapi_app/services/stock_out_service.py`：

- 删除文件头 docstring 中提及 `order_type`/`country` 的说明（L8 附近）
- 删除 L40-41 的 `if ...: raise ValueError('定制订单必须填写国家名称！')` 校验块
- L41 与 L289 两处调用改为 `await stock_service.calculate_available_shipment_quantity(db, product_id, customer)`
- 删除 L237 附近 `errors_map[idx] = '定制订单必须填写国家名称'` 分支
- 删除函数签名与内部对 `order_type` / `country` 的接收与透传

`fastapi_app/services/order/commands.py`：

- 删除 docstring 中「定制订单必须填写国家名称」（L99 附近）
- 删除 L102 附近的 `raise ValueError('定制订单必须填写国家名称')`
- 删除对 `order_type` / `country` 的赋值与使用

`fastapi_app/services/staging/stockout.py`：删除 `order_type` / `country` 的处理与存储。

`fastapi_app/services/approval_service.py`：删除文件头 TODO 中提及 `order.order_type`/`order.country` 的段落，以及函数体中对这两个属性的读写。

- [ ] **Step 4: 运行确认通过**

Run: `command python -m pytest tests/test_custom_order_removed.py -v`
Expected: PASS

- [ ] **Step 5: 更新既有测试**

- `tests/test_order.py`：删除 `test_..._custom_..._country` 两个用例（L228 起）中「定制订单未填写国家」与「定制订单 - 填写国家」；保留常规订单用例并去掉 `order_type`/`country` 实参
- `tests/test_stock.py`：删除 L368 附近「定制订单必须填写国家名称」断言；删除 L127 附近「定制订单入库」用例
- `fastapi_app/tests/test_batch_stockout.py`：删除 `test_custom_order_with_country`、`test_custom_order_without_country`；`_make_stockout_data` 去掉 `order_type`/`country` 形参与其 payload 键

- [ ] **Step 6: 跑测试**

Run: `command python -m pytest tests/test_order.py tests/test_stock.py fastapi_app/tests/test_batch_stockout.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
command git add fastapi_app/services/stock_out_service.py fastapi_app/services/order/commands.py fastapi_app/services/staging/stockout.py fastapi_app/services/approval_service.py tests/test_custom_order_removed.py tests/test_order.py tests/test_stock.py fastapi_app/tests/test_batch_stockout.py
command git commit -m "refactor(stock): 出库/订单/审批服务移除定制订单国家校验"
```

---

### Task 4: 国家接口删除与 available-shipment 参数收敛

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/auxiliary.py`
- Modify: `fastapi_app/services/auxiliary_service.py`
- Modify: `fastapi_app/schemas/` 中 `AvailableShipmentResponse` 所在文件
- Test: `fastapi_app/tests/test_auxiliary.py`、`fastapi_app/tests/services/test_auxiliary_service.py`

**Interfaces:**
- Consumes: Task 2 的三参 `calculate_available_shipment_quantity`
- Produces: `GET /aux/available-shipment?product_id=&customer=` 返回
  `{order_quantity, shipped_quantity, available_quantity}`；`/aux/countries` 全部路由不存在（404）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_available_shipment_contract.py`（新建）加：

```python
import pytest


def test_available_shipment_accepts_without_order_type():
    """接口签名不应再声明 order_type / country 查询参数。"""
    import inspect

    from fastapi_app.api.v1.endpoints.auxiliary import available_shipment

    params = set(inspect.signature(available_shipment).parameters)
    assert 'order_type' not in params
    assert 'country' not in params
    assert {'product_id', 'customer'} <= params


def test_country_routes_removed():
    from fastapi_app.api.v1.endpoints.auxiliary import router

    paths = {r.path for r in router.routes}
    assert not any('countries' in p for p in paths), f'仍存在国家路由: {paths}'
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_available_shipment_contract.py -v`
Expected: FAIL（`order_type` 仍在签名中）

- [ ] **Step 3: 收敛接口**

`fastapi_app/api/v1/endpoints/auxiliary.py`：

- `available_shipment` 删除 `order_type: str | None = Query(...)`（L277）与 `country: str | None = Query(...)`（L278）两个参数
- docstring 改为：`"""获取可出货量（按客户+产品维度）。"""`，删除 `order_type 参数用于逻辑隔离` 一句（L285）
- 提前返回改为：

```python
    if not product_id or not customer.strip():
        return {'order_quantity': 0, 'shipped_quantity': 0, 'available_quantity': 0}
```

- 调用改为 `await calculate_available_shipment_quantity(db, product_id, customer)`（L291-293）
- 返回体改为（删除 `regular_available` / `custom_available`）：

```python
    return {
        'order_quantity': shipment_info['order_quantity'],
        'shipped_quantity': shipment_info['shipped_quantity'],
        'available_quantity': shipment_info['available_quantity'],
    }
```

- 删除 `@router.get("/countries")`、`@router.post("/countries")`、`@router.delete("/countries/{country_id}")` 三个路由及其处理函数（L468-485 附近，含 `create_country` / `delete_country` 端点）
- `BatchOrderItem`（L359-374）：删 `order_type`（L366）、`country`（L367）与 `validate_custom_order` validator（L370-374）
- `BatchStockInItem`（L376-383）：删 `order_type`（L381）、`country`（L382）
- `BatchStockOutItem`（L385-392）：删 `order_type`（L390）、`country`（L391）

`fastapi_app/services/auxiliary_service.py`：删除 `get_country_by_name`（L231）、`get_country_by_id`（L237）、`create_country`（L267）、`delete_country`（L292）及其对 `Country` 的导入。

`AvailableShipmentResponse`：删除 `regular_available`、`custom_available` 两个字段（`command grep -rn "regular_available" fastapi_app/` 定位）。

- [ ] **Step 4: 运行确认通过**

Run: `command python -m pytest tests/test_available_shipment_contract.py -v`
Expected: PASS

- [ ] **Step 5: 更新既有测试**

- `fastapi_app/tests/test_auxiliary.py`：删除国家接口用例；`test_available_shipment_no_params` 断言改为不含 `regular_available`/`custom_available`
- `fastapi_app/tests/services/test_auxiliary_service.py`：删除 `# create_country`、`# delete_country` 两节及其全部用例（L205-262）

- [ ] **Step 6: 跑测试**

Run: `command python -m pytest fastapi_app/tests/test_auxiliary.py fastapi_app/tests/services/test_auxiliary_service.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
command git add fastapi_app/api/v1/endpoints/auxiliary.py fastapi_app/services/auxiliary_service.py fastapi_app/schemas tests/test_available_shipment_contract.py fastapi_app/tests/test_auxiliary.py fastapi_app/tests/services/test_auxiliary_service.py
command git commit -m "refactor(aux): 删除国家管理接口并收敛可出货量接口参数"
```

---

### Task 5: 批量导入忽略「国家」列

**Files:**
- Modify: `fastapi_app/services/batch_import_service.py`
- Modify: `fastapi_app/services/batch_import_core.py`
- Modify: `fastapi_app/services/batch_import_parser.py`
- Test: `tests/test_batch_import_country_ignored.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: 导入路径不再产出 `order_type` / `country` 值；`_parse_country_value` 不再存在。

- [ ] **Step 1: 写失败测试**

```python
import pytest


def test_parser_has_no_country_helper():
    import fastapi_app.services.batch_import_parser as parser

    assert not hasattr(parser, '_parse_country_value')


def test_rows_with_country_column_still_import():
    """带「国家」列的 Excel 行必须被正常接受（静默忽略该列）。"""
    import pathlib

    for name in ('batch_import_service.py', 'batch_import_core.py'):
        text = pathlib.Path('fastapi_app/services', name).read_text(encoding='utf-8')
        assert "'国家'" not in text, f'{name} 仍在解析国家列'
        assert 'order_type_parsed' not in text, f'{name} 仍在推导 order_type'
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_batch_import_country_ignored.py -v`
Expected: FAIL（`_parse_country_value` 仍存在）

- [ ] **Step 3: 删除国家解析**

`fastapi_app/services/batch_import_parser.py`：删除 `_parse_country_value` 函数（L265-276）。

`fastapi_app/services/batch_import_service.py`：

- 删除 L549-551 的 `country_val` / `country_parsed` / `order_type_parsed` 三行
- L583 附近调用去掉 `order_type=order_type_parsed, country=country_parsed or None` 两个实参
- L752 附近从 `import` 列表移除 `_parse_country_value`

`fastapi_app/services/batch_import_core.py`：

- 删除 L504-509 的 `country_val` 解析与 `order_type_parsed` 推导
- L543 附近调用去掉 `order_type=`、`country=` 实参

- [ ] **Step 4: 运行确认通过**

Run: `command python -m pytest tests/test_batch_import_country_ignored.py -v`
Expected: PASS

- [ ] **Step 5: 跑导入相关测试**

Run: `command python -m pytest tests/ -q -k "import"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
command git add fastapi_app/services/batch_import_service.py fastapi_app/services/batch_import_core.py fastapi_app/services/batch_import_parser.py tests/test_batch_import_country_ignored.py
command git commit -m "refactor(import): 批量导入静默忽略国家列并停止推导订单类型"
```

---

### Task 6: 库存聚合去除国家与定制维度

**Files:**
- Modify: `fastapi_app/services/stock_inventory_service.py`
- Test: `tests/test_multi_sku_inventory_stats.py`、`tests/test_inventory_totals.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces:
  - `get_inventory_paginated(db, search_customer='', search_product='', page=1, per_page=50) -> dict`（去掉 `country` 参数）
  - 返回体去掉 `all_countries`；`inventory_data` 每项去掉 `country_orders`
  - `get_stockins` / `get_stockouts` 去掉 `order_type` 参数
  - `get_stock_overview_stats(db) -> {order_quantity, stockin_quantity}`（去掉 `order_regular_quantity` / `order_custom_quantity`）

- [ ] **Step 1: 写失败测试**

`tests/test_inventory_totals.py`：

```python
from fastapi_app.services import stock_inventory_service as svc


def _empty_clauses() -> dict:
    return {
        'si_pid': '', 'si_cust': '', 'so_pid': '', 'so_cust': '',
        'oi_or_o_pid': '', 'o_cust': '', 'o_not_deleted': '',
        'prod_pid': '', 'pso_pid': '', 'sub_pid': '',
    }


def test_no_country_helpers_remain():
    assert not hasattr(svc, '_parse_country_data')
    assert not hasattr(svc, '_get_all_countries')


def test_inventory_paginated_has_no_country_param():
    import inspect

    params = set(inspect.signature(svc.get_inventory_paginated).parameters)
    assert 'country' not in params


def test_cte_has_no_custom_or_country_sql():
    sql = str(svc._build_inventory_cte_sql(_empty_clauses()))
    assert 'custom' not in sql
    assert 'country_agg' not in sql
    assert 'country_data' not in sql


def test_cte_total_order_is_order_plus_stockin():
    """总订单 = 订单余量 + 备货量（不再含定制余量）。"""
    sql = str(svc._build_inventory_cte_sql(_empty_clauses()))
    assert 'SUM(f.remaining) OVER() AS sum_order' in sql
    assert 'SUM(f.stockin_qty) OVER() AS sum_stockin' in sql
    assert 'remaining_cus' not in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_inventory_totals.py -v`
Expected: FAIL

- [ ] **Step 3: 改写 CTE**

`fastapi_app/services/stock_inventory_service.py` 的 `_build_inventory_cte_sql(clauses: dict) -> TextClause`（去掉 `country` 形参），SQL 用以下版本替换：

```python
    cte_sql = text(f"""
WITH stockin_agg AS (
    SELECT si.product_id, si.customer,
           SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty,
           1 AS has_stockin
    FROM stock_in si
    LEFT JOIN (
        SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed
        FROM stock_out WHERE stockin_id IS NOT NULL{c['sub_pid']}
        GROUP BY stockin_id
    ) sub ON sub.stockin_id = si.id
    WHERE 1=1{c['si_pid']}{c['si_cust']}
    GROUP BY si.product_id, si.customer
),
stockout_agg AS (
    SELECT so.product_id, so.customer,
        SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty,
        SUM(CASE WHEN so.order_id IS NOT NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS order_stockout_qty
    FROM stock_out so
    WHERE so.stockin_id IS NULL{c['so_pid']}{c['so_cust']}
    GROUP BY so.product_id, so.customer
),
order_agg AS (
    -- 多 SKU：按 OrderItem 维度聚合；无明细订单（批量导入兼容路径）回退订单级字段
    SELECT COALESCE(oi.product_id, o.product_id) AS product_id,
        o.customer,
        SUM(COALESCE(oi.quantity, o.quantity)) AS order_qty,
        1 AS has_order
    FROM "order" o
    LEFT JOIN order_item oi ON oi.order_id = o.id
    WHERE 1=1{c['oi_or_o_pid']}{c['o_cust']}{c['o_not_deleted']}
    GROUP BY COALESCE(oi.product_id, o.product_id), o.customer
),
production_agg AS (
    SELECT product_id, SUM(quantity) AS production_qty
    FROM daily_production_record
    WHERE product_id IS NOT NULL{c['prod_pid']}
    GROUP BY product_id
),
product_stockout_total AS (
    SELECT product_id, SUM(quantity - returned_quantity) AS total_stockout_qty
    FROM stock_out
    WHERE 1=1{c['pso_pid']}
    GROUP BY product_id
),
merged AS (
    SELECT
        COALESCE(si.product_id, so.product_id, od.product_id) AS product_id,
        COALESCE(si.customer, so.customer, od.customer) AS customer,
        COALESCE(si.stockin_qty, 0) AS stockin_qty,
        CASE WHEN si.product_id IS NOT NULL THEN true ELSE false END AS has_stockin,
        COALESCE(so.direct_stockout_qty, 0) AS direct_stockout_qty,
        COALESCE(so.order_stockout_qty, 0) AS order_stockout_qty,
        COALESCE(od.order_qty, 0) AS order_qty,
        CASE WHEN od.product_id IS NOT NULL THEN true ELSE false END AS has_order
    FROM stockin_agg si
    FULL OUTER JOIN stockout_agg so ON si.product_id = so.product_id AND si.customer = so.customer
    FULL OUTER JOIN order_agg od
        ON COALESCE(si.product_id, so.product_id) = od.product_id
        AND COALESCE(si.customer, so.customer) = od.customer
),
inventory_calc AS (
    SELECT m.*,
        GREATEST(0, m.order_qty - m.direct_stockout_qty - m.order_stockout_qty) AS remaining,
        m.stockin_qty + GREATEST(0, m.order_qty - m.direct_stockout_qty - m.order_stockout_qty) AS total_qty
    FROM merged m
),
filtered AS (
    SELECT ic.*, p.name AS product_name, p.barcode AS product_barcode,
        COALESCE(pa.production_qty, 0) AS production_qty,
        COALESCE(pst.total_stockout_qty, 0) AS total_product_stockout,
        COALESCE(pa.production_qty, 0) - COALESCE(pst.total_stockout_qty, 0) AS available_stock
    FROM inventory_calc ic
    JOIN product p ON p.id = ic.product_id
    LEFT JOIN production_agg pa ON pa.product_id = ic.product_id
    LEFT JOIN product_stockout_total pst ON pst.product_id = ic.product_id
    WHERE (ic.has_stockin OR ic.has_order) AND ic.total_qty > 0
)
SELECT f.product_id, f.customer, f.product_name, f.product_barcode,
    f.stockin_qty, f.direct_stockout_qty, f.order_stockout_qty,
    f.order_qty, f.remaining, f.total_qty,
    f.production_qty, f.available_stock,
    COUNT(*) OVER() AS total_count,
    SUM(f.stockin_qty) OVER() AS sum_stockin,
    SUM(f.remaining) OVER() AS sum_order,
    SUM(f.total_qty) OVER() AS sum_stock
FROM filtered f
ORDER BY f.customer, f.product_name
LIMIT :limit OFFSET :offset
""")  # nosec B608 - clauses 为模块级常量，值通过绑定参数传递
    return cte_sql
```

- [ ] **Step 4: 改写格式化与调用方**

- `_format_inventory_rows(rows) -> tuple[list, int, int, int, int, int]`：去掉 `all_countries`；`country_data` 相关行删除；`so_total` 改为 `int(row.direct_stockout_qty) + int(row.order_stockout_qty)`；`remaining` 取代 `remaining_reg`；行字典去掉 `'country_orders': country_data,`
- `_empty_inventory_response`：删除 `all_countries` 形参与返回键
- `get_inventory_paginated`：去掉 `country` 形参、缓存 key 的 `country` 段、`params['country']` 赋值、传给 `_build_inventory_cte_sql` 的第二实参，以及返回值中的 `'all_countries'`；**同时**把 L371-372 的七元解包
  `inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries, total_available_stock = _format_inventory_rows(rows)`
  改为六元（删去 `all_countries`）
- 删除 `_parse_country_data`（L640）、`_get_all_countries`（L652）、`_build_country_data_dict`（L737）
- `get_inventory()`（L283）与 `_build_inventory_query_clauses`（L718）、`_merge_inventory_rows`（L747）：删除 `country`/`custom` 相关字段与聚合
- `get_stockins`（L63）与 `get_stockouts`（L141）：去掉 `order_type` 形参、`if order_type:` 条件块（`get_stockouts` 中连带删除 `needs_order_join` 与该 JOIN）、缓存 key 中的 `ot:` 段；返回行去掉 `'order_type'`、`'country'` 键
- `get_stock_overview_stats`（L819）改为：

```python
async def get_stock_overview_stats(db: AsyncSession) -> dict:
    """库存统计聚合（自 stock.py 端点下沉）：订单数量与备货数量。

    多 SKU：按 OrderItem 维度统计；无明细订单（批量导入兼容路径）回退
    订单级字段（COALESCE），单 SKU 订单行为与旧实现一致。
    """
    item_qty = func.coalesce(OrderItem.quantity, Order.quantity)
    base = (
        select(func.coalesce(func.sum(item_qty), 0))
        .select_from(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.is_deleted.isnot(True))
    )
    order_quantity = int((await db.execute(base)).scalar() or 0)
    stockin_quantity = int((await db.execute(
        select(func.coalesce(func.sum(StockIn.quantity), 0))
    )).scalar() or 0)

    return {
        'order_quantity': order_quantity,
        'stockin_quantity': stockin_quantity,
    }
```

- [ ] **Step 5: 运行确认通过**

Run: `command python -m pytest tests/test_inventory_totals.py -v`
Expected: PASS

- [ ] **Step 6: 跑相关测试**

Run: `command python -m pytest tests/test_multi_sku_inventory_stats.py tests/ -q -k "inventory or stock"`
Expected: PASS（既有用例中依赖 `country_orders`/`all_countries` 的断言同步骤删除）

- [ ] **Step 7: Commit**

```bash
command git add fastapi_app/services/stock_inventory_service.py tests/test_inventory_totals.py tests/test_multi_sku_inventory_stats.py
command git commit -m "refactor(stock): 库存聚合移除国家维度与定制订单统计"
```

---

### Task 7: stock 端点与报表导出收敛

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/stock.py`
- Modify: `utils/report_exporter.py`
- Test: `tests/` 中导出与 stock 端点用例

**Interfaces:**
- Consumes: Task 6 的 `get_stock_overview_stats` 新返回结构
- Produces: stock 端点不再接收 `order_type`、不再返回 `order_custom_quantity`；报表不再输出国家列。

- [ ] **Step 1: 写失败测试**

在 `tests/test_custom_order_removed.py` 追加：

```python
import inspect

import pytest

from fastapi_app.api.v1.endpoints import stock as stock_ep


@pytest.mark.parametrize('fn', ['list_stockins', 'list_stockouts', 'create_stockout'])
def test_stock_endpoint_has_no_order_type_param(fn):
    params = set(inspect.signature(getattr(stock_ep, fn)).parameters)
    assert 'order_type' not in params
    assert 'country' not in params


def test_stock_stats_source_has_no_custom_quantity():
    src = inspect.getsource(stock_ep._fetch_stock_stats)
    assert 'order_custom_quantity' not in src
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_custom_order_removed.py -v`
Expected: FAIL

- [ ] **Step 3: 删除参数与字段**

先定位：`command grep -n "order_custom_quantity\|order_type\|country" fastapi_app/api/v1/endpoints/stock.py`

`fastapi_app/api/v1/endpoints/stock.py`：

- `list_stockins`（L43）：删除 `order_type: str | None = Query(None, description='订单类型')`（L47）、向 service 的 `order_type=order_type` 透传（L70），以及 docstring 中 `order_type: 订单类型筛选（regular/custom）。`（L59）
- `list_stockouts`（L164）：删除 `order_type` 查询参数（L168）、透传（L191）、docstring（L180）
- `create_stockout`（L200）：删除 `order_type=data.order_type, country=data.country,`（L219）
- `order_custom_quantity: int = 0   # 定制订单数量`（L408）：删除该键，并删除其数据来源——`fastapi_app/services/stock_inventory_service.py:get_stock_overview_stats` 已去掉对应返回值
- 删除 `order_type` / `country` 在请求体处理中的其余引用

`utils/report_exporter.py`：删除 L189-191 的 `country_orders` 读取与追加列逻辑。

- [ ] **Step 4: 运行确认通过**

Run: `command python -m pytest tests/test_custom_order_removed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
command git add fastapi_app/api/v1/endpoints/stock.py utils/report_exporter.py tests/test_custom_order_removed.py
command git commit -m "refactor(stock): 端点与报表导出移除订单类型与国家列"
```

---

### Task 8: ORM 模型删除字段与 country 模型

**Files:**
- Modify: `fastapi_app/shared_models/order.py`
- Modify: `fastapi_app/shared_models/order_item.py`
- Modify: `fastapi_app/shared_models/stock_in.py`
- Modify: `fastapi_app/shared_models/staging_order.py`
- Modify: `fastapi_app/shared_models/staging_stock_out.py`
- Delete: `fastapi_app/shared_models/country.py`
- Modify: `fastapi_app/shared_models/__init__.py`
- Test: `tests/test_models_no_custom_fields.py`（新建）

**Interfaces:**
- Consumes: Task 1-7 已移除全部服务层引用
- Produces: 五个模型不再有 `order_type`、`country` 属性；`Country` 模型不可导入。

- [ ] **Step 1: 写失败测试**

```python
import pytest


@pytest.mark.parametrize('module,cls', [
    ('fastapi_app.shared_models.order', 'Order'),
    ('fastapi_app.shared_models.order_item', 'OrderItem'),
    ('fastapi_app.shared_models.stock_in', 'StockIn'),
    ('fastapi_app.shared_models.staging_order', 'StagingOrder'),
    ('fastapi_app.shared_models.staging_stock_out', 'StagingStockOut'),
])
def test_model_has_no_custom_fields(module, cls):
    import importlib

    model = getattr(importlib.import_module(module), cls)
    cols = set(model.__table__.columns.keys())
    assert 'order_type' not in cols, f'{cls} 仍有 order_type 列'
    assert 'country' not in cols, f'{cls} 仍有 country 列'


def test_country_model_removed():
    with pytest.raises(ImportError):
        import fastapi_app.shared_models.country  # noqa: F401
```

- [ ] **Step 2: 运行确认失败**

Run: `command python -m pytest tests/test_models_no_custom_fields.py -v`
Expected: FAIL

- [ ] **Step 3: 删除模型字段**

每个文件删除 `order_type` 与 `country` 两行 `mapped_column(...)`，并删除 `to_dict()` 中对应键：

- `order.py`：L81-82 字段；L149-150 `'order_type': self.order_type,` / `'country': self.country or '',`
- `order_item.py`：L37-39 字段
- `stock_in.py`：L32-33 字段
- `staging_order.py`：L35-36 字段；L69-70 `to_dict` 键
- `staging_stock_out.py`：L33-34 字段；L66-67 `to_dict` 键

- [ ] **Step 4: 删除 country 模型**

```bash
command git rm fastapi_app/shared_models/country.py
```

`fastapi_app/shared_models/__init__.py`：删除 L31 `from fastapi_app.shared_models.country import Country` 及 `__all__` 中的 `'Country'`（若存在）。

- [ ] **Step 5: 运行确认通过**

Run: `command python -m pytest tests/test_models_no_custom_fields.py -v`
Expected: PASS

- [ ] **Step 6: 全量后端测试（第一道闸门）**

Run: `command python -m pytest tests/ fastapi_app/tests/ -q`
Expected: PASS。若有 FAIL，说明仍存在对已删字段的引用，逐一定位修复后再继续——**不得**跳过。

- [ ] **Step 7: Commit**

```bash
command git add fastapi_app/shared_models/ tests/test_models_no_custom_fields.py
command git commit -m "refactor(models): 删除订单类型/国家字段与 Country 模型"
```

---

### Task 9: 数据迁移（独立 commit）

**Files:**
- Create: `migrations/versions/pg_standalone_055_remove_custom_order_country.py`

**Interfaces:**
- Consumes: Task 8 的模型定义（与迁移后的表结构一致）
- Produces: 数据库删除 5 表的 `order_type`/`country` 列、`idx_order_custom_type` 索引与 `country` 表。

- [ ] **Step 1: 备份数据库**

按项目既有备份机制执行一次备份（参考 `docs/backend/backup-restore/` 与 `server_manager.py` 的备份入口）。备份完成前**不要**执行迁移。

- [ ] **Step 2: 写迁移文件**

```python
"""移除定制订单：删除 order_type/country 列与 country 表

Revision ID: pg_standalone_055_remove_custom_order_country
Revises: pg_standalone_054
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_055_remove_custom_order_country'
down_revision = 'pg_standalone_054'
branch_labels = None
depends_on = None

_TABLES = ('order', 'order_item', 'stock_in', 'staging_order', 'staging_stock_out')


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent():
        return
    op.drop_index('idx_order_custom_type', table_name='order')
    for table in _TABLES:
        op.drop_column(table, 'order_type')
        op.drop_column(table, 'country')
    op.drop_table('country')


def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent():
        return
    for table in _TABLES:
        nullable = table == 'staging_stock_out'
        op.add_column(table, sa.Column(
            'order_type', sa.String(20), nullable=nullable,
            server_default='regular',
            comment='订单类型：regular=常规订单, custom=定制订单',
        ))
        op.add_column(table, sa.Column(
            'country', sa.String(100), nullable=True,
            comment='国家名称（仅定制订单使用）',
        ))
    op.create_table(
        'country',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False, comment='国家名称'),
    )
    op.create_index(
        'idx_order_custom_type', 'order', ['product_id', 'customer', 'country'],
        postgresql_where=sa.text("(order_type)::text = 'custom'::text"),
    )
```

- [ ] **Step 3: 升级迁移**

Run: `command python -m alembic upgrade head`
Expected: 无报错，日志显示 `pg_standalone_055_remove_custom_order_country`

- [ ] **Step 4: 验证结构已删**

Run: `command python -m pytest tests/test_models_no_custom_fields.py tests/test_inventory_totals.py tests/test_custom_order_removed.py -v`
Expected: PASS

用只读副本核查结构（副本会同步 DDL，若刚迁移完请稍候重试）：

```bash
command python - <<'PY'
import asyncio, asyncpg
DSN = "postgresql://erp_readonly:U2Auv4_2EFoovkSeC0G2hZ2qT6yCmqme@localhost:5433/erp_system"
TABLES = ['order', 'order_item', 'stock_in', 'staging_order', 'staging_stock_out']
async def main():
    c = await asyncpg.connect(DSN)
    print("country table:", await c.fetchval("SELECT to_regclass('public.country')"))
    rows = await c.fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_name = ANY($1::text[]) AND column_name IN ('order_type','country')", TABLES)
    print("leftover cols:", [tuple(r) for r in rows])
    print("custom idx:", await c.fetchval("SELECT to_regclass('public.idx_order_custom_type')"))
    print("orders:", await c.fetch("SELECT id, order_no FROM \"order\" ORDER BY id"))
    await c.close()
asyncio.run(main())
PY
```

Expected: `country table: None`；`leftover cols: []`；`custom idx: None`；`orders` 正常返回 4 行（历史 regular 订单在删列后仍可查询——Review Focus 第 5 条）。

- [ ] **Step 5: 验证回滚可重建结构**

Run: `command python -m alembic downgrade -1` → 确认列与表重建 → `command python -m alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
command git add migrations/versions/pg_standalone_055_remove_custom_order_country.py
command git commit -m "feat(db): 迁移删除 order_type/country 列与 country 表"
```

---

### Task 10: 前端共享层（api / types）

**Files:**
- Modify: `frontend-vite/src/api/stock.ts`
- Modify: `frontend-vite/src/api/auxiliary.ts`
- Modify: `frontend-vite/src/api/material.ts`
- Modify: `frontend-vite/src/types/index.ts`
- Test: `frontend-vite/src/test/` 相关用例

**Interfaces:**
- Consumes: Task 4/6 的后端契约（`available-shipment` 无 order_type/country；库存响应无 `all_countries`/`country_orders`）
- Produces: 前端 API 与类型不再暴露定制/国家字段。

- [ ] **Step 1: 改 api**

- `api/stock.ts:34-35`：`availableShipment: (productId: number, customer: string) => get<ApiResponse<ShipmentInfo>>('/aux/available-shipment', { product_id: productId, customer })`
- `api/auxiliary.ts:49-50`：删除 `order_type?`、`country?`
- `api/material.ts:23-24`：删除 `order_type?`、`country?`

- [ ] **Step 2: 改 types**

`types/index.ts` 删除以下字段（`command grep -n "order_type\|country\|custom" frontend-vite/src/types/index.ts` 定位）：

- `order_type`（L66、L102、L136、L235、L272、L483、L575 等）
- `country`（L67、L103、L137、L236、L273、L484、L576 等）
- `custom_stockout_qty`（L154）、`custom_order_qty`（L156）
- `_custom_details`（L165）、`_country_available`（L166）
- `country_data`（L158）、`country_orders`（L163）、`available_stock_by_country`（L164）
- `regular_available`（L563）、`custom_available`（L564）
- `country_list` / `all_countries` 若存在一并删除

- [ ] **Step 3: 类型检查**

Run: `cd frontend-vite && command npm run type-check`
Expected: 输出错误列表（指向 views / stores / tests 中的引用）——这是预期，在 Task 11-14 处理。记录清单。

- [ ] **Step 4: Commit**

```bash
command git add frontend-vite/src/api/stock.ts frontend-vite/src/api/auxiliary.ts frontend-vite/src/api/material.ts frontend-vite/src/types/index.ts
command git commit -m "refactor(web): 前端共享类型与 API 移除定制订单/国家字段"
```

---

### Task 11: 前端 customer-order 视图

**Files:**
- Modify: `frontend-vite/src/views/customer-order/composables/useOrderForm.ts`
- Modify: `frontend-vite/src/views/customer-order/composables/useOrderList.ts`
- Modify: `frontend-vite/src/views/customer-order/composables/useOrderImport.ts`
- Modify: `frontend-vite/src/views/customer-order/composables/types.ts`
- Modify: `frontend-vite/src/views/customer-order/components/OrderInputPanel.vue`
- Modify: `frontend-vite/src/views/customer-order/components/EditOrderModal.vue`
- Modify: `frontend-vite/src/views/customer-order/CustomerOrderView.vue`

**Interfaces:**
- Consumes: Task 10 的类型
- Produces: `FormState` / `StagedItem` 无 `orderType`、`country`；`useOrderForm()` 返回值无 `orderTypeOptions`、`countryStore`、`countryDialogVisible`、`openCountryDialog`、`saveCountry`。

- [ ] **Step 1: 改 composables**

`composables/types.ts`：

- `StagedItem` 删除 `orderType`（L36）、`country`（L43）
- `FormState` 删除 `orderType`（L51）、`country`（L60）
- `OrderRecord` 删除 `order_type`（L86）、`country`（L87）及 `items[]` 中的同名键（L97-98）

`composables/useOrderForm.ts`：

- 删除 `import { useCountryStore } from '@/stores/country'`（L4）
- `form` 初始值删除 `orderType: 'normal'`（L57）、`country: ''`（L67）
- 删除 `isCustomOrder`（L69）、`orderTypeOptions`（L70-73）
- 删除 `lastCountry`（L75）与国家互斥 `watch`（L76-83）
- `missingFields` 删除 `if (isCustomOrder.value && !form.country) missing.push('国家')`（L95）
- 删除 `// ===== Country dialog =====` 整段（L104-132）：`countryDialogVisible`、`newCountryName`、`countryStore`、`fetchCountries`、`openCountryDialog`、`saveCountry`
- 返回值删除 `countryStore`（L209）及其它国家相关导出

`composables/useOrderList.ts`：删除 `{ value: 'custom', label: '定制订单' }`（L45）。

`composables/useOrderImport.ts`：删除 `order_type?: string`（L25）及映射处对该字段的赋值。

- [ ] **Step 2: 改组件**

`components/OrderInputPanel.vue`：

- 删除「订单类型」选择控件（使用 `orderTypeOptions` 的 `UiSelect`）
- 删除「国家」下拉与「新增国家」按钮（L23-33 附近）
- 从 props / emits 中删除 `orderTypeOptions`、`countryOptions`、`openCountryDialog`

`components/EditOrderModal.vue`：删除国家展示行（L36 附近 `<span class="oe-info-label">国家</span>`）与国家表格列（L56 `<th>国家</th>`）及其单元格。

`CustomerOrderView.vue`：

- 删除 `:order-type-options="orderTypeOptions"`（L26）、`:country-options="countryStore.countryOptions"`（L28）、`:open-country-dialog="openCountryDialog"`（L40）
- 删除国家弹窗块（L119-123）
- 删除 setup 中 `orderTypeOptions`（L159）、`countryStore`（L163）、`countryDialogVisible` / `newCountryName` / `saveCountry`（L167 附近）的引用
- `country: isCustomOrder.value ? form.country : ''`（L267）改为不传/删除该键

- [ ] **Step 3: 删除国家弹窗组件**

```bash
command git rm frontend-vite/src/views/customer-order/components/CountryDialog.vue
```

- [ ] **Step 4: 类型检查该模块**

Run: `cd frontend-vite && command npx vue-tsc --noEmit 2>&1 | command grep "customer-order"`
Expected: 无输出（该模块类型干净）

- [ ] **Step 5: Commit**

```bash
command git add frontend-vite/src/views/customer-order/
command git commit -m "refactor(web): customer-order 视图移除定制订单与国家录入"
```

---

### Task 12: 前端 stock 视图

**Files:**
- Modify: `frontend-vite/src/views/stock/StockOutTab.vue`
- Modify: `frontend-vite/src/views/stock/components/StockOutInputForm.vue`
- Modify: `frontend-vite/src/views/stock/components/StockOutEditStagedDialog.vue`
- Modify: `frontend-vite/src/views/stock/components/StockOutDetailDialog.vue`
- Modify: `frontend-vite/src/views/stock/components/StockOutRecords.vue`
- Modify: `frontend-vite/src/views/stock/composables/useStockWarning.ts`
- Modify: `frontend-vite/src/views/stock/InventoryTab.vue`
- Modify: `frontend-vite/src/views/stock/components/InventoryStatRow.vue`
- Delete: `frontend-vite/src/views/stock/components/StockWarningDialog.vue`

**Interfaces:**
- Consumes: Task 10 的类型、Task 6 的库存响应
- Produces: stock 视图无订单类型选择、无国家下拉、无定制库存告警；库存页无国家筛选与「定制订单」列；统计卡为 `订单数量 / 备货数量 / 总订单 / 可用库存`。

- [ ] **Step 1: 出库表单与记录**

- `StockOutTab.vue`：删除订单类型选择（L161 `{ value: 'custom', label: '定制订单' }` 及其选项数组）、`countryStore` 引入与 `countryOptions` 传参（L11、L59、L82、L101-103）、`// 定制订单：校验该国家该SKU的库存是否充足` 整段校验（L210 附近）
- `StockOutInputForm.vue`：删除「国家」`label` 与 `UiSelect`（L14-15）及 `countryOptions` prop
- `StockOutEditStagedDialog.vue`：删除「国家」`label`（L25）与 `UiSelect`（L26），国家不再是必填
- `StockOutDetailDialog.vue`：删除国家展示行（L34 附近）
- `StockOutRecords.vue`：删除 `{ value: 'custom', label: '定制订单' }`（L136）

- [ ] **Step 2: 告警与库存页**

- 删除 `StockWarningDialog.vue`：

```bash
command git rm frontend-vite/src/views/stock/components/StockWarningDialog.vue
```

- `useStockWarning.ts`：删除按国家校验逻辑与 `country_orders` 读取（L16 附近），保留与库存不足无关的既有行为；若该 composable 仅服务于定制告警，则连同其引用一并删除
- `InventoryTab.vue`：
  - `inventory` computed 中 `_custom_details` / `_country_available` / `country_orders` / `available_stock_by_country` 计算（L129-140）删除，仅保留 `_rowKey`
  - `inventoryColumns` 删除 `{ field: 'custom_details', header: '定制订单' }`（L148）
  - 删除 `totalCustomQty`（L156-161）、`totalRegularQty`（L162）计算，`totalOrderQty` 改为直接取 `invData.value?.total_order_quantity`
  - 传给 `InventoryStatRow` 的 `:regular="totalRegularQty"` / `:custom="totalCustomQty"` 改为 `:orders="totalOrderQty"`
  - 删除 `filters.country`（含 `handleReset` L175、`watch` L188）
  - 删除国家筛选项的模板与 `countryOptions`
- `InventoryStatRow.vue`：删除「定制订单」卡（L7-10）；props 去掉 `custom`、把 `regular` 重命名为 `orders`；`总订单` 改为 `orders + stockin`（L16）；「常规订单」卡文案改为「订单数量」

- [ ] **Step 3: 类型检查该模块**

Run: `cd frontend-vite && command npx vue-tsc --noEmit 2>&1 | command grep "views/stock"`
Expected: 无输出

- [ ] **Step 4: Commit**

```bash
command git add frontend-vite/src/views/stock/
command git commit -m "refactor(web): stock 视图移除订单类型、国家与定制库存逻辑"
```

---

### Task 13: 删除国家 store / api 与残留引用

**Files:**
- Delete: `frontend-vite/src/stores/country.ts`
- Delete: `frontend-vite/src/api/country.ts`
- Modify: `frontend-vite/src/api/index.ts`

**Interfaces:**
- Consumes: Task 11、Task 12 已移除全部消费者
- Produces: 无 `countryApi` 导出、无 `useCountryStore`。

- [ ] **Step 1: 确认无残留引用**

Run: `command grep -rn "useCountryStore\|countryApi" frontend-vite/src --include=*.ts --include=*.vue`
Expected: 仅剩 `stores/country.ts`、`api/country.ts`、`api/index.ts` 三处

- [ ] **Step 2: 删除文件并清理导出**

```bash
command git rm frontend-vite/src/stores/country.ts frontend-vite/src/api/country.ts
```

`frontend-vite/src/api/index.ts`：删除 L50 `export { countryApi } from './country'`。

- [ ] **Step 3: 再次确认无残留**

Run: `command grep -rn "useCountryStore\|countryApi" frontend-vite/src`
Expected: 无输出

- [ ] **Step 4: Commit**

```bash
command git add frontend-vite/src/api/index.ts
command git commit -m "refactor(web): 删除国家 store 与 API 模块"
```

---

### Task 14: 前端测试同步

**Files:**
- Delete: `frontend-vite/src/test/countrySidebarStore.test.ts`
- Modify: `frontend-vite/src/test/useStockWarning.test.ts`
- Modify: `frontend-vite/src/test/customerOrderQuantityRange.test.ts`
- Modify: `frontend-vite/src/test/customerOrderImportStaged.test.ts`
- Modify: `frontend-vite/src/test/customerOrderBatchSubmit.test.ts`
- Modify: `frontend-vite/src/test/OrderInputPanel.quantityReset.test.ts`
- Modify: `frontend-vite/src/test/CustomerOrderView.skuExpand.test.ts`
- Modify: `frontend-vite/src/test/useOutsourceProcess.test.ts`

**Interfaces:**
- Consumes: Task 11-13 的组件与类型
- Produces: 前端测试全绿。

- [ ] **Step 1: 删除国家 store 测试**

```bash
command git rm frontend-vite/src/test/countrySidebarStore.test.ts
```

- [ ] **Step 2: 同步其余用例**

- `useStockWarning.test.ts`：删除依赖 `country_orders` 的用例（L38、L50-64）
- `customerOrderQuantityRange.test.ts`：删除 `orderType: 'normal'`（L55）、`country: ''`（L58）
- `customerOrderImportStaged.test.ts`：删除 `order_type: 'regular'`（L62）、`country: ''`（L63、L147、L169）
- `customerOrderBatchSubmit.test.ts`：删除 `orderType`（L53）、`country`（L62）
- `OrderInputPanel.quantityReset.test.ts`：删除 `orderType`（L9）、`country`（L16）、`orderTypeOptions: []`（L32）、`countryOptions: []`（L34）
- `CustomerOrderView.skuExpand.test.ts`：删除 `countryListMock`（L9、L131-135）、`countryApi` mock（L38-39）、`@/stores/country` mock（L73-76）、`order_type` / `country` 字段（L233、L240-241、L250-251、L312、L363）
- `useOutsourceProcess.test.ts`：删除 `order_type: 'order'`（L57）、`country: null`（L58）

- [ ] **Step 3: 跑前端测试**

Run: `cd frontend-vite && command npx vitest run`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
command git add frontend-vite/src/test/
command git commit -m "test(web): 同步前端测试移除定制订单与国家用例"
```

---

### Task 15: 全量验证与收尾

**Files:**
- 无新增；可能修补 Step 中发现的问题

**Interfaces:**
- Consumes: Task 1-14 全部
- Produces: 可交付状态。

- [ ] **Step 1: 后端全量测试**

Run: `command python -m pytest tests/ fastapi_app/tests/ -q`
Expected: PASS

- [ ] **Step 2: 前端类型检查**

Run: `cd frontend-vite && command npm run type-check`
Expected: 无错误

- [ ] **Step 3: 前端测试与构建**

Run: `cd frontend-vite && command npx vitest run && command npm run build`
Expected: 测试 PASS，构建成功

- [ ] **Step 4: 全局残留搜索**

Run: `command grep -rn "定制订单\|order_type\|useCountryStore\|countryApi\|/aux/countries" fastapi_app frontend-vite/src utils --include=*.py --include=*.ts --include=*.vue`
Expected: 仅剩注释/文档中可接受的历史说明；任何代码命中都要清除

- [ ] **Step 5: 手动点验**

- `/customer-order`：录入订单无「订单类型」「国家」，可正常保存、列表展示、编辑
- `/stock`：出库无国家下拉，可正常出库；库存页无「定制订单」列、无国家筛选，统计卡为 `订单数量 / 备货数量 / 总订单 / 可用库存` 且总订单 = 订单 + 备货

- [ ] **Step 6: 更新 CHANGELOG**

在 `CHANGELOG.md` 追加一条移除说明。

- [ ] **Step 7: Commit**

```bash
command git add CHANGELOG.md
command git commit -m "docs(changelog): 记录定制订单与国家功能移除"
```
