# BUGFIX 记录

## BUG-2026-04-19-R3: JS getElementById null-unsafe + 死代码清理

### 根因
3个预存代码质量问题：
1. `finance.js` 中39处 `getElementById()` 返回值直接访问 `.style`/`.textContent`/`.querySelector`，模板元素变更即导致 `TypeError: Cannot read properties of null`
2. `product.html` 中 `id="paginationInfo"` 在两个互斥 Jinja2 分支中重复定义（违反 HTML 规范），且 pagination 为 falsy 时该元素不存在
3. `product.js` 中客户端分页代码（`paginationWrapper`/`paginationList`/`renderPagination`/`itemsPerPage`）在服务端分页替换后已成死代码，增加维护负担

### 影响范围
- `static/finance.js`: 7个函数受影响（renderCustomerSummary, resetCustomerSearch, searchCustomerSummary, renderDailyAmount, resetDailySearch, searchDailyAmount, renderDailyChart）
- `static/product.js`: renderTable/renderPagination/filterAndSort 函数
- `templates/product.html`: 分页区域

### 修复方案
1. **finance.js**: 所有 `getElementById` 调用添加 null guard — 使用 `const el = (id) => document.getElementById(id)` + `if (el('id'))` 模式；`paginationEl` 变量统一 null 检查后再访问属性；`showLoading`/`showEmpty` 辅助函数也加 null guard
2. **product.html**: 添加 `{% else %}` 分支，在 pagination 为 falsy 时也渲染隐藏的 `id="paginationInfo"` span，确保 JS `getElementById` 永远非 null
3. **product.js**: 删除所有死代码 — 移除 `paginationWrapper`/`paginationList`/`paginationInfo` 变量、`currentPage`/`itemsPerPage` 常量、`renderPagination()` 函数、`isServerPaginated` 双模式分支，简化 `renderTable()` 为纯服务端分页逻辑

### 验证结果
- Product list 每页20行、分页导航正常 ✅
- `paginationInfo` 唯一（1个实例，不再重复） ✅
- Edit 链接携带 page 参数 ✅
- Finance page 加载正常、元素存在 ✅
- JS 语法检查通过（node -c） ✅
- Health 3/3 通过 ✅
- Bandit: 0 high, 0 medium ✅

### 回滚预案
- 代码备份: `.tmp/code_backup/static_finance.js`, `.tmp/code_backup/static_product.js`, `.tmp/code_backup/templates_product.html`
- product.py: `git checkout app/routes/product.py`

---

## BUG-2026-04-19: 物料用量计算器产品选择加载缓慢

### 根因
`purchase_center_service.get_products()` 存在 N+1 查询问题：
- `db.query(Product)` 未使用 eager loading 加载 BOM 关联关系
- 对每个产品调用 `has_bom()` 触发4次 lazy load（material/fabrics/accessories/packagings）
- per_page=200 时产生 1 + 200×4 = 801 条 SQL 查询

### 影响范围
- 物料用量计算器页面首次加载
- 产品搜索建议 API
- 产品批量 BOM 查询 API

### 修复方案
1. 在 `get_products()` 查询中添加 `selectinload` 预加载4个 BOM 关系
2. 将 `bom_info` 计算从 `get_all_materials()` 过滤计数优化为直接 `len()` 计数
3. 对 `get_search_suggestions()` 和 `get_products_batch_bom()` 同样添加 `selectinload`

### 验证结果
- 修复前：50 产品 = 201 SQL 查询
- 修复后：50 产品 = 10 SQL 查询（减少 95.0%）
- API 响应正常，products 数据结构不变
- 健康检查 3/3 通过

### 回滚预案
代码备份位于 `.tmp/code_backup/`，可通过 `git checkout -- fastapi_app/services/purchase_center_service.py` 回滚
