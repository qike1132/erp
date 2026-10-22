# 批次 D — 低危收口 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 7 条低危缺陷（L1、L2、L4、L5、L7、L8、L9），并把原审查报告的错误结论勘误入档。

**Architecture:** 每条独立提交。金额改 Decimal 边界转换；配置在 app 创建期求值；密钥缓存加 TTL；CORS 默认值去掉 `null`。L2 只修可安全变更的状态时间戳，保留/告警的本地时间计算显式记档。

**Tech Stack:** Python 3.13、FastAPI、prometheus_client、pytest。

**Spec:** `docs/superpowers/specs/2026-10-22-performance-bug-fixes-design.md`（批次 D）

## Global Constraints

- 不重启生产、不改 `.env`。
- 每条先写失败测试，并做变异检查。
- 不新增迁移。

## Review Focus

1. 金额 Decimal→float 只在 JSON 边界发生，舍入仍是 HALF-UP。
2. `/metrics` token 比较常数时间且前缀不能绕过。
3. 签名密钥缓存 TTL 到期后重新读盘。
4. 开发默认 CORS 不再含 `null`。
5. metrics 去重不再依赖 prometheus_client 私有属性。

---

## Task 1: 金额 Decimal 边界转换（L1）

**Files:** Modify `fastapi_app/services/daily_production_service.py`; Test `tests/test_daily_money_decimal.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
from decimal import Decimal

def test_money_to_json_rounds_decimal_half_up():
    from fastapi_app.services.daily_production_service import _money_to_json
    assert _money_to_json(Decimal('1.005')) == 1.01
    assert _money_to_json(Decimal('2.675')) == 2.68
```

- [ ] **Step 2: 运行确认失败**（函数不存在）

- [ ] **Step 3: 实现**

```python
def _money_to_json(value) -> float:
    """金额只在 JSON 边界转 float；舍入始终在 Decimal 上做 HALF-UP。"""
    from decimal import ROUND_HALF_UP, Decimal
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return float(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
```

把 `round_money(float(...))` / `float(round_money(float(...)))` 四处改为 `_money_to_json(...)`。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(日报): 金额舍入改为 Decimal 边界转换，消除 0.01 级偏差`）

---

## Task 2: 备份状态时间戳改 aware UTC（L2 部分）

**Files:** Modify `fastapi_app/services/backup/records.py`、`fastapi_app/tasks/backup_tasks.py`；Test `tests/test_backup_timestamp_utc.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
def test_status_timestamp_is_utc_aware():
    import re
    from fastapi_app.services.backup import records
    src = open(records.__file__, encoding='utf-8').read()
    assert "datetime.now(UTC)" in src
    assert "datetime.now().strftime('%Y-%m-%d %H:%M:%S')" not in src
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

`records.py` 的状态 `timestamp` 与 sidecar `created_at` 改为 `datetime.now(UTC).isoformat()`（读回方按 ISO 解析）；`backup_tasks.py` 文件名保持本地时间并加注释说明「文件名格式被解析方依赖，刻意不改」。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(备份): 状态时间戳改 aware UTC，文件名保持本地时间并注明`）

---

## Task 3: `/metrics` token 常数时间比较（L4）

**Files:** Modify `fastapi_app/core/health.py`；Test `tests/test_metrics_token_compare.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
def test_token_compare_rejects_prefix_and_accepts_exact(monkeypatch):
    from fastapi_app.core import health
    monkeypatch.setenv('METRICS_BEARER_TOKEN', 'secret-token')
    assert health._metrics_token_ok('Bearer secret-token') is True
    assert health._metrics_token_ok('Bearer secret-token-extra') is False
    assert health._metrics_token_ok('Bearer secret') is False
```

- [ ] **Step 2: 运行确认失败**（helper 不存在）

- [ ] **Step 3: 实现**

```python
def _metrics_token_ok(authorization: str) -> bool:
    import hmac, os
    token = os.getenv('METRICS_BEARER_TOKEN', '')
    if not token:
        return False
    return hmac.compare_digest(authorization, f'Bearer {token}')
```

`/metrics` 用它替换 `startswith`。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(监控): /metrics token 改常数时间比较，前缀不再绕过`）

---

## Task 4: DOCS/CORS 在 app 创建期求值（L5）

**Files:** Modify `fastapi_app/main.py`；Test `tests/test_docs_url_runtime.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
def test_resolve_docs_urls_by_runtime_flag():
    from fastapi_app.main import resolve_docs_urls
    assert resolve_docs_urls(True) == (None, None, None)
    assert resolve_docs_urls(False) == ('/api/docs', '/api/redoc', '/api/openapi.json')
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
def resolve_docs_urls(is_production: bool):
    if is_production:
        return None, None, None
    return '/api/docs', '/api/redoc', '/api/openapi.json'
```

`create_app()` 用 `resolve_docs_urls(settings.is_production)` 传给 FastAPI；信息 payload 同源。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(配置): DOCS/OpenAPI 在 app 创建期求值，消除两套真相`）

---

## Task 5: metrics 去重不依赖私有属性（L7）

**Files:** Modify `fastapi_app/core/metrics.py`；Test `tests/test_metrics_registry.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
def test_duplicate_counter_returns_same_collector():
    from fastapi_app.core.metrics import _get_or_create_counter
    a = _get_or_create_counter('audit_dup_probe_total', 'probe', ['x'])
    b = _get_or_create_counter('audit_dup_probe_total', 'probe', ['x'])
    assert a is b
```

- [ ] **Step 2: 运行确认失败**（当前依赖 `REGISTRY._names_to_collectors`，重复创建时行为取决于私有属性）

- [ ] **Step 3: 实现**

模块级 `_CREATED_COLLECTORS: dict[str, object] = {}`；创建成功即登记；`ValueError` 分支从该字典取，取不到再 raise。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(监控): metrics 去重改自有登记表，不再依赖私有属性`）

---

## Task 6: 开发默认 CORS 去掉 null（L8）

**Files:** Modify `fastapi_app/core/config.py`；Test `tests/test_cors_default.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
def test_dev_cors_default_has_no_null_origin():
    from fastapi_app.core.config import DEFAULT_DEV_CORS_ORIGINS
    assert 'null' not in [o.strip() for o in DEFAULT_DEV_CORS_ORIGINS.split(',')]
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

抽出 `DEFAULT_DEV_CORS_ORIGINS` 常量并删除末尾 `,null`；`_raw_cors` 用它做默认值。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(配置): 开发默认 CORS 移除 null 源`）

---

## Task 7: JWT 签名密钥缓存 TTL（L9）

**Files:** Modify `fastapi_app/core/auth/token.py`；Test `tests/test_signing_key_ttl.py`（新建）。

- [ ] **Step 1: 写失败测试**

```python
def test_signing_key_cache_expires(monkeypatch, tmp_path):
    from fastapi_app.core.auth import token
    p = tmp_path / 'k.pem'
    p.write_text('KEY1', encoding='utf-8')
    monkeypatch.setattr(token.settings, 'ALGORITHM', 'RS256')
    monkeypatch.setattr(token.settings, 'JWT_PRIVATE_KEY_PATH', str(p))
    clock = {'t': 1000.0}
    monkeypatch.setattr(token.time, 'monotonic', lambda: clock['t'])
    token._signing_key_cache = None
    assert token._get_signing_key() == 'KEY1'
    p.write_text('KEY2', encoding='utf-8')
    clock['t'] += token._KEY_CACHE_TTL + 1
    assert token._get_signing_key() == 'KEY2'
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

`_KEY_CACHE_TTL = 300`；`_signing_key_cache_at`/`_verify_key_cache_at`；命中条件加时间窗；加载后写时间戳。

- [ ] **Step 4: 运行确认通过**

- [ ] **Step 5: 提交**（消息：`fix(认证): 签名密钥缓存加 TTL，轮换无需全量重启`）

---

## Task 8: 审查报告勘误入档（L6/D9）

**Files:** Create `docs/reviews/2026-10-22-performance-and-bug-review.md`（从工作区复制）；Modify 同文件顶部加勘误表。

- [ ] **Step 1: 复制报告并加勘误表**（M13 不属实、H3 未观测、M7 备份调度已有补跑、L15 maxclients、H1 量级、L6 刻意设计）。
- [ ] **Step 2: 提交**（消息：`docs(审计): 入档 2026-10-22 审查报告并附核实勘误`）。

---

## 批次 D 完成门槛

- [ ] 8 个任务全绿，每个有变异检查。
- [ ] 聚焦 + 提权全量 pytest 0 failed。
- [ ] ruff / mypy / quality_gate 通过。
