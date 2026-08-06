# 降低项目代码复杂度与算法优化 Spec

## Why

项目已从 Flask + SQLite + 原生 JS 迁移至 FastAPI + PostgreSQL + Vue 3 技术栈，但部分核心模块存在函数过长、分支嵌套深、变量名晦涩（如 `o`、`s`、`si`、`so`、`p`、`sc`、`pids`）、算法效率低（O(n²) 循环、N+1 查询、重复计算）等问题，导致可维护性差、内存占用偏高、热点路径响应慢。需在**不改变功能**的前提下系统性降低圈复杂度、提升可读性、优化内存与运行速度。

## 运行环境与技术栈（已核实）

### 后端
| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12 | ruff target-version = "py312" |
| FastAPI | 0.137.1 | Web 框架 |
| SQLAlchemy | 2.0.49 | async ORM |
| asyncpg | 0.31.0 | PostgreSQL 异步驱动 |
| PostgreSQL | — | 主数据库 |
| Redis | 7.4.1 (hiredis) | 缓存 + Celery broker |
| Celery | 5.6.3 | 异步任务 |
| Pydantic | 2.13.2 | 数据验证 |
| OpenTelemetry | 1.30.0 | 可观测性 |
| ruff | ≥0.11.0 | Lint + Format（替代 black/flake8/isort）|
| bandit | ≥1.7.6 | 安全扫描 |
| mypy | ≥1.15.0 | 类型检查 |
| memory-profiler | 0.61.0 | 内存分析 |
| py-spy | 0.3.14 | 采样性能分析 |

### 前端
| 组件 | 版本 | 说明 |
|------|------|------|
| Vue | 3.5.34 | 框架 |
| Vite | 8.0.16 | 构建 |
| TypeScript | 6.0.3 | 类型 |
| Pinia | 3.0.4 | 状态管理 |
| reka-ui | 2.9.7 | 无样式组件库 |
| Tailwind | 4.2.4 | 样式 |
| Capacitor | 8.3.4 | 移动端打包 |
| Vitest | 4.1.6 | 测试 |
| eslint | 9.28.0 | Lint |

### 高复杂度文件清单（已核实行数）
**后端服务层 Top 10**:
| 行数 | 文件 |
|------|------|
| 3540 | `fastapi_app/services/backup_service.py` |
| 1285 | `fastapi_app/services/stock_service.py` |
| 1189 | `fastapi_app/services/backup_recovery_test_service.py` |
| 1066 | `fastapi_app/services/case_service.py` |
| 1065 | `fastapi_app/services/purchase_plan_crud.py` |
| 1011 | `fastapi_app/services/purchase_order_query.py` |
| 844 | `fastapi_app/services/staging_service.py` |
| 842 | `fastapi_app/services/ocr_service.py` |
| 800 | `fastapi_app/services/dashboard_service.py` |
| 748 | `fastapi_app/services/order_crud.py` |

**后端端点 Top 5**:
| 行数 | 文件 |
|------|------|
| 2216 | `fastapi_app/api/v1/endpoints/backup.py` |
| 888 | `fastapi_app/api/v1/endpoints/batch.py` |
| 553 | `fastapi_app/api/v1/endpoints/purchase_plan.py` |
| 541 | `fastapi_app/api/v1/endpoints/auxiliary.py` |
| 510 | `fastapi_app/api/v1/endpoints/auth.py` |

**前端视图 Top 8**:
| 行数 | 文件 | 备注 |
|------|------|------|
| 1838 | `views/customer-order/CustomerOrderView.vue` | 已有 composables（useOrderActions/useOrderForm/useOrderList）|
| 1824 | `views/production/ProductionView.vue` | 已有 useProductionCharts |
| 1726 | `views/stock/StockOutTab.vue` | 未用虚拟滚动 |
| 1676 | `views/product/ProductListView.vue` | 未用虚拟滚动 |
| 1350 | `views/material/MaterialView.vue` | 未用虚拟滚动 |
| 1124 | `views/material-calculator/MaterialCalculatorView.vue` | 已用 VirtualList |
| 1117 | `views/purchase-plan/PurchasePlanView.vue` | 部分组件已用虚拟滚动 |
| 1082 | `views/case/CaseStockTab.vue` | 未用虚拟滚动 |

### 前端测试现状（已核实）
- 仅 2 个测试文件：`PurchaseView.autorefresh.test.ts`、`UiButton.test.ts`
- **前端重构验证不能依赖测试**，需以 `npm run type-check` + `npm run lint` + 手动冒烟为主

### 实测复杂度基线（AST 扫描 9 个核心文件）
| 指标 | 实测值 |
|------|--------|
| CC ≥ 10 的函数数 | 66 个（9 核心文件 AST 扫描）|
| CC ≥ 15 的函数数 | 46 个（需重构）|
| CC ≥ 20 的函数数 | 31 个 |
| CC ≥ 30 的函数数 | 11 个 |
| 最大 CC | 55（`backup_service.py::restore_from_zip`）|
| `await db.execute/get` 调用总数 | 568 处（services 507 + endpoints 61）|
| 潜在 N+1 模式（`for...await db.execute`）| 38 处 |

**注**：`baseline_cc.json` 因重定向捕获失败损坏（仅含 `]`），结构化基线不可回溯。`baseline_cc.txt` 保留 ruff 摘要 `Found 83 errors.`（全量 services+endpoints 作用域，与上表 9 文件 AST 扫描作用域不同）。重构后实测 48 errors，对比基线 83 减少 42.2%。

**Top 10 高 CC 函数**:
| CC | 文件 | 函数 |
|----|------|------|
| 55 | `backup_service.py` | `restore_from_zip` |
| 51 | `purchase_order_query.py` | `get_purchase_orders` |
| 47 | `backup_service.py` | `_do_create_full_backup` |
| 39 | `backup_service.py` | `restore_legacy_json` |
| 38 | `purchase_order_query.py` | `get_factory_order_summary` |
| 37 | `backup_service.py` | `restore_incremental` |
| 36 | `purchase_order_query.py` | `get_completed_purchase_orders` |
| 35 | `backup_service.py` | `verify_restore` |
| 33 | `backup_service.py` | `_do_create_full_backup_to_file` |
| 32 | `backup_service.py` | `cleanup_old_backups` |

### 预期收益（基于实测基线）
| 指标 | 重构前 | 重构后目标 | 提升幅度 | 置信度 |
|------|--------|-----------|----------|--------|
| 最大圈复杂度 | CC 55 | CC ≤ 10 | ~82% | 高（确定性）|
| CC≥15 函数数 | 46 个 | 0 个 | 100% | 高（确定性）|
| 单字母变量占比 | 高 | 全部语义化 | ~90% | 高（确定性）|
| 列表接口响应时间（100 条） | 基线 | — | ~40-60% | 中（依赖 N+1 修复）|
| 列表接口响应时间（1000 条） | 基线 | — | ~70-90% | 中（依赖 N+1 修复）|
| 大表格渲染时间（1000 行） | 基线 | — | ~70-90% | 中（依赖虚拟滚动）|
| 整体系统响应速度 | 基线 | — | ~15-25% | 低（热点路径为主）|

**诚实说明**:
1. 圈复杂度/变量名改善是**确定性**的（60-85%）
2. 性能提升是**范围性**的，取决于实际数据量和调用频率
3. "不改变功能"约束限制了激进优化空间
4. 最大收益来自 N+1 修复和虚拟滚动，而非变量重命名

## What Changes

### 一、降低函数圈复杂度（Cyclomatic Complexity）
- 使用 `ruff check --select C901 --output-format=json` 度量各函数 CC，目标 CC ≤ 10
- 拆分超长函数（>100 行或 CC > 15）为单一职责小函数
- 用**早返回（early return）/卫语句**替换深层 `if/else` 嵌套（目标嵌套深度 ≤ 2）
- 用**查表法/字典分派**替换长 `if-elif` 链
- **不改变**对外 API 签名、HTTP 响应、数据库写入结果

### 二、变量名可读性提升
- 将单字母/缩写变量重命名为语义化名称（如 `o`→`order`、`si`→`stock_in`、`so`→`stock_out`、`sc`→`customer_name`、`pids`→`product_ids`）
- **安全边界**：`report_service.py` 中 `_ALLOWED_IDENTIFIERS` 与 `_ALLOWED_EXPRS` 白名单常量、SQL 字符串别名（`o`/`s`/`si`/`so`/`p`）**不得修改**，仅重命名 Python/TS 局部变量
- `stock_service.py` 中 `_CUST_CLAUSE`/`_SI_CUST`/`_SO_CUST`/`_O_CUST`/`_PID_CLAUSE` 等 SQL 片段常量保留不动

### 三、算法复杂度分析与优化
- 识别 O(n²) 及以上循环（嵌套 list 遍历、重复 DB 查询），改用 dict/set 索引降至 O(n)
- 修复 N+1 查询：使用 `selectinload`/`joinedload` 预加载关联
- 消除重复计算：缓存循环内不变量（如 `len(list)`、聚合结果）
- 优化大列表内存占用：用生成器替换中间列表、分批处理超长序列

### 四、内存占用与运行速度优化
- 后端：避免在请求路径中加载全表到内存；分页查询强制 `LIMIT`；缓存热点查询结果
- 前端：避免 `computed` 中触发深拷贝大对象；`v-for` 使用稳定 `key`；大表格（>200 行）用虚拟滚动
- **基准对比**：重构前后用 `py-spy` 采样热点路径、`memory-profiler` 对比内存峰值
- 移除**仅本次重构产生的**孤儿导入/变量（不清理历史遗留死代码）

### 五、聚焦优先级（避免过度工程）
- **第一优先级**：后端 `backup_service.py`（3540 行）、`stock_service.py`（1285 行）、`order_crud.py`（748 行）
- **第二优先级**：后端 `case_service.py`、`purchase_plan_crud.py`、`purchase_order_query.py`、`report_service.py`
- **第三优先级**：前端 `StockOutTab.vue`、`ProductListView.vue`、`CaseStockTab.vue`（未用虚拟滚动的大列表）
- **第四优先级**：端点层 `backup.py`、`batch.py`
- `CustomerOrderView.vue`/`ProductionView.vue` 已有 composables，仅做变量重命名与 `computed` 优化，不重复提取

## Impact

- **Affected specs**: 无功能变更，不影响任何业务能力规格
- **Affected code**:
  - 后端服务层：`fastapi_app/services/` 下 10 个高复杂度文件
  - 后端端点：`fastapi_app/api/v1/endpoints/` 下 4 个高复杂度文件
  - 前端视图：`frontend-vite/src/views/` 下 5 个高复杂度文件
- **测试回归风险**: 高 — 后端依赖 `fastapi_app/tests/` 全套；前端依赖 `type-check` + `lint` + 手动冒烟
- **回滚策略**: 每个文件重构后立即提交 git，若测试失败可单独 revert 该文件

## ADDED Requirements

### Requirement: 函数圈复杂度降低
所有目标文件中圈复杂度 > 15 的函数 SHALL 被重构至 CC ≤ 10，且不改变对外行为。

#### Scenario: 超长函数拆分
- **WHEN** 某函数行数 > 100 或 CC > 15（由 `ruff C901` 度量）
- **THEN** 拆分为多个单一职责函数，每个函数 CC ≤ 10、行数 ≤ 80

#### Scenario: 深层嵌套扁平化
- **WHEN** 某函数存在 3 层及以上 `if/for` 嵌套
- **THEN** 通过卫语句、早返回、辅助函数将嵌套深度降至 ≤ 2 层

#### Scenario: 行为等价性验证
- **WHEN** 重构某后端函数后
- **THEN** 对应模块的 `fastapi_app/tests/test_*.py` 全部通过
- **AND** HTTP 响应与数据库状态与重构前一致

### Requirement: 变量名可读性
所有目标文件中的单字母变量与无意义缩写 SHALL 被替换为语义化名称。

#### Scenario: 单字母变量重命名
- **WHEN** 变量名为 `o`、`s`、`p`、`si`、`so`、`sc`、`pids` 等单字母/缩写
- **THEN** 重命名为 `order`、`stock`、`product`、`stock_in`、`stock_out`、`customer_name`、`product_ids` 等语义化名称
- **AND** SQL 字符串别名、`_ALLOWED_IDENTIFIERS`/`_ALLOWED_EXPRS` 白名单、`_CUST_CLAUSE` 等 SQL 片段常量**保持不变**

### Requirement: 算法复杂度优化
系统 SHALL 识别并优化 O(n²) 及以上算法，降至 O(n) 或 O(n log n)。

#### Scenario: 嵌套循环优化
- **WHEN** 存在 `for x in list_a: for y in list_b:` 形式的嵌套遍历
- **THEN** 通过 dict/set 预建索引将内层查找降至 O(1)，整体降至 O(n)

#### Scenario: N+1 查询修复
- **WHEN** 循环内执行 DB 查询
- **THEN** 改为批量查询 + `selectinload`/`joinedload` 预加载，查询次数从 O(n) 降至 O(1)

### Requirement: 内存与运行速度优化
系统 SHALL 在不改变功能的前提下降低内存占用、提升热点路径响应速度。

#### Scenario: 中间列表消除
- **WHEN** 存在不必要的中间列表构建（如 `[x for x in big_list if cond]` 后仅迭代一次）
- **THEN** 改用生成器表达式惰性求值

#### Scenario: 前端大列表虚拟化
- **WHEN** 某表格/列表渲染 > 200 行且未使用虚拟滚动
- **THEN** 替换为 `VirtualList.vue`/`VirtualTable.vue` 组件

#### Scenario: 性能基准对比
- **WHEN** 重构完成
- **THEN** 用 `py-spy` 采样热点路径、`memory-profiler` 对比内存峰值，确认无回退

## MODIFIED Requirements

### Requirement: 代码可维护性
现有代码 SHALL 在重构后满足：函数平均行数下降、最大圈复杂度下降、单字母变量占比下降，且全部测试通过。

## REMOVED Requirements

### Requirement: 无
本次重构不移除任何功能需求，仅优化实现质量。
