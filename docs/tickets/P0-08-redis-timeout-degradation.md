# P0-08　Redis 无 socket 超时 + `safe_*` 无 `wait_for`/熔断

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（稳定性根治项） |
| 类型 | 稳定性 · 基础设施 |
| 模块 | `fastapi_app/core/redis_client.py`、`fastapi_app/core/redis_wrapper.py`、`utils/redis_cache.py` |
| 预估工时 | 2 h（含演练） |
| 批次 | B |
| 依赖 | ⚠️ **必须在 P0-07 之后**（超时后要能降级，前提是异常能被捕获） |

## 现象

Redis 出现"TCP 已建连但不回包"（OOM、`BGSAVE`/`AOF rewrite` 阻塞、网络黑洞）时：

1. 每个走 `safe_*` 的请求最坏阻塞 **5–10 s**（`socket_timeout=5` × `retry_on_timeout=True` 两次）
2. 走 `core/redis_client.py` 的调用（健康检查、备份进度、维护模式）**永不超时**
3. 4 个 uvicorn worker 的事件循环被逐个占满 → **服务整体不可用**
4. 更糟：`/api/health/ready` 也卡死 → **探活无法触发摘除/重启，故障无法自愈**

这是本次审查中**唯一能让"整个服务不可用且无法自愈"**的缺陷。

## 定位

### 问题 1：`core/redis_client.py` 的共享客户端完全没有超时

`fastapi_app/core/redis_client.py:42-52`

```python
        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            encoded_password = quote_plus(settings.REDIS_PASSWORD)
            ...
        _async_redis_client = aioredis.from_url(url)     # ← L51 无任何超时参数
        return _async_redis_client
```

`redis-py` 默认 `socket_timeout=None`（**永不超时**）。调用方（均已核对）也没有 `wait_for` 包裹：

- `fastapi_app/core/health.py:206` → `await client.ping()`
- `fastapi_app/core/maintenance.py:33` → `await client.get(...)`

### 问题 2：`safe_*` 有 5 s 超时但无 `wait_for`、无熔断，且被放大成 10 s

`fastapi_app/core/redis_wrapper.py:18-26`（18 个 `safe_*` 函数同构）

```python
async def safe_get(key: str, fallback: Any = None, context: str = "") -> Any:
    try:
        from utils.redis_cache import redis_cache
        return await redis_cache.get(key)          # ← 无 asyncio.wait_for
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s读取失败: %s", _ctx(context, key), e)
        return fallback
```

底层客户端（`utils/redis_cache.py:51-58`）：

```python
                self.redis_client = aioredis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,        # ← 一次超时 → 重试 → 最坏 10s
                    max_connections=100
                )
```

**对比参照**：`fastapi_app/core/cache.py` 这一套做得是对的 ——
`CACHE_TIMEOUT = 0.3`（`cache.py:25`）、`asyncio.wait_for(..., timeout=CACHE_TIMEOUT)`、
断路器 `_REDIS_CIRCUIT_THRESHOLD = 3` / `_REDIS_CIRCUIT_COOLDOWN = 30s`（`cache.py:34/36`）。

**问题就是：这套正确的机制只存在于 `cache.py`，没有下沉到 `redis_wrapper`。**
两者能力差距：

| | `core/cache.py` | `redis_wrapper.safe_*` |
|---|---|---|
| 超时 | 0.3 s | 无（依赖 client 的 5 s，×2 重试 = 10 s） |
| 熔断 | 3 次失败 → 冷却 30 s | 无 |
| 故障期请求代价 | 立即返回 fallback | 每个请求阻塞 10 s |

## 修复方案

### 第 1 步：给共享客户端加超时（`core/redis_client.py`）

```diff
-        _async_redis_client = aioredis.from_url(url)
+        _async_redis_client = aioredis.from_url(
+            url,
+            # P0-08：必须显式设超时。redis-py 默认 socket_timeout=None（永不超时），
+            # Redis 假死（TCP 已连但不回包）时会挂死整个事件循环，
+            # 连 /api/health/ready 都无法返回，导致探活无法摘除/重启实例。
+            socket_timeout=1,
+            socket_connect_timeout=1,
+            retry_on_timeout=False,
+            health_check_interval=30,
+        )
         return _async_redis_client
```

### 第 2 步：把 `cache.py` 的正确机制下沉为 `redis_wrapper` 的统一执行器

在 `redis_wrapper.py` 顶部加一个内部执行器，**18 个 `safe_*` 全部改为调用它**：

```python
import asyncio
from datetime import datetime, timedelta

# ── 与 core/cache.py 对齐的超时与熔断参数 ──────────────────
REDIS_OP_TIMEOUT = float(os.getenv('REDIS_OP_TIMEOUT', '0.3'))
_CIRCUIT_THRESHOLD = 3
_CIRCUIT_COOLDOWN = timedelta(seconds=30)

_redis_fail_count = 0
_circuit_open_until: datetime | None = None


def _circuit_is_open() -> bool:
    return _circuit_open_until is not None and datetime.now() < _circuit_open_until


def reset_redis_circuit() -> None:
    """手动复位断路器（Redis 恢复后可由健康检查调用）"""
    global _redis_fail_count, _circuit_open_until
    _redis_fail_count = 0
    _circuit_open_until = None


async def _run(operation, fallback, context: str, key: str = ""):
    """统一执行 Redis 操作：超时保护 + 熔断 + 异常降级

    operation: 无参可等待对象（用 lambda 延迟构造，避免熔断时白造协程）
    """
    global _redis_fail_count, _circuit_open_until

    if _circuit_is_open():
        logger.debug("%s 熔断中，跳过 Redis", _ctx(context, key))
        return fallback

    try:
        return await asyncio.wait_for(operation(), timeout=REDIS_OP_TIMEOUT)
    except TimeoutError as e:
        _note_failure(context, key, f'超时(>{REDIS_OP_TIMEOUT}s)')
    except INFRA_EXCEPTIONS as e:
        _note_failure(context, key, str(e))
    return fallback


def _note_failure(context: str, key: str, detail: str) -> None:
    global _redis_fail_count, _circuit_open_until
    _redis_fail_count += 1
    if _redis_fail_count >= _CIRCUIT_THRESHOLD and not _circuit_is_open():
        _circuit_open_until = datetime.now() + _CIRCUIT_COOLDOWN
        logger.warning(
            "Redis 连续 %d 次失败，熔断 %ss：%s",
            _redis_fail_count, _CIRCUIT_COOLDOWN.total_seconds(), _ctx(context, key),
        )
    else:
        logger.warning("%s失败(%s): %s", _ctx(context, key), detail, detail)
```

改造示例（`safe_get` / `safe_set`，其余 16 个同构）：

```python
async def safe_get(key: str, fallback: Any = None, context: str = "") -> Any:
    async def _op():
        from utils.redis_cache import redis_cache
        return await redis_cache.get(key)
    return await _run(_op, fallback, context, key)


async def safe_set(key: str, value: Any, timeout: int = 300, context: str = "") -> bool:
    async def _op():
        from utils.redis_cache import redis_cache
        await redis_cache.set(key, value, timeout=timeout)
        return True
    return await _run(_op, False, context, key)
```

> ⚠️ **注意 `_run` 用 "lambda/闭包延迟构造协程"** 而不是接收现成协程对象：
> 否则熔断分支返回时，传入的协程**从未被 await**，会触发
> `RuntimeWarning: coroutine was never awaited`（且永久不执行）。

✓ 成功路径应清零计数（否则偶发失败会累积到熔断）：
```python
    try:
        result = await asyncio.wait_for(operation(), timeout=REDIS_OP_TIMEOUT)
        _reset_fail_count()          # 成功即清零
        return result
```

### 第 3 步：调小底层客户端超时、关掉重试放大（`utils/redis_cache.py`）

```diff
                 self.redis_client = aioredis.from_url(
                     redis_url,
                     decode_responses=True,
-                    socket_connect_timeout=5,
-                    socket_timeout=5,
-                    retry_on_timeout=True,
+                    # P0-08：单次超时已由 redis_wrapper 的 asyncio.wait_for(0.3s) 兜住。
+                    # 这里保留一个略大的客户端级超时作为最后防线；关闭 retry_on_timeout
+                    # 避免"一次超时 ×2 次重试"把 5s 放大成 10s。
+                    socket_connect_timeout=2,
+                    socket_timeout=3,
+                    retry_on_timeout=False,
                     max_connections=100
                 )
```

### 第 4 步（可选，建议）：健康检查回落时复位断路器

`core/health.py:193-209` 的 `/api/health/ready` 探测到 Redis 恢复后调用 `reset_redis_circuit()`，
避免"Redis 已恢复但仍在 30 s 熔断窗口内"。

## 验收标准

1. **超时生效**（核心断言）——模拟 Redis 假死（TCP 可连但不回包）：
   ```python
   @pytest.mark.asyncio
   async def test_safe_get_times_out_fast(monkeypatch):
       async def hang(*a, **k):
           await asyncio.sleep(60)          # 模拟假死
       monkeypatch.setattr('utils.redis_cache.redis_cache.get', hang)
       from fastapi_app.core.redis_wrapper import safe_get
       t0 = time.perf_counter()
       assert await safe_get('k', fallback='FB') == 'FB'
       assert time.perf_counter() - t0 < 0.6        # 修复前 ≥5s（且原为 10s）
   ```
2. **熔断生效**——连打 4 次，第 4 次必须"立即"返回（不触发 Redis 调用）：
   ```python
   @pytest.mark.asyncio
   async def test_circuit_opens_after_3_failures(monkeypatch):
       calls = 0
       async def failing(*a, **k):
           nonlocal calls; calls += 1
           raise ConnectionError('boom')
       monkeypatch.setattr('utils.redis_cache.redis_cache.get', failing)
       from fastapi_app.core import redis_wrapper as w
       w.reset_redis_circuit()
       for _ in range(4):
           await w.safe_get('k', fallback=None)
       assert calls == 3, '熔断后不应再触发 Redis 调用'
   ```
3. **契约不变**——所有 `safe_*` 的返回值语义与参数必须保持兼容（本工单不改签名）：
   ```bash
   grep -c "^async def safe_" fastapi_app/core/redis_wrapper.py   # 期望 18
   ```
4. **反例（修复前行为）**——上述测试 1 在修复前应观察到 ≥5 s（本次可先记录基线）。
5. 回归
   ```bash
   python -m pytest fastapi_app/tests/test_api_routes.py -q
   python -m pytest fastapi_app/tests/services/test_auxiliary_service.py -q
   ```

## 发布动作

改动 `core/redis_client.py` + `core/redis_wrapper.py` + `utils/redis_cache.py`（均为进程内模块）
→ **必须重启 `erp-prod`**。

## 回归风险

中低。返回语义未变，只是"最坏等待时间从 10 s 降到 0.3 s"。

**但必须做一次 Redis 故障演练来确认副作用**：
1. 临时停 `erp-redis` 服务（注意：需管理员，且 `erp-redis-broker:6380` 是 ARQ 用的，可分开处理）
2. 观察：`/api/health/ready` 是否能在 **1 s 内**返回（而非卡死）
3. 观察：业务列表接口是否返回降级数据而非 500
4. 观察：日志中是否出现"Redis 连续 3 次失败，熔断 30s"
5. 恢复 Redis → 确认 30 s 内自动恢复（或调 `reset_redis_circuit()` 立即恢复）

> 演练前请先确认 Redis 上**没有**未落盘的 ARQ 任务（否则停机可能丢任务）。
> 更安全的方式：不改服务，改 `.env` 里 `REDIS_PORT` 指向一个不可达端口 + 重启 `erp-prod`，演练完再改回。

## 关联

- **P0-07 必须先做**：`_note_failure` 依赖 `INFRA_EXCEPTIONS` 能抓到 `RedisError`，
  否则 `except INFRA_EXCEPTIONS` 仍然漏接，本工单的降级分支形同虚设。
- 本工单与 **P1-10**（`cache.py` 缓存击穿 100×100ms 轮询）是同一主题的两个面，
  建议排一起做，形成"Redis 故障全链路快速降级"的完整能力。
