# 批量上传功能扩展 Spec

## Why

当前 ERP 系统的订单、入库单和出库单模块只支持单条录入，无法批量导入数据，导致用户在处理大量数据时效率低下。需要为这三个模块分别开发批量上传功能，提高数据录入效率。

## What Changes

* **新增功能**：为 orders（订单）、stockins（入库单）、stockouts（出库单）三个模块分别添加批量上传功能

* **UI 集成**：在各模块现有界面中集成批量上传入口，参考产品页面的批量上传模块设计

* **后端 API**：创建三个新的批量上传 API 端点

* **数据验证**：实现严格的数据验证逻辑，确保上传数据符合业务规则

* **错误处理**：提供详细的错误提示，支持部分成功场景

* **用户体验**：添加上传进度显示和结果反馈

**非 BREAKING 变更**：新增功能，不影响现有功能

## Impact

* **Affected specs**:

  * ERP UI Design Specification（遵循现有设计规范）

  * 文件保存对话框扩展应用场景（复用文件对话框方案）

* **Affected code**:

  * `templates/order.html` - 订单页面 UI

  * `templates/stockin.html` - 入库单页面 UI

  * `templates/stockout.html` - 出库单页面 UI

  * `app.py` - 后端 API 路由

  * 可能需要创建新的模板文件

## ADDED Requirements

### Requirement: 批量上传功能

系统 SHALL 为订单、入库单和出库单模块提供批量上传功能，支持 Excel 文件格式。

#### Scenario: 订单批量上传 - 成功

* **WHEN** 用户上传符合格式的 Excel 文件

* **AND** 文件中所有数据都符合业务规则

* **THEN** 系统成功导入所有订单，显示成功记录和导入数量

#### Scenario: 订单批量上传 - 部分成功

* **WHEN** 用户上传的 Excel 文件中部分数据有效，部分数据无效

* **THEN** 系统导入有效数据，提示无效数据的错误信息和行号

#### Scenario: 订单批量上传 - 全部失败

* **WHEN** 用户上传的 Excel 文件中所有数据都无效

* **THEN** 系统不导入任何数据，显示详细错误列表

#### Scenario: 文件验证失败

* **WHEN** 用户上传的文件格式不正确或文件损坏

* **THEN** 系统拒绝导入，提示文件格式错误

### Requirement: UI 设计规范

批量上传模块 SHALL 遵循 ERP UI Design Specification，保持与现有界面的一致性。

* 使用折叠卡片设计，默认收起

* 拖拽上传区域样式统一

* 按钮样式符合规范（圆角、颜色、间距）

* 响应式布局，适配不同屏幕尺寸

### Requirement: 数据验证规则

系统 SHALL 对上传的数据进行以下验证：

**订单模块验证：**

* 客户名称必须为：MINISO 国际、MINISO 国内、MINISO 电商之一

* 产品名称必须存在于产品表中

* 订单数量必须为正整数

* 订单编号格式必须正确

**入库单模块验证：**

* 客户名称必须为：MINISO 国际、MINISO 国内、MINISO 电商之一

* 产品名称必须存在于产品表中

* 备货数量必须为正整数

* 备货时间格式必须正确

**出库单模块验证：**

* 客户名称必须为：MINISO 国际、MINISO 国内、MINISO 电商之一

* 产品名称必须存在于产品表中

* 出货数量必须为正整数

* 出货时间格式必须正确

* 出货数量不能超过当前库存

### Requirement: 错误提示

系统 SHALL 提供清晰、具体的错误提示，包括：

* 错误所在的行号

* 错误的具体原因

* 如何修正错误的建议

### Requirement: 上传进度和反馈

系统 SHALL 显示：

* 文件解析进度

* 数据验证进度

* 导入执行进度

* 最终结果统计（成功数量、失败数量）

## MODIFIED Requirements

### Requirement: 现有单条录入功能

**保持完全不变**，批量上传功能作为补充功能，不影响现有的单条录入流程。

## REMOVED Requirements

无

## Technical Specifications

### 文件格式要求

**Excel 模板结构：**

**订单模板列：**

1. 订单编号（必填）
2. 订单日期（必填，格式：YYYY-MM-DD）
3. 客户名称（必填，限定值）
4. 产品名称（必填）
5. 订单数量（必填，正整数）
6. 备注（可选）

**入库单模板列：**

1. 备货编号（必填）
2. 备货日期（必填，格式：YYYY-MM-DD）
3. 客户名称（必填，限定值）
4. 产品名称（必填）
5. 备货数量（必填，正整数）
6. 备注（可选）

**出库单模板列：**

1. 出货编号（必填）
2. 出货日期（必填，格式：YYYY-MM-DD）
3. 客户名称（必填，限定值）
4. 产品名称（必填）
5. 出货数量（必填，正整数）
6. 备注（可选）

### API 端点设计

```python
# 订单批量上传
POST /batch-import-orders
- Input: Excel file (multipart/form-data)
- Output: JSON { success, imported, failed, errors }

# 入库单批量上传
POST /batch-import-stockins
- Input: Excel file (multipart/form-data)
- Output: JSON { success, imported, failed, errors }

# 出库单批量上传
POST /batch-import-stockouts
- Input: Excel file (multipart/form-data)
- Output: JSON { success, imported, failed, errors }
```

### 错误处理策略

1. **文件级别错误**（格式错误、文件损坏）：立即终止，显示错误
2. **行级别错误**（单行数据无效）：记录错误，继续处理下一行
3. **系统级别错误**（数据库错误）：回滚事务，显示错误

### 事务处理

* 使用数据库事务确保数据一致性

* 部分成功场景下，只提交成功的数据

* 失败的数据不写入数据库

## Success Criteria

1. ✅ 三个模块的批量上传功能都能正常工作
2. ✅ UI 设计符合 ERP 规范，与现有界面风格一致
3. ✅ 数据验证准确，能识别所有无效数据
4. ✅ 错误提示清晰，用户能根据提示修正数据
5. ✅ 部分成功场景正确处理，不丢失有效数据
6. ✅ 不影响现有单条录入功能
7. ✅ 性能良好，能处理至少 1000 行数据

