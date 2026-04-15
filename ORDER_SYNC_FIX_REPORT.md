# 订单同步自动刷新功能修复报告

## 问题描述

**原始问题：**
- 订单创建后虽然自动同步到采购中心数据库
- 但采购中心页面不是实时刷新
- 需要手动点击"同步订单"按钮才能看到新订单

**问题根源：**
- 采购中心已有自动刷新机制（每3秒轮询）
- 但只检测订单数量变化，不检测订单内容更新
- 导致订单信息更新时不会触发刷新

---

## 解决方案

采用方案一：增强自动刷新检测机制

### 修改内容

#### 1. 后端API修改

**文件：** `app/routes/purchase_center.py`

**修改位置：** 第1276-1294行

**修改内容：**
- 在 `get_unprocessed_orders()` 函数中添加获取最新同步时间的逻辑
- 返回数据中增加 `latest_sync_time` 字段

**修改前：**
```python
return jsonify({
    'success': True,
    'orders': [o.to_dict() for o in orders],
    'total': total,
})
```

**修改后：**
```python
# 获取最新同步时间（用于前端检测订单更新）
latest_order = UnprocessedOrder.query
if status:
    latest_order = latest_order.filter(UnprocessedOrder.status == status)
if customer:
    latest_order = latest_order.filter(UnprocessedOrder.customer.ilike(f'%{customer}%'))
latest_order = latest_order.order_by(UnprocessedOrder.sync_time.desc()).first()
latest_sync_time = latest_order.sync_time.isoformat() if latest_order and latest_order.sync_time else None

return jsonify({
    'success': True,
    'orders': [o.to_dict() for o in orders],
    'total': total,
    'latest_sync_time': latest_sync_time,
})
```

#### 2. 前端JS修改

**文件：** `templates/purchase_center.html`

**修改位置：** 第2471-2528行

**修改内容：**
- 添加全局变量 `lastSyncTime` 记录上次同步时间
- 修改 `startAutoRefresh()` 函数，检测数量变化和时间变化

**修改前：**
```javascript
let lastUnprocessedCount = 0;
let autoRefreshInterval = null;

async function startAutoRefresh() {
    const initialRes = await apiGet('/unprocessed-orders?status=unprocessed');
    if (initialRes.success) {
        lastUnprocessedCount = initialRes.total || 0;
    }
    
    autoRefreshInterval = setInterval(async () => {
        // 只检测数量变化
        if (currentCount !== lastUnprocessedCount) {
            // 刷新列表
        }
    }, 3000);
}
```

**修改后：**
```javascript
let lastUnprocessedCount = 0;
let lastSyncTime = null;  // 新增
let autoRefreshInterval = null;

async function startAutoRefresh() {
    const initialRes = await apiGet('/unprocessed-orders?status=unprocessed');
    if (initialRes.success) {
        lastUnprocessedCount = initialRes.total || 0;
        lastSyncTime = initialRes.latest_sync_time || null;  // 新增
    }
    
    autoRefreshInterval = setInterval(async () => {
        // 检测数量变化或时间变化
        if (currentCount !== lastUnprocessedCount || currentSyncTime !== lastSyncTime) {
            console.log(`[自动刷新] 检测到订单变化`);
            lastUnprocessedCount = currentCount;
            lastSyncTime = currentSyncTime;
            // 刷新列表
        }
    }, 3000);
}
```

---

## 修改效果

修改完成后，采购中心将实现：

1. **新订单自动显示** - 创建订单后3秒内自动出现在采购中心
2. **订单更新自动刷新** - 编辑订单后3秒内自动更新显示
3. **订单删除自动移除** - 删除订单后3秒内自动从列表移除
4. **无需手动同步** - 不再需要点击"同步订单"按钮

---

## 技术原理

### 检测机制

**原机制：** 只检测数量变化
- 问题：订单更新时数量不变，不会触发刷新

**新机制：** 检测数量变化 + 时间戳变化
- 数量变化：新订单创建、订单删除
- 时间变化：订单信息更新、订单同步

### 工作流程

```
订单管理创建订单
    ↓
自动同步到 UnprocessedOrder 表
    ↓
更新 sync_time 时间戳
    ↓
采购中心每3秒轮询检测
    ↓
发现 latest_sync_time 变化
    ↓
自动刷新订单列表
```

---

## 测试验证

### 测试场景

1. **创建新订单**
   - 在订单管理中创建新订单
   - 切换到采购中心页面
   - 预期：3秒内自动显示新订单

2. **编辑订单信息**
   - 在订单管理中编辑订单（修改客户、数量等）
   - 切换到采购中心页面
   - 预期：3秒内自动更新显示

3. **删除订单**
   - 在订单管理中删除订单
   - 切换到采购中心页面
   - 预期：3秒内自动从列表移除

### 验证结果

- [OK] 所有订单已同步到采购中心
- [OK] 后端API正确返回 latest_sync_time 字段
- [OK] 前端正确检测时间戳变化
- [OK] Flask应用启动正常

---

## 文件清单

### 修改的文件

1. `app/routes/purchase_center.py` - 后端API
2. `templates/purchase_center.html` - 前端JS

### 备份文件

1. `app/routes/purchase_center.py.backup` - 后端备份
2. `templates/purchase_center.html.backup` - 前端备份

---

## 回滚方法

如果需要回滚修改：

```bash
cd /d/erp_system
cp app/routes/purchase_center.py.backup app/routes/purchase_center.py
cp templates/purchase_center.html.backup templates/purchase_center.html
```

---

## 性能影响

- **轮询频率：** 每3秒一次（不变）
- **查询开销：** 增加一次获取最新订单的查询（轻量）
- **网络流量：** 增加约50字节（时间戳字段）
- **整体影响：** 可忽略不计

---

## 注意事项

1. **浏览器兼容性：** 所有现代浏览器都支持
2. **并发安全：** 只读操作，无并发问题
3. **数据一致性：** 基于数据库事务，保证一致性
4. **刷新延迟：** 最多3秒延迟（可调整轮询间隔）

---

## 修改日期

**日期：** 2026-04-08

**修改人：** CodeArts代码智能体

**版本：** v1.0

