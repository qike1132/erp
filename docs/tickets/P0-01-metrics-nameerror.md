# P0-01　生产 `/metrics` 必抛 `NameError`

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（监控链路整体失效） |
| 类型 | 缺陷 · 单行修复 |
| 模块 | `fastapi_app/core/health.py` |
| 预估工时 | 5 min |
| 批次 | A |
| 依赖 | 无 |

## 现象

生产环境 `GET /metrics` 返回 500。Prometheus 抓取全部失败，指标断流 →
**基于指标的告警（慢查询、任务失败、连接池、备份健康）全部静默失效**，且运维会看到 500 而非 401，排障方向被误导。

## 定位

`fastapi_app/core/health.py:168-183`

```python
    try:
        from fastapi_app.core.metrics import get_content_type, get_metrics

        @app.get("/metrics", tags=["监控"])
        async def metrics(request: Request):
            # 生产环境要求 Bearer Token 或内网 IP 访问
            from fastapi_app.core.config import settings as _settings
            if _settings.is_production:               # ← 生产分支
                auth = request.headers.get('authorization', '')
                metrics_token = _os.getenv('METRICS_BEARER_TOKEN', '')   # ← L177: _os 未定义
                if metrics_token and not auth.startswith(f'Bearer {metrics_token}'):
                    from starlette.responses import JSONResponse
                    return JSONResponse(status_code=401, content={'detail': '未授权访问'})
            return Response(content=get_metrics(), media_type=get_content_type())
    except (ImportError, AttributeError):
        pass  # defensive: 异常静默处理,不影响主流程
```

文件顶部导入段（已核对）只有：

```python
import json
import logging
import time
import redis.exceptions
```

**没有 `import os`，也没有 `os as _os`。** 全文件 `_os` 仅在 L177 出现一次。

## 根因

`_os` 是历史重构（可能曾从 `import os as _os` 改名）遗留的悬挂引用。
注意 L182 的外层 `except (ImportError, AttributeError)` **拦不住 `NameError`**：
- 该 try 包裹的是**路由注册**（import 期执行），而 `NameError` 发生在**请求期**的函数体内；
- 因此异常不会被吞掉，而是冒泡为 500 —— 这正是"静默失效但看得到 500"的原因。

## 修复方案

**方案 A（最小改动，推荐）**

```diff
--- a/fastapi_app/core/health.py
+++ b/fastapi_app/core/health.py
@@
+import os
 import json
 import logging
 import time
 import redis.exceptions
@@
-                metrics_token = _os.getenv('METRICS_BEARER_TOKEN', '')
+                metrics_token = os.getenv('METRICS_BEARER_TOKEN', '')
```

**方案 B（增强，尽力为之）** —— 顺手把 `is_production` 分支的安全语义补完整。
当前逻辑有缺口：`if metrics_token and ...` 意味着**未配置 `METRICS_BEARER_TOKEN` 时生产环境 /metrics 完全裸奔**。
建议同时校验内网来源：

```python
            if _settings.is_production:
                auth = request.headers.get('authorization', '')
                metrics_token = os.getenv('METRICS_BEARER_TOKEN', '')
                client_host = request.client.host if request.client else ''
                is_internal = client_host.startswith(('127.', '10.', '192.168.', '172.1', '172.2', '172.3'))
                if metrics_token:
                    if not auth.startswith(f'Bearer {metrics_token}'):
                        return JSONResponse(status_code=401, content={'detail': '未授权访问'})
                elif not is_internal:
                    return JSONResponse(status_code=403, content={'detail': '禁止外部访问'})
```

> ⚠️ 方案 B 会改变对外行为（未配 token 时外部访问由 200 变 403）。若 Prometheus 与本机非同机（跨网段抓取），
> 会**打断现有抓取** —— 上线前先确认抓取源 IP，或在 `.env` 配好 `METRICS_BEARER_TOKEN` 再用方案 B。
> 稳妥起见：本次先只做方案 A，方案 B 另开工单。

## 验收标准

1. 静态检查
   ```bash
   grep -n "^import os" fastapi_app/core/health.py      # 应命中
   grep -n "_os\." fastapi_app/core/health.py           # 应无输出
   ```
2. 单元/集成验证（无需重启生产，起临时实例即可）
   ```bash
   APP_ENV=production uvicorn fastapi_app.main:app --port 5199
   curl --noproxy '*' -i http://127.0.0.1:5199/metrics
   ```
   - 期望：**200**（未配 token 且在方案 A 下）或 **401**（已配 token 且未带头）
   - 反例（修复前）：500
3. 生产重启后
   ```bash
   curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5002/metrics
   ```
   期望 200。Prometheus target 状态由 `DOWN` 转 `UP`。

> 注意：沙箱有 HTTP 代理，必须用 `--noproxy '*'`，否则会返回代理的 502 而误判。

## 发布动作

后端源码改动 → **必须重启 `erp-prod`**（NSSM 生产模式 4 worker，无 `--reload`）。
沙箱非提权，需管理员通过服务器管理器执行。

## 回归风险

极低。唯一风险是方案 B 的语义变更（本工单不做）。

## 建议补充的测试

新增 `fastapi_app/tests/test_metrics_endpoint.py`：

```python
@pytest.mark.parametrize('env,token,expect', [
    ('production', None, 200),
    ('production', 'secret', 401),
    ('development', None, 200),
])
def test_metrics_status(...): ...
```

本工单暴露的真正教训：**监控端点自身没有测试**，导致它坏了整整一段时间无人发现。
建议把「`/metrics` 返回 200」纳入健康巡检脚本。
