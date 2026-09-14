# P0-07　`INFRA_EXCEPTIONS` 漏掉 `RedisError` → 几乎所有降级分支实际失效

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（降级机制整体失效） |
| 类型 | 缺陷 · 异常处理 |
| 模块 | `fastapi_app/core/exception_handler.py`（单点定义，38 处使用） |
| 预估工时 | 15 min |
| 批次 | A |
| 依赖 | 无（但 **P0-08 依赖本工单**） |

## 现象

Redis 不可用（宕机、认证失败、网络不通）时，所有本应"静默降级"的路径**不再降级**，
而是抛异常冒泡成 500。受影响面覆盖：缓存读写、事件总线发布、通知分发、订单命令通道、死信队列。

即：**Redis 一挂，不只是慢，而是大面积 500。**

## 定位

`fastapi_app/core/exception_handler.py:18`

```python
INFRA_EXCEPTIONS = (OSError, ConnectionError)  # 移除 ValueError：业务校验异常不应被基础设施降级捕获
```

该元组的**使用面共 38 处**（已核对，`grep -rn INFRA_EXCEPTIONS`）：

| 文件 | 使用点数 |
|---|---|
| `core/redis_wrapper.py` | 18（`safe_get/set/delete/publish/lpush/lrange/incr/expire/exists/...` 全部 `safe_*`） |
| `core/exception_handler.py` | 2（`safe_call` / `safe_publish_event`） |
| `core/purchase_cache.py` | 5 |
| `core/event_bus.py` | 1 |
| `services/notification_service.py` | 4 |
| `services/order/commands.py` | 1 |
| `services/order/_common.py` | 1 |
| `services/order/{approval_flow,deduction,queries}.py` | 各 1（import） |

典型用法（`core/redis_wrapper.py:18-26`）：

```python
async def safe_get(key: str, fallback: Any = None, context: str = "") -> Any:
    try:
        from utils.redis_cache import redis_cache
        return await redis_cache.get(key)
    except INFRA_EXCEPTIONS as e:          # ← 这里抓不到 RedisError
        logger.warning("%s读取失败: %s", _ctx(context, key), e)
        return fallback
```

## 根因

**`redis-py` 的异常层级与内置异常无关**：

```
redis.exceptions.RedisError(Exception)
├── ConnectionError        ← redis.exceptions.ConnectionError，不是内置 ConnectionError
├── TimeoutError           ← redis.exceptions.TimeoutError，不是内置 TimeoutError
├── AuthenticationError
├── ...
```

所以 `except (OSError, ConnectionError)` **抓不到任何 Redis 异常**。

> **这一点项目内部其实已经知道**。`fastapi_app/core/redis_client.py:15-27` 有明确记载：
>
> ```python
> def redis_infra_exceptions():
>     """Redis 异常基类（redis.exceptions.RedisError）与内置基础设施异常并集。
>
>     注意：redis-py 的 ConnectionError/AuthenticationError 继承自 RedisError
>     而非 Python 内置 ConnectionError，必须显式纳入，否则 Redis 不可用/认证
>     失败会在启动预热时逃逸并导致应用启动崩溃。
>     """
>     from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
>     try:
>         import redis.exceptions as redis_exc
>         return (*INFRA_EXCEPTIONS, redis_exc.RedisError)
>     except Exception:
>         return INFRA_EXCEPTIONS
> ```
>
> **问题在于：只有 `redis_client` 这一个调用方用了正确的并集，
> 其余 38 处（含 `redis_wrapper` 全部 `safe_*`）仍在用有缺陷的 `INFRA_EXCEPTIONS`。**
> 这是典型的"知识写在了注释里，但没有落到类型定义上"。

## 修复方案（单点修复，38 处同时生效）

```diff
--- a/fastapi_app/core/exception_handler.py
+++ b/fastapi_app/core/exception_handler.py
@@
 import logging
 from collections.abc import Callable
 from typing import Any

 logger = logging.getLogger(__name__)

-INFRA_EXCEPTIONS = (OSError, ConnectionError)  # 移除 ValueError：业务校验异常不应被基础设施降级捕获
+try:
+    # redis-py 的 ConnectionError/TimeoutError/AuthenticationError 均继承
+    # redis.exceptions.RedisError，而非内置 ConnectionError/OSError。
+    # 不显式纳入会导致 Redis 不可用时 safe_* 全部漏接异常、降级机制失效（P0-07）。
+    from redis.exceptions import RedisError as _RedisError
+    _REDIS_INFRA: tuple[type[BaseException], ...] = (_RedisError,)
+except ImportError:  # pragma: no cover - redis 为硬依赖，此处仅防御轻量工具场景
+    _REDIS_INFRA = ()
+
+# 统一的基础设施异常元组：内置 IO/连接异常 + Redis 全部异常
+# 注：不再包含 ValueError（业务校验异常不应被基础设施降级捕获）
+INFRA_EXCEPTIONS: tuple[type[BaseException], ...] = (
+    OSError, ConnectionError, *_REDIS_INFRA
+)
```

### 配套改动（2 处，避免遗漏）

1. **`core/cache.py:301`** —— 这里没有用 `INFRA_EXCEPTIONS`，而是硬编码了字面量：
   ```python
   # cache.py:301
   except (OSError, ConnectionError) as e:
       logger.error("缓存装饰器执行失败: %s", e, exc_info=True)
       return await func(*args, **kwargs)
   ```
   改为 `except INFRA_EXCEPTIONS as e:`（需在文件内 import）。

2. **`core/cache.py:233`** —— 同类字面量：
   ```python
   with contextlib.suppress(TimeoutError, OSError, ConnectionError):
       await redis.delete(lock_key)
   ```
   建议改为 `contextlib.suppress(TimeoutError, *INFRA_EXCEPTIONS)`。

3. **`core/redis_client.py` 的 `redis_infra_exceptions()` 变为冗余** —— 修复后它返回的就是 `INFRA_EXCEPTIONS`。
   建议保留该函数（避免破坏调用方）但把实现简化为 `return INFRA_EXCEPTIONS`，
   并更新 docstring 指引读者去看 `exception_handler`。

## ⚠️ 权衡说明（请审阅者注意）

本改动会让**更多异常被吞掉**。这是一个**有意的取舍**：

| | 修复前 | 修复后 |
|---|---|---|
| Redis 故障时 | 抛异常 → 500（**可见，但用户侧不可用**） | 记 warning + 返回 fallback（**业务可用，但故障不可见**） |
| 排障 | 立刻暴露 | 依赖日志告警 |

因此**日志质量就是本工单的安全网**：必须确认所有降级点都落在 WARNING 级别且带 `context`，
否则会从"Redis 挂了 → 全站 500"变成"Redis 挂了 → 全站静默返回空数据"。后者往往更难排查。

`redis_wrapper` 的 `safe_*` 已有 `context=` 参数（由调用方传入，如 `context="客户名称缓存"`），符合要求。
**但 `services/order/commands.py:311`、`notification_service.py:130/238/253/259` 需逐个确认日志是否带上下文**
（本工单验收项 3）。

## 验收标准

1. **单点生效验证**
   ```bash
   python -c "
   import fastapi_app.core.exception_handler as m
   import redis.exceptions as r
   print('RedisError 已在元组内:', r.RedisError in m.INFRA_EXCEPTIONS)
   print('内置 ConnectionError 仍在:', ConnectionError in m.INFRA_EXCEPTIONS)"
   ```
   期望：两项均为 True
2. **反例验证（证明修复有效）**——直接把 `RedisError` 喂给捕获逻辑：
   ```python
   @pytest.mark.asyncio
   async def test_safe_get_degrades_on_redis_error(monkeypatch):
       from redis.exceptions import ConnectionError as RedisConnError
       async def boom(*a, **k): raise RedisConnError('redis down')
       monkeypatch.setattr('utils.redis_cache.redis_cache.get', boom)
       from fastapi_app.core.redis_wrapper import safe_get
       assert await safe_get('k', fallback={'x': 1}) == {'x': 1}   # 必须降级，不得抛
   ```
   **修复前该测试会失败（异常冒泡）** —— 这是本工单的核心回归保护。
3. **降级日志可读性巡检**（人工，5 min）——确认以下位置都有带上下文的 WARNING 日志：
   `services/order/commands.py:311`、`services/notification_service.py:130/238/253/259`
4. 全量相关单测
   ```bash
   python -m pytest fastapi_app/tests/services/test_auxiliary_service.py -q
   python -m pytest fastapi_app/tests/test_api_routes.py -q
   ```

## 发布动作

`core/exception_handler.py` 是进程内模块 → **必须重启 `erp-prod`**。

## 回归风险

**中**（本批 P0 中风险最高的两项之一，另一项是 P0-04）。

- 风险来源：从"异常冒泡"变成"静默降级"，可能**掩盖真实故障**
- 缓解措施：
  1. 上线后**主动制造一次 Redis 故障演练**（临时停 `erp-redis` 或改错 `REDIS_PASSWORD`），
     确认：业务接口返回降级值而非 500，且日志中能看到 `safe_*` 的 WARNING
  2. 为降级日志配一条告警规则（`grep "读取失败\|写入失败"` 超阈值告警），把"静默"补回来
- 若团队更倾向"宁可 500 也要可见"，可只对**缓存读路径**纳入 `RedisError`，
  写路径与订单路径保持原样。请审阅时明确选择。

## 关联

- **P0-08 依赖本工单**：Redis 超时治理需要"超时后能降级"这个前提，
  而当前降级根本抓不到异常，故 P0-08 必须在本工单之后做。
- 同一类问题还可延伸检查：`core/event_bus.py:27`、`core/purchase_cache.py:43/59/72` 用了
  `(RuntimeError, *INFRA_EXCEPTIONS)` 的组合，修复后行为同样改善，无需单独改动。
