# ERP系统迁移后BUG报告

## 测试时间
2026-03-22

## 测试环境
- 操作系统: Windows 10
- Python版本: 3.13.12
- Flask版本: 2.3.3
- 数据库: SQLite (开发环境)

---

## 发现的BUG列表

### BUG #1: 测试文件导入错误 (严重)

**问题描述:**
测试文件无法从`app`模块直接导入模型类，导致所有测试无法运行。

**错误信息:**
```
ImportError: cannot import name 'Product' from 'app' (C:\Users\Administrator\Desktop\erp_system\app\__init__.py)
```

**影响范围:**
- `tests/test_models.py`
- `tests/boundary/test_boundaries.py`
- `tests/functional/test_business_flow.py`
- `tests/integration/test_api.py`

**根本原因:**
新架构中，模型类定义在`app.models`模块中，但测试文件仍使用旧的导入方式：
```python
from app import app, db, Product, Order, StockIn, StockOut, User  # 错误
```

**正确导入方式:**
```python
from app import app, db
from app.models import Product, Order, StockIn, StockOut, User  # 正确
```

**复现步骤:**
1. 运行命令: `python -m pytest tests/ -v`
2. 观察导入错误

**修复优先级:** 🔴 高 (阻塞所有测试)

---

### BUG #2: API路由中使用了不存在的字段 (严重)

**问题描述:**
在`app/routes/api.py`的第71行和第80行，代码尝试访问`InventoryLog.created_at`字段，但模型中该字段名为`change_date`。

**错误位置:**
- `app/routes/api.py:71` - `InventoryLog.created_at.desc()`
- `app/routes/api.py:80` - `log.created_at.strftime(...)`

**模型定义:**
```python
# app/models/inventory_log.py
class InventoryLog(db.Model):
    change_date = db.Column(db.DateTime, default=datetime.now, ...)  # 正确字段名
```

**错误代码:**
```python
logs = InventoryLog.query.filter_by(product_id=product_id).order_by(
    InventoryLog.created_at.desc()  # ❌ 错误：应该是 change_date
).all()
```

**影响:**
- `/api/inventory-logs/<product_id>` 接口无法正常工作
- 会导致AttributeError异常

**修复优先级:** 🔴 高 (API功能完全失效)

---

### BUG #3: StockIn模型缺少stockin_no字段自动生成 (中等)

**问题描述:**
`StockIn`模型定义了`stockin_no`字段为必填且唯一，但在创建入库记录时没有自动生成编号。

**模型定义:**
```python
# app/models/stock_in.py
class StockIn(db.Model):
    stockin_no = db.Column(db.String(20), unique=True, nullable=False, ...)
```

**创建代码:**
```python
# app/routes/stock.py:45-51
stockin = StockIn(
    product_id=product_id,
    quantity=quantity,
    customer=customer,
    stockin_date=stockin_date,
    note=note
)  # ❌ 缺少 stockin_no
```

**影响:**
- 创建入库记录时会因缺少`stockin_no`而失败
- 数据库约束违反错误

**修复优先级:** 🟡 中 (入库功能完全失效)

---

### BUG #4: StockOut模型缺少stockout_no字段自动生成 (中等)

**问题描述:**
与BUG #3类似，`StockOut`模型也缺少自动生成编号的逻辑。

**影响:**
- 创建出库记录时会因缺少`stockout_no`而失败

**修复优先级:** 🟡 中 (出库功能完全失效)

---

### BUG #5: 订单创建逻辑问题 (中等)

**问题描述:**
在`app/routes/order.py`的第99行，订单创建时增加了库存，但这个逻辑可能不符合业务需求。

**问题代码:**
```python
# 订单增加库存
product.current_stock += quantity  # ❓ 订单应该增加库存吗？
```

**业务逻辑疑问:**
- 订单通常是客户下单，应该减少可用库存或占用库存
- 当前逻辑是增加库存，这可能不符合实际业务需求

**影响:**
- 库存计算可能不正确
- 需要确认业务需求

**修复优先级:** 🟡 中 (需要业务确认)

---

### BUG #6: 权限检查未实现 (低)

**问题描述:**
所有路由中的`api_permission_required`装饰器都只是占位符，没有实际实现权限检查。

**代码位置:**
- `app/routes/product.py:12-21`
- `app/routes/order.py:13-21`
- `app/routes/stock.py:14-22`
- `app/routes/api.py:16-24`

**代码:**
```python
def api_permission_required(permission_name):
    """权限检查装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # TODO: 实现权限检查逻辑
            return f(*args, **kwargs)  # ❌ 直接跳过权限检查
        return decorated_function
    return decorator
```

**影响:**
- 所有功能都没有权限保护
- 安全风险

**修复优先级:** 🟢 低 (功能可用，但有安全风险)

---

### BUG #7: 批量操作API未实现 (低)

**问题描述:**
批量操作API只是返回成功，没有实际实现功能。

**影响位置:**
- `/api/batch-submit-orders`
- `/api/batch-submit-stockins`
- `/api/batch-submit-stockouts`

**修复优先级:** 🟢 低 (功能未实现但不影响基本功能)

---

## 测试统计

- **总测试数:** 15
- **导入错误:** 5
- **可运行测试:** 10 (修复导入后)
- **通过率:** 待测试

---

## 修复建议

### 立即修复 (高优先级)
1. 修复所有测试文件的导入语句
2. 修复API路由中的字段名错误
3. 实现入库/出库编号自动生成

### 后续修复 (中优先级)
4. 确认订单创建的业务逻辑
5. 实现权限检查功能

### 低优先级
6. 实现批量操作API
7. 完善测试覆盖率

---

## 下一步行动

1. ✅ 已识别所有BUG
2. ⏳ 开始修复高优先级BUG
3. ⏳ 运行完整测试套件
4. ⏳ 验证修复效果
