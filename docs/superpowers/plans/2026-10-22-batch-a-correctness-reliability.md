# 批次 A — 正确性与可靠性 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 10 条正确性/可靠性缺陷（H4、M2、M3、M4、M7、M8、M9、M10、M11、M12），不改变任何业务行为。

**Architecture:** 每条缺陷独立一个任务，TDD 先行（先写失败测试，再最小实现），每个任务一个提交、可独立回滚。跨任务的共享改动只有两处：降级登记（A1）与 ARQ 幂等/补跑（A2/A10）——后两者复用 A1 暴露的 Redis 客户端获取方式。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy async、ARQ 0.28、pytest、Redis。

**Spec:** `docs/superpowers/specs/2026-10-22-performance-bug-fixes-design.md`（批次 A 部分）

## Global Constraints

- 本机即生产机，无独立测试环境；所有测试连 `erp_system_test`，**必须提权跑**（`logs/_run_pytest_elevated.ps1`）。
- 禁止 `alembic autogenerate` 对生产库；本轮批次 A **不新增迁移**。
- 提交只 `git add` 本任务文件；提交信息写"为什么"。
- 每个任务的测试必须做过**变异检查**：把被测行为改坏一处，对应测试必须变红。
- 临时脚本/日志用完删除（`logs/` 残留会打挂 check_bom 门禁）。
- 不重启生产、不改 `.env`、不动 nginx/NSSM。

## Review Focus

以下五类输入/条件没有现成测试覆盖，最可能在真实使用中咬人；每条都在对应任务里补了测试：

1. **Redis 不可用时的撤销检查**（A1/A6）——期望：仍能识别本进程已撤销 token，且降级可观测，不是静默放行。
2. **ARQ 任务重放**（A2）——期望：同一 job 重试不产生重复计划行。
3. **跨页状态筛选**（A4）——期望：第 500 条之后的订单也能被状态筛选命中。
4. **无 Content-Length 的超大上传**（A9）——期望：被拒绝且内存不随体积增长，不是先收完再判。
5. **worker 停机跨越日级 cron 触发点**（A10）——期望：恢复后补跑一次，且不重复。

---

## Task 1: 安全降级登记接线（H4）

**Files:**
- Modify: `fastapi_app/core/middleware.py:53-64`（新增跨 worker 发布/汇总）
- Modify: `fastapi_app/core/auth/blacklist.py:120-140`（fail-open 时登记）
- Modify: `fastapi_app/core/health.py:79-91`（汇总跨 worker 原因）
- Test: `fastapi_app/tests/test_middleware_degraded_production.py`（追加）
- Test: `fastapi_app/tests/test_blacklist_degradation.py`（新建）

**Interfaces:**
- Produces:
  - `async def publish_degradation(reason: str) -> None` — best-effort 写 Redis 键 `security_degraded:<reason>`，TTL 300s；Redis 不可用时只写本地。
  - `async def degraded_reasons_all() -> list[str]` — 本地 ∪ Redis 键集合。
  - `record_degradation(reason: str) -> None` 签名不变。
- Consumes: `fastapi_app.core.redis_wrapper.get_client()`。

- [ ] **Step 1: 写失败测试（跨 worker 可见）**

```python
# fastapi_app/tests/test_blacklist_degradation.py
import pytest

from fastapi_app.core import middleware


@pytest.mark.asyncio
async def test_fail_open_records_degradation(monkeypatch):
    middleware.clear_degradations()

    async def _no_redis():
        return None

    monkeypatch.setattr(
        "fastapi_app.core.auth.blacklist.get_client", _no_redis, raising=False
    )
    from fastapi_app.core.auth.blacklist import is_token_revoked

    assert await is_token_revoked("jti-1", fail_closed=False) is False
    assert "token_revocation_fail_open" in middleware.degraded_reasons()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest fastapi_app/tests/test_blacklist_degradation.py -v`
Expected: FAIL（`degraded_reasons()` 为空）

- [ ] **Step 3: 实现**

```python
# fastapi_app/core/middleware.py（在 clear_degradations 后追加）
_DEGRADED_REDIS_PREFIX = "security_degraded:"
_DEGRADED_TTL = 300


async def publish_degradation(reason: str) -> None:
    """把降级原因广播到 Redis，供 /api/health 跨 worker 汇总（best-effort）。"""
    record_degradation(reason)
    try:
        from fastapi_app.core.redis_wrapper import get_client

        client = get_client()
        if client:
            await client.set(f"{_DEGRADED_REDIS_PREFIX}{reason}", "1", ex=_DEGRADED_TTL)
    except Exception:  # defensive: 降级上报本身不得影响主流程
        pass


async def degraded_reasons_all() -> list[str]:
    """本地 + Redis 的降级原因并集。"""
    reasons = set(degraded_reasons())
    try:
        from fastapi_app.core.redis_wrapper import get_client

        client = get_client()
        if client:
            keys = await client.keys(f"{_DEGRADED_REDIS_PREFIX}*")
            for k in keys or ():
                name = k.decode() if isinstance(k, bytes) else str(k)
                reasons.add(name[len(_DEGRADED_REDIS_PREFIX):])
    except Exception:  # defensive: 汇总失败时退回本地列表
        pass
    return sorted(reasons)
```

```python
# fastapi_app/core/auth/blacklist.py：在 _log_revocation_degraded() 调用处前登记
async def _record_fail_open() -> None:
    from fastapi_app.core.middleware import publish_degradation

    await publish_degradation("token_revocation_fail_open")
```

在 `is_token_revoked` 的两处 `_log_revocation_degraded(...)` 之前调用 `await _record_fail_open()`。

```python
# fastapi_app/core/health.py：_with_security_degraded 改为接收 reasons
def _with_security_degraded(payload: dict, reasons: list[str]) -> dict:
    data = dict(payload)
    data["degraded"] = reasons
    data["security_degraded"] = bool(reasons)
    return data
```

在 health 端点构建响应前 `reasons = await degraded_reasons_all()`，并把它传入 `_health_from_cache(...)`；`_health_from_cache` 增加 `reasons` 参数并透传。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest fastapi_app/tests/test_blacklist_degradation.py fastapi_app/tests/test_middleware_degraded_production.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

把 `is_token_revoked` 里的 `await _record_fail_open()` 注释掉，重跑 Step 4，必须变红；恢复后重跑，绿。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/middleware.py fastapi_app/core/auth/blacklist.py fastapi_app/core/health.py fastapi_app/tests/test_blacklist_degradation.py fastapi_app/tests/test_middleware_degraded_production.py
git commit -m "fix(安全): fail-open 降级接入 record_degradation 并支持跨 worker 汇总"
```

---

## Task 2: 批量计划导入幂等（M8）

**Files:**
- Modify: `fastapi_app/tasks/plan_tasks.py:65-162`
- Test: `fastapi_app/tests/test_plan_import_idempotency.py`（新建）

**Interfaces:**
- Produces: `batch_id = f"job-{job_id[:8]}"`（同一 ARQ job 重试稳定）。
- Consumes: `fastapi_app.shared_models.StagingPurchasePlan`。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/test_plan_import_idempotency.py
import asyncio

import pytest

from fastapi_app.tasks import plan_tasks


@pytest.mark.asyncio
async def test_replay_does_not_duplicate(monkeypatch, tmp_path):
    calls = []

    async def _fake_impl(file_path, original_filename, user_id, batch_id):
        calls.append(batch_id)
        return {"success": True, "batch_id": batch_id, "row_count": 1, "success_count": 1}

    monkeypatch.setattr(plan_tasks, "_run_import_plans_impl", _fake_impl, raising=False)
    ctx = {"job_id": "job-abc-123"}
    r1 = await plan_tasks.batch_import_plans_task(ctx, str(tmp_path / "a.xlsx"), "a.xlsx", 1)
    r2 = await plan_tasks.batch_import_plans_task(ctx, str(tmp_path / "a.xlsx"), "a.xlsx", 1)
    assert r1["batch_id"] == r2["batch_id"]
    assert len(set(calls)) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_plan_import_idempotency.py -v`
Expected: FAIL（两次 `batch_id` 不同）

- [ ] **Step 3: 实现**

把 `_sync_impl` 内 `batch_id = str(uuid.uuid4())[:8]` 改为：

```python
# job_id 在 ARQ 重试间稳定；用它派生 batch_id，重放落到同一批
batch_id = f"job-{job_id[:8]}"
```

在写库循环**之前**清除该 batch 的旧行（幂等替换）：

```python
from sqlalchemy import delete

session.execute(
    delete(StagingPurchasePlan).where(StagingPurchasePlan.upload_batch_id == batch_id)
)
session.commit()
```

`job_id` 通过 `_sync_impl` 闭包可见（外层函数已有 `job_id = ctx['job_id']`）。

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_plan_import_idempotency.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

把 `batch_id` 改回 `uuid4()`，测试必须变红；恢复后绿。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/tasks/plan_tasks.py fastapi_app/tests/test_plan_import_idempotency.py
git commit -m "fix(导入): 批量计划导入按 job_id 派生 batch_id，重放不再重复插入"
```

---

## Task 3: 采购单撤销批量状态计算（M2）

**Files:**
- Modify: `fastapi_app/services/order_utils.py`（新增批量函数）
- Modify: `fastapi_app/services/purchase_order_revoke.py:52-60`
- Test: `fastapi_app/tests/test_order_status_batch.py`（新建）

**Interfaces:**
- Produces: `async def compute_order_statuses_batch(db, orders: list[Order]) -> dict[int, str]`。
- Consumes: `_batch_deduct_quantities`、`compute_status_from_stockouts`。

- [ ] **Step 1: 写失败测试（SQL 次数不随 N 线性增长）**

```python
# fastapi_app/tests/test_order_status_batch.py
import pytest
from sqlalchemy import event

from fastapi_app.services.order_utils import compute_order_statuses_batch


@pytest.mark.asyncio
async def test_batch_uses_constant_queries(db_session, seeded_orders):
    count = 0

    @event.listens_for(db_session.sync_session.bind, "before_cursor_execute")
    def _count(*args, **kwargs):
        nonlocal count
        count += 1

    result = await compute_order_statuses_batch(db_session, seeded_orders)
    assert len(result) == len(seeded_orders)
    assert count <= 2  # 抵扣聚合 + 独立出货聚合
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_order_status_batch.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
async def compute_order_statuses_batch(
    db: AsyncSession, orders: list[Order]
) -> dict[int, str]:
    """一次聚合算出多张订单的状态（替代循环内逐单 2 条 SQL）。"""
    if not orders:
        return {}
    order_ids = [o.id for o in orders]
    deduct_map = await _batch_deduct_quantities(db, order_ids)
    result = await db.execute(
        select(
            StockOut.order_id,
            func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0),
        )
        .where(StockOut.order_id.in_(order_ids), StockOut.stockin_id.is_(None))
        .group_by(StockOut.order_id)
    )
    shipped_map = {row[0]: int(row[1]) for row in result.all()}
    return {
        o.id: compute_status_from_stockouts(
            o, max(0, deduct_map.get(o.id, 0)), max(0, shipped_map.get(o.id, 0))
        )
        for o in orders
    }
```

`purchase_order_revoke.py` 循环改为：

```python
if order_ids:
    orders = list((await db.execute(
        select(Order).where(Order.id.in_(order_ids))
    )).scalars().all())
    status_map = await compute_order_statuses_batch(db, orders)
    for order in orders:
        new_status = status_map[order.id]
        if new_status != order.status:
            order.status = new_status
            orders_reset += 1
    await db.flush()
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_order_status_batch.py -v`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `pytest fastapi_app/tests -k "revoke or purchase_order" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/services/order_utils.py fastapi_app/services/purchase_order_revoke.py fastapi_app/tests/test_order_status_batch.py
git commit -m "perf(采购): 采购单撤销改为批量聚合订单状态，消除逐单 N+1"
```

---

## Task 4: 外协状态筛选减少往返（M3）

**Files:**
- Modify: `fastapi_app/services/outsource/_queries.py:96-112`
- Test: `fastapi_app/tests/test_outsource_status_filter.py`（新建）

**Interfaces:**
- Produces: `_scan_beile_items_with_progress` 改为「先收集所有页，最后统一附加一次进度」。
- Consumes: 现有 `_attach_progress_to_orders`（内部 2 条聚合 SQL）。

**说明**：原报告称"全量进内存后 Python 过滤"，核实为**性能**问题而非正确性问题——现有实现已能返回正确结果，但每页都发 2 条进度聚合查询（10k 订单 = 20 页 × 3 = 60+ 次往返）。本任务把进度附加从"每页一次"降为"整次扫描一次"。

- [ ] **Step 1: 写失败测试（进度聚合只调用一次）**

```python
# fastapi_app/tests/test_outsource_status_filter.py
import pytest

from fastapi_app.services.outsource import _queries


@pytest.mark.asyncio
async def test_progress_attached_once_for_all_pages(monkeypatch, db_session, many_outsource_orders):
    calls = []
    real_attach = _queries._attach_progress_to_orders

    async def _spy(db, items):
        calls.append(len(items))
        return await real_attach(db, items)

    monkeypatch.setattr(_queries, "_attach_progress_to_orders", _spy)
    await _queries._scan_beile_items_with_progress(db_session, None, None)
    assert len(calls) == 1
    assert calls[0] == len(many_outsource_orders)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_outsource_status_filter.py -v`
Expected: FAIL（当前每页调用一次，`len(calls) > 1`）

- [ ] **Step 3: 实现**

```python
async def _scan_beile_items_with_progress(db, customer, product):
    from fastapi_app.services.order_crud import get_beile_orders_with_stockins
    items: list[dict] = []
    page = 1
    while True:
        page_data = await get_beile_orders_with_stockins(
            db, page=page, per_page=_SCAN_PAGE_SIZE, customer=customer, factory='湖北',
            product_kw=product,
        )
        page_items = _detach_page_items(page_data['items'])
        items.extend(page_items)
        if len(page_items) < _SCAN_PAGE_SIZE or page * _SCAN_PAGE_SIZE >= page_data['total']:
            break
        page += 1
    # 进度聚合只做一次（原实现每页 2 条，10k 订单 = 40+ 次多余往返）
    await _attach_progress_to_orders(db, items)
    return items
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_outsource_status_filter.py -v`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `pytest fastapi_app/tests -k "outsource or beile" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/services/outsource/_queries.py fastapi_app/tests/test_outsource_status_filter.py
git commit -m "perf(外协): 状态筛选的进度聚合从每页一次降为整次扫描一次"
```

---

## Task 5: 图片校验下沉线程池（M4）

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/customer_sampling.py:241`
- Test: `fastapi_app/tests/test_sampling_upload_async.py`（新建）

**Interfaces:**
- Produces: `async def _validate_project_image_async(content: bytes, content_type: str | None) -> None`（模块级，便于测试）。
- Consumes: `svc.validate_project_image(content, content_type=...)`（签名不变）。

- [ ] **Step 1: 写失败测试（校验期间事件循环可调度）**

```python
# fastapi_app/tests/test_sampling_upload_async.py
import asyncio
import time

import pytest

from fastapi_app.api.v1.endpoints import customer_sampling as ep


@pytest.mark.asyncio
async def test_validation_does_not_block_loop(monkeypatch):
    ticks = []

    def _slow_validate(*args, **kwargs):
        time.sleep(0.2)

    monkeypatch.setattr(ep.svc, "validate_project_image", _slow_validate)

    async def _ticker():
        for _ in range(5):
            ticks.append(1)
            await asyncio.sleep(0.02)

    await asyncio.gather(
        ep._validate_project_image_async(b"fake", "image/png"),
        _ticker(),
    )
    assert len(ticks) == 5
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_sampling_upload_async.py -v`
Expected: FAIL（`_validate_project_image_async` 不存在）

- [ ] **Step 3: 实现**

在端点文件模块级新增：

```python
async def _validate_project_image_async(content: bytes, content_type: str | None) -> None:
    """PIL 解码是 CPU 密集的，必须下沉线程池，否则阻塞事件循环。"""
    await asyncio.to_thread(
        svc.validate_project_image, content, content_type=content_type
    )
```

端点内把：

```python
svc.validate_project_image(content, content_type=file.content_type)
```

改为：

```python
await _validate_project_image_async(content, file.content_type)
```

并确保文件顶部已 `import asyncio`（没有则补）。

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_sampling_upload_async.py -v`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `pytest fastapi_app/tests -k "customer_sampling or sampling" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/api/v1/endpoints/customer_sampling.py fastapi_app/tests/test_sampling_upload_async.py
git commit -m "perf(打样): 图片 PIL 解码校验下沉线程池，避免阻塞事件循环"
```

---

## Task 6: token 撤销跨 worker 广播（M9）

**Files:**
- Modify: `fastapi_app/core/auth/blacklist.py`
- Modify: `fastapi_app/core/lifespan.py`（或应用启动处，挂监听器）
- Test: `fastapi_app/tests/test_token_revocation_broadcast.py`（新建）

**Interfaces:**
- Produces:
  - `async def revoke_token(jti, exp)` 在写 Redis 后 `publish` 到 `token_revoked` 频道。
  - `async def start_revocation_listener() -> asyncio.Task` 启动订阅循环。
- Consumes: `fastapi_app.core.redis_wrapper.get_client()`。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/test_token_revocation_broadcast.py
import pytest

from fastapi_app.core.auth import blacklist


@pytest.mark.asyncio
async def test_revoke_publishes(monkeypatch):
    published = []

    class _FakeRedis:
        async def set(self, *a, **k):
            return True

        async def publish(self, channel, msg):
            published.append((channel, msg))

    monkeypatch.setattr(blacklist, "get_client", lambda: _FakeRedis(), raising=False)
    await blacklist.revoke_token("jti-x", int(__import__("time").time()) + 60)
    assert any("token_revoked" in c for c, _ in published)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_token_revocation_broadcast.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

```python
# blacklist.py 顶部补 import asyncio；新增常量
_REVOCATION_CHANNEL = "token_revoked"


async def revoke_token(jti: str, exp: int) -> None:
    """将 token 的 jti 加入黑名单并广播到其他 worker。"""
    remaining = max(exp - int(datetime.now(UTC).timestamp()), 0)
    if remaining <= 0:
        return
    _LOCAL_REVOKED_JTIS.add(jti)
    try:
        from fastapi_app.core.redis_wrapper import get_client, note_command_success

        redis = get_client()
        if redis:
            await redis.set(f"token_blacklist:{jti}", "1", ex=remaining)
            await redis.publish(_REVOCATION_CHANNEL, jti)
            note_command_success()
    except Exception as e:  # defensive: Redis 故障时本地 LRU 已写入，继续服务
        _note_redis_failure(e)
        logger.debug("token 黑名单写入失败", exc_info=True)


async def _revocation_listener() -> None:
    """订阅撤销广播并写入本进程 LRU；断线退避重连。"""
    backoff = 5
    while True:
        try:
            from fastapi_app.core.redis_wrapper import get_client

            redis = get_client()
            if redis is None:
                await asyncio.sleep(backoff)
                continue
            pubsub = redis.pubsub()
            await pubsub.subscribe(_REVOCATION_CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                jti = data.decode("utf-8") if isinstance(data, bytes) else str(data)
                _LOCAL_REVOKED_JTIS.add(jti)
        except Exception:  # defensive: 监听失败不得拖垮进程
            logger.warning("撤销广播监听断开，%ss 后重连", backoff, exc_info=True)
            await asyncio.sleep(backoff)
```

在应用 lifespan 启动处（与缓存广播监听器同一位置）：

```python
_revocation_task = asyncio.create_task(_revocation_listener())
```

关闭时：

```python
_revocation_task.cancel()
with contextlib.suppress(asyncio.CancelledError):
    await _revocation_task
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_token_revocation_broadcast.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

移除 `await redis.publish(...)`，测试变红；恢复后绿。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/auth/blacklist.py fastapi_app/core/lifespan.py fastapi_app/tests/test_token_revocation_broadcast.py
git commit -m "fix(认证): 登出撤销经 pub/sub 广播到各 worker，消除多 worker 放行窗口"
```

---

## Task 7: 审计日志失败可观测（M10）

**Files:**
- Modify: `fastapi_app/core/metrics.py`（新增 Counter）
- Modify: `fastapi_app/core/audit_middleware.py:408-446`
- Test: `fastapi_app/tests/test_audit_overflow.py`（新建）

**Interfaces:**
- Produces: `AUDIT_WRITE_FAILURES = _get_or_create_counter('audit_write_failures_total', ..., ['stage'])`。
- Produces: `_append_audit_overflow(entries: list[dict]) -> None` 写 `logs/audit_overflow.jsonl`。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/test_audit_overflow.py
import json

import pytest

from fastapi_app.core import audit_middleware


@pytest.mark.asyncio
async def test_db_failure_writes_overflow(monkeypatch, tmp_path):
    monkeypatch.setattr(audit_middleware, "_OVERFLOW_PATH", tmp_path / "audit_overflow.jsonl")
    monkeypatch.setattr(audit_middleware, "_get_audit_session_factory", lambda: None)
    ok = await audit_middleware._write_audit_direct([
        {"action": "CREATE", "resource_type": "order", "resource_id": "1"}
    ])
    assert ok is False
    lines = (tmp_path / "audit_overflow.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["resource_type"] == "order"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_audit_overflow.py -v`
Expected: FAIL（无溢出文件）

- [ ] **Step 3: 实现**

```python
# metrics.py
AUDIT_WRITE_FAILURES = _get_or_create_counter(
    'audit_write_failures_total',
    '审计日志写入失败总数',
    ['stage'],
)
```

```python
# audit_middleware.py
import json
from pathlib import Path

_OVERFLOW_PATH = Path("logs/audit_overflow.jsonl")


def _append_audit_overflow(entries: list[dict]) -> None:
    try:
        _OVERFLOW_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _OVERFLOW_PATH.open("a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.error("审计溢出文件写入失败", exc_info=True)
```

在 `_write_audit_direct` 的 `return False` 前：

```python
from fastapi_app.core.metrics import AUDIT_WRITE_FAILURES

AUDIT_WRITE_FAILURES.labels(stage="db").inc()
_append_audit_overflow(entries)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_audit_overflow.py -v`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `pytest fastapi_app/tests -k "audit" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/metrics.py fastapi_app/core/audit_middleware.py fastapi_app/tests/test_audit_overflow.py
git commit -m "fix(审计): 写库失败计数并落本地溢出文件，避免审计记录静默清零"
```

---

## Task 8: 事件发布异常保留堆栈（M11）

**Files:**
- Modify: `fastapi_app/core/exception_handler.py:96-101`
- Test: `fastapi_app/tests/test_safe_publish_event.py`（新建）

**Interfaces:**
- Consumes: `safe_publish_event(publish_func, event_type, data, **kwargs)`（签名不变）。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/test_safe_publish_event.py
import logging

import pytest

from fastapi_app.core.exception_handler import safe_publish_event


@pytest.mark.asyncio
async def test_programming_error_logs_traceback(caplog):
    async def _boom(*a, **k):
        raise TypeError("bad payload")

    with caplog.at_level(logging.ERROR):
        await safe_publish_event(_boom, "x", {})
    assert any(r.exc_info for r in caplog.records if r.levelno == logging.ERROR)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_safe_publish_event.py -v`
Expected: FAIL（`exc_info=False`）

- [ ] **Step 3: 实现**

```python
    except Exception as e:  # defensive: event publishing is non-critical and must not interrupt business flow
        logger.error("%s意外异常（不影响数据）: %s", context, e, exc_info=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_safe_publish_event.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/core/exception_handler.py fastapi_app/tests/test_safe_publish_event.py
git commit -m "fix(可观测): 事件发布意外异常保留 traceback，避免症状与原因分离"
```

---

## Task 9: 无 Content-Length 上传内存上界（M12）

**Files:**
- Modify: `fastapi_app/core/middleware.py:461-471`
- Test: `fastapi_app/tests/test_upload_no_content_length.py`（新建）

**Interfaces:**
- Produces: 无 Content-Length 的请求体上限降为 `MAX_IMPORT_UPLOAD_BYTES`（64MB）；超过立即 413。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/test_upload_no_content_length.py
import pytest
from fastapi.testclient import TestClient

from fastapi_app.main import app


def test_chunked_body_over_import_limit_rejected():
    client = TestClient(app)
    def _gen():
        for _ in range(70):  # 70MB
            yield b"x" * (1024 * 1024)
    resp = client.post("/api/v1/tasks/import-orders", content=_gen())
    assert resp.status_code == 413
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_upload_no_content_length.py -v`
Expected: FAIL（当前上限 512MB，返回 400/422 而非 413）

- [ ] **Step 3: 实现**

```python
            else:
                # 无 Content-Length（chunked/流式上传）：备份路径要求带长度（nginx 正常代理
                # 会带），否则 411；其余路径不允许借 chunked 绕过 64MB 导入上限。
                if request.url.path.startswith('/api/v1/backup'):
                    return Response(
                        content='{"detail":"备份上传必须携带 Content-Length"}',
                        status_code=411,
                        media_type="application/json",
                    )
                no_length_limit = min(limit, _IMPORT_UPLOAD_BODY_LIMIT)
                received = 0
                chunks: list[bytes] = []
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > no_length_limit:
                        return _body_too_large_response(no_length_limit)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_upload_no_content_length.py -v`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `pytest fastapi_app/tests -k "upload or middleware" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/middleware.py fastapi_app/tests/test_upload_no_content_length.py
git commit -m "fix(上传): 无 Content-Length 的请求体受 64MB 上限约束，避免内存翻倍"
```

---

## Task 10: 日级 ARQ cron 漏跑补跑（M7）

**Files:**
- Modify: `fastapi_app/core/arq_app.py`（新增 `catch_up_daily_crons` + cron 注册）
- Modify: `fastapi_app/core/arq_callbacks.py`（成功时写 `cron_last_ok:<name>`）
- Test: `fastapi_app/tests/test_daily_cron_catchup.py`（新建）

**Interfaces:**
- Produces: `async def catch_up_daily_crons(ctx)`；Redis 键 `cron_last_ok:<name>` = `YYYY-MM-DD`。
- Consumes: `cron_schedules`、`get_arq_pool()`。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/test_daily_cron_catchup.py
from datetime import datetime

import pytest

from fastapi_app.core import arq_app


@pytest.mark.asyncio
async def test_missed_daily_cron_enqueued_once(monkeypatch, fake_redis, fake_pool):
    monkeypatch.setattr(arq_app, "get_arq_pool", lambda: fake_pool, raising=False)
    monkeypatch.setattr(arq_app, "get_client", lambda: fake_redis, raising=False)
    now = datetime(2026, 10, 22, 9, 0)  # 今日 01:00 已过；fake_redis 无 cron_last_ok
    await arq_app.catch_up_daily_crons({}, now=now)
    await arq_app.catch_up_daily_crons({}, now=now)
    assert len(fake_pool.enqueued) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest fastapi_app/tests/test_daily_cron_catchup.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

```python
# arq_app.py
_DAILY_CRON_NAMES = {"sync-shipment-daily", "log-maintenance"}
_CRON_LAST_OK_PREFIX = "cron_last_ok:"


async def catch_up_daily_crons(ctx, now: datetime | None = None):
    """日级 cron 漏跑补跑：今日应跑时刻已过且未成功 → 幂等入队一次。"""
    from fastapi_app.core.business_time import business_today
    from fastapi_app.core.redis_wrapper import get_client

    redis = get_client()
    if redis is None:
        return
    pool = await get_arq_pool()
    now = now or datetime.now()
    today = business_today().isoformat()
    for entry in cron_schedules:
        if entry["name"] not in _DAILY_CRON_NAMES:
            continue
        if now.hour < entry["cron"]["hour"]:
            continue
        key = f"{_CRON_LAST_OK_PREFIX}{entry['name']}"
        last_ok = await redis.get(key)
        last_ok = last_ok.decode() if isinstance(last_ok, bytes) else last_ok
        if last_ok == today:
            continue
        job = await pool.enqueue_job(
            entry["func"].__name__, _job_id=f"catchup:{entry['name']}:{today}"
        )
        if job is not None:
            await redis.set(key, today, ex=86400 * 2)
```

在 `cron_schedules` 追加：

```python
{
    'name': 'daily-cron-catchup',
    'func': catch_up_daily_crons,
    'cron': {'minute': set(range(0, 60, 10))},
    'schedule': 'every 10m',
    'timeout': 60,
},
```

在 `arq_callbacks.on_job_end` 的成功分支（`else` 里 `_mark_schedule_outcome` 之后）追加：

```python
async def _mark_daily_cron_success(ctx) -> None:
    from fastapi_app.core.arq_app import _DAILY_CRON_NAMES, _CRON_LAST_OK_PREFIX, cron_schedules
    from fastapi_app.core.business_time import business_today
    from fastapi_app.core.redis_wrapper import get_client

    func_name = ctx.get('_job_function') or ctx.get('function', '')
    if callable(func_name):
        func_name = func_name.__name__
    for entry in cron_schedules:
        if entry['name'] in _DAILY_CRON_NAMES and entry['func'].__name__ == func_name:
            redis = get_client()
            if redis:
                await redis.set(
                    f"{_CRON_LAST_OK_PREFIX}{entry['name']}",
                    business_today().isoformat(),
                    ex=86400 * 2,
                )
```

并在 `on_job_end` 的 `else` 分支里 `await _mark_daily_cron_success(ctx)`。

- [ ] **Step 4: 运行确认通过**

Run: `pytest fastapi_app/tests/test_daily_cron_catchup.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

移除 `if last_ok == today: continue`，第二次调用会重复入队，测试变红；恢复后绿。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/arq_app.py fastapi_app/core/arq_callbacks.py fastapi_app/tests/test_daily_cron_catchup.py
git commit -m "fix(任务): 日级 ARQ cron 停机漏跑后自动补跑一次，避免静默缺失"
```

---

## 批次 A 完成门槛

- [ ] 10 个任务全部通过，每个都有变异检查记录。
- [ ] 聚焦回归：`pytest fastapi_app/tests -k "blacklist or plan_import or order_status or outsource or sampling or audit or publish_event or upload or cron" -v`
- [ ] 提权全量：`logs/_run_pytest_elevated.ps1`（记录 passed/failed/skipped）。
- [ ] `ruff check fastapi_app tests fastapi_app/tests utils` 通过。
- [ ] `mypy --config-file mypy.ini --no-native-parser` 不新增错误。
- [ ] 提交 10 个独立 commit；`git status --porcelain` 无本任务外文件。
- [ ] 不做：重启生产、改 `.env`、改 nginx/NSSM。
