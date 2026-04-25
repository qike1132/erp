# BUG-customer-order-blank-page 修复记录

- **修复时间**: 2026-04-22
- **影响页面**: /customer-order/、/stock/stockins、/stock/stockouts
- **现象**: "客户订单"模块中"备货管理"界面无法正常显示（UI不可见或打开为空白）

## 根因分析

### 根因1：模板上下文变量缺失（pages.py）

从 Flask 迁移到 FastAPI 时，`customer_order_page`（及 `stockin_page`、`stockout_page`）的路由函数被简化为使用 `_shell_page()` 渲染模板，但 `_shell_page()` 仅传递基础页面上下文（导航、用户信息），**未传递模板所需的业务数据变量**。

缺失的关键变量：
| 变量 | 用途 | 缺失影响 |
|------|------|---------|
| `customers` | 4处 `{% for c in customers %}` 循环 | Jinja2 UndefinedError → 模板渲染失败/500 |
| `countries` | 1处 `{% for c in countries %}` 循环 | 同上 |
| `orders_json` | `{{ orders_json \| safe }}` JS赋值 | 渲染为空 → JS语法错误 `= ;` |
| `stockins_json` | `{{ stockins_json \| safe }}` JS赋值 | 同上 |
| `preview_stockin_no` | 隐藏输入框默认值 | 空值（非致命） |
| `current_date` | 日期输入框默认值 | 空值（非致命） |
| `datetime` | 模板内日期格式化 | 空值（非致命） |

### 根因2：备货管理导航条目不显示（nav_context.py + 数据库）

数据库 `permission` 表中 `stockin_manage`（ID=187）的 `is_nav=0`，导致导航查询 `WHERE is_nav = True` 过滤掉了该条目，"备货管理"永远不会出现在侧边栏导航中。

对比同级模块：
- 产品管理 (`product_manage`): `is_nav=1` ✓
- 客户订单 (`order_manage`): `is_nav=1` ✓
- **备货管理 (`stockin_manage`): `is_nav=0`** ✗
- 出库管理 (`stockout_manage`): `is_nav=1` ✓

## 修复方案

### 修复1：模板上下文变量补全（pages.py）

修改 `fastapi_app/api/v1/endpoints/pages.py` 中三个页面路由函数，从 `_shell_page()` 改为显式查询数据并传递完整模板上下文：

1. **customer_order_page** (`/customer-order/`): 查询客户列表、生成备货编号、查询国家列表
2. **stockin_page** (`/stock/stockins`): 查询客户列表、生成备货编号
3. **stockout_page** (`/stock/stockouts`): 查询客户列表、生成出库编号

对于初始订单/备货数据（`orders_json`、`stockins_json`、`stockouts_json`），传入空JSON数组 `'[]'`，由前端 AJAX 分页加载。

### 修复2：导航可见性修复（nav_context.py + main.py）

1. **nav_context.py**: 添加 `FORCE_NAV_CODES = {'stockin_manage'}` 机制，在导航查询后补充获取被 `is_nav=0` 误隐藏但应强制显示的导航项
2. **main.py**: 启动时自动检测并修复 `stockin_manage` 的 `is_nav` 值为 `True`，同时清除导航缓存

## 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `fastapi_app/api/v1/endpoints/pages.py` | 三个路由函数补充模板上下文变量 |
| `fastapi_app/core/nav_context.py` | 添加 FORCE_NAV_CODES 机制 |
| `fastapi_app/main.py` | 启动时修复 is_nav + 导入 _AsyncSessionLocal |

## 验证结果

- L1 模板渲染测试: PASS (3个模板均成功渲染)
- L2 模块导入测试: PASS
- L3 语法检查: PASS
- L5 安全扫描: PASS (无新增高危)
