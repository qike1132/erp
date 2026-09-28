# 滨发协同系统（binfa-erp）上线前代码质量审查报告

- **审查对象**：`D:\erp_system`（FastAPI 后端 + Vue 3 PC/移动端前端 + PostgreSQL/Redis/ARQ + Nginx/NSSM 部署）
- **审查范围**：前端 `frontend-vite/src`（80,170 行）、后端 `fastapi_app`（77,955 行）、`utils`（4,237）、`migrations`（8,745）、测试（57,958）、运维脚本（33,773）；共 2,299 个受版本控制文件
- **审查日期**：2026-09-28
- **审查方式**：静态分析 + 实际运行工具 + 逐文件阅读。所有结论均附文件:行号与实测证据；凡未实测或无法验证的，均在文中显式标注
- **基线**：`main` @ `9fe2d0a2`（工作区含**未提交**的在建改动，见 §0）

> ⚠️ **关于工具的说明（诚实声明）**：本次审查**未使用 SonarQube**（该机器未安装、无网络授权）。等价替代：
> 圈复杂度/函数长度用自研 AST/mccabe 分析器（`temp/audit_metrics.py`，按 `if/elif/for/while/except/with/boolop/推导式` 记分）；
> Lint 用项目自带 `ruff`（含 `S`=bandit 安全规则）；依赖漏洞用 `pip-audit` + `npm audit`；覆盖率用 `pytest-cov`。
> 因此本文**不提供 SonarQube 特有的"可维护性指数（SQALE）"数值**，改以圈复杂度分布、重复率、覆盖率为量化依据。

---

## 0. 关键前提：工作区存在"半成品"改动（影响结论解读）

`git status` 显示工作区有 **22 个已修改文件 + 1 个未跟踪文件**，全部属于一次**未提交的 multi-SKU 重构**。

**实测对比（同一命令、同一环境）**：

| 代码状态 | `vue-tsc --noEmit` 结果 |
|---|---|
| **HEAD（已提交）** | **exit 0，0 错误**（用 `git worktree` 拉干净检出实测） |
| **当前工作区** | **22 个错误**（其中 11 个在生产源码） |

- 生产源码错误集中在 `BeileOrderDetailDialog.vue`（6 处）与 `PatternRoomView.vue`（5 处）：
  引用了 `useBeileOrders.ts` 中被**本次改动删除**的导出（`skuOrderQty`/`rowTotalOrderQty`/`NOT_ORDERED_TIP` 等）。
  实测：HEAD 版本这些符号**存在**（各出现 2–5 次），工作区版本**已为 0 次**。
- 后端同名重构痕迹：`TODO(multi-sku-order)` 共 **95 处**，横跨 `order/approval/inventory/purchase/report/shipment` 等模块，
  注释明写"**当前依赖首 item 兼容值**"（`order.py:269`、`approval_service.py:320`、`order/commands.py:206` …）。

**结论**：**"生产代码坏了"是误判，实际是"在建分支不能按原样发布"**。
由于 `package.json` 的 `build:atomic`/`build` 第一段就是 `vue-tsc -b`，而 `build:fast` **跳过类型检查**，
存在"半成品改动经 fast 通道静默上线"的真实风险 —— 这是流程风险，不是代码缺陷。

---

## 1. 代码结构与质量评估

### 1.1 规模与复杂度实测

| 指标 | 数值 | 判读 |
|---|---|---|
| Python 函数总数 | 7,872 | — |
| **圈复杂度 ≥ 15** | **1,070 个（13.6%）** | 偏高；工业界常以 >10 为告警线 |
| 圈复杂度 ≥ 10 | 1,555 个 | — |
| 有效行 > 80 行（项目门禁阈值） | 91 个（>150 行：14 个） | 项目已把其中 52 个列入基线豁免 |
| 文件 > 1600 行（门禁阈值） | 6 个（含 3 个测试文件） | 见下 |

**圈复杂度 Top（均为真实业务/运维路径）**：

| cx | 有效行 | 位置 | 说明 |
|---|---|---|---|
| **326** | 253 | `fastapi_app/services/backup/orchestration/core.py:148` `_do_create_full_backup` | 全备份编排 |
| **317** | 217 | `fastapi_app/services/bom_service.py:643` `copy_bom` | BOM 复制 |
| 231 | 154 | `services/backup/verify/core.py:133` `verify_restore` | 还原校验 |
| 229 | 159 | `services/backup/json_backup.py:375` `restore_legacy_json` | 遗留格式还原 |
| 190 | 76 | `tasks/plan_tasks.py:65` `batch_import_plans_task` | 批量导入 |
| 184 | 256 | `services/backup/dump.py:158` `restore_database_via_psql` | psql 还原 |
| 172 | 150 | `server_manager.py:2593` `_apply_hosting_data` | 运维 GUI |

> 判读：cx>300 的长函数在本项目**不是笔误，而是"把整个编排流程塞进一个 try 块"的写法**。
> 单函数同时承担校验→加锁→执行→校验→清理→写审计，任一分支回归都难以定位。

**超大文件**：`server_manager.py`（3,222）、`tests/test_outsource.py`（1,622）、
`fastapi_app/tests/test_purchase_center.py`（1,554）、`services/backup/orchestration/recovery_test_service.py`（1,354）、
`migrations/versions/pg_standalone_001_...initial_schema.py`（1,219）。

### 1.2 "屎山"特征逐项排查（**多数不成立，是加分项**）

| 检查项 | 实测结论 |
|---|---|
| 重复逻辑块（>3 处相同实现） | **AST 级函数体克隆仅 2 组**：`schemas/order.py:19/34/66` + `endpoints/auxiliary.py:371` 的 `validate_custom_order`（4 份）；`schemas/case.py:45`、`schemas/product.py:34/59` 的 `sanitize_image_url`（3 份）。**后端函数级重复率极低** |
| 命名不规范 | ruff `N` 规则无新增告警；命名总体规范 |
| 架构分层混乱（业务逻辑侵入 UI/端点） | **部分成立**：`api/v1/endpoints/backup/validation.py`（835 行）内含 zip 解压/解密/sha256 校验/健康探针，属领域逻辑；`endpoints/purchase_center/export_utils.py`（386 行）内建 openpyxl/xlsxwriter 报表生成。**但**：实测端点内**无 ORM/裸 SQL**（仅 `monitoring.py:168`、`records.py:116` 两处），服务层不反向依赖 API 层，`import fastapi_app.main` 无循环导入 |
| 模块间耦合过高 | `services→services` 316 处；`backup` 被导入 54 次为最大枢纽。属可接受范围，需观察 |

### 1.3 真正的结构性问题（可维护性风险）

**A. 分页重复 —— 39 处 / 26 个文件**
`(page - 1) * per_page` 模式在 `case/queries.py:94,138,258,301,347`、`order_batch_service.py:266,324,363`、
`outsource/_queries.py:120` 等 **26 个文件、39 处**重复；全库 `.offset()/.limit()` 共 107 处。
项目已有 `enhanced_pagination.py` 但仅 4 个文件在用。
→ **后果**：off-by-one / limit 上限缺失类 bug 需在 39 处分别修。
→ **方案**：`paginate(stmt, page, per_page)` 单点化（含 limit 上限钳制）。**4–6 人时**

**B. 错误处理双轨制 —— `raise HTTPException` 276 处 vs 类型化 `AppError` 58 处**
`NotFoundError/BusinessError/ConflictError` 体系已存在（用了 58 次）但与 276 处裸 `HTTPException` 并存；
`get_async_db as get_db` 别名（`supplier.py:15`）、`get_async_db_context()` 手工会话（`monitoring.py:121,136,167`）与主流
`Depends(get_async_db)+db_transaction`（235 处）三套写法并存。**4–6 人时**

**C. 用中文错误文案反推 HTTP 状态码（脆弱、与语言耦合）**
`material_registration.py:174,218,260,359`（4 处）、`supplier.py:102`、`backup/records.py:109`：
```python
status_code = 404 if '不存在' in msg else 400
```
→ 改一句文案就静默改掉状态码。应改为服务层抛类型化异常。**6–8 人时**

**D. 死代码：5 个 `utils/` 模块零引用**
实测活引用数：`utils/notification.py`=0、`utils/batch_import_handler.py`=0、`utils/reports.py`=0、
`utils/batch_handler.py`=0、`utils/date_utils.py`=0；`utils/excel_handler.py` 仅被已死的 `batch_handler.py` 引用（传递性死代码）。
它们与在用的 `services/notification_service.py`、`services/batch_import_service.py` **平行存在**，易误改。**2–4 人时**

---

## 2. 代码复用性分析

### 2.1 UI 组件复用（前端）

**结论：UI 套件采用率高，不是主要问题。** 实测 `UiDataTable` ≈15 个视图、`UiPagination` ≈18 个组件、
`UiDialog/UiConfirmDialog` 49 个文件、`UiBadge/UiStatusBadge` 已存在。

**唯一显著缺口：状态语义与徽章样式重复（~17 套样式 + 22 处标签函数）**

| 类型 | 数量 | 位置示例 |
|---|---|---|
| 手写 `statusLabel/statusClass/statusColor` | 22 处 | `mobile/views/purchase/MPurchaseView.vue:168`、`mobile/views/shipment/MShipmentView.vue:157`、`views/approval/composables/useApproval.ts:96`、`views/outsource/OutsourceShipmentView.vue:227`、`views/outsource/composables/useOutsourceProcess.ts:248`、`OutsourceShipmentDetailDialog.vue:104`、`components/backup/BackupActions.vue:98,105` |
| 独立徽章 CSS 方案 | ~17 套 | `us-badge`/`sp-status-badge`/`ap-badge`/`osv-status-badge`/`m-badge` … |

**`src/utils/` 下没有 `status.ts`** —— 状态字典散落 5 处（`MStatusBadge.vue:19`、`MaterialDetailDialog.vue:82`、
`PlanDetailDrawer.vue:62`、`PlanDetailCardList.vue:85`、`useOrderList.ts:48`）。
→ 后果：同一状态在 PC/移动/各模块间**语义与配色会漂移**。
→ **方案**：single source `src/utils/status.ts`（`{label, variant}` 映射），`UiStatusBadge` 直接吃 `status`。**8–10 人时**

### 2.2 业务逻辑复用（前端最重的一处）

**`src/views/purchase/composables/useSummaryModal.ts` = 931 行**（全库最大文件，门禁阈值 400 的 2.3 倍），
把**三类关注点**混在一处：
- 纯损耗率数学（`magnifyByLossRate`/`ceilMagnifiedByLossRate`/`unmagnifyByLossRate`，L42–106）
- 工厂/供应商 HTML 构建（`buildFactoryHtml` L148+）
- 导出器（`downloadAsXls` L204）与 Modal 响应式状态

采购是**收入核心链路**，回归代价最高。且纯函数被锁在 `views/` 下，**移动端/委外无法复用**。
→ **方案**：拆 `utils/lossRate.ts`（纯数学）+ `utils/summaryExport.ts`（HTML/导出）+ 瘦身 composable（<300 行）。**6–8 人时**

附带：`useSummaryModal.ts:204-217` 的 `downloadAsXls` 与 `utils/xls.ts:21` 的 `downloadXls` 是**功能克隆**。**0.5 人时**

### 2.3 工具函数复用（前端）

- **日期格式化重复**：`utils/format.ts`（`formatDate/toISODate` 等）已被 ~18 个文件使用（好），
  但**手写拼 `YYYY-MM-DD` 仍有 ~9 处**：`ProductionView.vue:156`、`useProductionEntry.ts:50`、`useOrderForm.ts:14-15`、
  `useCreateShipmentPlan.ts:35`、`ImportPanel.vue:210`、`UiDateRangePicker.vue:61-62`、`ProjectCardItem.vue:156`、
  `useProjectGrouping.ts:55`、`useDashboardMobileData.ts:20,35`。**2–3 人时**
- **防抖样板重复**：`debouncedSearch + onSearchInput + clearSearch` 三件套在
  `useSupplier.ts:41-59`、`useCustomer.ts:33`、`useApproval.ts:43`、`useCaseInventory.ts:59`、`PurchasePlanView.vue:135` 重复 5 份，
  而 `useDebouncedSearch` **已存在且其中 3 个文件已 import**（只是没用）。**3 人时**
- **抽象债**：4 个通用列表 composable 并存，实测 `useListQuery`=0 引用、`useVirtualScrollList`=0 引用、`usePagedSearch` 仅测试引用，只有 `useEnhancedList`（`ProductTable.vue` 1 处）在用。**3–4 人时**

### 2.4 桌面端 vs 移动端

**API 契约共享良好**：移动端统一 `import from '@/api'`，并复用 `useMaterialCalculator`/`useNotifications`；
20 个 `M*` 组件是有意的移动设计层，**不是重复实现**。
问题在**视图内逻辑**：移动端 5,800 行只有 1 个本地 composable（`useDashboardMobileData.ts`），
状态/日期格式化在 `.vue` 里重写。**4–5 人时**（与 §2.1 的 `status.ts` 一并解决）

---

## 3. 技术栈与依赖评估

### 3.1 安全扫描（实测，非引用）

| 生态 | 命令 | 结果 |
|---|---|---|
| Python 生产依赖 | `pip-audit -r requirements/base.txt` | **78 个包，0 个已知漏洞** ✅ |
| 前端依赖 | `npm audit` | **3 个 moderate，全部为 dev-only**（`vitest`/`@vitest/coverage-v8`/`@vitest/mocker` 的 mock 路径穿越）；**生产依赖 0 高危/严重** ✅ |

> 注：`pip-audit` 首次运行**崩溃**——`pip_requirements_parser` 用 `gbk`(cp936) 解码 UTF-8 的 `requirements/*.txt`，
> `UnicodeDecodeError`。**这是一条真实发现**：中文 Windows 下该工具链（及任何走 `pip_requirements_parser` 的工具）
> 对含中文注释的 requirements 不可用。**规避**：`python -X utf8 -m pip_audit`。
> 项目 `CHANGELOG` 已记录同类 `file_size_gate.py` 中文控制台崩溃修复，建议一并给 requirements 解析加 UTF-8 强制。

### 3.2 冗余与过时

| 项 | 证据 | 建议 | 收益 / 成本 |
|---|---|---|---|
| `opentelemetry-instrumentation-requests` | **零 import**（项目用 httpx，且无 httpx instrumentation） | 删除 | 0.1 人时 |
| `rollup-plugin-visualizer` | devDep，**未接线** | 删除或接线 | 0.1 人时 |
| `@babel/traverse@^8.0.4` | 直接 devDep 但未直接使用；Babel 8 属实（最新 8.0.6） | 移入 `overrides` | 0.5 人时 |
| `@capacitor/*` | `vite.config.ts` 的 `optimizeDeps.include`/`manualChunks` 引用，但**未声明依赖**、`node_modules` 中不存在 | 删除死配置或补声明 | 1 人时 |
| `starlette>=1.0.1` | 生产依赖中**唯一非精确钉** | 钉死精确版本 | 0.1 人时 |
| 无 Python lockfile | `uv.lock`/`poetry.lock`/`Pipfile.lock` 均不存在，传递依赖浮动 | `pip-compile`/`uv lock` | 2–4 人时 |
| OTel 全家桶 | 1.30.0（落后 15 个小版本至 1.45.0），且**默认生产开启** | 升级或收敛 | 8–16 人时 |
| `polars==1.35.2` | 已用（批量导入），但 ~40MB，而 `openpyxl` 已在 | 评估替换 | 4–8 人时 / 镜像 −40MB |
| `primevue` | 4.5.5（最新 5.0.1，落后 1 个大版本） | 规划升级 | 见 R3 |

### 3.3 技术选型与业务规模匹配度

**过度工程化（明确）**：**三套并行可观测性栈** —— Prometheus（`prometheus-client`）+ **完整 OpenTelemetry**
（api+sdk+4 个 instrumentation+OTLP-**gRPC** 导出器，拖入原生 `grpcio`）+ **Sentry**，
而这是**单机自托管内网 ERP**。`telemetry.py:26` 显示 OTel 默认开启。
→ 建议保留 2 套（如 Sentry 错误 + Prometheus 指标），OTel 降级为按需开关。**8–16 人时**

**工程不足（仅一处）**：可复现性 —— 无 Python lock + 一处浮动版本钉。

**选型正确、无需改动**：`asyncpg`（异步）+ `psycopg`（Alembic 同步）并存**确有理由**；
`openpyxl`（读/写）+ `XlsxWriter`（专精写）分工合理；ARQ 替代 Celery 与全异步栈一致；
`redis 5.3.1` 落后 3 个大版本但**被 `arq<6` 约束**，非疏漏。

### 3.4 性能隐患

前端打包实测（`dist/`，构建于 17:31）：

| 产物 | 原始 | 说明 |
|---|---|---|
| `dist/` 总体 | **4.3 MB** | JS 3.02 MB + CSS 565 KB |
| `vendor-primevue` | **688 KB** | 最大单块 |
| `vendor-echarts` | 570 KB | 已 `echarts/core` + 按需 `use()` **且动态导入** ✅ |
| `index-*.js`（应用共享块） | 453 KB | |
| `vendor-fa-icons` | 146 KB | 图标已按需懒加载 ✅ |

**做得对**：路由全懒加载、`manualChunks` 分包、生产无 sourcemap、`esbuild.drop:['console','debugger']`、
`primevue` 与 `echarts` 均异步、`optimizeDeps.noDiscovery`+显式 include（冷启动快）。
**风险**：Service Worker 在 install 阶段**预缓存 125 个资源 ≈3.6 MB**（后台下载）；`primevue` 单块偏大。

---

## 4. 生产级标准符合性

### 4.1 边界处理与输入校验 —— **良好**
写接口普遍使用 Pydantic schema；上传路径统一做了**扩展名白名单 + magic byte/PIL 解码 + 体积上限**
（`auth.py:423`、`tasks.py:71`、`customer_sampling/upload.py`、`backup/validation.py`）；
备份文件名用 `Path(name).name` 防穿越、存储 key 为 UUID。

### 4.2 异常与日志 —— **良好，但有 2 处硬伤**
**好**：`structlog` JSON 日志 + `X-Request-ID` 关联、审计中间件、慢请求/Prometheus 指标、
生产环境 500 返回通用文案（`main.py:349`）、422 脱敏、`sanitize_error` 生产脱敏。

**硬伤 1（Confirmed）—— 生产错误遥测形同虚设**：
`frontend-vite/src/main.ts:55` 调用 `captureException`，但**全仓不存在 `Sentry.init()`**
（`grep -rn "Sentry.init" frontend-vite/src/` 为空；引用 sentry 的文件只有 `main.ts` 一个）。
→ 前端所有异常上报是 **no-op**；`window` 的 `unhandledrejection`（`main.ts:69`）只 `console.error`，
而生产 `esbuild.drop:['console']` 会**把它也删掉**。**结论：生产前端零错误可见性。**
→ 修复：加受 `VITE_SENTRY_DSN` 保护的 `Sentry.init({app,dsn,environment,tracesSampleRate,beforeSend})`。**1–2 人时**

**硬伤 2 —— 静默 `except: pass`**：ruff `S110` 22 处（`server_manager.py` 占多数）。
运维工具中尚可接受，但会吞掉真实故障。

### 4.3 安全防护 —— **基础扎实，有 4 处待补**
**做得好的（实测确认）**：
- 鉴权覆盖完整：v1 共 33 个 `include_router`，**32 个带 router 级 `Depends(get_current_user_id)`**；
  唯一例外 `material_registration.py` 虽在文件内不写 `get_current_user`，但已被 `router.py:177` 的
  `dependencies=[Depends(get_current_user_id)]` + 每个端点 `require_any_permission(...)` **双层保护**（实测确认，非漏洞）。
  授权集中（`require_permission/require_superuser`），无端点内散落 `has_permission`。
- **Web 端 token 存 httpOnly cookie**（`auth.py:207-208`），**localStorage 无 token**；
  CSRF 双提交（`fastapi_csrf_token` cookie + `X-CSRF-Token` 头，`request.ts:72-86`）；401 单飞刷新+重放。
- JWT：`algorithms=[ALGORITHM]` 钉死、`exp`/`jti`/`type`、refresh/access 类型混淆已挡。
- 口令 Argon2id；CORS 非通配 + 生产拒绝 `null` 源与 `*` Host；HSTS/nosniff/DENY；生产绑定 127.0.0.1；生产关闭 docs。
- 注入：裸 SQL 全用绑定参数、标识符白名单、`escape_like`，无用户可控 `ORDER BY`。
- `bandit.yaml` 的豁免逐条复核：**未发现危险的豁免**。

**待补（按严重度）**：

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| S1 | **Critical** | **git 历史中含真实密钥** | `.env.production`（`DB_PASSWORD`、`SECRET_KEY`、`REDIS_PASSWORD`）、`config/.env.production`、`config/jwt/private.pem`（RSA-4096）、`android-app/release.keystore` 均曾被提交。**HEAD 已干净**（`git ls-files` 仅 `.env*.example`），且已换 ES256 + 轮换口令；但历史副本仍可克隆 |
| S2 | High | **全局限流被关闭** | `core/limiter.py:26` `Limiter(..., enabled=False, # 内网环境关闭全局限流)` → 所有 `@limiter.limit(...)` 全是空操作；仅 `/auth/login` 有手写限流。导出/报表/库存等重端点**无有效限流** |
| S3 | Medium | **鉴权存在"失败开放"路径** | `get_current_user_id_strict`/`get_current_user_strict`（`deps.py:235,268`）**已定义、已导出，但零调用点**（实测仅定义处引用）→ Redis 故障时黑名单退化为进程内 LRU，**已吊销 token 仍被接受** |
| S4 | Medium | **refresh token 不轮换** | `auth.py:344-397`：只签发新 access token，**不签发新 refresh、不吊销旧 refresh、无重用检测** → 被窃 refresh token 可用满 7 天 |
| S5 | Medium | **`/monitoring/vitals` 匿名且无限流** | `monitoring.py:204` + `router.py:270`；`sendBeacon` 无法带头故设计为公开，但每请求最多写 50 行 `web_vital` |
| S6 | Medium | **SW 缓存鉴权响应且登出不清** | `vite.config.ts:58-75` 对 `/api/v1/(dashboard|products|stock|report|customer)/` 用 `StaleWhileRevalidate`。登出只清 sessionStorage + Vue Query，**全仓无 `caches.delete`** → 共用工作站上后一用户可能读到前一用户缓存 |
| S7 | Medium | **CSP 允许 `script-src 'unsafe-inline'`** | `config/security-headers.conf:8`，因 `index.html:82-95` 有内联脚本；当前无用户可控 HTML sink（全仓 **0 处 `v-html`**、0 处 `eval`），故可利用性低，但 CSP 失去兜底价值 |

### 4.4 性能 —— 见 §3.4；另：`UiDataTable.vue:94` 的虚拟滚动**定义了但无人启用**（消费者均有分页，风险有限）

### 4.5 测试覆盖 —— **本次最需要正视的一项**

**实测数据（`pytest --cov=fastapi_app --cov=utils`，含 tests/ 与 fastapi_app/tests/）**：

| 指标 | 数值 |
|---|---|
| 收集用例 | **2,875** |
| 覆盖率（行，`fastapi_app`+`utils`） | **55.3%**（串行全量；并行跑为 55.1%，36,393 statements / ≈20,100 覆盖） |
| 覆盖率（行，仅 `fastapi_app`） | ~51% — 与上行的差异来自 `--cov` 范围不同，两者均实测 |
| **CI 覆盖率门禁** | **40%**（`.github/workflows/ci-cd.yml:39` `COVERAGE_MIN: "40"`；同文件 `:135` 内联的默认值 20 仅在未设该变量时生效）→ 实际 55% 高于门禁，**此项健康** |
| **前端测试** | **651 个用例，当前树 31 个失败**（与后端同源的未提交重构）；**前端覆盖率仅 12.00% 语句**（项目自己的 `deliverables/P0-2_前端测试补齐报告.md:15`，从 9.70% 提升而来），且 **`vitest.config.ts` 未配置 threshold、CI 也不跑前端覆盖率** |

**关键子系统覆盖率过低（>150 语句模块）**：

| 覆盖率 | 模块 |
|---|---|
| **0.0%** | `fastapi_app/shared/report_data_service.py`（**有 2 个活调用点**）、`utils/report_exporter.py`（**有 3 个活调用点**）、`utils/excel_handler.py`(死) |
| 4.6% | `services/ocr/_text_parsers.py` |
| **7.2%** | `services/backup/dump.py`（psql 还原） |
| 8.8% | `services/backup/incremental.py`（增量还原） |
| 10.7% | `services/backup/cleanup/service.py` |
| 11.1% | `services/production_summary_service.py` |
| 12.7% | `api/v1/endpoints/backup/restore.py`（**还原端点**） |
| 13.2% | `services/backup/orchestration/recovery_test_service.py` |
| 13.9% | `tasks/backup_tasks.py` |
| 15.7% | `services/batch_import_service.py` |

> **判读**：**备份/还原链路——最不可逆、最需要测试的子系统——覆盖率仅 7–16%**；
> 报表生成/导出是**活代码但 0%**。这两处是"出问题最贵"的地方。

**测试执行实测（关键，已跑完串行全量）**：

- **串行全量跑批（权威）**：`2677 passed / 32 failed / 168 skipped`，耗时 **10 分 57 秒**；覆盖率 **55.3%**。
- 并行跑（`-n 4`）：2585 passed / 16 failed / **110 errors**，其中 **`DeadlockDetectedError` 出现 194 次**
  → 那 110 个 error 是我并行跑共享同一 PG 造成的死锁，**不是产品缺陷**。
- **⚠️ 真问题：该套件是"非密闭（non-hermetic）"的，结果随运行顺序漂移 —— 我的两次运行直接证明了这一点。**
  同一个文件 `tests/test_multi_sku_inventory_stats.py`：**单独跑全通过**（与另 4 个文件同批 9 passed），
  **放进全量会话则 2 个失败**。同类：`tests/test_health_check.py::test_v1_health_check` 报
  `RuntimeError: Event loop is closed`。独立复核者亦测得同一命令在**有并发负载时 30 failed、独占时 4 failed**。
  → 后果：**绿灯不等于通过、红灯不可定位** —— 门禁失去作为判据的意义（见 §5.2 P1-8b 与 §6.3 风险表）。

**32 个失败的归因分解（逐个定位后）**：

| 类别 | 数量 | 明细 | 是否产品缺陷 |
|---|---|---|---|
| **需真实服务的用例，本机未启动后端/Nginx** | **17** | `tests/e2e_api/test_auth_flow.py`(7)、`test_write_paths.py`(7) 连接 `127.0.0.1:5002` 被拒（实测本机仅 Redis `6379` 在听）；`TestD1ProbeFalsification::test_*_live`(3) 需真实 Nginx `:3000` | **否**（但这些用例"连不上就 fail 而非 skip"本身是测试设计缺陷） |
| CI 已排除的目录 | 4 | `tests/qa/test_smoke.py`(3)、`test_database.py`(1) | 否（CI 不跑） |
| 环境相关 | 1 | `test_backup_policy_service::test_load_policy_config`：断言 `encryption_enabled is False`，本地 `.env:115` 为 `true`（`.env.example:155` 为 `false`），fixture 未固定该变量 | 否（测试未与环境隔离） |
| 在建改动引入 | 2 | `TestD6ViteConfigConsistency`（vite 缓存守卫，见下） | 否（回退即绿） |
| **已提交代码的确定性失败** | **8** | 见下表 | **是，需修** |

**8 个确定性失败**：

| 失败 | 数量 | 根因（实测） |
|---|---|---|
| `tests/test_migration_timezone.py` | 3 | `migrations/_legacy_base_guard.py:54` 的 `table_columns()` 在 Alembic 运行时上下文之外调用 `op.get_bind()` → `NameError: '_proxy' is not defined` |
| `tests/test_migrate_erp_web_dryrun.py` | 2 | 测试**硬编码 `["powershell", ...]` 且无 OS 守卫**（`tests/test_migrate_erp_web_dryrun.py:16-18`），本机 `returncode==0` 但 `stdout` 为空 → `assert 'nssm stop erp-prod' in ''`。**在 CI 的 ubuntu-latest 上 `powershell` 不存在，此文件必然失败**（除非该 job 有 pwsh 且改名为 `pwsh`） |
| `tests/test_health_check.py::test_v1_health_check` | 1 | `RuntimeError: Event loop is closed`（顺序/事件循环污染，单独跑通过） |
| `tests/test_multi_sku_inventory_stats.py` | 2 | 单独跑通过、全量会话失败 —— 顺序依赖（同上） |

**额外的重要发现（测试自带回归锁被违反）**：
`fastapi_app/tests/test_qa_prod_stack_regression.py:455` 存在一条**明确禁止 vite 缓存 handler** 的守卫：
```python
for bad in ("StaleWhileRevalidate", "NetworkFirst"):
    assert f"handler: '{bad}'" not in text, f"{fname}: 仍存在 handler '{bad}'（缓存陈旧数据）"
```
以及 `:449` 要求 `/api/` 必须是 `NetworkOnly`。
实测：**HEAD 的 `vite.config.ts` 合规**（handler 为 CacheFirst/CacheFirst/**NetworkOnly**）；
**工作区 `vite.config.ts`（已修改）新增了 `StaleWhileRevalidate`(L60) 与 `NetworkFirst`(L73)** → 守卫失败。
（`vite.config.js` 是 `.ts` 生成物且被 `.gitignore:2` 忽略，二者同时违反。）
→ 即：**在建改动不仅自身类型错误，还破坏了项目刻意建立的"禁止缓存 API 响应"的回归锁**，
且这正是 §4.3 S6 所述的安全问题来源。

**CI 实际执行范围（重要，已逐行核对 workflow）**：

- CI 主测试步骤**排除** `tests/qa`、`tests/e2e`、`tests/stress`、`tests/performance`（`.github/workflows/ci-cd.yml:73-87`），
  我本地失败中的 `tests/qa/*` 正属被排除目录。
- 另有 `-m "not flask_legacy"` **反选掉 220 个用例**；`tests/e2e_api/**` 需真实后端（`127.0.0.1:5002`）故**在 CI 恒为 skip**。
  → 即：**CI 从未真正跑过任何端到端/跨层流程**。
- `test_migration_timezone` 与 `test_backup_policy_service` **不在排除之列** → 按当前配置 **CI 应为红**。
  ⚠️ 本次无法验证 CI 实际状态（`gh` 在本机不可用），**请以 CI 面板为准**；若 CI 为绿，说明门禁未被真正执行。
- ✅ **修正一处易误判**：CI 前端步骤是 **`npm run build`**（`:200`，即含 `vue-tsc -b`），**不是 `build:fast`**。
  故 **CI 会拦住 §0 的 22 个类型错误**；`build:fast` 的风险仅存在于**本地/手工发布路径**（见 §5.1 P0-1 的措辞）。

**额外测试质量发现（严重度不低于覆盖率不足）**：

| 发现 | 证据 | 影响 |
|---|---|---|
| **"自证式"测试：测试自己重声明 ORM 模型** | `tests/test_user_management.py`、`test_stock_management.py`、`test_routes_coverage.py`、`test_shipment_limit.py` 均含 `declarative_base()` 并在 `sqlite:///:memory:` 上自建 `Product/User/StockIn` 表，**不导入生产模型/服务**（实测导入数为 0–1）。约 **55 个用例**在 CI 中"通过" | 测试的是**与生产平行的另一套 schema**；生产模型改了它不会红 —— **虚假信心**，比没有测试更危险 |
| **前端测试脆且浅** | 16 个文件断言 `style`/`className`/`innerHTML`/DOM 顺序（如 `VirtualList.dynamicHeight.test.ts` 断言内联字符串含 `'min-height'`）；71 个文件中 **44 个用裸 `mount`，仅 1 个用 testing-library** | 断言实现细节而非用户可见行为，重构即碎、真 bug 不红 |
| 前端 e2e 缺失 | `package.json` 无 `test:e2e`、无 `playwright.config.*` 与 `e2e/` 目录（CI 注释 `:203-205` 自述该步骤"必然失败"故已替换为跨端对齐检查） | 前端无端到端覆盖 |

### 4.6 配置与部署

**做得好的（实测确认）**：
- `config.py` **fail-fast 到位**：生产强制 `SECRET_KEY`≥32 字符、`ALLOWED_HOSTS` 非空且非 `*`、CORS 拒 `null`、
  PEM 必须存在、`FASTAPI_DEBUG` 默认 false、生产关 docs。**无危险默认值**。
- `prod_runner.py`：worker 数取 `UVICORN_WORKERS` 或 `min(4,cpu)`；**绑 127.0.0.1**（避开绕过 Nginx 的直连）；
  重启需"连续 3 次健康失败 + 90s 窗口 + 进程确已死"（防抖动）；退避 30/60/120/300s；SIGTERM 优雅退出；
  状态文件原子 `os.replace`；50MB 日志轮转。
- `ActionGate`（`server_manager.py:354-461`）有真实的**并发抢占锁 + 看门狗 + run_id 僵尸防护**。
- 备份/容灾设计强：ARQ 定时轮询驱动全量/增量/校验/清理；每周 `disaster_recovery_test_task` 走**真实还原**；
  AES-256-GCM + PBKDF2(600k)；**曾经的"随机密钥不可恢复"回退已被移除**（`_constants.py:43`）——历史 P0 已修。
- Migration 链**线性、恰好 1 个 head**（`pg_standalone_054`）；CI 跑 `alembic upgrade head` + `alembic check`。
- 质量门禁**实测通过**：`python scripts/quality_gate.py` → `[PASS] 无新增质量问题`（裸 except 5 < 基线 9）。

**待补（按严重度）**：

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| D1 | **High** | **运维 GUI 的破坏性操作无二次确认** | `server_manager.py` 中 `askyesno`/`messagebox.ask` **出现 0 次**；而 `:3108` 会对**全部三个生产服务**执行 `nssm remove <name> confirm`。一次误点即可拆掉生产托管 |
| D2 | High | `server_manager.py` 3,222 行上帝类 | `ServerManagerApp` 类跨 `:825-3194`（**2,370 行**），混合 GUI 主题、NSSM 控制、Redis 生命周期、进程树、日志 tail；最大方法 `_apply_hosting_data:2593-2772`（180 行）；自行解析 `.env`（`:907-922`）而非 dotenv |
| D3 | Medium | **文件规模门禁存在盲区** | `scripts/file_size_gate.py:36` `SCAN_DIRS=("fastapi_app","tests","utils","scripts")` **不含仓库根目录** → 最大的上帝文件 `server_manager.py` 恰恰**不被门禁扫描**；`frontend-vite` 也不在内 |
| D4 | Medium | 端口/服务名多处硬编码 | `5002/3000/6379` 在 `server_manager.py:54,146-147`、`server_manager_config.json`、`prod_runner.py`、`start.py` ≥4 处重复；NSSM 服务名仅在 `server_manager.py:58-72` |
| D5 | Medium | CI 无密钥扫描 | CI 只有 bandit + pip-audit；唯一密钥防线是 `.githooks/pre-commit`（可 `--no-verify` 绕过，其自身头部即标注为待办）。另：`pre-commit` 框架**未安装**，`ruff`/`ruff-format` 本地实际未跑 |
| D6 | Medium | 仓库卫生：构件已入库，`.gitignore` 形同虚设 | 实测**已跟踪**：`evidence/` 163 个（**含 103 张 PNG 界面截图，疑含业务/客户数据**）、`.archive/` 151、`deliverables/` 87、`static/uploads/` 24（**真实用户上传**）、`backups/` 17。`.gitignore` 中的 `/backups/`、`/static/uploads/` 对**已入库文件无效**，给出虚假安全感。`.git` 体积 **530 MB** |
| D7 | Medium | 前端原子切换非真原子、且删掉唯一回滚副本 | `frontend-vite/scripts/swap-dist.mjs` 为两次连续 rename，中断窗口内 `dist` 缺失 → Nginx 404；成功后**删除 `dist-old`**（唯一回滚点） |
| D8 | Medium | 迁移可重入性与数据保全 | `pg_standalone_001...`（1,219 行）**无 `IF NOT EXISTS` 守卫**，不自幂等；5 个迁移执行 `DROP TABLE`（038/041/045/047/050），**均有 downgrade 但只恢复结构不恢复数据** |
| D9 | Low | `.gitignore` 漏项 | `.superpowers/`、`.claude/` **未被忽略**（`git check-ignore` 实测）；`.claude/settings.local.json` 可能含权限/路径；`server_manager_config.json` 已入库且含机器绝对路径 |
| D10 | Low | ARQ worker 无健康探针 | `prod_runner.py:437` ARQ 无 `health_url` → 卡死但存活的 worker 不会被重启（uvicorn 会）；`check()` 无磁盘空间预检 |

> **补充（依赖工具链）**：`pip-audit` 在本机对含中文注释的 `requirements/*.txt` 直接崩溃（GBK 解码 UTF-8），见 §3.1。

---

## 5. 问题分级与优先级

### 5.1 上线前必须处理（阻断性）—— 合计约 **1.5–2.5 人日**

| 优先级 | # | 问题 | 位置 | 根因 | 改进建议 | 工作量 |
|---|---|---|---|---|---|---|
| **P0-1** | B1 | **在建改动不可发布**：22 个 vue-tsc 错误（11 处生产源码），且 `build:fast` 会跳过类型检查 | `BeileOrderDetailDialog.vue:32,86-90`、`PatternRoomView.vue:27,99,170,253,260`；`build:fast` 脚本 | 半成品 multi-SKU 重构：删除导出但消费方未同步 | 二选一：① 补齐 `useBeileOrders.ts` 导出并修 `PatternRoomView` 5 处；② 暂缓该分支。**并封堵 `build:fast` 通道**（发布必须走带 `vue-tsc` 的 `build:atomic`） | 2–4 人时 |
| **P0-2** | B2 | **在建改动破坏了自带回归锁**：`vite.config.ts:60,73` 新增 `StaleWhileRevalidate`/`NetworkFirst` | `frontend-vite/vite.config.ts:58-75` vs 守卫 `test_qa_prod_stack_regression.py:449,455` | 为"提速"加了 API 响应缓存，违反项目明令 | **回退该改动**，恢复 `/api/` 为 `NetworkOnly`；若确需缓存，先改守卫并评估 §4.3 S6 的跨账号串数据风险 | 0.5–1 人时 |
| **P0-3** | B3 | 已提交测试**确定性失败 ×5**（迁移相关 2 个文件） | ① `migrations/_legacy_base_guard.py:54` → `tests/test_migration_timezone.py`(3)；② `tests/test_migrate_erp_web_dryrun.py:16-18`(2) | ① `table_columns()` 在 Alembic 上下文外调用 `op.get_bind()`；② 硬编码 `powershell` 且**无 OS 守卫**，CI 跑 ubuntu 必然失败 | ① 将 `op.get_bind()` 移入 callable 或注入 `op/bind`；② 加 `@pytest.mark.skipif(sys.platform!='win32')` 或改用 `pwsh` 并跳过；两者各补串行可跑回归 | 2–4 人时 |
| **P0-4** | B4 | **前端生产错误零可见性** | `frontend-vite/src/main.ts:55`（无 `Sentry.init`） | Sentry 依赖已装但从未初始化；`console` 又被生产剥离 | 加受 `VITE_SENTRY_DSN` 守卫的 `Sentry.init`（含 `beforeSend` 脱敏），并把 `unhandledrejection` 接上；否则**移除依赖**避免误导 | 1–2 人时 |
| **P0-5** | B5 | **密钥残留在 git 历史** | `config/jwt/private.pem`、`.env.production`、`config/.env.production`、`android-app/release.keystore` | 早期误提交，后删除但 blob 仍在 | 已轮换（务必确认全部泄露值都已轮换，含 readonly 口令与 keystore）；随后 `git filter-repo` 清除、强推、通知所有克隆方 | 4–8 人时 |
| **P0-6** | B6 | 运维 GUI 破坏性操作无二次确认 | `server_manager.py:3108`（全仓 0 处 `askyesno`） | 未加确认环节 | 任何 `nssm remove` / 批量 stop 前加 `messagebox.askyesno` | 1–2 人时 |

> P0-1/P0-2 若选择"该分支不发布"，则工作量并入后续窗口；但**其余 P0 与分支无关，必须处理**。

### 5.2 上线后 1 个月内（非阻断，但影响稳定与合规）

| 优先级 | # | 问题 | 位置 | 工作量 |
|---|---|---|---|---|
| P1-1 | S1/S2 | 重新开启全局限流（Redis `storage_uri`）并覆盖导出/报表/库存等重端点 | `core/limiter.py:26`；`stock.py:351`、`report.py:154`、`daily_production.py:215` | 3–4 人时 |
| P1-2 | S3 | 把 `*_strict` 变体接到 admin/backup/user 等敏感路由 | `core/deps.py:235,268` | 2 人时 |
| P1-3 | S4 | refresh token 轮换 + 重用检测 | `api/v1/endpoints/auth.py:344-397` | 4 人时 |
| P1-4 | S5 | `/monitoring/vitals` 按 IP 限流 / 限制表增长 | `monitoring.py:204` | 2 人时 |
| P1-5 | S6 | 登出时 `caches.delete()` 清理 API 缓存，或把敏感端点移出 runtime caching | `stores/auth.ts:230`、`vite.config.ts:58-75` | 2–3 人时 |
| P1-6 | T1 | **补备份/还原链路测试**（当前 7–16%） | `services/backup/dump.py`、`incremental.py`、`endpoints/backup/restore.py` | 16–24 人时 |
| P1-7 | T2 | 补报表导出测试（活动代码 0%） | `shared/report_data_service.py`、`utils/report_exporter.py` | 8–12 人时 |
| P1-8 | T3 | 后端覆盖率门禁 40% → 60%+（分步收紧并在 CI 卡住） | `.github/workflows/ci-cd.yml:39` | 2 人时 + 补测 |
| P1-8b | T4 | **消除测试非密闭性**：隔离/标记顺序与负载敏感的用例（backup 文件系统/时间依赖、event-loop 关闭类），要求"串行跑批稳定绿"后才认门禁 | `fastapi_app/tests/test_backup*.py`、`tests/test_health_check.py` | 12–30 人时 |
| P1-8c | T5 | **清理"自证式"测试**：删除或改为对生产模型/服务断言 | `tests/test_user_management.py`、`test_stock_management.py`、`test_routes_coverage.py`、`test_shipment_limit.py` | 16–30 人时 |
| P1-8d | T6 | 前端补覆盖率门禁（当前 12% 且无 threshold）+ 把 DOM 细节断言改为行为断言 | `frontend-vite/vitest.config.ts`、16 个脆断言文件 | 4 人时 + 补测 |
| P1-9 | D1 | 仓库瘦身：`git rm -r --cached` 构件目录；处理 `evidence/` 中 103 张截图（含数据的应移出仓库） | `evidence/`、`.archive/`、`static/uploads/`、`backups/` | 4–8 人时 |
| P1-10 | D5 | CI 加 `gitleaks`/`trufflehog`；安装 `pre-commit` 框架让 ruff 真正本地生效 | `.github/workflows/ci-cd.yml`、`.pre-commit-config.yaml` | 2–4 人时 |
| P1-11 | D3 | `file_size_gate.py` 扫描范围补仓库根 + `frontend-vite`（对存量设豁免） | `scripts/file_size_gate.py:36` | 1–2 人时 |
| P1-12 | D7 | 部署保留最近 N 个 `dist-old` 作为回滚点 | `scripts/swap-dist.mjs` | 2–3 人时 |

### 5.3 上线后 3 个月内（结构性偿还）

| 优先级 | # | 主题 | 关键位置 | 工作量 |
|---|---|---|---|---|
| P2-1 | 拆分超大函数/类 | `backup/orchestration/core.py:148`(cx326/253L)、`bom_service.py:643`(cx317/217L)、`dump.py:158`(256L)、`dashboard/mobile.py:41`(242L)、`server_manager.py` 上帝类 | 24–40 人时 |
| P2-2 | 完成 multi-SKU 迁移（消除 `首 item 兼容值`） | 95 处 `TODO(multi-sku-order)`，跨 order/approval/inventory/purchase/report/shipment | 需专项 spec |
| P2-3 | 分页单点化（39 处/26 文件） | 见 §1.3 A | 4–6 人时 |
| P2-4 | 错误处理统一到 `AppError`（276 处 `HTTPException`） | 见 §1.3 B/C | 6–8 人时 |
| P2-5 | 前端抽取 `utils/status.ts` + 徽章统一（22 处/17 套） | 见 §2.1 | 8–10 人时 |
| P2-6 | 拆分 `useSummaryModal.ts`(931L) → `lossRate.ts`+`summaryExport.ts` | 见 §2.2 | 6–8 人时 |
| P2-7 | 删除 5 个死 `utils/` 模块（~2100 行） | 见 §1.3 D | 2–4 人时 |
| P2-8 | 收敛三套可观测性栈；清冗余依赖；补 Python lock | 见 §3 | 16–32 人时 |
| P2-9 | 前端日期格式化/防抖/列表抽象收敛 | 见 §2.3 | 8–11 人时 |
| P2-10 | 备份域逻辑从 API 层下沉到 `services/backup/` | `endpoints/backup/validation.py:378,562` | 16–24 人时 |

---

## 6. 最终交付物

### 6.1 整体代码质量评分：**7.0 / 10**

| 维度 | 分 | 依据（全部实测） |
|---|---|---|
| 架构分层 | 8.0 | 端点内无 ORM/裸 SQL、无反向依赖、无循环导入；扣分项：`endpoints/backup/validation.py`(835L)、`export_utils.py`(386L) 领域逻辑上行 |
| 安全 | 7.5 | httpOnly cookie + CSRF + 集中授权 + Argon2id + 参数化 SQL 全对；扣分项：限流关闭、鉴权失败开放、refresh 不轮换、密钥历史残留、CSP `unsafe-inline` |
| 依赖健康 | 8.5 | `pip-audit` 78 包 0 漏洞、`npm audit` 生产 0 高危、无第三方源、可选依赖正确门控；扣分项：无 lock、OTel 落后且冗余 |
| 可维护性 | 6.5 | 函数级重复极低（仅 2 组）；扣分项：1,070 个 cx≥15、91 个 >80 行、巨型文件、分页/错误处理双轨制 |
| 测试 | 5.0（最弱项） | 2,875 后端 + 651 前端用例；后端 55.3% 覆盖（**CI 门禁 40% 达标**）、前端仅 **12%** 且无门禁；备份/还原 7–16%、报表 0%；**套件非密闭（同文件单独跑绿、全量会话内红）**、**55 个"自证式"测试**、8 个已提交用例确定性失败、CI 从不跑端到端 |
| 生产就绪/运维 | 6.5 | prod_runner 监督扎实、fail-fast 配置、备份容灾设计强、质量门禁实测通过；扣分项：前端零错误遥测、运维 GUI 无确认、仓库卫生差（`.git` 530MB） |
| 前端工程质量 | 7.5 | 0 处 `v-html`、`any` 密度极低、路由懒加载、分包合理、API 层纪律强（有脚本强制）；扣分项：巨型 composable、状态语义重复、4 个列表抽象 3 个闲置 |

**评分依据小结**：这是一个**明显做过质量工程、且文档极其认真**的代码库——质量门禁、基线棘轮、
`prod_audit` L1–L12 分层审核、详尽的 CHANGELOG 与 runbook 都是加分项；
短板集中在"**关键路径测试不足**"（备份/还原、报表）与"**生产可观测性缺失**"，
以及一次**尚未收口的重构**遗留。**扣分不是因为烂，而是因为离"生产级完备"还差几块关键拼图。**

### 6.2 上线可行性结论：**有条件通过（Conditional GO）**

**不建议无条件按计划上线。** 建议按下列条件放行：

**放行条件（必须全部满足）**
1. **明确发布哪个树**：把 multi-SKU 重构收口（或从发布分支剥离）。**发布必须走 `npm run build:atomic`（含 `vue-tsc`），禁止 `build:fast` 上生产** —— 实测 HEAD 类型检查 0 错误，问题只在工作区。
2. 回退 `vite.config.ts` 的 API 缓存改动，使自带守卫测试重新变绿。
3. 修已提交代码的 5 个确定性失败：`migrations/_legacy_base_guard.py:54`（`test_migration_timezone` 3 条）+ `tests/test_migrate_erp_web_dryrun.py` 的 Windows 专用断言（2 条）。
4. 初始化 Sentry 或移除依赖（消除"以为有监控其实没有"的假象）。
5. `server_manager.py` 破坏性操作加二次确认（生产托管 GUI 是运维天天用的入口）。
6. 确认所有历史泄露密钥均已轮换（尤其 keystore 与 readonly 口令）。

**强烈建议同时完成（可与上线并行，1 周内）**
7. 重开限流；8. 修 `*_strict` 接线；9. 登出清理 SW 缓存；10. CI 加密钥扫描。
11. **把测试套件密闭化**：在门禁可信之前，CI 的绿灯**不能**被当作上线依据 —— 见 §4.5 与 §6.3 风险表。

**为什么仍给出"通过"而非"延迟"**：核心业务链路（订单/采购/BOM/库存）的鉴权、事务、
分层与依赖卫生均在合格线以上，且**已提交代码可构建、质量门禁实测通过**。
剩余阻断项**均可在 1.5–2.5 人日内闭环**，且大多需要"决定"而非"重写"。

**若无法在上线前闭环第 1、2、5 条，则建议延迟上线** —— 因为这三条分别对应
"发布物可能带类型错误/半成品"、"自带回归锁被违反"、"一键拆生产"。

### 6.3 关键风险点汇总与缓解

| 风险 | 触发场景 | 影响 | 缓解 |
|---|---|---|---|
| **备份/还原未经充分验证**（覆盖 7–16%，迁移链"从未端到端跑通"） | 真需要还原时才发现失败 | **最高——数据不可逆** | 上线前**做一次真实的全量还原演练**并留证；用 `recovery_test_service` 跑通；优先补 §5.2 T1 |
| **前端无错误遥测** | 生产报错用户不反馈 | 问题长期潜伏、定位靠猜 | P0-4 |
| 限流关闭 + `/vitals` 匿名 | 恶意/失控客户端打重导出端点；或匿名刷 `web_vital` | CPU/DB 耗尽、磁盘增长 | P1-1 / P1-4 |
| 鉴权失败开放 + refresh 不轮换 | Redis 抖动；token 被窃 | 已吊销/已登出会话仍可用 | P1-2 / P1-3 |
| 共用终端跨账号读到缓存响应 | 多用户共用一台机器 | 数据越权可见 | P1-5（并回退 P0-2） |
| 运维 GUI 无确认 + 端口硬编码 | 误点"卸载服务"；改端口漏一处 | 生产整体停机 / GUI 探针失灵 | P0-6 / P1-11 及 D4 |
| 半成品改动经 `build:fast` 静默上线（**仅本地/手工发布路径** —— CI 用 `npm run build`，含 `vue-tsc`，不会被绕过） | 手工发布时图快跳过类型检查 | 类型/契约错误进生产 | P0-1（封堵该通道） |
| **测试门禁不可信**：同命令在负载不同时给出 4 或 30 个失败 | 上线决策依赖 CI 绿灯 | **误判"安全可发"**（假绿比假红更危险） | P1-8b 密闭化；在此之前以**串行稳定跑批 + 人工还原演练**替代绿灯 |
| **"自证式"测试制造虚假信心**：55 个用例在自建 sqlite schema 上跑 | 生产模型/服务变更 | 真实回归被掩盖 | P1-8c |
| 仓库含业务截图与历史密钥 | 仓库权限扩大 / 被 fork | 数据与凭据泄露 | P0-5 / P1-9 |

### 6.4 分阶段改进路线图

**阶段一 · 上线前（目标 ≤2.5 人日）**
- P0-1 收口/剥离 multi-SKU 分支，封堵 `build:fast` 发布通道
- P0-2 回退 vite API 缓存改动，守卫测试转绿
- P0-3 修 `_legacy_base_guard.py:54`，`test_migration_timezone` 转绿
- P0-4 Sentry 初始化（或移除）
- P0-5 确认轮换 + 启动 `git filter-repo`
- P0-6 运维 GUI 破坏性操作加确认
- **出口标准**：`vue-tsc` 0 错误；`scripts/quality_gate.py` PASS；**串行全量跑批稳定绿**（而非仅 CI 绿 —— 见非密闭性）；一次真实还原演练成功

**阶段二 · 上线后 1 个月（约 12–18 人日）**
- 安全闭环：P1-1…P1-5
- 测试补齐：P1-6（备份/还原优先）、P1-7、P1-8（后端门禁 40%→60%）、**P1-8b 密闭化**、**P1-8c 清理"自证式"测试**、**P1-8d 前端覆盖率门禁**
- 工程卫生：P1-9 仓库瘦身、P1-10 CI 密钥扫描、P1-11 门禁盲区、P1-12 回滚副本
- **出口标准**：备份/还原覆盖率 ≥60%；后端门禁 ≥60% 且 CI 卡住；前端有覆盖率门禁且 ≥30%；**串行跑批连续 3 次结果一致**；前端错误可见；仓库体积显著下降

**阶段三 · 上线后 3 个月（约 90–140 人日，按需排期）**
- 结构偿还：P2-1 拆超长函数/类、P2-3 分页单点化、P2-4 错误处理统一、P2-5/P2-6 前端复用重构、P2-7 删死代码、P2-9 工具函数收敛
- 专项：P2-2 完成 multi-SKU 迁移（消除"首 item 兼容值"）
- 技术栈收敛：P2-8 三套可观测性栈收敛、清冗余依赖、补 Python lock
- **出口标准**：cx≥15 函数较当前下降 ≥30%；`utils/status.ts` 单一来源；无 `TODO(multi-sku-order)` 兼容值

---

## 附录 A · 实测命令与原始证据（可复现）

```bash
# 类型检查（干净 HEAD vs 工作区）
git worktree add --detach <tmp> HEAD && cd <tmp>/frontend-vite && npx vue-tsc --noEmit   # HEAD: exit 0
cd frontend-vite && npx vue-tsc --noEmit                                                # 工作区: 22 errors

# 质量门禁（项目自带）
python scripts/quality_gate.py            # → [PASS] 无新增质量问题（裸 except 5 < 基线 9）

# 依赖安全
python -X utf8 -m pip_audit -r requirements/base.txt --format json   # 78 包 / 0 漏洞
npm audit --json                                                     # 3 moderate，均 dev-only

# 测试与覆盖率
python -X utf8 -m pytest fastapi_app/tests tests -q --cov=fastapi_app --cov=utils
# 串行全量：2677 passed / 32 failed / 168 skipped（10m57s）；行覆盖率 55.3%
# 并行 -n4 ：2585 passed / 16 failed / 110 errors，其中 194× DeadlockDetectedError（并行不安全，非产品缺陷）
# 顺序依赖举证：tests/test_multi_sku_inventory_stats.py 单独跑 9 passed，全量会话内 2 failed

# 复杂度/重复（自研 AST 分析器）
python temp/audit_metrics.py   # 7,872 函数；cx>=15: 1,070；>80 行: 91；函数体克隆(>=3份): 2 组
```

**关键实测数字速查**：圈复杂度 ≥15 共 **1,070** 个（最高 **326**）；>80 行函数 **91** 个；
后端函数级重复仅 **2** 组；分页重复 **39 处/26 文件**；前端状态标签重复 **22 处**；
后端测试 **2,875 用例 / 串行 2677 passed / 32 failed**、覆盖率 **55.3%**（备份/还原 **7–16%**，报表 **0%**）；
前端测试 **651 用例 / 当前树 31 failed**、覆盖率 **12%**；CI 覆盖率门禁 **40%**（后端达标、前端无门禁）；
`pip-audit` **0 漏洞**；包体 **4.3MB**（`vendor-primevue` 688KB）；`.git` **530MB**。

## 附录 B · 本次审查的置信度与未覆盖面

- **已独立复核的关键结论**（不采信任何单一来源的陈述）：HEAD/工作区类型检查、质量门禁结果、
  限流开关、Sentry 是否初始化、`*_strict` 接线、refresh 轮换、运维确认弹窗、vite 守卫违反、
  密钥历史与已入库构件、备份策略测试的环境依赖、`test_migration_timezone` 根因、
  "自证式"测试（4 个文件实测 `declarative_base()`）、前端 12% 覆盖率（项目自有文档佐证）。
- **本次复核中否定或修正的结论（4 条）** —— 记录在此以示审查可回溯：
  1. ❌ 子代理称"**质量门禁当前为红、CI 会阻断发布**" → **实测 `quality_gate.py` 为 PASS**（裸 except 5 < 基线 9）。已否定。
  2. ❌ 子代理称"`fastapi_app/tests/test_security_and_batch.py:159-160` 在**模块导入期**设置 `os.environ`，污染每个会话" → 实测该赋值位于**三引号字符串 `test_script = '''...'''` 内**（供子进程执行），不在采集期执行。已否定。
  3. ❌ 子代理称"CI 前端用 `npm run build:fast`" → 实测 workflow 用的是 **`npm run build`**（含 `vue-tsc`）。已修正（§4.5）。
  4. ✅ **我自己的初稿把 CI 覆盖率门禁写成 20%** → 实测为 **`COVERAGE_MIN: "40"`**（`:39`），20 只是内联默认值。已在 §4.5 更正。
- **未能覆盖**：
  1. **未访问真实运行中的系统**（未做运行时/负载/渗透测试），所有安全结论均为静态分析；
  2. **未验证 CI 实际状态**（`gh` 本机不可用），§4.5 的"CI 应为红"是**基于 workflow 配置的推断**（并已发现 `test_migrate_erp_web_dryrun.py` 在 ubuntu 上必然失败这一独立佐证）；
  3. **未使用 SonarQube**，故无 SQALE 可维护性指数（见文首声明）；
  4. 前端 `npm run test` 与 `npm run build` **未完整跑完**（时间盒限制）；前端结论以静态分析、`dist` 实测与他人复现的 31 个失败为主；
  5. `migrations/` **未在真实新建库上执行 `upgrade head`** 验证；
  6. §4.5 的失败归因基于**本机环境**（无后端在 `:5002`、无 Nginx 在 `:3000`）；在生产机上跑同一套件，那 17 个"需真实服务"的用例结果会不同。
