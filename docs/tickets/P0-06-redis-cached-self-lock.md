# P0-06　`redis_cached` 同步分支在事件循环内自锁（**零调用死代码**）

| 字段 | 值 |
|---|---|
| 严重度 | 🟡 中 → **实际为「潜伏隐患」**（见下方修正） |
| 类型 | 死代码 / 隐患 |
| 模块 | `utils/redis_cache.py` |
| 预估工时 | 10 min（建议**直接删除**） |
| 批次 | A |
| 依赖 | 无 |

## ⚠️ 分级修正（复核后下调）

初审报告把它列为 P0 并描述为"每次缓存读写卡 5s"。**复核后发现它从未被调用**：

```bash
grep -rn "redis_cached" --include=*.py . | grep -v __pycache__ \
  | grep -v "def redis_cached\|utils/redis_cache.py"
# → 无输出（零调用点）
```

即：**当前不存在"每次卡 5s"的实际影响**。它是一颗**尚未引爆的地雷** ——
一旦有人拿它去装饰同步函数，就会立刻踩中。

> 之所以仍留在 P0 批次：修复成本 10 分钟、且顺手清掉死代码可降低后续误用概率。
> 但**不应以"性能故障"为由排期**，这点必须在工单上看清，避免误导优先级判断。

## 定位

`utils/redis_cache.py:263-312`

```python
def redis_cached(timeout: int = 300, key_prefix: str | None = None):
    """异步 Redis 缓存装饰器，支持 async 和 sync 函数"""
    def decorator(f):
        is_async = asyncio.iscoroutinefunction(f)

        if is_async:
            ...                                   # async 分支：正常
        else:
            @wraps(f)
            def sync_wrapper(*args, **kwargs):
                cache_key = _generate_cache_key(f, key_prefix, args, kwargs)
                import asyncio as _aio
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    result = _aio.run_coroutine_threadsafe(       # ← L291
                        redis_cache.get(cache_key), loop
                    ).result(timeout=5)                            # ← L293
                else:
                    result = _aio.run(redis_cache.get(cache_key))
                ...
```

## 根因

`get_running_loop()` **成功**意味着当前线程就是这条事件循环的线程。
此时再 `run_coroutine_threadsafe(coro, loop)` 是把协程投回**同一条** loop，
然后 `.result(timeout=5)` **阻塞该 loop 等待自己** —— 被等待的协程永远没有机会被执行。

**必然结果**：每次都等到 5 秒超时，抛 `concurrent.futures.TimeoutError`，协程从未运行。

正确的判断是反过来的：**只有在"非 loop 线程"里才能用 `run_coroutine_threadsafe`**。

## 修复方案

### 方案 A（推荐）：直接删除

理由：
1. `redis_cached` 与其 async 分支**均无调用点**，属纯死代码
2. 项目已有更完善的缓存装饰器（`fastapi_app/core/cache.py` 的 `cache_result`
   带 L1/L2 两级缓存、分布式锁、断路器），没有理由保留第二个平行的缓存装饰器
3. 删除是唯一能**彻底消除误用风险**的方案

```bash
# 1) 删除 redis_cached 及其同步分支（L263-312）
# 2) 确认无残留引用
grep -rn "redis_cached" --include=*.py . | grep -v __pycache__
#    期望：无输出
# 3) 若有测试引用，一并删除
```

### 方案 B（若必须保留）：修掉自锁

```diff
--- a/utils/redis_cache.py
+++ b/utils/redis_cache.py
@@
             @wraps(f)
             def sync_wrapper(*args, **kwargs):
                 cache_key = _generate_cache_key(f, key_prefix, args, kwargs)
                 import asyncio as _aio
                 try:
-                    loop = _aio.get_running_loop()
+                    _aio.get_running_loop()
                 except RuntimeError:
-                    loop = None
-
-                if loop and loop.is_running():
-                    result = _aio.run_coroutine_threadsafe(
-                        redis_cache.get(cache_key), loop
-                    ).result(timeout=5)
-                else:
-                    result = _aio.run(redis_cache.get(cache_key))
-
-                if result is not None:
-                    return result
-
-                result = f(*args, **kwargs)
-
-                if result is not None:
-                    if loop and loop.is_running():
-                        _aio.run_coroutine_threadsafe(
-                            redis_cache.set(cache_key, result, timeout), loop
-                        )
-                    else:
-                        _aio.run(redis_cache.set(cache_key, result, timeout))
-
-                return result
+                    # 场景 1：不在事件循环线程内 → 可安全用 asyncio.run
+                    result = _aio.run(redis_cache.get(cache_key))
+                    if result is not None:
+                        return result
+                    result = f(*args, **kwargs)
+                    if result is not None:
+                        _aio.run(redis_cache.set(cache_key, result, timeout))
+                    return result
+                # 场景 2：已在事件循环线程内 → 同步阻塞该 loop 是自锁，
+                # 必须显式拒绝，让调用方改用 async 版本
+                raise RuntimeError(
+                    'redis_cached 不支持在事件循环线程内装饰同步函数：'
+                    '请改用 async 版本的 cache_result（fastapi_app.core.cache）'
+                )
             return sync_wrapper
```

方案 B 的取舍：把"静默卡 5 秒"改成"立刻抛错"。**这比自锁好，但仍不如方案 A** ——
它保留了重复的缓存实现。

**唯一不可接受的选项是维持现状。**

## 验收标准

1. ```bash
   grep -rn "redis_cached" --include=*.py . | grep -v __pycache__
   ```
   方案 A：无输出；方案 B：仅有定义处
2. 门禁
   ```bash
   python -m ruff check utils/redis_cache.py
   ```
3. 通用缓存回归（确认删除未影响真正在用的缓存）
   ```bash
   python -m pytest fastapi_app/tests/services/test_auxiliary_service.py -q
   ```
4. **反向验证（方案 B 必做）**——写一个临时用例证明它现在会抛错而不是卡 5s：
   ```python
   @pytest.mark.asyncio
   async def test_redis_cached_sync_in_loop_raises():
       @redis_cached(timeout=1)
       def sync_fn(): return 1
       with pytest.raises(RuntimeError, match='不支持在事件循环线程内'):
           sync_fn()
   ```
   修复前：该测试会**挂起 5 秒后抛 TimeoutError**（即证明缺陷存在）。

## 发布动作

`utils/redis_cache.py` 被 `fastapi_app` 导入（经 `redis_wrapper`），
若采用方案 A/B 改动该文件 → **需重启 `erp-prod`**（模块已加载在进程内）。

## 回归风险

极低。零调用点意味着运行时行为不可能改变。

## 相关线索（同一文件，一并留意）

`utils/redis_cache.py:51-58` 的 `RedisCacheManager.redis_client` 构造参数为
`socket_timeout=5, retry_on_timeout=True`。这本身合理，但它是 P0-08 的关联项：
`safe_*` 包装缺 `asyncio.wait_for`，一次超时会被 `retry_on_timeout=True` 放大为两次（≈10s）。
修 P0-08 时需回到本文件确认客户端参数。
