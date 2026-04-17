# 代码审核标准操作程序（CODE REVIEW RULES）

> 本文件为代码审核的强制执行标准。审核任何代码变更时，必须逐项检查以下规则。不符合规则的代码必须被驳回或要求修改。

---

## 审核流程总览

```
1. 提取变更声称 → 验证实际覆盖率
2. 端到端数据流追踪 → 确认无丢失
3. 协议语义验证 → 不依赖框架不报错
4. 业务约束完整性 → 检查模型隐含约束
5. 跨层一致性 → 交叉对比参数
6. DRY 风险评估 → 当前正确≠未来安全
7. 前端类型安全 → 动态访问必须防护
8. 依赖声明完整性 → 代码 import 与 requirements 交叉比对
```

---

## 规则 1：安全声称必须全量验证【强制】

**问题来源：** 变更声称"新增 SQL LIKE 注入防护"，但 `finance_service.py`、`report_service.py`、`stock.py` 中的 LIKE 调用未使用 `escape_like`。

**规则：**
- 审核安全相关变更时，不得以"新增了防护函数"作为达标依据。
- 必须通过 `grep` 全量搜索验证覆盖率达到 100%。
- 原始 SQL（`text()`）和 ORM（`.like()`）同等对待。

**审核操作：**
```bash
# 每次审核涉及 LIKE 的变更时必须执行
grep -rn "\.like(" fastapi_app/ --include="*.py"
grep -rn "LIKE" fastapi_app/ --include="*.py"
```
对每条结果标注：用户输入→已转义 | 内部常量→标注安全 | 未处理→标记缺陷

---

## 规则 2：跨层数据流端到端追踪【强制】

**问题来源：** service 层返回 `{'items': [...], 'total': N, 'page': P, 'per_page': PP}`，但 API 的 response schema 只有 `data` 和 `total`，`page`/`per_page` 被静默丢弃。

**规则：**
- service 返回的每个字段，必须在 endpoint 中被消费，且在 response schema 中有对应字段。
- 字段在传递链中丢失 = 缺陷，无论"当前是否使用"。

**审核操作：**
1. 列出 service 函数返回的 dict 的所有 key
2. 在 endpoint 中确认每个 key 都被传入 response 构造
3. 在 schema 中确认每个传入的值都有对应字段
4. 任何环节丢失 → 标记缺陷

---

## 规则 3：HTTP 语义正确性验证【强制】

**问题来源：** `HTTPException(status_code=307)` 不设置 `Location` 头，不是真正的 HTTP 重定向。

**规则：**
- `HTTPException` 仅用于错误响应（4xx/5xx）。
- 重定向（3xx）必须使用 `RedirectResponse`。
- "框架未报错"不等于"代码正确"。

**审核操作：**
- 遇到任何 `HTTPException(status_code=3xx)` → 立即标记为 bug
- 遇到重定向逻辑 → 验证响应包含 `Location` 头

---

## 规则 4：软删除与业务约束完整性【强制】

**问题来源：** `Order` 模型有 `is_deleted` 字段，但 `get_orders` 查询未过滤软删除记录。

**规则：**
- 审核列表查询时，必须检查涉及模型的字段定义。
- 如果模型有 `is_deleted`/`deleted_at`，查询必须包含对应过滤条件。
- 审核范围不限于 diff，必须检查变更上下文的完整性。

**审核操作：**
1. 识别查询涉及的 ORM 模型
2. 检查模型是否有 `is_deleted`/`deleted_at`/`status`/`active` 等状态字段
3. 确认查询正确应用了业务约束过滤

---

## 规则 5：跨层默认值一致性【强制】

**问题来源：** endpoint 的 `per_page` 默认 50，service 的 `per_page` 默认 5000。

**规则：**
- 同一参数在 endpoint 层和 service 层的默认值必须一致。
- endpoint 的约束（`ge`/`le`）必须覆盖 service 的默认值。

**审核操作：**
- 列出 endpoint `Query()` 的所有参数和默认值
- 对比 service 函数签名的同名参数和默认值
- 不一致 → 标记缺陷

---

## 规则 6：DRY 违反标记与消除【强制】

**问题来源：** `order_service.py` 的筛选条件在 data query 和 count query 中各写一遍；`stock_service.py` 的 `stockin_id.is_(None)` 写了两遍。

**规则：**
- 同一条件不得在多个查询中重复书写。
- 必须提取为共享条件或从 base query 派生。
- "当前逻辑正确"不豁免 DRY 违反。

**审核操作：**
- 在 data query 和 count query 中搜索相同的 `.where()` 条件
- 发现重复 → 要求提取为共享条件

---

## 规则 7：前端类型安全防护【强制】

**问题来源：** `showToast(message, type)` 中 `notify[type || 'info'](message)` 在 type 无效时抛出 TypeError。

**规则：**
- 通过动态键访问对象方法时，必须验证键存在且值为函数类型。
- 必须提供安全的 fallback 行为。

**审核操作：**
- 搜索 `obj[variable]()` 模式
- 缺少 `typeof` 检查和 fallback → 标记缺陷

---

## 规则 8：依赖声明完整性验证【强制】

**问题来源：** 集成 RapidTable 时，`rapidocr_pdf`、`numpy`、`opencv-python` 被代码直接 `import`，但未在 `requirements/base.txt` 中声明。开发环境因增量安装而测试通过，全新部署时才会 `ImportError`。

**规则：**
- 代码中直接 `import` 的每个第三方包，必须在 `requirements/base.txt` 中显式声明。
- 传递依赖不算声明——即使包 A 随包 B 安装，代码直接 `import A` 就必须声明 A。
- 多个 requirements 文件之间，功能子集的依赖必须各自完整。

**审核操作：**
- 提取变更涉及的文件中所有 `import` / `from ... import` 语句
- 逐项确认：该 import 对应的包是否在 `requirements/base.txt` 中有显式声明
- 如果是新安装的包，必须确认已追加到 `requirements/base.txt`

---

## 审核检查清单（每次审核必须逐项确认）

| # | 检查项 | 通过标准 | 状态 |
|---|--------|---------|------|
| 1 | 安全声称全量验证 | `grep LIKE` 覆盖率 100% | ☐ |
| 2 | 数据流端到端追踪 | service→endpoint→schema 无字段丢失 | ☐ |
| 3 | HTTP 语义正确性 | 3xx 使用 RedirectResponse，含 Location 头 | ☐ |
| 4 | 软删除/业务约束 | 模型状态字段已在查询中过滤 | ☐ |
| 5 | 跨层默认值一致 | endpoint 默认值 = service 默认值 | ☐ |
| 6 | DRY 违反消除 | data query 和 count query 无重复条件 | ☐ |
| 7 | 前端类型安全 | 动态属性访问有 typeof 检查和 fallback | ☐ |
| 8 | 依赖声明完整性 | 代码 import 的第三方包全部在 requirements 中显式声明 | ☐ |

**执行要求：** 审核完成时，此清单必须全部勾选通过。任何未通过项必须在审核意见中明确标注为缺陷，并要求修改后重新提交审核。
