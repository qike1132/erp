# 架构设计与架构债评估（Archi / 系统架构师）

> 任务 #2 · 只读架构审查 · 对象 `D:\erp_system`（主应用 `fastapi_app/` + `frontend-vite/src/`）
> 证据口径：全部结论均附「可复核命令 + 原始输出」或 `文件:行`。复核脚本落盘于本目录 `_archi_scan.py` / `_archi_scan2.py` / `_archi_scan3.py` + 对应 `.out`。

---

## 0. 架构健康度总评

**一句话：整体分层方向是对的（反向依赖实测 = 0），但「契约层」与「巨石模块」两处已成系统性风险源——线上 500 与前端平行路径同源于此。**

| 维度 | 评级 | 依据 |
|---|---|---|
| 分层方向（依赖倒置） | 🟢 良好 | `core→api`、`services→api` 真反向依赖 **0 处**（唯一 `main.py` 是组合根，属正常） |
| 契约一致性（DTO/Schema） | 🔴 高风险 | 6 个请求 DTO 双定义；响应模型弱/强类型混用 → 已致线上 500 |
| 模块粒度（服务文件） | 🟠 待治理 | 8 个文件 > 800 行；`bom_service.py` = **1009 行** |
| 函数粒度 | 🟠 待治理 | 4134 个函数中 **90 个 ≥ 80 行**，最长 288 行 |
| 前端一致性 | 🔴 高风险 | 物料计算器 / 产品录入 两页「角色」维度不统一，无共享组件 |
| 迁移纪律 | 🟡 隐忧 | 84 个 version 文件，命名两套并存，`017` 前缀重复 3 次，2 次 `merge_*_heads` |
| 运行时栈（引用已实测事实） | 🟢 健康 | `nssm(1272)→prod_runner(18916)→uvicorn master(7676)→8 worker`；ARQ 哨兵键 `arq:queue:health-check`@6380 TTL=59 在线 |

---

## 1. 严重发现（按优先级）

### 🔴 F1 — 服务文件超 800 行：全量扫描确认 **8 个**，`bom_service.py` 达 **1009 行**

**复核命令**（脚本 §A）：
```bash
python deliverables/engineering-assurance/_archi_scan.py   # 见 _archi_scan.out:1-10
```

```
=== A. FILES > 800 LINES (total 462 py files) ===
   1476  fastapi_app/tests/test_purchase_center.py
   1353  fastapi_app/services/backup/orchestration/recovery_test_service.py
   1009  fastapi_app/services/bom_service.py          ← 点名复核项，确认 >1000
    962  fastapi_app/tasks/backup_tasks.py
    852  fastapi_app/core/prod_runner.py
    839  fastapi_app/services/stock_inventory_service.py
    825  fastapi_app/api/v1/endpoints/backup/validation.py
    808  fastapi_app/services/backup/cleanup/service.py
  count over800 = 8
```

**`bom_service.py` 函数清单**（`_archi_scan3.out:183-195`，含 4 个 ≥80 行函数）：

| 函数 | 行范围 | 跨度 |
|---|---|---|
| `copy_bom` | L642–897 | **256** |
| `save_bom` | L286–471 | **186** |
| `_copy_bom_into_role` | L542–639 | 98 |
| `_save_material_bom_items` | L200–283 | 84 |
| 其余 8 个 | — | ≤73 |

→ 判定：`bom_service.py` 是**单体 God Service**：角色作用域合并 + 物料三项写 + 复制 + 预览 4 类职责同居一文件，`save_bom`/`copy_bom` 两个巨型函数携带全部事务与作用域推理。**影响面**：BOM 是采购中心核心域，改动回归成本高。**修复代价 L**（按角色/作用域拆 `bom/save.py`、`bom/copy.py`、`bom/query.py`）。

---

### 🟠 F2 — 超长函数分布：**90 处 ≥ 80 行**（上轮「53 处」口径核实）

**复核命令**：`_thr.out`
```
阈值:  60→194  80→90  85→75  90→66  95→57  100→49  120→31   (总函数数 4134)
```
→ 上轮“53 处”对应阈值约 **97 行**，与实测 49~57 之间吻合，量级一致；本报告统一采用 **≥80 行 = 90 处** 口径。

**模块分布（`文件` 计数，`_archi_scan.out:14-73`）— 头部 9 个模块各 3–4 处：**

| 模块 | ≥80 行函数数 | 代表函数（`文件::函数`） |
|---|---|---|
| `services/bom_service.py` | **4** | `bom_service.py::copy_bom`(256)、`bom_service.py::save_bom`(186) |
| `services/backup/orchestration/recovery_test_service.py` | 3 | `recovery_test_service.py::_validate_constraints`(183) |
| `api/v1/endpoints/backup/validation.py` | 3 | `validation.py::validate_backup_file`(172)、`validation.py::validate_backup_integrity`(156) |
| `core/cache.py` | 3 | `cache.py::cache_result`(148)（含嵌套 `decorator` 133 / `wrapper` 126，**AST 重复计数**） |
| `services/daily_production_service.py` | 3 | `daily_production_service.py::export_records`(145) |
| `services/backup/incremental.py` | 3 | `incremental.py::restore_incremental`(136)、`::create_wal_incremental_backup`(136) |
| `services/batch_import_core.py` | 3 | — |
| `services/customer_sampling/parts.py` | 3 | — |
| `services/backup/verify/health_check_service.py` | 3 | `verify/core.py::verify_restore`(168) |

全仓最长 TOP3（`_archi_scan.out:75-77`）：`backup/dump.py::restore_database_via_psql`(**288**) > `dashboard/mobile.py::fetch_mobile_dashboard`(283) > `backup/orchestration/core.py::_do_create_full_backup`(281)。

> 注：`core/cache.py` 的“3 处”为装饰器工厂嵌套所致（`cache_result`→`decorator`→`wrapper`），非 3 个独立业务函数 — 已在债项中降级处理。

---

### 🔴 F3 — 契约重复：**6 个请求 DTO 双定义**，且「canonical」文件里的副本**全是死代码**

团队点名复核 `BomSaveRequest` —— **该重复已修复**，需更正：

**`BomSaveRequest` 现状（已收口，非重复）**
- 唯一定义：`fastapi_app/schemas/purchase_center.py:128`（强类型版，`FillingItem/FabricItem/AccessoryItem/RoleItem` 全部强类型）
- `api/v1/endpoints/purchase_center/schemas.py:8-17` 仅为 **re-export**（注释明写“已收口到 canonical 位置…见架构 §9.3”）
- 复核命令：`_archi_scan.out:285-290`

**真正残留的 6 组双定义（`_archi_scan.out:168-259`）——宽松版全部位于 `schemas/purchase_center.py`，且均未被任何路由导入：**

| DTO | 宽松版（**死代码**） | 强类型版（**实际被端点导入**） | 路由导入证据 |
|---|---|---|---|
| `CustomerSyncRequest` | `schemas/purchase_center.py:235`（无校验） | `endpoints/purchase_center/schemas.py:36`（`max_length=500`+`force`） | `customer_routes.py` ← `...purchase_center.schemas` |
| `CustomerBatchRequest` | `schemas/purchase_center.py:240`（`ids: list[int]` 无界） | `endpoints/.../schemas.py:41`（`min_length=1,max_length=500`） | 同上 |
| `OneClickGenerateRequest` | `schemas/purchase_center.py:302`（`order_ids`） | `endpoints/.../schemas.py:101`（**`composite_ids`，字段名都不同！**） | `order_routes.py:107` |
| `FactorySummarySaveRequest` | `schemas/purchase_center.py:326`（`edits: list[dict]` 无校验） | `endpoints/.../schemas.py:123`（强类型 `FactorySummaryEditItem`） | `order_routes.py:106` |
| `SummaryPrintRequest` | `schemas/purchase_center.py:393` | `endpoints/.../schemas.py:127` | `print_routes.py:132` |
| `BatchCompleteRequest` | `schemas/order_batch.py:17` | `endpoints/.../schemas.py:97` | `order_routes.py:104` |

**复核命令**：`_archi_scan3.out:61-181`（逐路由 `ImportFrom` 解析，显示端点全部从 `...purchase_center.schemas` 取强类型版）。

**架构判定**：`schemas/purchase_center.py` 自称 canonical，但**请求侧早已被端点本地 `schemas.py` 夺权**；两者字段名/校验规则均可分叉（`OneClickGenerateRequest` 已分叉为 `order_ids` vs `composite_ids`）。任一未来改动若误改“canonical”文件 → **静默无效果**（因副本是死代码），是典型的“双写幻象”。**影响面**：采购中心全部写接口。**修复代价 S**（删除 6 个死副本 + 在 canonical 文件加 `__getattr__` 弃用告警即可，无需改路由）。

> 更正：团队口径里的 `MaterialCalculateRequest` **在全仓不存在**（`_archi_scan2.out:122-156` 全量搜 `Material*Calculate*`）。实际的请求模型名为 `CalculateMaterialRequest`，定义于 `endpoints/purchase_center/schemas.py:57`，**被 `product_routes.py:291` 正常使用，非死代码**。此条**不予采信**，改以 F7 的真实死代码清单替代。

---

### 🔴 F4 — 线上 `ResponseValidationError 500` 根因链（契约层根因，非“重复”导致）

由**项目自带回归文档**直接坐实（`fastapi_app/tests/test_calculate_material_null_code.py:1-27` 原文）：

```
## 背景（2026-09-17 线上事故）
生产环境 POST /purchase-center/calculate 返回 500，堆栈为 fastapi.exceptions.ResponseValidationError：
 {'loc': ('response','groups',0,'fabric',0,'material_code'),
  'msg': 'Input should be a valid string', 'input': None}
```

**四环根因链（每环可复核）：**

1. **响应模型内部「弱/强类型》混装**：`schemas/purchase_center.py:167-177` 中扁平字段声明为**无类型 `list`**（`filling: list = []` …永不校验），而新增的 `groups: list[MaterialCalcScopeGroup]`（L175）走**强类型** `MaterialCalcRow.material_code: str`（L143）。
2. **生产者/消费者契约不对称**：DB 三张物料表 `material_code`/`unit` 可空（生产实测 11 行 NULL），`to_dict()` 原样吐 `None`；schema 要求非空 `str`。
3. **旧路径被弱类型掩蔽**：扁平字段因 `list` 无校验而“永不报错”，缺陷直到 `groups` 引入强类型才暴露 → 校验失败 → FastAPI 序列化期抛 `ResponseValidationError`。
4. **接口 except 元组有缺口**：`product_routes.py:311` `except (ValueError, OperationalError, DisconnectionError, RuntimeError)` —— `ResponseValidationError`/`ArithmeticError` **不在其内** → 退化为无友好文案的裸 500（`test_..._null_code.py:155-163` 亦点明 `InvalidOperation` 同源）。

**架构结论**：这不是“DTO 重复”导致的，而是**同一响应模型内弱/强类型并存的非对称契约** + **序列化期异常未纳入统一错误边界**。修复已由 `test_calculate_material_null_code.py` 固化（聚合侧 None→`''` 归一）。
**残余债**：① 扁平字段仍是 `list`（建议收敛为 `list[MaterialCalcRow]`）；② 全局错误边界未覆盖响应序列化异常（建议 `core/exceptions.py` 注册 `ResponseValidationError` handler / 中间件兜底）。**修复代价 M**。

---

### 🟠 F5 — 事务边界两种惯用法并存于端点层

**端点层自管事务（手写 commit/rollback）**：
- `api/v1/endpoints/supplier.py:91,93,102,106,279,282`（`await db.commit()` / `db.rollback()`）
- `api/v1/endpoints/purchase_center/order_routes.py:137,147,159,166,172`

**端点层用上下文管理器**：
- `api/v1/endpoints/purchase_center/product_routes.py:227,252,279` → `async with db_transaction(db)`

`supplier.py:82-87` 的 docstring 自述“服务层 flush-only，事务+缓存失效由端点编排”——**该决策本身合理**（事务边界贴近 HTTP 请求），但**两种写法并行**导致：缓存失效时机（提交前/后各一次，见 `supplier.py:90,109`）只在手写路径存在，`db_transaction` 路径无对称保障 → **缓存一致性地雷**。
**影响面**：全部写接口的缓存正确性。**修复代价 S**（统一为 `db_transaction`，并把「提交前后双失效」下沉为可选 hook）。

---

### 🟠 F6 — 领域/服务层依赖 Web 传输原语（`fastapi` 泄漏）

**复核命令**：`grep -r "from fastapi import" fastapi_app/services`
```
services/auxiliary_service.py:12  from fastapi import HTTPException
services/auth_service.py:9        from fastapi import HTTPException
services/auth_service.py:12       from starlette.concurrency import run_in_threadpool
services/batch_import_parser.py:15 from fastapi import UploadFile
services/batch_import_service.py:20 from fastapi import HTTPException, Response, UploadFile
services/order_batch_create.py:16  from fastapi import HTTPException
```
→ 服务层用 `HTTPException` 表达业务错误（把 HTTP 状态码语义绑进领域层）、以 `UploadFile`/`Response` 为签名参数（把传输类型绑进领域层）。
**影响面**：服务层不可脱离 FastAPI 单测/复用（ARQ worker 复用同一批 service 时尤其明显）。**修复代价 M**（定义领域异常 `core/exceptions.py`，端点层映射状态码）。

> 附带更正：团队“service 层持 `Request`”的口径**不成立**。全量搜 `fastapi_app/services` 无 `fastapi.Request` 引用；此前命中的 43 处是模型名 `ApprovalRequest`（`approval_service.py:32,71,…`）造成的**子串误报**。

---

### 🟡 F7 — 死代码 DTO（`schemas/purchase_center.py` 内 refs=0 类）

`_archi_scan3.out:1-59` 逐类统计外部引用数，其中 **refs=0**（除 F3 已列的 6 个请求副本外）：

| 类 | 位置 | 备注 |
|---|---|---|
| `PurchaseOrderComplete` | `schemas/purchase_center.py:270` | 与 `BatchCompleteRequest` 职责重叠 |
| `PurchaseOrderBatchComplete` | `schemas/purchase_center.py:274` | 同上 |
| `CompletedOrdersExportRequest` | `schemas/purchase_center.py:306` | 已被 `endpoints/.../schemas.py::ExportCompletedRequest:105` 取代 |
| `BatchPrintRequest` | `schemas/purchase_center.py:314` | 已被 `OrderIdsRequest` 取代 |
| `FactorySummaryRequest` | `schemas/purchase_center.py:322` | — |
| `GenerateFactoryOrderRequest` | `schemas/purchase_center.py:330` | — |
| `GenerateSupplierOrderRequest` | `schemas/purchase_center.py:334` | — |
| `SupplierSummaryExportRequest` | `schemas/purchase_center.py:373` | — |
| `SupplierOrderSummaryRequest` | `schemas/purchase_center.py:377` | — |
| `SavedQueryCreate` | `schemas/purchase_center.py:412` | 端点实际用 `SaveQueryRequest`（`endpoints/.../schemas.py:140`） |

→ 共 **10 个** 零引用 DTO（+F3 的 6 个宽松副本，本文件内共 **16 个**死/幻影 DTO）。这是“canonical 文件被端点本地 schemas 夺权”后的**沉积层**。
> 说明：`MaterialCalcScopeGroup`(L150)、`SearchSuggestionItem`(L48)、`RoleItemDTO`(L184) 虽是“外部零引用”，但**同文件内被引用**（`MaterialCalculateResponse:175` / `SearchSuggestionResponse:57` / `RoleListResponse:203`），**非死代码**——已排除。
**修复代价 S**（批量删除 + CI 加 `vulture`/`deadcode` 门禁）。

---

### 🟡 F8 — 迁移纪律：84 个 version 文件、双命名体系、`017` 前缀三连、反复 merge heads

**复核命令**：`_archi_scan.out:292-378`
```
migration version files: 84
  ├─ 哈希式: 659467a97350_add_approval_system_and_order_lock_.py, 9b7b1ead6c4a_add_phone_column_to_user.py
  ├─ 语义式: add_*.py / perf_*.py / change_*.py / drop_*.py / merge_*.py
  └─ 编号式: pg_standalone_001_..045_
```
- **命名两套并存**：`<hash>_slug`（autogenerate 默认）与 `pg_standalone_NNN_slug` 手工编号混用，`pg_standalone_002` 与哈希式文件混排 → 排序/审计困难。
- **`017` 前缀重复 3 次**：`pg_standalone_017_add_po_source_order_ids_gin_index.py`、`pg_standalone_017_pattern_room_v2.py`、`pg_standalone_017_product_aggregate_mv.py`（人工编号冲突，`alembic_history` 顺序依赖 `down_revision` 而非文件名，但人读易错）。
- **反复多头/合头**：`merge_all_heads.py` + `merge_resolve_all_heads.py` 两个 merge 迁移的存在，本身即“多次产生多头”的证据。
**影响面**：生产迁移（`erp-prod-db-migration`）可维护性、`alembic upgrade head` 确定性。**修复代价 M**（冻结命名规范 + CI 校验前缀唯一 + `alembic heads` 单头断言）。

---

### 🔴 F9 — 前端平行路径根因：物料计算器 vs 产品录入「角色」维度未统一

**两条路径的实现文件（已定位）：**

| | 物料计算器（Path A） | 产品录入 / BOM 编辑器（Path B） |
|---|---|---|
| 页面 | `frontend-vite/src/views/material-calculator/MaterialCalculatorView.vue` | `frontend-vite/src/views/product/components/BomEditor.vue:116` |
| 角色组件 | `views/material-calculator/components/RoleMatrix.vue`（只读矩阵） | `views/product/components/BomRolePicker.vue`（可交互字典选择器） |
| 数据来源 | 后端 `MaterialCalculateResponse.groups` → `composables/useMaterialCalculator.ts:55` → `utils/roleMatrix.ts::deriveRoleMatrix` | `roleApi.list()` → `GET /purchase-center/roles`（`api/role.ts:75`） |
| **角色身份维度** | **`role_id`**（产品角色关联行 id；`null`=默认 BOM）<br>`utils/roleMatrix.ts:75-78`：`scopeKeyOf → p\|<product>\|r\|<role_id\|default>` | **`global_role_id`**（全局角色字典 id）<br>`views/product/composables/bomTypes.ts:11-14,138-139` |
| 角色显示名 | `utils/roleMatrix.ts:81-85` **前端合成**：缺失即 `角色#<id>` | 字典 `name`（`api/role.ts:20-27`） |

**根因（架构层，三层叠加）：**

1. **缺共享「角色」抽象**：无共享 `RolePicker`/`RoleBadge` 组件，也无共享 `useRoles()` composable。两页**各自重造**角色处理（只读矩阵 vs 交互字典），`utils/roleMatrix.ts`（纯函数）与 `api/role.ts`（字典 CRUD）各管一半，**没有单一真相源**。
2. **身份维度分叉（根本）**：计算器以 **`role_id`** 为键，产品录入以 **`global_role_id`** 为键。同一逻辑角色在 A 是 `p|12|r|5`、在 B 是 `global_role_id=5`，**无法互认、无法互跳**。
3. **API 契约不给统一维度**：`schemas/purchase_center.py:150-164` 的 `MaterialCalcScopeGroup` **只暴露 `role_id` + `role_name`，不含 `global_role_id`**，且 `role_name` 是 best-effort 投影（docstring 明写“缺失退化为 `角色#<id>`”）→ 计算器**根本没有**字典维度的数据可用 → 前端分叉是**被契约逼出来的**。

**后果**：同一角色在计算器页显示 `角色#5`、在产品录入页显示「夏季款」；用户无法在两页间对齐“同一个角色”。

**统一方案（建议，ADR 化）：**
- **后端（先做，S）**：`MaterialCalcScopeGroup` 增加 `global_role_id: int | None`（与 `role_id` 并列），使计算器可持字典身份；并保证 `role_name` 由全局字典补齐（不再前端兜底）。
- **前端（M）**：抽 `composables/useRoles.ts`（单一查询 + 缓存，暴露 `{globalRoleId, productRoleId, name}`）+ 共享 `RoleBadge.vue`/`RolePicker.vue`；**删除** `roleMatrix.ts::scopeNameOf` 的 `角色#<id>` 兜底（命名归一化只留一处）。
- **验收**：两页同一 `global_role_id` 必须渲染**同名字符串**（可加契约测试）。

---

### 🟢 F10 — 正向结论：反向依赖实测 = 0

**复核命令**：`_archi_scan2.py` §C3b/C3c（`_archi_scan2.out:1-120`）
- `core/* → api/*` 真反向依赖：**仅 `main.py:28-30`**（`api.v1.router`/`api.v2.router`/`api.ws`）——**组合根（composition root），符合架构规范**。
- `services/* → api/*`：**0 处**。
- 依赖方向（`api → services/schemas/core`、`services → core/shared_models`）整体正确。
> 更正：`_archi_scan.py` 首轮 C3 把 `import fastapi` 误判为 `→api`（子串误报），已由 C3b 的 `import fastapi_app.api.*` 精确匹配推翻。

---

## 2. 架构债清单

| # | 严重度 | 债项 | 证据 | 影响面 | 修复代价(S/M/L) |
|---|---|---|---|---|---|
| D1 | 🔴 | 6 个请求 DTO 双定义；「canonical」副本全为死代码 | `_archi_scan.out:186-256`；`_archi_scan3.out:61-181`；`schemas/purchase_center.py:235,240,302,326,393` vs `endpoints/.../schemas.py:36,41,101,123,127` | 采购中心全部写接口；改“canonical”静默无效 | **S** |
| D2 | 🔴 | 响应模型弱/强类型混装 → `ResponseValidationError` 500（含错误边界缺口） | `test_calculate_material_null_code.py:1-27`；`schemas/purchase_center.py:143,167-177`；`product_routes.py:311` | `/purchase-center/calculate` 全量；已出线上事故 | **M** |
| D3 | 🔴 | 前端「角色」维度分叉（`role_id` vs `global_role_id`），无共享组件 | `utils/roleMatrix.ts:75-85` vs `bomTypes.ts:11-14`；`api/role.ts:20-27`；`MaterialCalcScopeGroup` 缺 `global_role_id`(`schemas/purchase_center.py:150-164`) | 物料计算器 / 产品录入；用户认知不一致 | **M** |
| D4 | 🟠 | `bom_service.py` 1009 行 God Service（`save_bom`186/`copy_bom`256） | `_archi_scan.out:1-10,183-195` | 核心 BOM 域改动回归成本 | **L** |
| D5 | 🟠 | 90 个函数 ≥80 行（集中 9 个模块，各 3–4 处） | `_archi_scan.out:12-114`；`_thr.out` | 可测试性/可读性/并发审查 | **L** |
| D6 | 🟠 | 事务边界两惯用法并存，缓存双失效仅覆盖手写路径 | `supplier.py:82-110` vs `product_routes.py:227,252,279` | 写接口缓存一致性 | **S** |
| D7 | 🟠 | 服务层依赖 `fastapi` 原语（`HTTPException`/`UploadFile`/`Response`） | `grep services/`：`auxiliary_service.py:12`、`auth_service.py:9,12`、`batch_import_service.py:20`、`order_batch_create.py:16` | 领域层可复用性/ARQ 侧复用 | **M** |
| D8 | 🟡 | 16 个死/幻影 DTO 沉积于 `schemas/purchase_center.py` | `_archi_scan3.out:1-59` | 误改风险、IDE 噪声 | **S** |
| D9 | 🟡 | 迁移 84 文件、双命名体系、`017`×3、2 次 merge heads | `_archi_scan.out:292-378` | 生产迁移确定性 | **M** |

**债项合计**：🔴×3、🟠×4、🟡×2。

---

## 3. ADR 式评估（三个关键决策）

### ADR-ARCHI-01：请求/响应契约的单一真相源
**状态:** Proposed | **日期:** 2026-09-17
**背景**：`schemas/purchase_center.py` 自称 canonical，但请求侧被 `endpoints/.../schemas.py` 实际接管，形成 6 组双定义 + 16 个死 DTO。
**选项**：
| 选项 | 复杂度 | 成本 | 可扩展性 |
|---|---|---|---|
| A. 维持现状（两处并存） | 低 | 低（但持续累积） | 差（D1/D8 反复复发） |
| B. 全部收口到 `schemas/` 顶层，端点只 re-export（BomSaveRequest 已走此路） | 中 | 中 | 好 |
| C. 按域拆 `schemas/purchase_center/` 包（request/response 分离） | 中高 | 中高 | 最好 |
**决策**：**选 B**（与已成功的 `BomSaveRequest` 收口一致，收益/代价最优；C 留待 D4 重构时一并做）。删除 6 个宽松副本 + 10 个死 DTO，CI 加 `deadcode` 门禁。
**影响**：变容易——契约审计可单点完成；需重新审视——所有 `from ...purchase_center.schemas import *` 的测试导入。

### ADR-ARCHI-02：错误边界统一覆盖「响应序列化期」
**状态:** Proposed
**背景**：D2 的 500 是序列化期异常逃逸统一错误处理所致。
**决策**：在 `core/exceptions.py`/中间件层注册全局 `ResponseValidationError` → 统一 500 文案 + 结构化日志（`loc` 落日志），并在契约 CI 中以“真实生产者 payload”做响应模型 `model_validate` 冒烟（`test_calculate_material_null_code.py` 已开先例，扩展为通用契约测试）。
**影响**：变容易——同类 500 收敛；需重新审视——`MaterialCalculateResponse` 扁平字段 `list` → `list[MaterialCalcRow]` 的兼容性。

### ADR-ARCHI-03：前端「角色」维度统一
**状态:** Proposed
**背景**：D3，两页两维度。
**选项**：
| 选项 | 复杂度 | 成本 | 可维护性 |
|---|---|---|---|
| A. 只在前端做映射表（`role_id ↔ global_role_id`） | 低 | 低 | 差（后端不保证数据） |
| B. 后端 `MaterialCalcScopeGroup` 增 `global_role_id` + 前端共享 `useRoles()`/`RoleBadge` | 中 | 中 | 好 |
| C. 后端统一改为只暴露 `global_role_id`（破坏性） | 中 | 高 | 好但需双版本 API |
**决策**：**选 B**（增字段=向后兼容；前端抽共享 composable 消除双实现）。
**影响**：变容易——两页角色对齐、命名单点；需重新审视——`roleMatrix.ts::scopeNameOf` 的 `角色#<id>` 兜底须移除。

---

## 4. 附：可复核命令清单

```bash
# 文件行数 + 超长函数 + 分层探针 + 契约重复 + 迁移清单
python deliverables/engineering-assurance/_archi_scan.py    # → _archi_scan.out
python deliverables/engineering-assurance/_archi_scan2.py   # → _archi_scan2.out（真反向依赖/死代码/阈值）
python deliverables/engineering-assurance/_archi_scan3.py   # → _archi_scan3.out（死类/路由导入解析/bom_service 函数表）
python -c "..."                                             # → _thr.out（阈值 60..120 函数计数）

# 运行时栈（引用 team-lead 已实测事实，未重复验证）
# nssm(1272) → prod_runner(18916) → uvicorn master(7676) → 8 workers
# erp-arq: nssm(4328) → ARQ python(16904); Redis :6379(redis-server 16448)、:6380(broker)
# arq:queue:health-check @6380 TTL=59, j_failed=0 j_retried=0 → ARQ 在线
```

---
*（Archit/Archi · 只读审查，未改动任何生产代码；分析脚本为新增只读文件）*
