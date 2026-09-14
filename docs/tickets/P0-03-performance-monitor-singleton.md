# P0-03　`performance_monitor` 单例 `__init__` 未执行 → 系统统计接口 500

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（接口稳定 500） |
| 类型 | 缺陷 · 构造错误 |
| 模块 | `utils/performance_monitor.py`、`fastapi_app/services/auxiliary_service.py` |
| 预估工时 | 30 min |
| 批次 | A |
| 依赖 | 无 |

## 现象

系统统计接口（`get_system_stats`）稳定 500。而该端点不在启动路径上，因此**应用启动正常、无任何启动期告警**，
只在有人打开系统统计/运维面板时才暴露 —— 典型的"长期无人发现"型缺陷。

## 定位

`utils/performance_monitor.py:101`

```python
performance_monitor = PerformanceMiddleware.__new__(PerformanceMiddleware)
```

`PerformanceMiddleware.__init__` 才负责初始化状态（`:20-30`）：

```python
class PerformanceMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, slow_query_threshold: float = 1.0,
                 slow_request_threshold: float = 2.0):
        super().__init__(app)
        self.slow_query_threshold = slow_query_threshold
        self.slow_request_threshold = slow_request_threshold
        self.stats = {
            'total_requests': 0, 'slow_requests': 0, 'errors': 0, 'avg_response_time': 0.0
        }
```

消费方 `fastapi_app/services/auxiliary_service.py:306-323`：

```python
async def get_system_stats() -> dict:
    try:
        from utils.performance_monitor import performance_monitor, query_tracker
        return {
            'cache': {},
            'performance': {
                **performance_monitor.get_stats(),      # ← L318  AttributeError: 'stats'
                'queries': query_tracker.get_stats()
            }
        }
    except ImportError:                                  # ← L322  只捕 ImportError
        return {'cache': {}, 'performance': {}}
```

## 根因

`__new__` 只分配对象、**不调用 `__init__`**，因此 `self.stats` / `self.slow_query_threshold` /
`self.slow_request_threshold` 全部缺失 → `get_stats()` 读 `self.stats` 抛 `AttributeError`。

而消费方只 `except ImportError`，`AttributeError` 直接冒泡 → 500。

> 注：`PerformanceMiddleware` 需要 `app` 参数，本就不能在模块级直接实例化 ——
> 这也是当初写 `__new__` 的原因，属于"为了绕过构造参数而引入错误构造"。

### 关键补充发现（决定修复方式）

**`PerformanceMiddleware` 在全仓范围内从未注册**：

```bash
grep -rn "PerformanceMiddleware\|performance_monitor" fastapi_app/main.py fastapi_app/core/*.py
# → 无输出
```

即这个全局对象**从来没有被写入过数据**，`get_stats()` 修好后返回的必然是「全 0 + 阈值」。
这也解释了为什么缺陷能潜伏这么久：没有任何代码路径真正依赖它的数据。

因此**修复目标是"让它不再崩溃"，而不是"让它有数据"**。
是否真正注册该中间件（会为每个请求增加一次中间件开销）属于**独立决策**，不应捆绑在热修里（见文末「后续」）。

## 修复方案

把"需要 app 的中间件"与"无依赖的统计持有者"解耦：

```diff
--- a/utils/performance_monitor.py
+++ b/utils/performance_monitor.py
@@
-performance_monitor = PerformanceMiddleware.__new__(PerformanceMiddleware)
+class PerformanceStatsHolder:
+    """性能统计持有者（无 app 依赖，供 get_system_stats 等只读消费方使用）
+
+    与 PerformanceMiddleware 的区别：本类不参与请求处理，仅保存/暴露统计值。
+    若后续注册了 PerformanceMiddleware，应改为由中间件实例把值同步到这里
+    （或在 get_system_stats 里直接取中间件实例）。
+    """
+
+    def __init__(self, slow_query_threshold: float = 1.0,
+                 slow_request_threshold: float = 2.0):
+        self.slow_query_threshold = slow_query_threshold
+        self.slow_request_threshold = slow_request_threshold
+        self.stats = {
+            'total_requests': 0, 'slow_requests': 0, 'errors': 0, 'avg_response_time': 0.0
+        }
+
+    def get_stats(self) -> dict:
+        return {
+            **self.stats,
+            'slow_query_threshold': self.slow_query_threshold,
+            'slow_request_threshold': self.slow_request_threshold,
+            'timestamp': datetime.now().isoformat(),
+        }
+
+    def reset_stats(self) -> None:
+        for k in self.stats:
+            self.stats[k] = 0
+
+
+performance_monitor = PerformanceStatsHolder()
```

**同时收窄消费方的异常捕获**（否则下次换个 AttributeError 还是 500）：

```diff
--- a/fastapi_app/services/auxiliary_service.py
+++ b/fastapi_app/services/auxiliary_service.py
@@
-    except ImportError:
+    except (ImportError, AttributeError) as e:
+        logger.warning('系统统计不可用: %s', e, exc_info=True)
         return {'cache': {}, 'performance': {}}
```

> ⚠️ 只改 `performance_monitor.py` 也能让接口恢复 200。
> 但**不加宽 except 就等于保留了下一次 500 的通道** —— 建议两处都改。
> 注意 `except (ImportError, AttributeError)` 会掩盖真实缺陷，所以必须**带日志**（上例已加 `exc_info=True`），不能静默 `pass`。

## 验收标准

1. 直接验证不崩
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe -c "
   from utils.performance_monitor import performance_monitor, query_tracker
   print(performance_monitor.get_stats()); print(query_tracker.get_stats())"
   ```
   期望：打印出含 `total_requests: 0` 的 dict，**不抛 AttributeError**。
2. 端到端
   ```bash
   curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5002/api/v1/auxiliary/system-stats
   ```
   期望 200。（未鉴权时应为 401，需带 cookie 或换用已有前端调用的路径）
3. 既有测试
   ```bash
   C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe -m pytest fastapi_app/tests/services/test_auxiliary_service.py -q
   ```
   `test_auxiliary_service.py:277-288` 已 `patch` 该单例，改动后**必须仍通过**
   （它 patch 的是 `performance_monitor` 名字，本方案保留同名 → 兼容）。

## 发布动作

后端源码改动 → **必须重启 `erp-prod`**。

## 回归风险

低。`performance_monitor` 仅在 `auxiliary_service.py:318` 被消费，且无写入方，改动面收敛。
已确认 `test_auxiliary_service.py` 对它有 patch，需一并跑过。

## 后续（另开工单，不在本工单范围）

1. **决定是否注册 `PerformanceMiddleware`**：它提供 `X-Response-Time`/`X-Request-ID` 响应头与慢请求日志。
   但 `core/middleware.py` 已有类似职责（含 Prometheus 指标），存在**功能重叠**。
   建议先比对两者，择一保留，避免请求链路上挂两个性能中间件。
2. `query_tracker.queries / slow_queries` 是无界 list（`:144-160` 只 append、只提供手动 `clear()`），
   且 `params` 把整份 args/kwargs 转字符串常驻 → **长跑进程无界内存泄漏**。
   若没有人消费 `query_tracker`，建议直接删除；否则改 `collections.deque(maxlen=N)`。
