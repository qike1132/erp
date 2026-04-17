# ERP System - Comprehensive Code Quality & Performance Audit Report

**Audit Date:** 2026-04-17  
**Scope:** Full-stack (Flask + FastAPI backend, Vanilla JS frontend, infrastructure, toolchain)  
**Methodology:** Dual-strategy audit (Breadth-first 6-dimension checklist + Depth-first execution path tracing), iteratively verified  

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| **P0 (Critical)** | 11 | Runtime crashes, data corruption, security vulnerabilities (XSS, auth bypass), missing dependencies |
| **P1 (High)** | 30 | Performance bottlenecks, code duplication, resource leaks, authentication gaps, cross-browser issues |
| **P2 (Medium)** | 40 | N+1 queries, structural issues, configuration weaknesses, responsive design gaps |
| **P3 (Low)** | 22 | Naming inconsistencies, unused imports, minor code smells, accessibility gaps |
| **Total** | **103** | |

**Top 5 Most Impactful Issues:**
1. XSS via unescaped `innerHTML` in `stockin.html` and `stockout.html` - **arbitrary JavaScript execution** from user-controlled data
2. JWT Token never expires (`deps.py:29-30`) - **permanent access** on token leak
3. `AsyncNumberGenerator.generate()` method does not exist - **runtime crash** in batch stockin/stockout (`stock_service.py:517,597`)
4. File upload endpoint missing authentication (`auth.py:183-215`) - **anyone can upload files**
5. Race condition in number generation - **duplicate order numbers** under concurrent load (`batch_service.py:82-101`)
3. `slowapi` missing from `requirements/base.txt` - **fresh install will fail** (`fastapi_app/main.py:11-14`)

---

## Part 1: P0 Critical Issues

### P0-1: AsyncNumberGenerator.generate() Does Not Exist (Runtime Crash)

**File:** `fastapi_app/services/stock_service.py:517,597`  
**Impact:** `batch_create_stockins()` and `batch_create_stockouts()` will raise `AttributeError` at runtime

```python
# Line 517 - CRASH
stockin_no = await AsyncNumberGenerator.generate('SI', StockIn, 'stockin_date', 'stockin_no', db)
# Line 597 - CRASH
stockout_no = await AsyncNumberGenerator.generate('SO', StockOut, 'stockout_date', 'stockout_no', db)
```

The `AsyncNumberGenerator` class only has methods: `__new__`, `is_initialized`, `set_initialized`, `reset_counter`, `get_next_seq`. There is no `generate()` classmethod. The correct call should use the module-level `generate_number_async()` function.

**Fix:**
```python
# stock_service.py:517
from fastapi_app.services.batch_service import generate_number_async
stockin_no = await generate_number_async('SI', StockIn, 'stockin_date', 'stockin_no', db)

# stock_service.py:597
stockout_no = await generate_number_async('SO', StockOut, 'stockout_date', 'stockout_no', db)
```

---

### P0-2: Race Condition in AsyncNumberGenerator (Duplicate/Skipped Numbers)

**File:** `fastapi_app/services/batch_service.py:82-101`  
**Impact:** Under concurrent load, two coroutines can generate the same sequence number or skip numbers

**Root Cause:** No `asyncio.Lock` protects the check-then-init-then-increment pattern:
```python
# Line 82: Check (non-atomic with the init below)
if not _async_number_generator.is_initialized(prefix, date_str):
    # Line 83: YIELDS CONTROL here - another coroutine can interleave
    result = await db.execute(...)
    # Line 99: Initialize
    _async_number_generator.get_next_seq(prefix, date_str, db_max)
# Line 101: Increment
current_seq = _async_number_generator.get_next_seq(prefix, date_str, 0)
```

**Fix:** Add an `asyncio.Lock` per prefix:
```python
import asyncio
_locks: dict[str, asyncio.Lock] = {}

def _get_lock(prefix: str, date_str: str) -> asyncio.Lock:
    key = f"{prefix}:{date_str}"
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]

async def generate_number_async(prefix, model, date_field, number_field, db):
    lock = _get_lock(prefix, datetime.now().strftime('%Y%m%d'))
    async with lock:
        # ... existing logic ...
```

---

### P0-3: get_inventory() Loads All Data Into Memory (O(P*C*S) Complexity)

**File:** `fastapi_app/services/stock_service.py:349-479`  
**Impact:** With 1000+ products and thousands of orders/stockins, this causes severe latency and memory pressure

**Problem Breakdown:**
- Line 361-374: `selectinload` loads ALL products with ALL orders and stockins into memory
- Line 387-393: Loads ALL stockouts separately
- Line 422: `all_stockouts_for_product = [so for so in all_stockouts if so.product_id == product.id]` - linear scan for each product = O(P*T)
- Line 435-452: Triple-nested loop (products x customers x stockins) with in-memory filtering

**Fix:** Replace the entire in-memory aggregation with a SQL query using GROUP BY:
```python
async def get_inventory(db, search_customer='', search_product=''):
    stmt = (
        select(
            Product.name.label('product_name'),
            Product.barcode.label('product_barcode'),
            Order.customer,
            func.coalesce(func.sum(Order.quantity), 0).label('order_qty'),
            func.coalesce(func.sum(StockIn.quantity), 0).label('stockin_qty'),
            func.coalesce(func.sum(StockOut.quantity), 0).label('stockout_qty'),
        )
        .select_from(Product)
        .outerjoin(Order, and_(Order.product_id == Product.id, ...))
        .outerjoin(StockIn, ...)
        .outerjoin(StockOut, ...)
        .group_by(Product.id, Order.customer)
    )
    # Apply filters at SQL level, not in Python
```

---

### P0-4: Missing Dependency `slowapi` in requirements/base.txt

**File:** `fastapi_app/main.py:11-14` imports `slowapi` but `requirements/base.txt` does not list it  
**Impact:** Fresh installation will fail with `ModuleNotFoundError: No module named 'slowapi'`

**Fix:** Add `slowapi>=0.1.9` to `requirements/base.txt`

---

### P0-5: God File - purchase_center_service.py (1907 lines, 7+ domains)

**File:** `fastapi_app/services/purchase_center_service.py`  
**Impact:** Maintenance nightmare, impossible to test in isolation, sync/async split prevents code sharing

This single file handles: Product/BOM, Material Calculation, Supplier CRUD, Customer Management (duplicating `customer_service.py`), Purchase Orders, Unprocessed Orders, Modification Logs, Factory Summary, BOM Copy - all using synchronous `Session` while the rest of the system uses `AsyncSession`.

**Recommended decomposition:**
| New Module | Extracted Functions | Lines |
|------------|-------------------|-------|
| `purchase_product_service.py` | `get_products`, `get_products_batch_bom`, BOM save/copy | ~400 |
| `purchase_material_service.py` | `calculate_material` | ~55 |
| `purchase_supplier_service.py` | `get_suppliers`, CRUD, `_sync_supplier_info` | ~160 |
| `purchase_order_service.py` | Order CRUD, complete, batch, generate | ~400 |
| `purchase_summary_service.py` | Factory summary, supplier groups | ~290 |
| `purchase_query_service.py` | Saved queries, status logs, modification logs | ~80 |

---

### P0-6: staging_service.py - 3 Nearly Identical Import Functions

**File:** `fastapi_app/services/staging_service.py:249-386, 518-638, 820-953`  
**Impact:** ~360 lines of copy-pasted code; any bug fix must be applied 3 times

Three `import_staging_*_from_excel()` functions share ~80% identical code (Excel parsing, temp file handling, product map building, error handling). Only the sheet name, column names, and entity creation differ.

**Fix:** Extract generic function:
```python
async def _import_staging_from_excel(db, file_content, session_id, Model, sheet_name, 
                                       column_map, entity_builder, ...):
    """Generic staging import - parameterized by model and column mapping"""
    ...
```

---

## Part 2: P1 High Issues

### Algorithm & Data Structure

| # | File:Line | Issue | Impact |
|---|-----------|-------|--------|
| P1-1 | `purchase_center_service.py:379-396` | N+1 query in `get_suppliers(with_stats=True)` - one COUNT query per supplier | O(S) queries |
| P1-2 | `purchase_center_service.py:318-330` | N+1 query in `calculate_material()` - `db.get(Product, id)` inside loop | O(K) queries |
| P1-3 | `purchase_center_service.py:731-840` | N+1 query in `one_click_generate_order()` - individual order fetches | O(O) queries |
| P1-4 | `purchase_center_service.py:90-100` | Lazy-loaded relationship access in loop - `has_bom()`/`get_all_materials()` per product | O(P*R) queries |
| P1-5 | `batch_service.py:293-311` | N+1 query in `calculate_available_shipment_quantity()` - one SUM query per order | O(O) queries |
| P1-6 | `stock_service.py:422` | Linear scan `all_stockouts` per product instead of dict lookup | O(P*T) |
| P1-7 | `material_registration_service.py:17-84` | 4 separate COUNT queries that should be one GROUP BY | 4x query overhead |

### Code Structure & Modularity

| # | File:Line | Issue |
|---|-----------|-------|
| P1-8 | `purchase_center_service.py:541-612` | Customer management duplicates `customer_service.py` (sync vs async) |
| P1-9 | `purchase_center_service.py:48-178` | Product queries duplicate `product_service.py` (sync vs async) |
| P1-10 | `purchase_center_service.py:181-311` | `save_product_bom()` is a 130-line god method |
| P1-11 | `purchase_plan_service.py` vs `production_plan_service.py` | 8+ duplicated functions: `_last_day_of_month`, `_normalize_plan_date`, `_build_inventory_map`, `_calc_shipment_status`, `upload_excel`, `validate_staging` |
| P1-12 | `staging_service.py:115-147,420-449,672-710` | `update_staging_*()` - identical 8-line product validation block copied 3 times |

### Resource Management

| # | File:Line | Issue |
|---|-----------|-------|
| P1-13 | `ocr_service.py:27` | `_progress_store` dict grows unboundedly - no TTL or eviction |
| P1-14 | `ocr_service.py:537` | PyMuPDF document not closed on exception - should use `with fitz.open(...)` |
| P1-15 | `batch_service.py:347,372` | `pd.ExcelFile` objects never closed - file handle leaks |
| P1-16 | `report_service.py:97,219,343,468` | `export_report_to_excel` defined 4 times - only last one used; dead code creates Flask apps per call |

### Frontend

| # | File:Line | Issue |
|---|-----------|-------|
| P1-17 | `order.js:1043-1203,1231-1392` | Duplicate rendering logic `renderGroupedOrderList()` vs `renderGroupedOrderListLocal()` (~150 lines) |
| P1-18 | `purchase-center.js:134-203` | 4 near-identical API helpers duplicating `api-client.js` functionality |
| P1-19 | `order.js,product.js` | Direct `fetch()` calls bypass centralized `api-client.js` (missing CSRF, retry, error handling) |
| P1-20 | `product.js:74-123` | Missing `response.ok` check in `uploadImage()` - non-2xx responses will crash JSON parse |
| P1-21 | `api-client.js:267-313` | Double-enqueue of requests on 401 - `_addPendingRequest` before throw + `_handleUnauthorized` adds again |

### Boundary & Exception Handling

| # | File:Line | Issue |
|---|-----------|-------|
| P1-22 | `purchase_center_service.py:310` | `db.commit()` without try/except - session left inconsistent on DB error |

---

## Part 3: P2 Medium Issues

### Algorithm & Data Structure

| # | File:Line | Issue |
|---|-----------|-------|
| P2-1 | `purchase_center_service.py:619-633` | Full table scan + in-memory max for `_generate_order_no()` - should use SQL `MAX()` |
| P2-2 | `purchase_center_service.py:992-1017` | N+1 query in `batch_complete_purchase_orders()` |
| P2-3 | `purchase_center_service.py:1649-1673` | N+1 in `search_products_for_bom_copy()` - re-queries each product individually |
| P2-4 | `purchase_center_service.py:1297-1304` | O(T^2) nested linear scan in `query_supplier_groups()` - should use dict lookup |
| P2-5 | `purchase_center_service.py:1886-1894` | N+1 in `batch_delete_purchase_orders()` |
| P2-6 | `batch_service.py:410-451` | N+1 in `import_products_from_data()` - per-row product name check |
| P2-7 | `batch_service.py:634-717` | N+1 in `import_stockouts_from_data()` - no product map pre-loading |
| P2-8 | `material_registration_service.py:438-462` | Loads ALL registrations into memory to count statuses |

### Resource Management

| # | File:Line | Issue |
|---|-----------|-------|
| P2-9 | `ocr_service.py:493-527` | `page_images` holds large numpy arrays - no chunked processing for large PDFs |
| P2-10 | `batch_service.py:29-30` | `AsyncNumberGenerator._counters/_initialized` never cleaned - slow memory growth |
| P2-11 | `report_service.py:107-109` | Flask app created per export call - expensive connection pool initialization |
| P2-12 | `main.py:271-278` | Flask app created per WebSocket connection for cookie verification |
| P2-13 | `main.py:343-351` | New Redis connection per health check - should use connection pool |
| P2-14 | `main.py:258-296` | WebSocket connections have no heartbeat timeout - stale connections persist indefinitely |
| P2-15 | `run.py:106-113` | Port 5002 detection matches unintended ports (e.g., 50020) |
| P2-16 | `run.py:171-175` | uvicorn stdout/stderr redirected to DEVNULL - crash logs silently discarded |

### Code Structure

| # | File:Line | Issue |
|---|-----------|-------|
| P2-17 | `purchase_center_service.py:843-885,1020-1084` | `get_purchase_orders()` and `get_completed_purchase_orders()` share ~70% filter logic |
| P2-18 | `staging_service.py:80-97,391-399,643-651` | Identical query/filter/map pattern for 3 staging entity types |
| P2-19 | `stock_concurrency.py:55-117` | `update_stock_with_optimistic_lock` is dead code - never called |
| P2-20 | `purchase-plan.js` vs `production-plan.js` | Duplicate `apiFetch()` helpers across frontend files |

### Frontend

| # | File:Line | Issue |
|---|-----------|-------|
| P2-21 | `order.js:55-66` | Event listener leak in autocomplete - new click listeners on every keystroke |
| P2-22 | `product.js:20-35` | MutationObserver on `document.body` never disconnected |
| P2-23 | `product.js:108` | XSS risk in image preview - `escapeHtml` doesn't sanitize URL-based attacks |
| P2-24 | `purchase-center.js:191-203` | Missing auth check in `apiDelete()` - 401 on DELETE silently fails |
| P2-25 | `api-client.js:301-305` | Fragile retry detection - string-matching `err.message.includes('500')` |
| P2-26 | `order.js:1016-1021` | Fire-and-forget DELETE in `beforeunload` - orphaned staging orders if it fails |

### Boundary & Exception Handling

| # | File:Line | Issue |
|---|-----------|-------|
| P2-27 | `stock_concurrency.py:35-36` | No lock timeout on pessimistic lock - uses global 50s `innodb_lock_wait_timeout` |
| P2-28 | `stock_concurrency.py:112` | `await db.rollback()` in optimistic lock rolls back entire transaction (dangerous side effect) |
| P2-29 | `purchase_center_service.py:168-171` | `get_product_bom` returns `None` instead of raising exception - inconsistent with other services |

### Infrastructure

| # | File | Issue |
|---|------|-------|
| P2-30 | `docker-compose.yml` | No resource limits (memory/CPU) on any container |
| P2-31 | `docker-compose.yml` | Hardcoded Redis password in 4 places |

---

## Part 4: P3 Low Issues

### Imports & Dependencies

| # | File:Line | Unused Import |
|---|-----------|---------------|
| P3-1 | `batch_service.py:6` | `import os` - unused |
| P3-2 | `batch_service.py:7` | `import tempfile` - unused |
| P3-3 | `batch_service.py:8` | `import shutil` - unused |
| P3-4 | `report_service.py:4` | `from sqlalchemy import or_` - unused |
| P3-5 | `report_service.py:5` | `from sqlalchemy.orm import joinedload` - unused |
| P3-6 | `report_service.py:8` | `from fastapi_app.shared_models import StockOut, StockIn, Order, Product` - all unused |
| P3-7 | `product_service.py:12` | `from sqlalchemy.exc import SQLAlchemyError` - unused |
| P3-8 | `order_service.py:14` | `from sqlalchemy.exc import SQLAlchemyError` - unused |
| P3-9 | `stock_service.py:10` | `from sqlalchemy import delete, or_` - both unused |
| P3-10 | `notification_service.py:10` | `from typing import Optional` - unused |
| P3-11 | `ocr_service.py:19` | `from sqlalchemy import delete` - unused |
| P3-12 | `main.py:147,158` | `from urllib.parse import urlparse` imported inside middleware on every request |

### Naming & Semantics

| # | File:Line | Issue |
|---|-----------|-------|
| P3-13 | `ocr_service.py:1453` | `import_staging_stockouts_from_pdf` alias misleading - function handles PDFs and images |
| P3-14 | `purchase-center.js:220-223` | `formatDateTime(dt)` is a no-op function - returns input unchanged |
| P3-15 | `product.js:801-803` | `renderBomItem()` is dead code - returns empty string, never called |
| P3-16 | `purchase-center.js:100,358` | Duplicate `closeModal()` functions in global scope |
| P3-17 | `order.js:164` | Misleading variable: `cachedStockinQuantity` vs `currentAvailableStock` track same concept |

### Code Style

| # | File:Line | Issue |
|---|-----------|-------|
| P3-18 | `batch_service.py:134` | `import re` placed mid-file instead of at top |

---

## Part 5: Dependency Performance Assessment

### Redundant Dependencies (Recommended Removal)

| Package | Reason | Savings |
|---------|--------|---------|
| `fuzzywuzzy==0.18.0` | Replaced by `rapidfuzz` in production; only test file uses it | ~1MB |
| `pypinyin==0.51.0` | Only used in `test_new_libraries.py`; no production code | ~5MB |
| `gunicorn>=21.2.0` | Never imported anywhere; Windows uses waitress | ~2MB |
| `xlrd==1.2.0` | Only reads legacy `.xls`; `openpyxl` handles `.xlsx` | ~1MB |
| `charset-normalizer>=3.4` | Transitive dependency of `requests`; redundant explicit listing | ~3MB |

### Heavy But Underutilized

| Package | Size | Usage | Recommendation |
|---------|------|-------|----------------|
| `pandas>=2.1.4` | ~100MB | Only for `pd.read_excel()` in `batch_service.py` | Replace with `openpyxl.load_workbook()` direct iteration |
| `opencv-python>=4.8.0` | ~60MB | Only `cv2.imdecode()` in `ocr_service.py` | Switch to `opencv-python-headless` (-30MB) |

### Version Pinning Issues

| Package | Issue | Risk |
|---------|-------|------|
| `Flask>=3.1.0` | No upper bound; Flask 4.0 could break | Medium |
| `fastapi>=0.135` | No upper bound; FastAPI evolves fast | Medium |
| Mixed `==` and `>=` | Inconsistent strategy reduces reproducibility | Low |

### Critical Missing Dependency

| Package | Used In | Status |
|---------|---------|--------|
| `slowapi` | `main.py:11-14`, `auth.py:114` | **MISSING from requirements/base.txt** |

### OCR Stack Assessment

The OCR stack accounts for ~70% of the Docker image (~350-400MB). Consider:
- Extracting OCR into a separate microservice
- Making OCR dependencies optional (install only when enabled)
- The lazy import pattern is good but doesn't reduce image size

---

## Part 6: Development Toolchain Evaluation

### Current State

| Aspect | Status | Assessment |
|--------|--------|------------|
| **Build system** | No `package.json`, no webpack/vite | JS/CSS served raw - no minification, bundling, or tree-shaking |
| **Code quality (Python)** | No `pyproject.toml`, no `ruff`/`black`/`isort` config | No automated formatting or linting |
| **Code quality (JS)** | No ESLint, Prettier, or TypeScript | No static analysis or formatting enforcement |
| **Test coverage** | `pytest.ini` exists; `htmlcov/` present | Coverage data exists but no enforcement threshold |
| **CI/CD** | No `.github/workflows/` or equivalent | No automated build/test/deploy pipeline |
| **Docker** | `Dockerfile` + `docker-compose.yml` exist | Multi-stage build present; no layer caching optimization |

### Missing Infrastructure

1. **No frontend build pipeline** - 25+ individual JS/CSS files loaded via `<script>` tags, no minification, no source maps, no cache busting beyond `?v=` query param
2. **No automated linting** - Python: no `ruff`, `black`, `mypy`; JS: no ESLint, Prettier
3. **No CI/CD** - No automated test execution on commit; no deployment automation
4. **No coverage enforcement** - No minimum coverage threshold in CI
5. **Docker security** - No `read_only: true`, no resource limits, hardcoded passwords

---

## Part 7: Refactoring Plans & Implementation Roadmap

### Phase 1: Critical Fixes (Week 1)

**Goal:** Eliminate P0 bugs that cause runtime crashes and data corruption

| Task | File(s) | Risk | Verification |
|------|---------|------|-------------|
| Fix `AsyncNumberGenerator.generate()` calls | `stock_service.py:517,597` | Low | Send batch stockin/stockout API requests |
| Add `asyncio.Lock` to number generator | `batch_service.py:26-102` | Low | Test concurrent number generation |
| Add `slowapi` to requirements | `requirements/base.txt` | None | Fresh install test |
| Add `try/except` around `fitz.open()` | `ocr_service.py:537` | Low | OCR with corrupt PDF |

**Expected Impact:** Eliminate 2 crash scenarios, prevent duplicate order numbers

### Phase 2: Performance (Week 2-3)

**Goal:** Address N+1 queries and memory-intensive operations

| Task | File(s) | Risk | Verification |
|------|---------|------|-------------|
| Rewrite `get_inventory()` as SQL aggregation | `stock_service.py:349-479` | Medium | Compare output with current version |
| Fix N+1 in `purchase_center_service.py` (6 locations) | Multiple | Low-Medium | SQL query count logging |
| Fix N+1 in `batch_service.py` (3 locations) | `batch_service.py` | Low | Batch import performance test |
| Replace `pd.read_excel()` with `openpyxl` | `batch_service.py:343-357` | Low | Import same Excel file, compare results |
| Add Redis connection pool to health check | `main.py:343-351` | None | Health check latency test |

**Expected Impact:** 
- Inventory page load: **50-80% reduction** (SQL vs Python aggregation)
- Batch import: **60-70% reduction** in DB queries
- Docker image: **~80MB smaller** (remove pandas)

### Phase 3: Structural Refactoring (Week 3-5)

**Goal:** Decompose god files, eliminate code duplication

| Task | File(s) | Risk | Verification |
|------|---------|------|-------------|
| Decompose `purchase_center_service.py` into 6 modules | New files | High | Full regression test of purchase center features |
| Extract generic staging import function | `staging_service.py` | Medium | Test all 3 staging import types |
| Extract shared plan utilities | New `plan_utils.py` | Low | Test purchase_plan and production_plan |
| Migrate `purchase_center_service.py` to async | The file + endpoint | High | Full purchase center regression |
| Unify frontend API calls to use `api-client.js` | `order.js`, `product.js`, etc. | Medium | Test all CRUD operations |

**Expected Impact:**
- Code duplication: **~40% reduction** in service layer
- Maintainability: Single-responsibility per module
- Testability: Each module independently testable

### Phase 4: Infrastructure & Toolchain (Week 5-6)

| Task | Risk | Verification |
|------|------|-------------|
| Add `ruff` + `black` for Python linting/formatting | Low | CI passes |
| Add ESLint + Prettier for JS linting/formatting | Low | CI passes |
| Set up GitHub Actions CI pipeline | Medium | Automated test execution |
| Add Docker resource limits and security hardening | Medium | Container stress test |
| Remove redundant dependencies (5 packages) | Low | Fresh install + smoke test |
| Switch to `opencv-python-headless` | None | OCR functionality test |
| Add coverage threshold (≥80% target) | Medium | Coverage report |

**Expected Impact:**
- Docker image: **~120MB smaller** (pandas + opencv-headless + redundant packages)
- Build time: **CI pipeline** enables early detection of regressions
- Security: Eliminate hardcoded passwords, add resource limits

---

## Part 8: Verification Plan

### Functional Regression Test Matrix

| Feature | Test Method | Key Assertions |
|---------|------------|----------------|
| Order CRUD | API test | Create, read, update, delete orders; verify number uniqueness |
| Stock In/Out | API test | Batch stockin/stockout; verify inventory calculations |
| Inventory View | API test | Compare output before/after SQL rewrite |
| Batch Import | Integration test | Import Excel files for orders, stockins, stockouts, products |
| OCR Import | Integration test | Upload PDF, verify staging stockouts created |
| Purchase Center | E2E test | Full workflow: BOM -> material calc -> order generation |
| Number Generation | Concurrency test | 50 concurrent requests; verify no duplicates |
| WebSocket Notifications | Integration test | Connect, verify session, receive notification |

### Performance Benchmark Metrics

| Metric | Current (Estimated) | Target | Measurement Method |
|--------|-------------------|--------|--------------------|
| Inventory page API response (1000 products) | ~2-5s | <500ms | `time curl /api/v1/stock/inventory` |
| Batch import 100 rows | ~10s (N+1 queries) | <3s | Batch endpoint timing |
| Docker image size | ~1.2GB | <1.0GB | `docker images` |
| Fresh install (pip install) | N/A | Succeeds without ModuleNotFoundError | Clean venv test |

---

## Appendix: Audit Methodology

This audit was conducted using the **dual-strategy approach** as mandated:

1. **Breadth-first scan (6 dimensions):**
   - Algorithm & Data Structure: Analyzed time/space complexity in all 21 service files
   - Code Structure & Modularity: Evaluated god files, code duplication, DRY violations
   - Naming & Semantics: Checked variable/function naming, misleading aliases
   - Resource Management: Traced file handles, connections, memory lifecycle
   - Imports & Dependencies: Verified all imports against actual usage
   - Boundary & Exception Handling: Checked error handling, null safety, transaction safety

2. **Depth-first execution path tracing:**
   - Traced 5 critical methods end-to-end: `get_inventory()`, `generate_number_async()`, `import_staging_stockouts_from_file()`, `one_click_generate_order()`, WebSocket notification handler
   - For each: identified all callers, traced data flow, checked statement order, identified blocking points, verified thread safety, checked resource lifecycle

3. **Iterative verification:**
   - All P0 findings were verified by reading actual source code
   - Race condition in AsyncNumberGenerator was traced step-by-step through interleaved coroutine execution

4. **Second-round iterative audit (new findings):**
   - Audited Flask application layer, Flask routes, database models, security, configuration, Celery tasks
   - Audited HTML templates for XSS, accessibility, CSRF, and responsive design
   - **5 new P0 issues found** (XSS vulnerabilities, authentication bypasses, JWT never expires)
   - **8 new P1 issues found** (CSRF exemptions, missing auth, LIKE injection, Firefox breakage)
   - **9 new P2 issues found** (DELETE via GET, duplicate routes, missing indexes, responsive gaps)
   - **4 new P3 issues found** (accessibility, inline scripts, z-index, breakpoints)

---

## Part 9: Round 2 Iterative Audit Findings

### New P0 Critical Issues (Round 2)

#### P0-7: XSS via Unescaped innerHTML in stockin.html

**File:** `templates/stockin.html:431-461,473-498,803-845,875-1002`  
**Impact:** Arbitrary JavaScript execution from user-controlled data (customer names, notes, product names)

User data is injected directly into `innerHTML` without calling `escapeHtml()`:
```javascript
// Line 437
<i class="fas fa-user me-1"></i>${stockin.customer}
// Line 447
${stockin.note ? `<span ...>备注: ${stockin.note}</span>` : ''}
```
If a customer name contains `<script>alert(1)</script>`, it executes. The `escapeHtml()` function exists in `base.html:158` but is not used here.

**Fix:** Wrap all user-controlled data in `escapeHtml()`:
```javascript
<i class="fas fa-user me-1"></i>${escapeHtml(stockin.customer)}
```

#### P0-8: XSS via Unescaped innerHTML in stockout.html

**File:** `templates/stockout.html:551-595,607-632,447-452,1543-1590`  
**Impact:** Same as P0-7, plus OCR-parsed data from external documents is injected unescaped

The OCR preview section (lines 1561-1568) is especially dangerous - OCR output comes from external PDFs:
```javascript
// Line 1563
<td>${item.customer || '-'}</td>
```

#### P0-9: XSS via `| safe` Jinja2 Filter on JSON Data

**File:** `templates/stockin.html:708`, `templates/stockout.html:886`, `templates/customer_order.html:480,958`, `templates/order.html:179`, `templates/approval_detail.html:274`  
**Impact:** If database values contain `</script><script>...`, they break out of the JavaScript context

```javascript
const stockinsData = {{ stockins_json | safe }};
```
**Fix:** Replace `| safe` with `| tojson` (which adds HTML-safe escaping for script contexts):
```javascript
const stockinsData = {{ stockins_json | tojson }};
```

#### P0-10: JWT Token Never Expires

**File:** `fastapi_app/core/deps.py:29-30`  
**Impact:** Leaked tokens provide permanent access

```python
# 不设置 exp 字段，Token永不过期
return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
```
The `ACCESS_TOKEN_EXPIRE_MINUTES` setting exists in config but is never used.

**Fix:**
```python
expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
to_encode.update({"exp": expire})
return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
```

#### P0-11: File Upload Endpoint Missing Authentication

**File:** `fastapi_app/api/v1/endpoints/auth.py:183-215`  
**Impact:** Any unauthenticated user can upload files to the server

```python
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # No Depends(get_current_user) or Depends(require_permission(...))
```

**Fix:** Add authentication dependency:
```python
@router.post("/upload")
async def upload_file(file: UploadFile = File(...), current_user=Depends(get_current_user)):
```

---

### New P1 High Issues (Round 2)

| # | File:Line | Issue |
|---|-----------|-------|
| P1-23 | `deps.py:94-95` | Flask session cookie never expires - stolen cookie provides indefinite access |
| P1-24 | `app/__init__.py:340-354` | 10 blueprints CSRF-exempt including `approval_bp` and `material_registration_bp` - state-changing operations without CSRF protection |
| P1-25 | `app/routes/case.py:21-27` | Case management page missing `@page_permission_required` decorator |
| P1-26 | `app/routes/report.py:94,98-99,161,165-166,222,226-227,279,283-284` | SQL LIKE pattern injection - user input not escaped with `escape_like()`, allowing `%` and `_` wildcards |
| P1-27 | `app/routes/api.py:435-444` | `/api/log-operation` endpoint missing `@api_permission_required` decorator |
| P1-28 | `shared_models/stock_out.py:19` | Missing index on `stockout_date` column - date-range queries do full table scan |
| P1-29 | `shared_models/order.py:34-36`, `stock_in.py:25-26`, `stock_out.py:27-28` | Missing `back_populates` on several relationships - uses legacy `backref` pattern, risking SQLAlchemy warnings and bidirectional navigation issues |
| P1-30 | `static/style.css:37` | `body { zoom: 1.1; }` is non-standard - **breaks Firefox** (renders at 100% instead of 110%) |

---

### New P2 Medium Issues (Round 2)

| # | File:Line | Issue |
|---|-----------|-------|
| P2-32 | `app/__init__.py:154-162` | Missing `Content-Security-Policy` header - no XSS mitigation layer |
| P2-33 | `app/__init__.py:176-242` | Navigation permission cache not invalidated on permission changes - 5-min stale cache |
| P2-34 | `app/routes/user.py:116,136`, `order.py:359`, `stock.py:282,572` | Destructive operations (delete, toggle) via GET requests - CSRF-vulnerable and violates HTTP semantics |
| P2-35 | `app/routes/api.py:121-430` vs `fastapi_app/api/v1/endpoints/auxiliary.py:292-328` | Flask and FastAPI duplicate batch-submit routes - inconsistent behavior and double attack surface |
| P2-36 | `app/routes/report.py:444-482` | `/report/api/test-export` is CSRF-exempt and unauthenticated - should not be in production |
| P2-37 | `static/order.css` | No `@media` rules at all - order page not responsive on mobile |
| P2-38 | `static/style.css` | Duplicate CSS rules for `.top-header`, `.content-container` - confusing cascade |
| P2-39 | Multiple CSS files | Inconsistent breakpoints: 992px vs 991.98px vs 1199.98px across files |
| P2-40 | `templates/stockin.html:29`, `templates/stockout.html:29` | Missing `required` attribute on date input fields |
| P2-41 | `templates/stockin.html:43`, `templates/stockout.html:43` | No `max` validation on quantity inputs - allows extremely large numbers |

---

### New P3 Low Issues (Round 2)

| # | File:Line | Issue |
|---|-----------|-------|
| P3-19 | `templates/base.html:16-20` | No skip-to-content link for keyboard/screen-reader users (WCAG 2.1 SC 2.4.1) |
| P3-20 | `templates/base.html:18` | Sidebar overlay `onclick` has no keyboard equivalent or `tabindex`/`role` |
| P3-21 | `templates/base.html:91` | Menu toggle button uses `title` but no `aria-label` |
| P3-22 | `static/purchase-center.css:938` | Excessive `z-index: 99999` - unmaintainable z-index stacking |

---

## Part 10: Updated Implementation Roadmap

### Phase 1: Critical Security & Crash Fixes (Week 1) - REVISED

| Priority | Task | File(s) | Risk | Verification |
|----------|------|---------|------|-------------|
| **P0** | Fix XSS in stockin/stockout innerHTML | `templates/stockin.html`, `templates/stockout.html` | Low | Inject `<script>` in customer name; verify no execution |
| **P0** | Fix XSS in `| safe` Jinja2 filters | 5 template files | Low | Inject `</script>` in product name; verify no execution |
| **P0** | Add JWT expiration | `deps.py:29-30` | Low | Verify token has `exp` claim and expires |
| **P0** | Add auth to upload endpoint | `auth.py:183-215` | None | Verify 401 on unauthenticated upload |
| **P0** | Fix `AsyncNumberGenerator.generate()` | `stock_service.py:517,597` | Low | Batch stockin/stockout API test |
| **P0** | Add `asyncio.Lock` to number generator | `batch_service.py:26-102` | Low | Concurrent number generation test |
| **P0** | Add `slowapi` to requirements | `requirements/base.txt` | None | Fresh install test |
| **P0** | Fix PyMuPDF resource leak | `ocr_service.py:537` | Low | OCR with corrupt PDF |

### Phase 2: Performance (Week 2-3) - UNCHANGED

(See Part 7 for details)

### Phase 3: Security Hardening (Week 3-4) - NEW

| Task | File(s) | Risk | Verification |
|------|---------|------|-------------|
| Remove CSRF exemptions from sensitive blueprints | `app/__init__.py:340-354` | Medium | Test all Flask routes still work with CSRF |
| Add `Content-Security-Policy` header | `app/__init__.py` | Medium | CSP violation report test |
| Convert DELETE operations from GET to POST/DELETE | `app/routes/user.py`, `order.py`, `stock.py` | Medium | Test all delete operations |
| Add authentication to case management page | `app/routes/case.py` | Low | Unauthenticated access returns 401 |
| Remove test-export endpoint from production | `app/routes/report.py` | None | 404 on /report/api/test-export |
| Fix Firefox zoom issue | `static/style.css:37` | Low | Visual comparison Chrome vs Firefox |
| Add `escape_like()` to Flask report routes | `app/routes/report.py` | Low | Test LIKE wildcard input |

### Phase 4: Structural Refactoring (Week 4-6) - UNCHANGED

(See Part 7 for details)

### Phase 5: Infrastructure & Toolchain (Week 6-7) - UNCHANGED

(See Part 7 for details)
