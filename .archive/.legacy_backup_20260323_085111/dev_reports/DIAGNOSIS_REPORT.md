# 备货抵扣功能问题诊断报告

## 问题概述
系统中发现备货抵扣功能的后端逻辑无法正常工作，已进行全面排查。

## 已发现的问题

### 问题1: 前端提交与后端重定向不兼容
**位置**: `order.html` 第581行提交订单时
**问题描述**: 
- 前端使用 `fetch` 发送 POST 请求到 `/orders`
- 后端返回重定向响应 (`redirect(url_for('orders'))`)
- `fetch` 无法正确处理重定向，导致页面不刷新

### 问题2: 抵扣备货状态保存
**问题描述**: 前端在暂存订单时正确保存了抵扣信息，但需要确保提交时正确传递。

### 问题3: 权限装饰器兼容性（测试时发现）
**位置**: `app.py` 权限验证装饰器
**问题描述**: 在某些测试场景下，权限验证可能导致异常。

## 错误复现步骤

1. 启动应用程序并访问订单管理页面
2. 选择一个产品并输入订单数量
3. 点击"抵扣备货"按钮
4. 点击"新增订单"暂存订单
5. 点击"添加订单"提交所有订单
6. 观察抵扣逻辑是否正常执行

## 代码分析

### 前端代码分析 (`order.html`)

**暂存订单逻辑** (第387-415行):
```javascript
document.getElementById('addNewOrderBtn').addEventListener('click', function() {
    // 正确保存了抵扣信息: deductStock 和 deductibleQuantity
    const order = {
        ...,
        deductStock,
        deductibleQuantity,
        ...
    };
    stagedOrders.push(order);
});
```

**提交订单逻辑** (第548-613行):
```javascript
document.getElementById('submitAllOrdersBtn').addEventListener('click', async function() {
    for (const order of stagedOrders) {
        const formData = new FormData();
        // 正确设置了所有字段
        formData.append('deduct_stock', order.deductStock);
        if (order.deductibleQuantity > 0) {
            const stockinData = [{ id: 'custom', quantity: order.deductibleQuantity }];
            formData.append('deduct_stockins', JSON.stringify(stockinData));
        }
        // 问题: fetch 无法正确处理重定向
        const response = await fetch('/orders', { method: 'POST', body: formData });
    }
});
```

### 后端代码分析 (`app.py`)

**订单创建和抵扣逻辑** (第482-669行):
```python
@app.route('/orders', methods=['GET', 'POST'])
def orders():
    if request.method == 'POST':
        # 验证逻辑正确
        deduct_stock = request.form.get('deduct_stock') == 'on'
        
        if deduct_stock:
            # 抵扣逻辑完整且正确
            # 解析自定义抵扣数量
            # 计算可用备货
            # 创建出货记录
            # 更新库存和订单状态
        db.session.commit()
        # 问题: 返回重定向，与 fetch 不兼容
        return redirect(url_for('orders'))
```

## 修复方案

### 修复1: 改进前端提交逻辑，处理重定向
将 `fetch` 提交改为传统表单提交，或者在成功后强制刷新页面。

### 修复2: 添加后端API响应改进
为批量提交添加专门的API接口，返回JSON响应而不是重定向。

### 修复3: 权限装饰器改进
确保权限验证在所有情况下正常工作。

## 建议的修复优先级

1. **高优先级**: 修复前端提交逻辑，确保抵扣功能正常工作
2. **中优先级**: 改进后端响应处理
3. **低优先级**: 优化权限验证装饰器
