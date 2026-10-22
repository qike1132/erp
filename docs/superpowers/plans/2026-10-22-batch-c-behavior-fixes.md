# 批次 C — 行为修正 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 9 条行为/正确性缺陷（M5、M6、M13、M14、M15、L11、L12、L13、L14），其中 M5/M6 会改变生产行为，已由 owner 批准。

**Architecture:** 后端两项（M5/M6）各自独立提交；前端七项按组件/基础设施分组提交。M6 的历史回填写成幂等脚本，**不在本批执行**，需 owner 单独发话。

**Tech Stack:** FastAPI、SQLAlchemy async、Vue 3 + TS + Vite 7、vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-10-22-performance-bug-fixes-design.md`（批次 C 部分）

## Global Constraints

- 生产机：不重启、不改 `.env`、不执行回填。
- 全量 pytest 提权；前端 vitest 需 `TEMP` 指进仓内（`frontend-vite/.vitest-tmp`）。
- 每条修复先写失败测试，并做变异检查。
- 单 .vue 文件 ≤400 行；不新增颜色类视觉信号。
- 提交只 `git add` 本任务文件。

## Review Focus

1. **M5 工厂闸门**：厂绑定用户对异厂产品下单必须 404；本厂/超管/未绑定不受影响。
2. **M6 时区**：01:00 CST 触发时目标日期必须是业务昨日；窗口重跑不重复。
3. **M6 回填**：脚本只读核对 + 幂等 upsert，不碰其他日期。
4. **M14 mount 时序**：mount 前 PrimeVue 已安装。
5. **M15 虚拟滚动**：200 条下拉不再一次渲染全部 DOM。
6. **L13 取消**：路由切换 abort 旧请求，不产生错误提示。

---

## Task 1: 订单创建工厂闸门（M5）

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/order.py:312-316`
- Modify: `fastapi_app/api/v1/endpoints/auxiliary.py:451-461`
- Test: `tests/test_order_factory_gate.py`（新建）

**Interfaces:** 复用 `fastapi_app.shared.factory_scope.assert_product_factory_scoped`。

- [ ] **Step 1: 写失败测试**

```python
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_single_create_calls_factory_gate(monkeypatch):
    from fastapi_app.api.v1.endpoints import order as ep
    called = []

    async def _gate(db, pid, user, *, what):
        called.append((pid, what))

    class _CM:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(ep, "assert_product_factory_scoped", _gate)
    monkeypatch.setattr(ep, "db_transaction", lambda db: _CM())
    monkeypatch.setattr(ep.order_service, "create_order", AsyncMock(return_value={}))
    monkeypatch.setattr(ep.cache_mgr, "invalidate_dashboard", AsyncMock())

    data = SimpleNamespace(product_id=42, quantity=1, customer="C", note="")
    await ep.create_order(data=data, db=AsyncMock(),
                          user=SimpleNamespace(factory="东莞", is_super=False))
    assert called == [(42, "产品")]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_order_factory_gate.py -v`
Expected: FAIL（`called == []`）

- [ ] **Step 3: 实现**

`order.py` 在 `order_service.create_order` 前：

```python
from fastapi_app.shared.factory_scope import assert_product_factory_scoped
...
async with db_transaction(db):
    await assert_product_factory_scoped(db, data.product_id, user, what="产品")
    await order_service.create_order(...)
```

`auxiliary.py` 批量下单在 `orchestrate_batch_orders` 前逐项校验：

```python
from fastapi_app.shared.factory_scope import assert_product_factory_scoped
...
for item in data.items:
    await assert_product_factory_scoped(db, item.product_id, user, what="产品")
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_order_factory_gate.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

移除 `assert_product_factory_scoped` 调用，测试变红。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/api/v1/endpoints/order.py fastapi_app/api/v1/endpoints/auxiliary.py tests/test_order_factory_gate.py
git commit -m "fix(订单): 创建订单接入工厂隔离闸门，消除跨厂下单漏洞"
```

---

## Task 2: 出货同步时区 + 回看窗口（M6）

**Files:**
- Modify: `fastapi_app/tasks/plan_tasks.py:26-62`
- Test: `tests/test_shipment_sync_dates.py`（新建）

**Interfaces:** `def _sync_target_dates(today: date, lookback_days: int = 3) -> list[date]`。

- [ ] **Step 1: 写失败测试**

```python
from datetime import date

def test_target_dates_use_business_yesterday():
    from fastapi_app.tasks.plan_tasks import _sync_target_dates
    assert _sync_target_dates(date(2026, 10, 22), 3) == [
        date(2026, 10, 21), date(2026, 10, 20), date(2026, 10, 19)
    ]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_shipment_sync_dates.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

```python
from fastapi_app.core.business_time import business_today

def _sync_target_dates(today: date, lookback_days: int = 3) -> list[date]:
    """从业务昨日开始回看 N 天；窗口内每天幂等 upsert，自然补上漏跑。"""
    return [today - timedelta(days=i) for i in range(1, lookback_days + 1)]
```

`sync_shipment_records_task` 内：

```python
target_dates = _sync_target_dates(business_today())
for target_date in target_dates:
    # 现有单日查询 + upsert 逻辑（按 shipment_no 幂等）放进循环
```

删除 docstring 中"并刷新 purchase_plan_details.shipped_qty 缓存"的失实描述。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_shipment_sync_dates.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/tasks/plan_tasks.py tests/test_shipment_sync_dates.py
git commit -m "fix(任务): 出货同步改用业务昨日并回看 3 天，避免 UTC 日界漏单"
```

---

## Task 3: 出货同步历史回填脚本（M6 运维件，不执行）

**Files:**
- Create: `scripts/backfill_shipment_records.py`
- Test: `tests/test_backfill_shipment_script.py`（新建）

**Interfaces:** `def parse_args(argv) -> Namespace`；`--from YYYY-MM-DD --to YYYY-MM-DD --dry-run`（默认 dry-run）。

- [ ] **Step 1: 写失败测试**

```python
def test_backfill_defaults_to_dry_run():
    from scripts.backfill_shipment_records import parse_args
    args = parse_args(["--from", "2026-10-08", "--to", "2026-10-21"])
    assert args.dry_run is True
    assert args.start.isoformat() == "2026-10-08"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_backfill_shipment_script.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

脚本只读统计每天 `stock_out` 有效行数与 `shipment_records` 行数；`--apply` 才调用与任务相同的幂等 upsert。默认 dry-run，且**不**接入 `_prod_write_guard`（脚本只写 `shipment_records`，不碰业务表；但仍要求显式 `--apply`）。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_backfill_shipment_script.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/backfill_shipment_records.py tests/test_backfill_shipment_script.py
git commit -m "feat(运维): 新增出货同步历史回填脚本（默认 dry-run）"
```

---

## Task 4: 删除 catalog 死配置（M13）

**Files:**
- Modify: `frontend-vite/src/stores/catalog.ts`
- Test: `frontend-vite/src/test/catalogStoreSurface.test.ts`（新建）

- [ ] **Step 1: 写失败测试**

```ts
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { useCatalogStore } from '@/stores/catalog'

describe('catalog store surface', () => {
  it('only exposes the customer-name entry that is actually used', () => {
    setActivePinia(createPinia())
    const store = useCatalogStore()
    expect(store.ensureActiveCustomerNames).toBeTypeOf('function')
    expect((store as any).ensureProducts).toBeUndefined()
    expect((store as any).ensureCustomers).toBeUndefined()
    expect((store as any).ensureSuppliers).toBeUndefined()
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "catalog store surface"`
Expected: FAIL（`ensureProducts` 仍存在）

- [ ] **Step 3: 实现**

删除 `CATALOG_PAGE_PARAMS`、`ensureProducts`、`ensureCustomers`、`ensureSuppliers` 及其类型/请求逻辑；保留 `ensureActiveCustomerNames` 与 `CustomerNameOption`。

- [ ] **Step 4: 运行确认通过**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "catalog store surface"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/stores/catalog.ts frontend-vite/src/test/catalogStoreSurface.test.ts
git commit -m "refactor(前端): 删除 catalog store 无调用的全量下拉配置"
```

---

## Task 5: PrimeVue 安装先于 mount（M14）

**Files:**
- Modify: `frontend-vite/src/main.ts:108,120-148`
- Test: `frontend-vite/src/test/primevueMountOrder.test.ts`（新建）

- [ ] **Step 1: 写失败测试（源码顺序守卫）**

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('main.ts mount order', () => {
  it('installs PrimeVue before mounting the app', () => {
    const src = readFileSync(resolve(__dirname, '../main.ts'), 'utf-8')
    const install = src.indexOf("await import('primevue/config')")
    const mount = src.indexOf("app.mount('#app')")
    expect(install).toBeGreaterThan(-1)
    expect(mount).toBeGreaterThan(-1)
    expect(install).toBeLessThan(mount)
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "mount order"`
Expected: FAIL（mount 在 install 之前）

- [ ] **Step 3: 实现**

把 `app.mount('#app')` 移到 `bootstrap()` 内、`await import('primevue/config').then(...)` 之后（或改为 `const PrimeVueMod = await import('primevue/config'); app.use(...)` 再 mount）。

- [ ] **Step 4: 运行确认通过**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "mount order"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/main.ts frontend-vite/src/test/primevueMountOrder.test.ts
git commit -m "fix(前端): PrimeVue 安装完成后再 mount，消除弹层样式/层级竞态"
```

---

## Task 6: AutoComplete 虚拟滚动（M15）

**Files:**
- Modify: `frontend-vite/src/components/ui/UiAutocomplete.vue:279-301`
- Test: `frontend-vite/src/test/autocompleteVirtualScroll.test.ts`（新建）

- [ ] **Step 1: 写失败测试**

```ts
import { mount } from '@vue/test-utils'
import AutoComplete from 'primevue/autocomplete'
import { describe, expect, it } from 'vitest'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'

describe('UiAutocomplete', () => {
  it('passes virtualScrollerOptions to PrimeVue AutoComplete', () => {
    const wrapper = mount(UiAutocomplete, { props: { modelValue: '', suggestions: [] } })
    const ac = wrapper.findComponent(AutoComplete)
    expect(ac.props('virtualScrollerOptions')).toMatchObject({ itemSize: expect.any(Number) })
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "UiAutocomplete"`
Expected: FAIL（prop 为 undefined）

- [ ] **Step 3: 实现**

模板加：

```vue
:virtual-scroller-options="{ itemSize: 40 }"
```

- [ ] **Step 4: 运行确认通过**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "UiAutocomplete"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/components/ui/UiAutocomplete.vue frontend-vite/src/test/autocompleteVirtualScroll.test.ts
git commit -m "perf(前端): AutoComplete 启用虚拟滚动，避免一次渲染上千节点"
```

---

## Task 7: SW 预缓存体积上限（L11）

**Files:**
- Modify: `frontend-vite/vite.config.ts:84-90`
- Test: `frontend-vite/src/test/swPrecacheLimit.test.ts`（新建）

- [ ] **Step 1: 写失败测试（源码守卫）**

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('service worker precache', () => {
  it('caps the precached file size', () => {
    const src = readFileSync(resolve(__dirname, '../../vite.config.ts'), 'utf-8')
    expect(src).toMatch(/maximumFileSizeToCacheInBytes\s*:/)
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "service worker precache"`
Expected: FAIL

- [ ] **Step 3: 实现**

`workbox` 配置加 `maximumFileSizeToCacheInBytes: 2 * 1024 * 1024`，超大 chunk 走 runtime caching（`StaleWhileRevalidate`，cacheName `large-chunks`）。

- [ ] **Step 4: 运行确认通过**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "service worker precache"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/vite.config.ts frontend-vite/src/test/swPrecacheLimit.test.ts
git commit -m "perf(前端): SW 预缓存加单文件上限，超大 chunk 改运行时缓存"
```

---

## Task 8: 可编辑行稳定 key（L12）

**Files:**
- Modify: `frontend-vite/src/views/pattern-room/components/DialogRoleEditor.vue:3-15`
- Modify: `frontend-vite/src/views/customer-order/components/ShipmentPlanControl.vue:15`
- Test: `frontend-vite/src/test/stableRowKeys.test.ts`（新建）

- [ ] **Step 1: 写失败测试**

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('editable row keys', () => {
  it('does not use array index as key', () => {
    for (const rel of [
      '../views/pattern-room/components/DialogRoleEditor.vue',
      '../views/customer-order/components/ShipmentPlanControl.vue',
    ]) {
      const src = readFileSync(resolve(__dirname, rel), 'utf-8')
      expect(src).not.toMatch(/:key="idx"/)
    }
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "editable row keys"`
Expected: FAIL

- [ ] **Step 3: 实现**

为每行数据引入稳定 id（前端临时 uuid），`v-model` 按 id 定位、删除按 id 过滤。

- [ ] **Step 4: 运行确认通过**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "editable row keys"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/views/pattern-room/components/DialogRoleEditor.vue frontend-vite/src/views/customer-order/components/ShipmentPlanControl.vue frontend-vite/src/test/stableRowKeys.test.ts
git commit -m "fix(前端): 可编辑行改用稳定 id 作 key，避免删行后焦点/IME 错位"
```

---

## Task 9: 请求取消与 console 收口（L13/L14）

**Files:**
- Modify: `frontend-vite/src/api/request.ts`
- Modify: `frontend-vite/src/main.ts:18-31`
- Test: `frontend-vite/src/test/requestAbort.test.ts`（新建）
- Test: `frontend-vite/src/test/consoleErrorScope.test.ts`（新建）

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { abortPendingRequests, get } from '@/api/request'

describe('request abort', () => {
  it('aborts pending requests', async () => {
    const p = get('/slow', {}, { signal: new AbortController().signal })
    abortPendingRequests()
    await expect(p).rejects.toBeTruthy()
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "request abort"`
Expected: FAIL（`abortPendingRequests` 不存在）

- [ ] **Step 3: 实现**

`request.ts`：维护 `AbortController` 集合，`get/post` 接受可选 `signal`；新增 `abortPendingRequests()`。`main.ts` 路由 `beforeEach` 调 `abortPendingRequests()`。

console 收口：把 `SUPPRESS_PATTERNS` 改为精确匹配已知噪音，且 `Error` 对象首参永不吞。

- [ ] **Step 4: 运行确认通过**

Run: `TEMP=frontend-vite/.vitest-tmp npx vitest run -t "request abort"`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/api/request.ts frontend-vite/src/main.ts frontend-vite/src/test/requestAbort.test.ts frontend-vite/src/test/consoleErrorScope.test.ts
git commit -m "fix(前端): 路由切换取消旧请求；收窄 console.error 吞错范围"
```

---

## 批次 C 完成门槛

- [ ] 9 个任务全绿，每个有变异检查。
- [ ] 后端聚焦 + 提权全量 pytest 0 failed。
- [ ] 前端 `npm run type-check` / `npm test` / `npm run lint` / `check:*` 全绿。
- [ ] 不重启生产、不执行回填。
