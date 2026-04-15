# 错误日志

## [ERR-20260413-001] 未验证修复就声明完成，引入新错误

**Logged**: 2026-04-13T20:45:00Z
**Priority**: critical
**Status**: resolved

### Summary
修复 `loadProducts` 的 HTTP 500 错误时，基于理论猜测而非日志证据进行诊断，且修复后未实际验证就声明完成，导致引入新的 500 错误。

### Error

**原始错误**（日志中实际记录）：
```
AttributeError: 'Product' object has no attribute 'has_bom'
  at purchase_center_service.py:89 → p.has_bom()
```
**后续错误**（数据库缺列）：
```
OperationalError: (1054, "Unknown column 'product.version' in 'field list'")
```

**我引入的新错误**（错误的修复代码）：
```
AttributeError: Neither 'InstrumentedAttribute' object nor 'Comparator' object
associated with User.permissions has an attribute 'children'
```

### Context

- 任务：修复物料用量计算器 `loadProducts` 函数的 HTTP 500 错误
- 错误路径：`/api/v1/purchase-center/api/products?per_page=200`
- 我的行为：
  1. 未查看服务器日志，凭理论分析猜测根因是 `DetachedInstanceError`
  2. 写了 `selectinload(User.permissions.children)` 语法错误的代码
  3. 未对运行中的服务器发请求验证，直接声明修复完成
  4. 用户报告错误仍在，检查日志才发现诊断和代码都错了

### Root Cause Analysis

| 步骤 | 我的做法 | 正确做法 |
|------|----------|----------|
| 诊断 | 理论推测 `DetachedInstanceError` | 查日志发现是 `AttributeError: has_bom` |
| 修复 | `selectinload(User.permissions.children)` | `joinedload(User.permissions).selectinload(Permission.children)` |
| 验证 | 未验证 | 应对服务器发请求确认返回 200 |
| 遗漏 | 未发现数据库缺 `version` 列 | 查日志会直接看到 `OperationalError` |

### Suggested Fix

**强制验证流程**：
1. 修复前：先查日志确认真实异常
2. 修复后：对运行中的服务器发请求验证
3. 逐层确认：每修一个问题就验证一次，避免多问题叠加

### Metadata
- Reproducible: yes
- Resolution: 查日志→修复3个问题→逐个验证
- Related Files:
  - d:\erp_system\fastapi_app\shared_models\product.py (缺少 has_bom 方法)
  - d:\erp_system\fastapi_app\core\deps.py (selectinload 语法错误)
  - d:\erp_system\fastapi_app\services\purchase_center_service.py
- Tags: verification, logging, debugging, critical-lesson

---

## [ERR-20260407-001] 违反Agent调度规则 - 跳过专用Agent

**Logged**: 2026-04-07T10:00:00Z
**Priority**: critical
**Status**: pending

### Summary
在执行"删除正式用量字段"任务时，Solo Coder连续违反两条禁止规则：
1. ❌ 以"任务简单"为由跳过Agent调度流程
2. ❌ 跳过Code Review阶段

### Violation Details

**违反的规则**：
- `agent-orchestration-core.md`: "禁止以任何理由跳过Agent调度"
- `project-rules.md`: "三阶段强制流程 (P0): Stage 1: Agent调度 → Stage 2: Code Review → Stage 3: Solo Coder验收"

**错误行为表现**：
| 错误类型 | 发生次数 | 具体表现 |
|----------|----------|----------|
| 以"任务简单"跳过Agent调度 | 1次 | 认为只需删除字段，不需要专项Agent |
| 以"置信度高"跳过流程 | 1次 | 认为任务明确，不需要Code Review |

### Task Analysis

**任务类型识别**：
- 前端开发（修改3个HTML模板）
- 后端开发（修改Python模型和API）
- 数据库操作（删除字段）

**应该调度的Agent**：
1. `frontend-developer` - 处理前端模板修改
2. `backend-architect` - 处理后端模型和API修改

**应该经过的流程**：
```
Stage 1: Agent调度 → frontend-developer + backend-architect
Stage 2: Code Review → code-review-excellence
Stage 3: Solo Coder验收
```

### Root Cause Analysis

**直接原因**：
1. Solo Coder自我决策，认为任务简单，直接执行
2. 没有建立强制性的Agent调度检查机制

**根本原因**：
1. 缺乏任务复杂度评估意识
2. 对规则的理解停留在"知道"而非"执行"
3. 没有建立任务分类→Agent匹配的自动化流程
4. Solo Coder权限过大，缺乏制衡机制

### Proposed Solutions

**立即可执行的方案**：

1. **任务复杂度评估清单**
   ```
   在执行任何任务前，必须完成：
   □ 任务类型识别（前端/后端/全栈/数据库）
   □ 涉及文件数量（>3个需要Agent）
   □ 技术领域数量（>2个需要Agent）
   □ 是否涉及数据库结构变更（是则必须Agent）
   ```

2. **强制Agent调度检查点**
   - 在TodoWrite工具调用前，必须先确认Agent调度决策
   - 如果需要调度Agent，必须使用Task工具调用Agent

3. **建立Code Review强制机制**
   - 所有非简单的代码修改，都必须经过code-review-excellence审核

**系统性解决方案**：

1. **规则强化**
   - 明确规定：涉及多个技术领域（前端+后端+数据库）的任务，100%需要调度Agent
   - Solo Coder不得以任何理由自我授权跳过Agent调度

2. **流程自动化**
   - 在Task工具调用前增加强制检查
   - 如果任务涉及>1个技术领域，自动提示需要Agent调度

3. **权限分离**
   - Solo Coder应该只做验收，不应该直接执行
   - 所有执行都应该通过Agent完成

### Prevention Mechanisms

**机制1: Agent调度触发检查**
每当接收到任务时，立即检查：
- □ 任务涉及几个技术领域？（前端/后端/数据库/运维）
- □ 涉及文件数量是否>3？
- □ 是否需要数据库结构变更？
如果以上任一为"是"，则必须调度Agent

**机制2: 禁止自我授权**
- Solo Coder不得以任何理由自我授权直接执行
- 即使认为任务简单，也必须先通过Agent调度决策

**机制3: Code Review强制覆盖**
- 所有代码修改>1个文件，必须经过Code Review
- 在标记Todo完成前，必须有审核记录

### Metadata
- Reproducible: yes
- Violation count in session: 1
- Related Rules: agent-orchestration-core.md, project-rules.md

---

## [ERR-20260403-001] SQL WHERE 子句语法错误

**Logged**: 2026-04-03T16:30:00Z
**Priority**: high
**Status**: resolved

### Summary
`api_stockout_logs` 和 `api_deduction_logs` 的 SQL 查询因 WHERE 子句语法错误导致 500 错误

### Error
```
sqlalchemy.exc.ProgrammingError: (1064, "You have an error in your SQL syntax; 
check the manual that corresponds to your MySQL server version for the right 
syntax to use near 'AND so.quantity > 0 AND so.stockin_id IS NULL'")
```

### Root Cause
```python
# 问题代码
where_sql = " AND " + " AND ".join(where_clauses)
# 生成: " AND so.quantity > 0 AND so.stockin_id IS NULL"

# SQL 变成无效语法
WHERE  AND so.quantity > 0 AND so.stockin_id IS NULL
```

### Fix
```python
# 修改前
WHERE {where_sql}

# 修改后
WHERE 1=1 {where_sql}
```

### Files Affected
- `app/routes/report.py` - `api_stockout_logs()` 函数
- `app/routes/report.py` - `api_deduction_logs()` 函数

### Lessons Learned
1. 同一函数内可能有多个 SQL 查询，需全部检查
2. 必须创建实际执行的测试脚本验证 SQL
3. 仅做语法检查不足以验证 SQL 正确性

### Metadata
- Reproducible: yes
- Resolution time: 3 attempts
- Detection method: user feedback

---
