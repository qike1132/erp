# 学习记录

## [LRN-20260408-001] JavaScript变量重复声明导致整个脚本无法执行

**Logged**: 2026-04-08T12:00:00Z
**Priority**: high
**Status**: resolved
**Area**: frontend

### Summary
JavaScript中使用`let`重复声明变量会导致语法错误，阻止整个脚本执行，所有函数定义都失效。

### Details

**问题现象**：
- 错误信息：`Uncaught ReferenceError: switchTab is not defined`
- 触发场景：点击标签页按钮时
- 根本原因：变量 `autoRefreshInterval` 被声明了两次（第1834行和第2927行）

**问题原因**：
在实施"方案B：部分删除"时，删除了用料计算面板的标签页按钮和JavaScript函数，但：
1. HTML面板未完全删除
2. 初始化函数仍引用已删除的元素
3. 变量声明区域重复

**关键发现**：
使用Node.js语法检查工具发现根本原因：
```bash
node -e "const fs = require('fs'); const content = fs.readFileSync('file.html', 'utf8'); const scriptMatch = content.match(/<script>([\s\S]*?)<\/script>/); if (scriptMatch) { try { new Function(scriptMatch[1]); console.log('No syntax errors found'); } catch (e) { console.log('Syntax error:', e.message); } }"
```

输出：`Syntax error: Identifier 'autoRefreshInterval' has already been declared`

**解决方案**：
删除重复的变量声明（第2926-2927行），保留文件开头的声明。

### Suggested Action

**预防措施**：
1. 在文件开头集中声明所有全局变量
2. 使用注释块标记变量声明区域
3. 代码审查时重点检查变量声明
4. 集成ESLint等静态分析工具

**最佳实践**：
```javascript
// ============ Global Variables ============
const API_BASE = '/api';
let globalVar1 = null;
let globalVar2 = new Set();
// ... 其他全局变量
```

**删除功能检查清单**：
```
□ HTML元素（面板、按钮、输入框等）
□ CSS样式
□ JavaScript函数
□ JavaScript变量
□ 事件监听器
□ API端点
□ 路由定义
```

### Metadata
- Source: error
- Related Files: 
  - d:\erp_system\templates\purchase_center.html
  - d:\erp_system\app\routes\purchase_center.py
- Tags: javascript, syntax-error, variable-declaration, debugging, refactoring

---

## [LRN-20260408-002] 代码重构时需确保完整性

**Logged**: 2026-04-08T12:10:00Z
**Priority**: high
**Status**: resolved
**Area**: frontend

### Summary
删除功能时必须完整删除所有相关代码，包括HTML、CSS、JavaScript、变量声明等，否则会导致难以排查的问题。

### Details

**问题**：
在删除"用料计算面板"功能时：
- ✅ 删除了标签页按钮
- ✅ 删除了JavaScript函数
- ❌ 未删除HTML面板（第1531-1593行）
- ❌ 未删除变量声明（重复声明）
- ❌ 未更新初始化函数

**导致的问题**：
1. 初始化函数引用已删除元素，导致JavaScript错误
2. 变量重复声明，导致整个脚本无法执行
3. 残留HTML面板占用资源

**正确做法**：
使用系统化的删除检查清单，确保所有相关代码都被删除。

### Suggested Action

建立代码重构流程：
1. 识别所有相关代码（使用Grep搜索）
2. 创建删除清单
3. 逐一删除并验证
4. 运行语法检查
5. 进行功能测试

### Metadata
- Source: error
- Related Files: d:\erp_system\templates\purchase_center.html
- Tags: refactoring, code-cleanup, best-practice

---

## [LRN-20260408-003] 错误诊断应从语法检查开始

**Logged**: 2026-04-08T12:20:00Z
**Priority**: medium
**Status**: resolved
**Area**: frontend

### Summary
遇到"函数未定义"错误时，应首先检查语法错误，而不是直接检查函数定义位置或作用域。

### Details

**错误诊断流程**：
```
1. 语法检查（使用Node.js或ESLint）
   ↓
2. 作用域检查
   ↓
3. 加载顺序检查
   ↓
4. 运行时逻辑检查
```

**关键转折点**：
初期假设函数未定义或作用域问题，花费大量时间检查函数定义位置。使用语法检查工具后，立即发现变量重复声明问题。

**工具推荐**：
- **Node.js**：快速语法验证
- **ESLint**：JavaScript语法和代码质量检查
- **Prettier**：代码格式化

### Suggested Action

在项目开发流程中：
1. 集成ESLint到IDE
2. 设置pre-commit hook进行代码检查
3. 在CI/CD流程中加入语法检查步骤

### Metadata
- Source: debugging
- Related Files: d:\erp_system\templates\purchase_center.html
- Tags: debugging, syntax-check, eslint, best-practice

---

## [LRN-20260408-004] 一键生成采购订单API数据源问题

**Logged**: 2026-04-08T12:30:00Z
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
前端从Order表获取数据，但后端API错误地从UnprocessedOrder表查询，导致"成功生成0张采购订单"。

### Details

**问题**：
- 前端：`get_unprocessed_orders()` API 从 `Order` 表查询"待备货"状态的订单
- 后端：`one_click_generate_order()` API 尝试从 `UnprocessedOrder` 表查询
- 结果：查询不到数据，返回"成功生成 0 张采购订单"

**解决方案**：
修改后端API，从 `Order` 表查询订单：
```python
# 修改前
unprocessed_order = UnprocessedOrder.query.get(order_id)

# 修改后
order = Order.query.get(order_id)
```

**同时修复**：
- 使用 `product.has_bom()` 方法检查BOM配置（而不是访问不存在的 `has_bom` 属性）
- 更新订单状态为"已备货"（而不是标记为processed）

### Suggested Action

**API设计原则**：
1. 确保前后端数据源一致
2. 使用明确的API命名（如 `/api/orders/one-click-generate` 而不是 `/api/unprocessed-orders/...`）
3. 添加API文档说明数据来源

### Metadata
- Source: error
- Related Files: 
  - d:\erp_system\app\routes\purchase_center.py
  - d:\erp_system\templates\purchase_center.html
- Tags: api, backend, data-source, bug-fix

---

## [LRN-20260408-005] 按钮状态更新函数调用错误

**Logged**: 2026-04-08T12:40:00Z
**Priority**: medium
**Status**: resolved
**Area**: frontend

### Summary
删除函数后，其他函数仍调用已删除的函数，导致功能失效。

### Details

**问题**：
- 删除了 `updateBatchCalculateButton()` 函数
- 但 `updateSelectionUI()` 函数仍调用它（第2456行）
- 导致选择订单后按钮状态不更新

**解决方案**：
```javascript
// 修改前
updateBatchCalculateButton();

// 修改后
updateOneClickButton();
```

### Suggested Action

**重构检查**：
删除函数后，使用Grep搜索所有调用位置：
```bash
grep -n "functionName(" file.js
```

### Metadata
- Source: error
- Related Files: d:\erp_system\templates\purchase_center.html
- Tags: refactoring, function-call, bug-fix

---
