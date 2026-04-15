# [LRN-20260401-002] 批量上传抵扣备货字段处理问题

**Logged**: 2026-04-01T11:00:00Z
**Priority**: high
**Status**: completed
**Area**: frontend

### Summary
批量上传订单时，抵扣备货相关字段在前端处理时存在命名不一致问题，导致抵扣备货信息无法正确保存和显示

### Details
1. **问题现象**：上传包含抵扣备货信息的订单数据后，系统未能正确识别和处理抵扣备货字段
2. **根本原因**：前端代码中使用了不一致的字段命名：
   - `deductStock` (驼峰) vs `deduct_stock` (下划线)
   - `deductibleQuantity` (驼峰) vs `deduct_quantity` (下划线)
3. **影响范围**：
   - 添加订单时字段命名错误
   - 编辑订单后字段未正确更新
   - 提交订单时验证逻辑失效

### 问题代码位置
1. **添加订单** (order.html:486-496)
   - 原代码使用 `deductStock` 和 `deductibleQuantity`
   - 修改为 `deduct_stock` 和 `deduct_quantity`

2. **编辑保存** (order.html:758-768)
   - 原代码使用 `deductibleQuantity` 和 `deductStock`
   - 修改为 `deduct_quantity` 和 `deduct_stock`

3. **提交订单验证** (order.html:1069)
   - 原代码使用 `deductStock === 'on'`
   - 修改为 `deduct_stock === true`

### 正确的字段命名规范
```javascript
// 数据模型字段
deduct_stock: Boolean  // 是否抵扣备货
deduct_quantity: Number // 抵扣备货数量

// 后端API字段（与数据模型一致）
deduct_stock: Boolean
deduct_quantity: Number
```

### 修复过程
1. 添加订单时：
```diff
- deductStock,
- deductibleQuantity,
+ deduct_stock: deductStock === 'on',
+ deduct_quantity: deductibleQuantity,
```

2. 编辑保存时：
```diff
- stagedOrders[editingStagedIndex].deductibleQuantity = newDeductibleQuantity;
+ stagedOrders[editingStagedIndex].deduct_quantity = newDeductibleQuantity;

- if (stagedOrders[editingStagedIndex].deductibleQuantity > 0) {
-     stagedOrders[editingStagedIndex].deductStock = 'on';
+ if (stagedOrders[editingStagedIndex].deduct_quantity > 0) {
+     stagedOrders[editingStagedIndex].deduct_stock = true;
```

3. 提交订单验证时：
```diff
- stagedOrders.filter(o => o.deductStock === 'on' && o.deductibleQuantity > 0)
+ stagedOrders.filter(o => o.deduct_stock === true && o.deduct_quantity > 0)
```

### 自检清单
- [x] 检查所有JavaScript变量引用是否一致
- [x] 检查添加订单时字段命名
- [x] 检查编辑保存时字段命名
- [x] 检查提交验证时字段命名
- [x] 检查暂存订单列表显示
- [x] 检查后端API字段处理

### Metadata
- Source: user_feedback
- Related Files:
  - templates/order.html (第293-294, 493-494, 762-768, 1069, 1122-1123行)
  - app/routes/staging_order.py (第174-193行)
- Tags: bug_fix, deduct_stock, field_naming, frontend
- Prevention: 在修改字段时，使用全局搜索确保所有引用都一致

---
