# ERP 系统上线前代码优化方案

> 审核发现 62 个问题（高危 7 · 中危 30 · 低危 25），以下按优先级给出逐文件优化方案。

---

## P0 — 阻断上线（必须立即修复）

### 1. `.env.production` — 生产环境凭据泄露

**问题**：数据库密码、JWT 密钥、Redis 密码硬编码且已提交 git 历史。

**优化方案**：

```bash
# 步骤 1：立即将 .env.production 加入 .gitignore
echo ".env.production" >> .gitignore

# 步骤 2：从 git 历史彻底清除（使用 BFG）
bfg --delete-files .env.production
git reflog expire --expire=now --all && git gc --prune=now --aggressive

# 步骤 3：轮换所有已泄露凭据（在新的 .env.production 中填入新凭据）
# 新 .env.production 不再提交 git，通过部署脚本从密钥管理服务注入

# 步骤 4：提供 .env.production.example 作为模板（不含真实值）
```

**`.env.production.example` 模板**：
```env
POSTGRES_PASSWORD=<从密钥管理服务注入>
JWT_SECRET_KEY=<从密钥管理服务注入>
REDIS_PASSWORD=<从密钥管理服务注入>
# 其他非敏感配置可保留
```

---

### 2. `fastapi_app/api/v1/endpoints/backup/records.py` 第 89 行 — 路径遍历漏洞

**问题**：`delete_server_backup` 未校验 filename 中的 `../`，可删除任意文件。

**修改前**（第 89-114 行）：
```python
@router.delete('/delete-by-name/{filename}', response_model=BackupDeleteResponse)
async def delete_server_backup(
    filename: str,
    user: User = Depends(require_backup_permission('delete_server_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    deleted = ''
    try:
        deleted = backup_service.delete_backup_file(filename)
```

**修改后**：
```python
from pathlib import Path

@router.delete('/delete-by-name/{filename}', response_model=BackupDeleteResponse)
async def delete_server_backup(
    filename: str,
    user: User = Depends(require_backup_permission('delete_server_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    # 路径遍历防护：确保 filename 不含目录分隔符
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='文件名包含非法路径字符')
    deleted = ''
    try:
        deleted = backup_service.delete_backup_file(safe_name)
```

---

### 3. `fastapi_app/services/notification_service.py` 第 129 行 — NameError

**问题**：`INFRA_EXCEPTIONS` 未导入就使用，运行时抛 NameError。

**修改前**（第 19-23 行导入）：
```python
from fastapi_app.core.redis_client import (
    get_async_redis_client,
    redis_infra_exceptions as _redis_infra_exceptions,
    reset_async_redis_client,
)
```

**修改后**（添加导入）：
```python
from fastapi_app.core.redis_client import (
    get_async_redis_client,
    redis_infra_exceptions as _redis_infra_exceptions,
    reset_async_redis_client,
)
from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
```

> 同步修复第 237、252、258 行同样引用 `INFRA_EXCEPTIONS` 的位置——添加导入后全部解决。

---

### 4. `requirements.txt` — 依赖安全

**优化方案**：
```bash
# 步骤 1：锁定所有依赖精确版本
pip-compile requirements.in --output-file requirements.txt

# 步骤 2：扫描已知漏洞
pip-audit --requirement requirements.txt

# 步骤 3：升级有 CVE 的依赖
pip-audit --fix

# 步骤 4：前端同理
cd frontend-vite && npm audit && npm audit fix
```

---

## P1 — 上线前强烈建议修复

### 5. `fastapi_app/api/v1/endpoints/customer_sampling.py` 第 231 行 — 文件上传无大小限制

**修改前**：
```python
content = await file.read()
```

**修改后**：
```python
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
content = await file.read()
if len(content) > MAX_IMAGE_SIZE:
    raise HTTPException(status_code=413, detail='文件大小超过 10MB 限制')
```

---

### 6. `fastapi_app/api/v1/endpoints/backup/validation.py` 第 407 行 — 同步 IO 阻塞

**修改前**：
```python
content = filepath.read_bytes()
```

**修改后**：
```python
import asyncio
content = await asyncio.to_thread(filepath.read_bytes)
```

---

### 7. `fastapi_app/api/v1/endpoints/backup/restore.py` 第 105 行 — .gz 误判为 JSON

**修改前**：
```python
is_json = filename.endswith('.json') or filename.endswith('.gz') or (content[:1] == b'{' and content.strip().endswith(b'}'))
```

**修改后**：
```python
import gzip
is_json = filename.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
is_gz = filename.endswith('.gz') or (content[:2] == b'\x1f\x8b')  # gzip 魔数
if not is_zip and not is_json and not is_gz:
    raise HTTPException(status_code=400, detail='无法识别的备份文件格式')
# is_gz 时先解压再按 JSON 处理
if is_gz:
    content = await asyncio.to_thread(gzip.decompress, content)
    is_json = True
```

---

### 8. `fastapi_app/api/v1/endpoints/backup/actions.py` 第 118-120 行 — 异常处理缺失

**修改前**：
```python
if password:
    from fastapi_app.core.backup_progress import store_task_password
    await store_task_password(task_id, password)
```

**修改后**：
```python
if password:
    from fastapi_app.core.backup_progress import store_task_password
    try:
        await store_task_password(task_id, password)
    except Exception:
        logger.warning('store_task_password 失败，继续入队（task_id=%s）', task_id)
```

---

### 9. `fastapi_app/core/config.py` 第 106、111 行 — Cookie 过期 + ALLOWED_HOSTS

**修改前**：
```python
COOKIE_MAX_AGE: int = int(os.getenv("COOKIE_MAX_AGE", 2678400))  # 31天
ALLOWED_HOSTS: list[str] = os.getenv("ALLOWED_HOSTS", "*").split(",")
```

**修改后**：
```python
# 缩短 Cookie 有效期至 1 天，配合 refresh token 续期
COOKIE_MAX_AGE: int = int(os.getenv("COOKIE_MAX_AGE", 86400))  # 1天
# 生产环境必须显式设置 ALLOWED_HOSTS，默认空列表（拒绝所有）
ALLOWED_HOSTS: list[str] = os.getenv("ALLOWED_HOSTS", "").split(",") if os.getenv("ALLOWED_HOSTS") else []
```

> 同时在 `__init__` 中添加生产环境校验：
```python
if self.APP_ENV == "prod" and (not self.ALLOWED_HOSTS or "*" in self.ALLOWED_HOSTS):
    raise RuntimeError("生产环境必须通过 ALLOWED_HOSTS 设置具体域名")
```

---

### 10. `fastapi_app/core/middleware.py` 第 78 行 — CSRF Cookie 安全标志

**修改前**：
```python
_csrf_secure = os.getenv("CSRF_COOKIE_SECURE", "").lower() in ("true", "1", "yes")
```

**修改后**：
```python
from fastapi_app.core.config import settings
# 生产环境默认 Secure，开发环境可通过环境变量显式关闭
_csrf_secure = os.getenv("CSRF_COOKIE_SECURE", "true" if settings.APP_ENV == "prod" else "").lower() in ("true", "1", "yes")
```

---

### 11. `fastapi_app/core/backup_progress.py` 第 135 行 — 密码明文存入 Redis

**修改前**：
```python
await client.set(_TASK_PASSWORD_PREFIX + task_id, password, ex=_TASK_PASSWORD_TTL)
```

**修改后**（使用应用层加密包装）：
```python
from fastapi_app.core.backup_encryption import _derive_key, _encrypt_bytes
import os

# 使用专用密钥加密密码后再存入 Redis
_TASK_PWD_ENC_KEY = os.getenv("TASK_PWD_ENC_KEY", "")  # 专用加密密钥

async def store_task_password(task_id: str, password: str) -> bool:
    try:
        client = await _get_redis()
        if client is None:
            return False
        # 加密后存储，避免 Redis 中明文密码
        if _TASK_PWD_ENC_KEY:
            key = _derive_key(_TASK_PWD_ENC_KEY, b'task_pwd_v1')
            encrypted = _encrypt_bytes(key, password.encode('utf-8'))
            await client.set(_TASK_PASSWORD_PREFIX + task_id, encrypted, ex=_TASK_PASSWORD_TTL)
        else:
            # 无加密密钥时降级为明文（开发环境）
            await client.set(_TASK_PASSWORD_PREFIX + task_id, password, ex=_TASK_PASSWORD_TTL)
        return True
    except Exception as e:
        logger.warning("写入任务密码侧信道失败（task_id=%s）: %s", task_id, e)
        return False
```

---

### 12. `fastapi_app/core/deps.py` 第 72 行 — 权限缓存延迟

**修改前**：
```python
_PERMISSION_CACHE = _TTLCache(ttl=30, maxsize=500)
```

**修改后**：
```python
# 缩短 TTL 至 5 秒，降低权限撤销后的越权窗口
_PERMISSION_CACHE = _TTLCache(ttl=5, maxsize=500)

# 并添加主动失效方法供权限变更时调用
async def invalidate_user_permission_cache(user_id: int) -> None:
    await _PERMISSION_CACHE.delete(user_id)
```

> 在用户权限变更（如角色修改、用户禁用）的 service 方法中调用 `invalidate_user_permission_cache(user_id)`。

---

### 13. `fastapi_app/core/arq_app.py` 第 157-168 行 — 连接池无锁保护

**修改前**：
```python
_arq_pool = None

async def get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(redis_settings)
    return _arq_pool
```

**修改后**：
```python
import asyncio

_arq_pool = None
_pool_lock = asyncio.Lock()

async def get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        async with _pool_lock:
            if _arq_pool is None:  # double-check
                _arq_pool = await create_pool(redis_settings)
    return _arq_pool
```

---

### 14. `fastapi_app/services/bom_service.py` 第 261-268 行 — N+1 查询

**修改前**：
```python
for filling_data in fillings_data or []:
    filling_role_id = _resolve_role_id(filling_data)
    filling_result = await db.execute(
        select(ProductMaterial).where(
            ProductMaterial.product_id == product_id,
            ProductMaterial.role_id == filling_role_id if filling_role_id else ProductMaterial.role_id.is_(None),
        )
    )
    filling_material = filling_result.scalars().first()
```

**修改后**（批量查询）：
```python
if fillings_data:
    # 批量查询所有需要的 ProductMaterial，消除 N+1
    filling_role_ids = [_resolve_role_id(fd) for fd in fillings_data]
    batch_result = await db.execute(
        select(ProductMaterial).where(
            ProductMaterial.product_id == product_id,
            ProductMaterial.role_id.in_([rid for rid in filling_role_ids if rid]),
        )
    )
    existing_map = {m.role_id: m for m in batch_result.scalars()}

    for filling_data in fillings_data:
        filling_role_id = _resolve_role_id(filling_data)
        filling_material = existing_map.get(filling_role_id)
        # ... 后续逻辑不变
```

---

### 15. `frontend-vite/src/router/index.ts` 第 183 行 — 前端权限绕过

**修改前**：
```typescript
// navSections 未加载时放行（非阻塞门）
if (authStore.user && !authStore.user.is_super && authStore.navSections.length > 0) {
```

**修改后**：
```typescript
// navSections 未加载时阻止导航（fail-closed），而非放行
if (authStore.user && !authStore.user.is_super) {
  if (authStore.navSections.length === 0) {
    // navSections 尚未加载，等待加载而非放行
    return false  // 阻止导航，用户停留在当前页
  }
  const targetPath = '/' + to.path.split('/').filter(Boolean)[0]
  const allowedPaths = authStore.filteredNavSections.flatMap((s) => s.items.map((i) => i.path))
  if (targetPath !== '/dashboard' && targetPath !== '/notifications' && targetPath !== '/' && !allowedPaths.includes(targetPath)) {
    return '/dashboard'
  }
}
```

> ⚠️ 前端权限检查仅用于 UI 体验，**后端 API 必须有独立权限校验**（已有 `require_permission` 依赖）。

---

### 16. `frontend-vite/src/views/product/composables/useBomCopyDialog.ts` 第 25 行 — 内存泄漏

**修改前**：
```typescript
export function useBomCopyDialog({ currentProductId, reloadBom }: UseBomCopyDialogDeps) {
  // ...
  const _pendingTimeouts = new Set<ReturnType<typeof setTimeout>>()
  // ... 无清理逻辑
  return { /* ... */ }
}
```

**修改后**：
```typescript
import { ref, reactive, onUnmounted, type Ref } from 'vue'

export function useBomCopyDialog({ currentProductId, reloadBom }: UseBomCopyDialogDeps) {
  // ...
  const _pendingTimeouts = new Set<ReturnType<typeof setTimeout>>()

  // 组件卸载时清理所有待处理定时器
  onUnmounted(() => {
    _pendingTimeouts.forEach(clearTimeout)
    _pendingTimeouts.clear()
  })

  // ... 其余逻辑不变
  return { /* ... */ }
}
```

---

### 17. `fastapi_app/schemas/backup.py` 第 140 行 — 加密密码过短

**修改前**：
```python
password: str = Field(min_length=1, description="加密密码")
```

**修改后**：
```python
password: str = Field(min_length=8, max_length=128, description="加密密码")
```

---

### 18. `fastapi_app/schemas/user.py` 第 9 行 — 用户密码过短

**修改前**：
```python
password: str = Field(..., min_length=6, max_length=128)
```

**修改后**：
```python
password: str = Field(..., min_length=8, max_length=128)
```

---

### 19. `fastapi_app/shared_models/__init__.py` 第 113 行 — DeviceToken 未导入

**修改前**：`__all__` 包含 `'DeviceToken'` 但未导入。

**修改后**：
```python
# 方案 A：添加导入（如果文件存在）
from .device_token import DeviceToken

# 方案 B：从 __all__ 移除（如果不需要）
# __all__ = [... 去掉 'DeviceToken' ...]
```

---

### 20. `fastapi_app/services/backup/schedule_service.py` 第 183 行 — Service 层直接 commit

**修改前**：
```python
await db.commit()
```

**修改后**：
```python
await db.flush()  # 刷新到数据库但不提交，由调用方控制事务
```

---

## P2 — 上线后尽快修复（中危汇总）

| # | 文件 | 行号 | 修改摘要 |
|---|------|------|----------|
| 21 | `backup/restore.py` | 326 | 查询进度时校验 task_id 与当前用户关联 |
| 22 | `backup/dump.py` | 241 | SQL 拼接改用参数化查询 `text("... :db")` |
| 23 | `purchase_plan_staging.py` | 115 | 校验失败时 `continue` 而非用 `date.today()` |
| 24 | `backup/incremental.py` | 229 | 先内存中加密再写入，避免明文残留 |
| 25 | `bom_service.py` | 78 | 用 `inspect(product).unloaded` 检查关系是否已加载 |
| 26 | `order_batch_service.py` | 384 | `sync_same_batch` 分支对同步订单也加 `with_for_update()` |
| 27 | `stock_inventory_service.py` | 313 | `int(qty_str)` 包裹 try/except ValueError |
| 28 | `circuit_breaker.py` | 61 | HALF_OPEN 状态用信号量限制并发测试 |
| 29 | `exception_handler.py` | 18 | 从 `INFRA_EXCEPTIONS` 移除 `ValueError` |
| 30 | `main.py` | 413 | 生产环境 `host="127.0.0.1"`，由 Nginx 反代 |
| 31 | `audit_middleware.py` | 129 | 配置可信代理列表，只信任最后一跳 IP |
| 32 | `redis_client.py` | 41 | 用 `quote_plus` 编码 Redis 密码 |
| 33 | `schemas/backup.py` | 379 | `encryption_mode` 改用 `Literal['off','password','key','env']` |
| 34 | `customer_access_log.py` | 89 | `commit()` 改为 `flush()` |
| 35 | `product_routes.py` | 46 | `sort_by/sort_order` 改用 `Literal` 校验 |
| 36 | `schemas.py`(purchase_center) | 34 | `dict`/`list[dict]` 改用具体 Pydantic 模型 |
| 37 | `useMaterialCalculator.ts` | - | composable 内添加 `onUnmounted` 自动清理 `calcTimer` |
| 38 | `router.py` | 293 | `pattern_maker_router` 前缀改为 `/pattern-maker` |
| 39 | `actions.py` | 130 | 异常捕获添加 `redis.exceptions.RedisError` |
| 40 | `config.py` | 111 | 生产环境强制校验 `ALLOWED_HOSTS` 不含 `*` |

---

## P3 — 后续迭代优化（低危汇总）

| # | 文件 | 行号 | 修改摘要 |
|---|------|------|----------|
| 41 | `backup/export.py` | 633 | 删除死代码 `datetime.now().strftime(...)` |
| 42 | `backup/records.py` | 162 | `r['created_at']` 改为 `r.get('created_at')` |
| 43 | `print_routes.py` | 67 | 异常捕获添加 `SQLAlchemyError` |
| 44 | `validation.py` | 758 | `total_records=0` 时返回 `0.0` 而非 `100.0` |
| 45 | `product_routes.py` | 145 | `Query('', min_length=1)` 改为 `Query(..., min_length=1)` |
| 46 | `export.py` | 489 | `rename` 前检查目标存在，或用 `shutil.move` |
| 47 | `backup/restore.py` | 84 | `get_event_loop()` 改为 `get_running_loop()` |
| 48 | `purchase_plan_queries.py` | 120 | `.limit(500)` 改为可配置参数 |
| 49 | `json_backup.py` | 309 | `datetime.now()` 改为 `datetime.now(timezone.utc)` |
| 50 | `customer_sampling/upload.py` | 126 | 用 SQLAlchemy 事件系统替代 `db.info` 修改 |
| 51 | `stock_inventory_service.py` | 582 | 删除死代码 `int(row.remaining_cus)` |
| 52 | `backup_progress.py` | 249 | `datetime.now()` 改为 `datetime.now(timezone.utc)` |
| 53 | `logger.py` | 99 | `setup_logging()` 改为显式调用 |
| 54 | `logger.py` | 66 | `datetime.now()` 改为 `datetime.now(timezone.utc)` |
| 55 | `database.py` | 84 | `_init_async_engine()` 改为延迟初始化 |
| 56 | `audit_middleware.py` | 152 | 保留时区信息，不去除 `tzinfo` |
| 57 | `useBomQuickCopy.ts` | 96 | `setTimeout` 保存变量，`onUnmounted` 清理 |
| 58 | `useToast.ts` | 186 | `innerHTML` 改用 DOM API 创建元素 |
| 59 | `MobileLayout.vue` | 60 | `innerHTML` 改用 `v-html` + sanitize |
| 60 | `performanceAudit.ts` | 37 | `try/finally` 确保恢复 `getComputedStyle` |
| 61 | `ShipmentRecordsTab.vue` | 74 | 添加运行时校验替代 `as unknown as` |
| 62 | `UserCreateForm.vue` | 68 | 添加密码复杂度校验（大小写+数字+特殊字符） |
| 63 | `customer_access_log.py` | 99 | `datetime.now()` 改为 `datetime.now(timezone.utc)` |

---

## 实施顺序建议

```
第一阶段（上线前阻断）：P0 全部 4 项 → 预计 2-4 小时
第二阶段（上线前高优）：P1 第 5-20 项 → 预计 6-8 小时
第三阶段（上线后快修）：P2 第 21-40 项 → 预计 8-10 小时
第四阶段（迭代优化）  ：P3 第 41-63 项 → 预计 4-6 小时
```

## 验证清单

每个修复完成后，执行以下验证：

```bash
# 1. 后端单元测试
cd D:\erp_system && python -m pytest fastapi_app/tests/ -v

# 2. 前端单元测试
cd D:\erp_system\frontend-vite && npm run test

# 3. 安全扫描
bandit -r fastapi_app/ -c bandit.yaml
pip-audit --requirement requirements.txt

# 4. 类型检查
mypy fastapi_app/ --config-file mypy.ini
cd frontend-vite && npx tsc --noEmit

# 5. 代码规范
ruff check fastapi_app/ --config ruff.toml
```