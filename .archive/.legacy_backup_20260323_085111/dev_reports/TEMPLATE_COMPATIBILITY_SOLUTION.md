# 模板兼容性解决方案

## 问题说明

用户在使用旧架构（legacy_app.py）时，模板已经被修改为新架构的路由引用（如 `url_for('main.logout')`），导致旧架构无法找到路由端点。

## 解决方案

### 方案选择

采用**模板使用旧路由名称 + 新架构添加兼容性路由**的方案：

- **模板**：使用旧路由名称（如 `url_for('logout')`）
- **旧架构**：直接使用这些路由名称
- **新架构**：通过兼容性路由重定向到新的蓝图路由

### 实现方式

#### 1. 模板使用旧路由名称

模板中的路由引用：
```html
<a href="{{ url_for('logout') }}">退出登录</a>
<a href="{{ url_for('products') }}">产品管理</a>
<a href="{{ url_for('orders') }}">订单管理</a>
```

#### 2. 新架构添加兼容性路由

在 `app/routes/main.py` 中：
```python
@main_bp.route('/logout')
def logout():
    """退出登录"""
    session.clear()
    resp = make_response(redirect(url_for('main.login')))
    resp.set_cookie('user_id', '', max_age=0)
    return resp

@main_bp.route('/products')
def products():
    """兼容性路由：产品管理"""
    return redirect(url_for('product.products'))

@main_bp.route('/orders')
def orders():
    """兼容性路由：订单管理"""
    return redirect(url_for('order.orders'))
```

### 优势

1. **兼容性好**：新旧架构都能正常工作
2. **无需修改旧架构**：保持旧架构代码不变
3. **平滑过渡**：可以逐步迁移到新架构
4. **维护简单**：模板只需要维护一套路由引用

## 路由映射关系

| 模板中的引用 | 旧架构路由 | 新架构兼容性路由 | 新架构实际路由 |
|-------------|-----------|----------------|--------------|
| `url_for('logout')` | `/logout` | `main.logout` | - |
| `url_for('products')` | `/products` | `main.products` | `product.products` |
| `url_for('orders')` | `/orders` | `main.orders` | `order.orders` |
| `url_for('stockins')` | `/stockins` | `main.stockins` | `stock.stockins` |
| `url_for('stockouts')` | `/stockouts` | `main.stockouts` | `stock.stockouts` |
| `url_for('inventory')` | `/inventory` | `main.inventory` | `stock.inventory` |

## 使用说明

### 使用旧架构

```bash
# 不设置环境变量，默认使用旧架构
python run.py
```

访问 http://127.0.0.1:5003，使用旧架构（legacy_app.py）

### 使用新架构

```bash
# 设置环境变量使用新架构
export USE_NEW_ARCH=true
python run.py
```

访问 http://127.0.0.1:5003，使用新架构（app包）

## 恢复的文件

已恢复以下模板文件的路由引用：

1. templates/base.html
2. templates/edit_order.html
3. templates/edit_product.html
4. templates/edit_stockin.html
5. templates/edit_stockout.html
6. templates/index.html
7. templates/inventory.html

## 工具脚本

- `restore_template_routes.py` - 恢复模板路由引用脚本
- `fix_template_routes.py` - 修改模板路由引用脚本（备用）

## 结论

通过这种方案，实现了新旧架构的完美兼容：
- ✅ 旧架构可以正常工作
- ✅ 新架构可以正常工作
- ✅ 模板无需修改
- ✅ 平滑过渡到新架构

系统现在可以灵活选择使用新旧架构，为逐步迁移提供了便利。
