# 交叉核验：QA 报告 M-1（catalog per_page 截断）——结论修正

**核验人**：主理人（Lead）｜**时间**：2026-09-17 10:4x｜**方式**：只读源码/构建产物/DB 实测
**被核验项**：QA 报告 M-1「catalog store `per_page=1000` 被后端 422 拒绝 → 下拉实际只取 200 条」

## 一、原始断言的内部矛盾

QA 同一句话里同时说了两件互斥的事：
1. `per_page=1000` → **422**；
2. 「下拉实际只取 **200** 条」。

这两者不可能同时成立。422 是**整个请求失败**（`api/request.ts:129` 直接 `Promise.reject`，422 不在 `RETRY_STATUS_CODES=[502,503,504]`，无重试、无吞错、无 clamp），结果应当是**下拉为空**，而不是"截断到 200"。

## 二、逐环节实测证据

### 1) 前端确实发 1000
- 源码 `frontend-vite/src/stores/catalog.ts:21`：`const CATALOG_PAGE_PARAMS = { page: 1, per_page: 1000 }`
- 构建产物 `frontend-vite/dist/assets/index-Bh2zx18f.js`：`ee={page:1,per_page:1e3}` —— **线上包就是 1000**（源码自 2026-08-15 `4f15ad8` 起未改，git status 干净）。

### 2) 后端三个端点全部 le=200 → 422
| 端点 | 约束 | 位置 |
|---|---|---|
| GET /products/list | `Query(20, ge=1, le=200)` | `api/v1/endpoints/product.py:82` |
| GET /customers/list | `Query(50, ge=1, le=200)` | `api/v1/endpoints/customer.py:130` |
| GET /suppliers/list | `Query(50, ge=1, le=200)` | `api/v1/endpoints/supplier.py:116` |

即：**若这三个调用真的发出，三个都会 422**。

### 3) 但它们从未被调用（关键）
全仓对 `catalogStore.*` 的属性访问穷举（`rg 'catalogStore\.[A-Za-z]+'`）：
```
HubeiSearchBar.vue:139-140   ensureActiveCustomerNames() / activeCustomerNames
useOrderForm.ts:16,19        ensureActiveCustomerNames() / activeCustomerNames
StockOutTab.vue:113,116      ensureActiveCustomerNames() / activeCustomerNames
ReportView.vue:52,55         ensureActiveCustomerNames() / activeCustomerNames
useReportData.ts:77,80       ensureActiveCustomerNames() / activeCustomerNames
```
**`ensureProducts` / `ensureCustomers` / `ensureSuppliers` 零调用**（`catalog.ts` 里只是被 `return` 导出，无人消费）。
→ `productsEntry` / `customersEntry` / `suppliersEntry` 三个 createCatalogEntry 实为**死代码**。
→ 客户下拉走的是 `/customers/active-names` **轻量端点**（`catalog.ts:100-105` 注释自陈"选择器视图实际使用的数据源"），**不受 per_page 约束影响**。

### 4) 基础数据行数实测（DB，只读；详见 `_rowcount.txt`）
| 表 | 行数 |
|---|---|
| product | **119** |
| customer | **5** |
| supplier | **5** |
| material_registration | **20** |
| product_role | 3 |

→ 即使三个 entry 被启用，**200 的上限当前也完全够用**，不存在"缺项"。

## 三、修正后的定级与建议

| 原定级 | 修正定级 | 理由 |
|---|---|---|
| MEDIUM（"下拉只取 200 条，数据 >200 会缺项"） | **MILD / 潜伏隐患（死代码）** | 调用为零 → 当前**无任何运行时影响**；且 422 而非截断，"缺项"表述不成立 |

**建议（非上线阻塞）**：二选一
- **A（推荐，最小改动）**：删除 `catalog.ts` 中未被消费的 `productsEntry` / `customersEntry` / `suppliersEntry` 三个 entry 及其导出（`catalog.ts:83-98, 115-129`），只保留 `activeCustomerNames`。消除死代码 + 消除 1000 这个雷。
- **B（保留能力）**：把 `CATALOG_PAGE_PARAMS` 的 `per_page` 改为 200，并补「按 total 翻页拉全」循环；同时移除或保留导出，视后续是否要接产品/供应商下拉。

**上线前必办清单中，M-1 可从 P0 降级**（QA 原将其列为 P0-2"确认基础数据行数并修 catalog"）。行数已确认，且调用为零 —— 不构成上线阻塞。

## 附：方法论备忘（入 rules-method）
> 核验"某接口参数超限导致功能异常"时，必须区分**请求被拒（4xx 整体失败）**与**结果被截断（200 但少数据）**——两者现象完全不同。
> 且必须穷举**该 fetcher 是否真有调用方**（死代码会让"潜在 bug"零影响）。仅凭"参数超限 + 端点有 le 约束"就下结论，会同时错判现象与严重度。
