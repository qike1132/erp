# ERP 系统代码规范准则

> 基于生产级代码审核实践制定 | 版本 1.0 | 2026-08-18

---

## 1. 编码风格规范

### 1.1 命名规则

| 类别 | 规则 | 示例 |
|------|------|------|
| Python 函数/变量 | snake_case | `async def get_user_by_id()` |
| Python 类名 | PascalCase | `class OrderService:` |
| Python 常量 | UPPER_SNAKE | `MAX_RETRY_COUNT = 3` |
| Python 私有 | 前缀下划线 | `_internal_helper()` |
| TypeScript 函数/变量 | camelCase | `const getUserById = async () => {}` |
| TypeScript 类/接口 | PascalCase | `interface OrderResponse {}` |
| TypeScript 常量 | UPPER_SNAKE | `const API_BASE_URL = '...'` |
| Vue 组件 | PascalCase 文件名 | `OrderInputPanel.vue` |
| Vue composable | camelCase + use 前缀 | `useOrderList.ts` |
| CSS 类名 | kebab-case | `.order-list-item` |
| 数据库列名 | snake_case | `created_at`, `user_id` |
| API 路径 | kebab-case | `/api/v1/purchase-orders` |

### 1.2 缩进与格式

**Python（ruff 自动执行）**
- 缩进：4 空格
- 行宽：≤120 字符
- 引号：单引号 `'`
- 导入排序：标准库 → 第三方 → 本项目（`isort` 规则 I001）

**TypeScript/Vue（eslint 自动执行）**
- 缩进：2 空格
- 行宽：≤120 字符
- 分号：必加
- 引号：单引号

### 1.3 注释标准

**Python docstring（Google 风格）**
```python
async def get_order(db: AsyncSession, order_id: int) -> Order:
    """根据 ID 获取订单。

    Args:
        db: 异步数据库会话
        order_id: 订单 ID

    Returns:
        Order 对象

    Raises:
        OrderNotFoundError: 订单不存在
    """
```

**特殊注释标记（审核豁免专用）**

| 标记 | 用途 | 示例 |
|------|------|------|
| `# noqa: S101` | ruff 规则豁免 | `assert x is not None  # noqa: S101` |
| `# nosec B608` | bandit 安全豁免 | `text(f"SELECT ... {table}")  # nosec B608` |
| `# type: ignore[code]` | mypy 类型豁免 | `os.killpg(...)  # type: ignore[attr-defined]` |
| `# broad-except: 原因` | 宽泛 except 豁免 | `except Exception:  # broad-except: 顶层错误兜底` |
| `# defensive: 原因` | 空 except 豁免 | `except ImportError: pass  # defensive: 可选依赖` |
| `# manual-tx: 原因` | 手动事务豁免 | `await db.commit()  # manual-tx: savepoint 提交` |
| `# batch-loop: 原因` | 循环查询豁免 | `await db.execute(...)  # batch-loop: 逐表备份,非 N+1` |
| `# sql-safe: 原因` | SQL 注入豁免 | `text(f"SELECT ... {col}")  # sql-safe: 列名已白名单校验` |

> **原则**：每个豁免标记必须附注原因，禁止裸 `# noqa` 或 `# nosec`。

---

## 2. 架构与设计原则

### 2.1 分层架构

```
api/v1/endpoints  →  services  →  core  →  shared_models + schemas
    (端点层)         (服务层)    (核心层)     (数据层)
```

**依赖方向约束（禁止反向）**：

| 源层 | 禁止依赖 | 允许依赖 |
|------|---------|---------|
| endpoints | models（跨层） | services, core, schemas |
| services | endpoints（反向） | core, shared_models, schemas |
| core | services, endpoints（反向） | config, shared_models |

**延迟导入例外**：`core` 层如需调用 `services` 层功能（如 Redis 客户端），必须在函数体内延迟导入，不得在模块顶层导入。

### 2.2 模块划分策略

| 维度 | 上限 | 超标处理 |
|------|------|---------|
| Python 函数行数 | ≤80 行 | 按职责拆分为多个小函数 |
| Vue 组件行数 | ≤400 行 | 提取子组件 + composable |
| Python 服务文件 | ≤800 行 | 按功能域拆分为多个服务模块 |
| Python 类方法数 | ≤20 个 | 按职责拆分为多个类 |

**Vue 组件拆分模式**：
```
主组件（≤400行）
├── components/SubComponentA.vue（100-300行）
├── components/SubComponentB.vue（100-300行）
└── composables/useXxx.ts（共享逻辑）
```

### 2.3 接口设计规范

**REST API**：
- 资源路径：`/api/v1/{resource}` 或 `/api/v1/{resource}/{id}/{sub-resource}`
- HTTP 方法：GET（查询）、POST（创建）、PUT（全量更新）、PATCH（部分更新）、DELETE（删除）
- 响应格式：`{ "code": 200, "message": "success", "data": {...} }`
- 错误格式：`{ "code": 400, "message": "参数错误", "detail": "..." }`

**HTTP 状态码白名单**：
`200, 201, 202, 204, 303, 400, 401, 403, 404, 409, 416, 422, 429, 500, 503, 504`

**前后端 Schema 一致性**：
- 后端 Pydantic Schema 与前端 TypeScript 接口字段必须一致
- 可选字段：后端 `field: str | None = None` ↔ 前端 `field?: string | null`
- 必填字段：后端 `field: str` ↔ 前端 `field: string`

### 2.4 端点瘦身原则

端点层**禁止**包含以下业务逻辑：
- `session.commit()` / `session.rollback()` / `session.flush()`
- `await db.execute()` / `await db.scalar()` / `await db.scalars()`
- 复杂业务计算与状态转换

端点层**仅允许**：
- 参数校验与转换
- 调用 service 层函数
- 构造响应对象

---

## 3. 性能与质量要求

### 3.1 N+1 查询预防

**禁止**在循环内执行数据库查询：
```python
# ❌ 错误：N+1 查询
for item in items:
    result = await db.execute(select(Product).where(Product.id == item.id))

# ✅ 正确：批量查询
product_ids = [item.id for item in items]
results = await db.execute(select(Product).where(Product.id.in_(product_ids)))
```

**例外标记**：逐表备份/恢复、分页游标拉取等无法批量化的场景，添加 `# batch-loop: 原因` 注释。

### 3.2 SQL 注入防护

**规则**：
- 用户输入必须通过绑定参数传递：`text("WHERE id = :id"), {"id": user_id}`
- 禁止 f-string 拼接用户输入到 SQL
- 表名/列名如需动态拼接，必须通过白名单校验

**已审核的安全模式**（附 `# sql-safe:` 或 `# nosec B608` 注释）：
- `escape_like()` 转义后的 LIKE 查询
- 模块级常量片段 + 绑定参数
- 白名单校验后的标识符

### 3.3 异常处理机制

**宽泛 except 约束**：
- 禁止裸 `except:`，使用 `except Exception:`
- `except Exception` 必须附 `# broad-except: 原因` 注释
- 优先捕获具体异常类型：`except (ValueError, TypeError, SQLAlchemyError)`

**空 except 块约束**：
- `except ...: pass` 必须附 `# defensive: 原因` 注释
- 优先添加 `logger.debug(...)` 记录异常

**异常链传递**：
```python
# ✅ 正确：保留异常链
except SomeError as e:
    raise HTTPException(400, detail=str(e)) from e

# ❌ 错误：丢失异常链
except SomeError as e:
    raise HTTPException(400, detail=str(e))
```

### 3.4 事务管理

- 优先使用 `async with db_transaction()` 上下文管理器
- 手动 `commit()`/`rollback()` 必须附 `# manual-tx: 原因` 注释
- savepoint 嵌套事务使用 `async with db.begin_nested()`

### 3.5 日志记录规范

**必需上下文字段**：`request_id`, `user_id`, `timestamp`, `level`

**日志级别**：
| 级别 | 使用场景 |
|------|---------|
| CRITICAL | 系统不可用，需立即处理 |
| ERROR | 业务错误，需关注 |
| WARNING | 异常但可恢复，如降级 |
| INFO | 关键业务流程节点 |
| DEBUG | 调试信息，生产环境不输出 |

**前端日志**：使用 `devLog` 工具，禁止直接 `console.log()`
```typescript
import { devLog } from '@/utils/devLog'
devLog.log('调试信息')
devLog.warn('警告信息')
devLog.error('错误信息')
```

### 3.6 安全要求

**密钥管理**：
- 禁止在代码或 `.env` 文件中硬编码密钥
- 生产环境使用 `${ENV_VAR}` 占位符，通过环境变量注入
- `SECRET_KEY` 长度 ≥32 字符

**输入校验**：
- 所有 API 输入必须通过 Pydantic Schema 校验
- 字符串输入应设置 `max_length` 限制
- 文件上传需校验类型与大小

**加密**：
- 密码哈希使用 bcrypt/argon2，禁止 MD5/SHA1
- JWT 使用 RS256 非对称签名
- 文件校验和可使用 MD5（非安全用途）

---

## 4. 可维护性指导

### 4.1 代码复用原则

**DRY（Don't Repeat Yourself）**：
- 重复逻辑提取为 composable（前端）或工具函数（后端）
- 共享类型定义放在 `schemas/`（后端）或 `types/`（前端）

**单一职责**：
- 每个服务模块负责一个功能域
- 每个函数只做一件事
- 每个组件只渲染一个 UI 区块

**依赖注入**：
- 数据库会话通过 FastAPI `Depends` 注入
- 配置通过 `Settings` 对象注入
- 禁止在模块顶层创建数据库连接

### 4.2 TypeScript 类型安全

**禁止 `any` 类型**：
```typescript
// ❌ 错误
const data: any = await fetchData()
function process(items: any[]): void {}

// ✅ 正确
const data: OrderResponse = await fetchData()
function process(items: OrderItem[]): void {}

// 不确定类型时使用 unknown
const data: unknown = JSON.parse(raw)
```

**类型定义规范**：
- API 响应类型定义在 `src/api/` 或 `src/types/`
- 组件 props 类型定义在组件内 `interface Props {}`
- composable 返回类型显式声明

### 4.3 无障碍（a11y）要求

| 元素 | 要求 |
|------|------|
| `<button>` | 必须有 `aria-label` 或文本内容 |
| `<a>` | 必须有 `aria-label` 或文本内容 |
| `<img>` | 必须有 `alt` 属性（装饰性图片 `alt=""`） |
| `<input>` | 必须有关联 `<label>` 或 `aria-label` |
| `<select>` | 必须有 `aria-label` |
| 图标按钮 | 必须有描述性 `aria-label` |

### 4.4 单元测试要求

| 维度 | 覆盖率阈值 |
|------|-----------|
| 核心模块（core/） | ≥85% |
| 备份模块（backup/） | ≥80% |
| 来料模块（inbound/） | ≥75% |
| 仪表盘（dashboard/） | ≥70% |

**测试规范**：
- 测试文件放在 `tests/` 目录，命名 `test_xxx.py`
- 使用 `pytest` + `pytest-asyncio`
- 每个公开函数至少一个测试用例
- 测试不依赖外部服务（使用 mock）

### 4.5 文档编写标准

**Python docstring**：所有公开函数/类必须有 docstring（Google 风格）

**API 文档**：FastAPI 自动从 docstring + Pydantic Schema 生成 OpenAPI 文档

**变更日志**：重要变更记录在 `CHANGELOG.md`

---

## 5. 审查与验收标准

### 5.1 代码审查检查清单

**提交前自检**：

| # | 检查项 | 命令/工具 |
|---|--------|----------|
| 1 | ruff 检查通过 | `python -m ruff check fastapi_app/ scripts/ tests/` |
| 2 | mypy 类型检查通过 | `python -m mypy fastapi_app/core/` |
| 3 | bandit 安全扫描通过 | `python -m bandit -c bandit.yaml -r fastapi_app/` |
| 4 | 函数行数 ≤80 | `python scripts/check_function_length.py --max-length 80 fastapi_app` |
| 5 | Vue 组件 ≤400 行 | `python scripts/check_vue_component_length.py --max-length 400 frontend-vite/src` |
| 6 | 宽泛 except 已标注 | `python scripts/check_bare_except.py fastapi_app` |
| 7 | 单元测试通过 | `python -m pytest fastapi_app/tests/ -x -q` |
| 8 | 无硬编码密钥 | 检查 `.env.production` 使用 `${VAR}` 占位符 |
G

**ruff 配置基准（`ruff.toml`）**：
```toml
[lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "C4", "S", "RUF"]
ignore = [
    "E501", "B008", "SIM108",
    "RUF001", "RUF002", "RUF003",  # 中文全角字符误报
    "S311", "S608", "S603", "S607",  # 非加密random/已审核SQL/subprocess
    "S104", "S310", "S324",  # Docker绑定/内部URL/文件校验和
    "E402", "F405", "N806",  # 延迟导入/star重导出/数学常量
    "SIM117", "E702", "E701", "N815", "SIM113", "SIM102", "E741", "UP046",
]
```

### 5.2 合并准入条件

**必须全部满足**：

| 条件 | 阈值 | 验证方式 |
|------|------|---------|
| ruff 检查 | 0 error | `ruff check` 全绿 |
| mypy 检查 | 0 error | `mypy fastapi_app/core/` 全绿 |
| bandit 扫描 | 0 HIGH | `bandit -r fastapi_app/` 无 HIGH |
| 单元测试 | 100% pass | `pytest` 全绿 |
| 函数行数 | ≤80 行 | `check_function_length.py` 全绿 |
| 组件行数 | ≤400 行 | `check_vue_component_length.py` 全绿 |
| 宽泛 except | 已标注 | `check_bare_except.py` 全绿 |
| 无 `any` 类型 | 0 处 | eslint `no-explicit-any` 全绿 |
| 无 `console.log` | 0 处 | eslint `no-console` 全绿 |
| 无硬编码密钥 | 0 处 | L11 审核通过 |

### 5.3 生产就绪评分标准

**12 层审核 pipeline**（`python scripts/run_prod_audit.py`）：

| 层 | 权重 | 审核内容 |
|----|------|---------|
| L1 | 0.10 | 静态分析（ruff/bandit/mypy/函数行数/组件行数） |
| L2 | 0.08 | 架构分层（反向依赖/循环依赖/服务文件长度/端点瘦身） |
| L3 | 0.12 | 业务逻辑（宽泛except/空except/手动事务/循环6 | 0.15 | 安全审核（红队SQL注入/缺失maxlength） |
| L7 | 0.10 | 性能（N+1查询/SELECT*/懒加载/缓存/产物体积） |
| L8 | 0.07 | 可观测性（日志上下文/健康端点/指标端点/告警） |
| L9 | 0.08 | 测试质量（覆盖率/测试依赖/重复测试） |
| L10 | 0.05 | 前端/移动端（any类型/console.log/a11y/组件长度/APK契约） |
| L11 | 0.04 | 部署就绪（配置完整性/密钥管理/回滚预案） |
| L12 | 0.03 | 报告与上线决策（评分聚合/签字单/历史对比） |

**评分公式**：
- 层得分 = max(0, 100 - Σ(问题数 × 扣分值))
- 扣分值：critical=25, high=15, medium=1, low=0, info=0
- 总分 = Σ(层得分 × 权重)
- 就绪条件：总分 ≥85 且无 critical/high 阻断问题

### 5.4 豁免标记使用规范

**原则**：豁免标记是审核工具的精准配合，不是逃避质量的借口。

| 场景 | 标记 | 审核要求 |
|------|------|---------|
| 中文全角字符 | ruff ignore RUF001/002/003 | 全局配置 |
| 非加密 random | ruff ignore S311 / bandit skip B311 | 确认非安全用途 |
| 已审核 SQL | `# nosec B608` / `# sql-safe:` | 确认参数化绑定 |
| 宽泛 except | `# broad-except: 原因` | 确认无法缩小范围 |
| 空 except | `# defensive: 原因` | 确认无需记录 |
| 手动事务 | `# manual-tx: 原因` | 确认无法使用上下文管理器 |
| 循环查询 | `# batch-loop: 原因` | 确认无法批量化 |
| 类型豁免 | `# type: ignore[code]` | 确认 mypy 误报 |

> **审查重点**：每个豁免标记在代码审查时必须验证其理由是否成立。

---

## 附录 A：常见问题速查

| 问题 | 解决方案 |
|------|---------|
| ruff RUF001/002/003 | 中文全角字符误报，已在 `ruff.toml` 全局忽略 |
| ruff S311 | `random` 用于非加密场景，添加 `# noqa: S311` 或全局忽略 |
| ruff S608 | SQL 使用参数化绑定，添加 `# nosec B608` |
| ruff F821 | 真实 bug：变量未定义/未导入，必须修复 |
| mypy attr-defined | 平台相关 API（如 `os.killpg`），添加 `# type: ignore[attr-defined]` |
| bandit B105/106 | 测试文件中的测试密码，在 `bandit.yaml` skips 中添加 |
| L2 REVERSE-DEP | core → services 反向依赖，改为函数内延迟导入 |
| L3 BROAD-EXCEPT | `except Exception` 添加 `# broad-except: 原因` |
| L3 LOOP-DB-QUERY | 循环内查询添加 `# batch-loop: 原因` 或改为批量查询 |
| L10 ANY-001 | `any` 替换为 `unknown` 或具体类型 |
| L10 CONSOLE-001 | `console.log` 替换为 `devLog.log` |

## 附录 B：工具命令速查

```bash
# 代码检查
python -m ruff check fastapi_app/ scripts/ tests/ --fix
python -m mypy fastapi_app/core/
python -m bandit -c bandit.yaml -r fastapi_app/ -q

# 行数检查
python scripts/check_function_length.py --max-length 80 fastapi_app
python scripts/check_vue_component_length.py --max-length 400 frontend-vite/src
python scripts/check_bare_except.py fastapi_app

# 单元测试
python -m pytest fastapi_app/tests/ -x -q
python -m pytest scripts/prod_audit/tests/ -x -q

# 生产审核
python scripts/run_prod_audit.py
python scripts/run_prod_audit.py --resume-from L4
```