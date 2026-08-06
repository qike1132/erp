# 采购订单号生成规格重新设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将采购订单号从独立实现 `CGYYYYMMDDXXX`（3位序号、无分隔符、无并发锁）统一为 `CG-YYYYMMDD-XXXX`（4位序号、带分隔符、复用通用 AsyncNumberGenerator 的 advisory lock + FOR UPDATE + 内存缓存）。

**Architecture:** 在 `services/numbering.py` 新增 `generate_purchase_order_number(db)` helper，复用已有 `generate_number_async` 函数（与销售订单 PO、备货 BH、出货 SO 完全同构）。移除 `purchase_order_crud.py` 中的独立 `generate_purchase_order_no` 函数，将 `create_purchase_order` 中的两处调用切换到新 helper。清理 Facade 层的 re-export。

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (async), PostgreSQL (advisory lock + FOR UPDATE), pytest

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `fastapi_app/services/numbering.py` | 修改 | 新增 `generate_purchase_order_number(db)` helper |
| `fastapi_app/services/purchase_order_crud.py` | 修改 | 移除旧 `generate_purchase_order_no`，切换 `create_purchase_order` 到新 helper |
| `fastapi_app/services/purchase_order_service.py` | 修改 | 移除 `generate_purchase_order_no` 的 re-export |
| `fastapi_app/services/purchase_center_service.py` | 修改 | 移除 `generate_purchase_order_no` 的 re-export |
| `fastapi_app/tests/test_numbering.py` | 修改 | 新增采购订单号格式测试 |
| `fastapi_app/tests/test_purchase_center.py` | 修改 | 更新 mock 返回值格式以匹配新规格 |

---

## Task 1: 在 numbering.py 新增 generate_purchase_order_number helper

**Files:**
- Modify: `fastapi_app/services/numbering.py:30` (import 行) 和 `fastapi_app/services/numbering.py:149` (文件末尾)

- [ ] **Step 1: 在 numbering.py 的 import 中加入 PurchaseOrder**

修改 `fastapi_app/services/numbering.py` 第 30 行：

```python
# 修改前
from fastapi_app.shared_models import Order, StockIn, StockOut

# 修改后
from fastapi_app.shared_models import Order, PurchaseOrder, StockIn, StockOut
```

- [ ] **Step 2: 在 numbering.py 末尾追加 generate_purchase_order_number 函数**

在 `fastapi_app/services/numbering.py` 文件末尾（第 149 行 `generate_case_stockin_number` 函数之后）追加：

```python
async def generate_purchase_order_number(db: AsyncSession) -> str:
    """生成采购订单编号 CG-YYYYMMDD-XXXX"""
    return await generate_number_async('CG', PurchaseOrder, 'create_time', 'order_no', db)
```

- [ ] **Step 3: 验证 import 无循环依赖**

Run: `python -c "from fastapi_app.services.numbering import generate_purchase_order_number; print('OK')"`
Expected: 输出 `OK`，无 ImportError

- [ ] **Step 4: Commit**

```bash
git add fastapi_app/services/numbering.py
git commit -m "feat: 在 numbering.py 新增 generate_purchase_order_number helper"
```

---

## Task 2: 为新 helper 编写格式测试（TDD - 先写测试）

**Files:**
- Modify: `fastapi_app/tests/test_numbering.py:9` (import 行) 和文件末尾

- [ ] **Step 1: 在 test_numbering.py 的 import 中加入 generate_purchase_order_number**

修改 `fastapi_app/tests/test_numbering.py` 第 9 行：

```python
# 修改前
from fastapi_app.services.numbering import generate_order_number, generate_stockin_number

# 修改后
from fastapi_app.services.numbering import generate_order_number, generate_purchase_order_number, generate_stockin_number
```

- [ ] **Step 2: 在 TestNumberingFormat 类中追加采购订单号格式测试**

在 `fastapi_app/tests/test_numbering.py` 的 `TestNumberingFormat` 类末尾（第 46 行之后）追加：

```python
    @pytest.mark.asyncio
    async def test_generate_purchase_order_number_format(self):
        """采购订单编号格式应为 CG-YYYYMMDD-XXXX（4位序号，带分隔符）"""
        with patch('fastapi_app.services.numbering.generate_number_async', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = f"CG-{datetime.now().strftime('%Y%m%d')}-0001"
            number = await generate_purchase_order_number(MagicMock())

        today = datetime.now().strftime('%Y%m%d')
        assert number.startswith(f'CG-{today}-')
        assert len(number) == 16  # CG-YYYYMMDD-XXXX
        assert number.split('-')[-1].isdigit()
        assert int(number.split('-')[-1]) == 1
```

- [ ] **Step 3: 运行测试验证通过**

Run: `python -m pytest fastapi_app/tests/test_numbering.py::TestNumberingFormat::test_generate_purchase_order_number_format -v`
Expected: PASS

- [ ] **Step 4: 运行全部 numbering 测试确保无回归**

Run: `python -m pytest fastapi_app/tests/test_numbering.py -v`
Expected: 全部 PASS（3 个原有测试 + 1 个新测试）

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/tests/test_numbering.py
git commit -m "test: 新增采购订单号 CG-YYYYMMDD-XXXX 格式测试"
```

---

## Task 3: 切换 create_purchase_order 到新 generator 并移除旧函数

**Files:**
- Modify: `fastapi_app/services/purchase_order_crud.py:10` (import), `fastapi_app/services/purchase_order_crud.py:28-50` (删除旧函数), `fastapi_app/services/purchase_order_crud.py:58` 和 `fastapi_app/services/purchase_order_crud.py:83` (切换调用)

- [ ] **Step 1: 在 purchase_order_crud.py 中导入新 helper**

在 `fastapi_app/services/purchase_order_crud.py` 第 23 行（`from fastapi_app.shared_models import (...)` 块之后）追加导入：

```python
from fastapi_app.services.numbering import generate_purchase_order_number
```

- [ ] **Step 2: 删除旧的 generate_purchase_order_no 函数**

删除 `fastapi_app/services/purchase_order_crud.py` 第 28-50 行的整个 `generate_purchase_order_no` 函数（从 `async def generate_purchase_order_no` 到 `return f'{prefix}{date_str}{seq}'`）。

- [ ] **Step 3: 将 create_purchase_order 中的首次调用切换到新 helper**

修改 `fastapi_app/services/purchase_order_crud.py` 中 `create_purchase_order` 函数内的调用（原第 58 行）：

```python
# 修改前
    order_no = await generate_purchase_order_no(db)

# 修改后
    order_no = await generate_purchase_order_number(db)
```

- [ ] **Step 4: 将 IntegrityError 重试中的调用切换到新 helper**

修改 `fastapi_app/services/purchase_order_crud.py` 中 `create_purchase_order` 函数的 except 块（原第 83 行）：

```python
# 修改前
        # 并发时 order_no 可能重复，重新生成编号后再 flush
        order_no = await generate_purchase_order_no(db)

# 修改后
        # 并发时 order_no 可能重复，重新生成编号后再 flush
        order_no = await generate_purchase_order_number(db)
```

- [ ] **Step 5: 清理不再使用的 import**

检查 `fastapi_app/services/purchase_order_crud.py` 顶部 import。删除旧函数后，如果 `timedelta` 不再被使用（原仅用于 `generate_purchase_order_no` 的 `today_max = today_min + timedelta(days=1)`），则从第 10 行移除 `timedelta`：

```python
# 修改前
from datetime import UTC, datetime, timedelta

# 修改后（仅当 timedelta 无其他使用时）
from datetime import UTC, datetime
```

验证方法：在文件中搜索 `timedelta`，确认无其他引用后再删除。

- [ ] **Step 6: 验证模块可正常导入**

Run: `python -c "from fastapi_app.services.purchase_order_crud import create_purchase_order; print('OK')"`
Expected: 输出 `OK`，无 ImportError / NameError

- [ ] **Step 7: Commit**

```bash
git add fastapi_app/services/purchase_order_crud.py
git commit -m "refactor: 采购订单号切换到通用 AsyncNumberGenerator (CG-YYYYMMDD-XXXX)"
```

---

## Task 4: 清理 Facade 层的 re-export

**Files:**
- Modify: `fastapi_app/services/purchase_order_service.py:21`
- Modify: `fastapi_app/services/purchase_center_service.py:43`

- [ ] **Step 1: 从 purchase_order_service.py 移除 generate_purchase_order_no 的 re-export**

修改 `fastapi_app/services/purchase_order_service.py` 第 14-24 行的 import 块，删除 `generate_purchase_order_no,` 这一行：

```python
# 修改前
from fastapi_app.services.purchase_order_crud import (
    _build_order_summary,
    batch_complete_purchase_orders,
    cleanup_orphan_pending_purchase_orders,
    complete_purchase_order,
    create_purchase_order,
    delete_purchase_order,
    generate_purchase_order_no,
    save_factory_summary_edits,
    update_purchase_order,
)

# 修改后
from fastapi_app.services.purchase_order_crud import (
    _build_order_summary,
    batch_complete_purchase_orders,
    cleanup_orphan_pending_purchase_orders,
    complete_purchase_order,
    create_purchase_order,
    delete_purchase_order,
    save_factory_summary_edits,
    update_purchase_order,
)
```

- [ ] **Step 2: 从 purchase_center_service.py 移除 generate_purchase_order_no 的 re-export**

修改 `fastapi_app/services/purchase_center_service.py` 中对应 import 块，删除 `generate_purchase_order_no,` 这一行。

- [ ] **Step 3: 验证无其他代码引用已删除的 re-export**

Run: `python -c "import fastapi_app.services.purchase_order_service; import fastapi_app.services.purchase_center_service; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 4: 全局搜索确认无残留引用**

Run: `python -c "import ast, pathlib; [print(p) for p in pathlib.Path('fastapi_app').rglob('*.py') if 'generate_purchase_order_no' in p.read_text(encoding='utf-8')]"`
Expected: 无输出（没有任何文件引用旧函数名）

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/purchase_order_service.py fastapi_app/services/purchase_center_service.py
git commit -m "chore: 移除已废弃的 generate_purchase_order_no re-export"
```

---

## Task 5: 更新 test_purchase_center.py 中的 mock 格式

**Files:**
- Modify: `fastapi_app/tests/test_purchase_center.py:621`

- [ ] **Step 1: 更新 mock 返回值以匹配新格式**

修改 `fastapi_app/tests/test_purchase_center.py` 第 621 行：

```python
# 修改前
            return {'order_no': f'CG{len(created):03d}', 'id': len(created), 'total_amount': 0}

# 修改后
            return {'order_no': f'CG-20260624-{len(created):04d}', 'id': len(created), 'total_amount': 0}
```

- [ ] **Step 2: 运行相关测试验证通过**

Run: `python -m pytest fastapi_app/tests/test_purchase_center.py::TestOneClickGenerateGrouping -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add fastapi_app/tests/test_purchase_center.py
git commit -m "test: 更新 mock order_no 格式为 CG-YYYYMMDD-XXXX"
```

---

## Task 6: 全量回归验证

**Files:**
- 无文件修改，仅验证

- [ ] **Step 1: 运行全部 numbering 相关测试**

Run: `python -m pytest fastapi_app/tests/test_numbering.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 运行全部 purchase 相关测试**

Run: `python -m pytest fastapi_app/tests/test_purchase_center.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 全局搜索确认旧格式无残留**

Run: `python -c "import pathlib; [print(p) for p in pathlib.Path('fastapi_app').rglob('*.py') if 'generate_purchase_order_no' in p.read_text(encoding='utf-8')]"`
Expected: 无输出

- [ ] **Step 4: 验证新订单号格式端到端生成（手动）**

启动后端服务后，通过 API 创建一个采购订单，确认返回的 `order_no` 格式为 `CG-YYYYMMDD-XXXX`。

Run: `python -c "import asyncio; from fastapi_app.core.database import _AsyncSessionLocal; from fastapi_app.services.numbering import generate_purchase_order_number; async def t(): 
    async with _AsyncSessionLocal() as db:
        no = await generate_purchase_order_number(db)
        print(no)
asyncio.run(t())"`
Expected: 输出类似 `CG-20260624-0001`（格式正确，4位序号，带分隔符）
