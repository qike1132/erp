# ERP 系统 API 配置说明文档

## 📋 文件说明

本文档用于说明 ERP 系统中产品搜索和皮套入库相关的 API 配置，方便进行错误检测和功能验证。

## 📍 配置文件位置

- **JSON 配置文件**: `C:\Users\Administrator\Desktop\erp_api_config.json`
- **说明文档**: 本文件

## 🔍 核心 API 列表

### 1. 产品搜索 API
```
GET /api/product-search?q={keyword}
```
- **用途**: 搜索产品（用于产品管理和皮套入库模块）
- **权限**: order_manage
- **参数**: q - 搜索关键字
- **返回**: 产品列表（ID、名称、条码、库存）

### 2. 皮套搜索 API
```
GET /api/case-search?q={keyword}
```
- **用途**: 搜索皮套
- **权限**: case_manage
- **参数**: q - 搜索关键字
- **返回**: 皮套列表（ID、名称、条码、库存）

### 3. 批量提交皮套入库 API
```
POST /api/batch-submit-case-stockins
```
- **用途**: 批量提交皮套入库记录
- **权限**: case_manage
- **请求体**: JSON 格式，包含入库记录数组

### 4. 删除产品 API
```
DELETE /api/product/<id>
```
- **用途**: 删除产品（AJAX 方式，避免页面闪动）
- **权限**: product_manage

### 5. 删除订单 API
```
DELETE /api/order/<id>
```
- **用途**: 删除订单（AJAX 方式，保持页面滚动位置）
- **权限**: order_manage

## ✅ 检测清单

### 产品搜索功能检测
- [ ] API 路径正确：`/api/product-search`
- [ ] 返回数据包含：id, name, barcode, current_stock
- [ ] 支持模糊查询
- [ ] 权限验证正常

### 皮套入库模块检测
- [ ] 界面标签显示："产品名称"（非"皮套名称"）
- [ ] 调用 API：`/api/product-search`（非`/api/case-search`）
- [ ] 搜索框 placeholder："输入产品名称搜索"
- [ ] 表格列标题："产品名称"
- [ ] 只显示产品名称，无库存数量显示

### 批量提交功能检测
- [ ] API 路径：`/api/batch-submit-case-stockins`
- [ ] 请求方法：POST
- [ ] 请求体格式：JSON
- [ ] 返回格式：包含 success, message, success_count, failed_count

## 🐛 常见问题排查

### 问题 1: 搜索无结果
**检查点**:
1. API 路径是否正确
2. 搜索关键字是否匹配产品名称
3. 数据库是否有相关产品记录

### 问题 2: 提交入库失败
**检查点**:
1. productId 是否正确（应该是产品 ID，不是皮套 ID）
2. 必填字段是否完整（productId, quantity, stockinDate, customer）
3. 权限是否足够（case_manage）

### 问题 3: 界面标签不一致
**检查点**:
1. 表单标签：应为"产品名称"
2. 表格列头：应为"产品名称"
3. 编辑弹窗：应为"产品名称"

## 📊 数据流说明

```
用户输入关键字
    ↓
前端防抖处理（300ms）
    ↓
调用 /api/product-search
    ↓
后端查询数据库
    ↓
返回产品列表（JSON）
    ↓
前端显示下拉选项
    ↓
用户选择产品
    ↓
添加到暂存列表
    ↓
批量提交
    ↓
调用 /api/batch-submit-case-stockins
    ↓
后端处理入库
    ↓
返回处理结果
```

## 🔧 配置验证步骤

1. **打开配置文件**
   - 位置：`C:\Users\Administrator\Desktop\erp_api_config.json`
   - 工具：任意文本编辑器或 JSON 查看器

2. **检查 JSON 格式**
   - 使用 JSON 验证工具检查语法
   - 确保无语法错误

3. **核对 API 路径**
   - 对比配置文件与实际代码
   - 确保路径一致

4. **测试 API 响应**
   - 使用 Postman 或浏览器访问
   - 验证返回数据格式

## 📝 修改记录

- **2026-03-17**: 创建初始版本，包含产品搜索和皮套入库相关 API
- **2026-03-17**: 更新皮套入库模块使用产品搜索 API

## 💡 使用建议

1. **开发时参考**: 修改相关功能时参考此配置文件
2. **测试依据**: 根据检测清单逐项测试
3. **文档同步**: 修改 API 后及时更新此配置文件

---
**生成时间**: 2026-03-17
**系统版本**: ERP System v1.0
**服务器地址**: http://localhost:5003
