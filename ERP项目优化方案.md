# 滨发协同系统（ERP）优化实施方案

**方案版本**: v1.0  
**制定日期**: 2026-04-20  
**数据源**: final_report_v6.md (v6.0) + trae.md v3.0 终极整合版（972行）  
**原则**: 分阶段实施，每阶段可独立验证，保持业务连续性

---

## 目录

1. [问题总览与优先级排序](#1-问题总览与优先级排序)
2. [P0 核心优化（必须立即执行）](#2-p0-核心优化必须立即执行)
3. [P1 重要优化（P0完成后执行）](#3-p1-重要优化p0完成后执行)
4. [P2 次要优化（P1完成后执行）](#4-p2-次要优化p1完成后执行)
5. [实施时间表与依赖关系](#5-实施时间表与依赖关系)
6. [验证标准与回滚方案](#6-验证标准与回滚方案)

---

## 1. 问题总览与优先级排序

### 1.1 问题清单汇总

| 编号 | 优先级 | 问题 | 影响 | 方案 |
|------|--------|------|------|------|
| #1 | P0 | 27+29 个数据库模型文件完全重复 | 维护成本翻倍，数据不一致 | Phase 1 统一模型 |
| #2 | P0 | 同步Session在异步上下文中危险使用 | 连接泄漏，生产崩溃风险 | Phase 1 替换驱动+修复 |
| #3 | P0 | 连接池膨胀（30连接） | 资源浪费，可能耗尽MySQL连接 | Phase 1 精简连接池 |
| #4 | P0 | MySQL 8.0 已达 EOL | 不再接收安全补丁 | Phase 4 升级8.4 LTS |
| #5 | P1 | Flask主进程管理FastAPI子进程 | 架构反模式，级联阻塞 | Phase 3 统一为Uvicorn |
| #6 | P1 | 权限检查无缓存 | 高频场景性能差 | Phase 1 增加Redis缓存 |
| #7 | P1 | api-client.js已开发但未使用 | 377行代码浪费，各页面重复封装 | Phase 5 启用统一API客户端 |
| #8 | P1 | WebSocket客户端不共享 | 仅1个页面可使用实时通知 | Phase 5 提取共享模块 |
| #9 | P1 | 无CI/CD流水线 | 质量无自动化保障 | Phase 5 建立GitHub Actions |
| #10 | P1 | 无.dockerignore | 镜像包含无关文件 | Phase 4 新增 |
| #11 | P1 | Redis生产配置未生效 | 生产配置未挂载 | Phase 4 挂载配置 |
| #12 | P2 | escape_like() 4处重复定义 | 工具函数未统一 | Phase 1 提取公共模块 |
| #13 | P2 | Redis密码硬编码在配置文件 | 安全隐患 | Phase 4 迁移到Docker Secrets |
| #14 | P2 | Tab系统未统一使用 | 组件重复实现 | Phase 5 统一替换 |
| #15 | P2 | enhanced_ui.js未加载 | 415行代码浪费 | Phase 5 启用 |
| #16 | P2 | style.css达2020行 | 全模块混合，难维护 | Phase 5 拆分模块化 |
| #17 | P2 | Alertmanager接收方为空 | 告警不发送 | Phase 4 配置接收方 |
| #18 | P2 | 前端无构建工具 | 无压缩优化 | Phase 5 引入Vite |
| #19 | P2 | Flask代理转发SSRF防护不完整 | 路径遍历风险 | Phase 3 移除代理转发 |
| #20 | P2 | nav上下文处理器过于庞大 | 80+行业务逻辑嵌入模板 | Phase 2 重构为服务层 |

### 1.2 实施分组

| 组别 | 包含问题 | 实施阶段 |
|------|---------|---------|
| **核心组** | #1, #2, #3, #12 | Phase 1 — 统一数据模型层 |
| **迁移组** | #6, #20, #19 | Phase 2 — Flask路由迁移至FastAPI |
| **清理组** | #5, #10 | Phase 3 — 移除Flask依赖 |
| **基础设施组** | #4, #11, #13, #17 | Phase 4 — 基础设施升级 |
| **前端优化组** | #7, #8, #14, #15, #16, #18, #9 | Phase 5 — CI/CD + 前端优化 |

---

## 2. P0 核心优化（必须立即执行）

### 2.1 #1 统一数据模型层（27+29文件重复）

**问题描述**：`app/models/`（27个Flask-SQLAlchemy模型）和 `fastapi_app/shared_models/`（29个纯SQLAlchemy模型）映射到同一组数据库表，完全重复。

**具体步骤**：

**步骤 1：创建统一模型目录结构**

```
fastapi_app/shared_models/          ← 保留为唯一模型源
  ├── __init__.py
  ├── base.py                        ← SQLAlchemy 2.0 Base
  ├── user.py
  ├── order.py
  ├── ... (29个模型文件)
app/models/                          ← 全部删除（27个文件）
```

**步骤 2：修复依赖引用**

查找所有引用 `app.models` 的地方：

```bash
# 在项目根目录执行
grep -r "from app.models" --include="*.py"
grep -r "import app.models" --include="*.py"
```

将引用改为：

```python
# 旧引用
from app.models import User, Order

# 新引用
from fastapi_app.shared_models import User, Order
```

**步骤 3：统一导入**

修改 `fastapi_app/shared_models/__init__.py`：

```python
from .base import Base, get_sync_session, get_async_session
from .user import User
from .order import Order
# ... 导出所有模型

__all__ = [
    "Base",
    "get_sync_session", 
    "get_async_session",
    "User", "Order",  # 所有模型
]
```

**步骤 4：删除 Flask 模型目录**

```bash
rm -rf app/models/
```

**步骤 5：删除 to_dict() 重复**

在每个模型中，将 `to_dict()` 方法标记为废弃：

```python
# 在模型类中添加
import warnings

def to_dict(self):
    warnings.warn(
        "to_dict() is deprecated. Use Pydantic Schema for serialization.",
        DeprecationWarning,
        stacklevel=2
    )
    return {
        column.name: getattr(self, column.name)
        for column in self.__table__.columns
    }
```

新建 Pydantic Schema 替代：

```python
# fastapi_app/schemas/user.py
from pydantic import BaseModel
from typing import Optional

class UserSchema(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    
    class Config:
        from_attributes = True  # 支持 from sqlalchemy_orm 对象转换
```

**验证标准**：
- [ ] `app/models/` 目录已删除
- [ ] 所有 `from app.models` 引用已替换
- [ ] `pytest tests/` 全部通过
- [ ] `grep -r "from app.models"` 无结果

---

### 2.2 #2 修复同步Session在异步上下文中的危险使用

**问题描述**：`fastapi_app/core/deps.py:148` 中 `get_current_user()` 在异步处理器中创建 `SyncSessionLocal()`，异常路径会导致连接泄漏。`stock_service.py` 中9处同样问题。

**具体步骤**：

**步骤 1：修改 deps.py 中的 get_current_user()**

```python
# 修改前（危险）
from fastapi_app.core.database import SyncSessionLocal

async def get_current_user(token: str = Depends(oauth2_scheme)):
    db = SyncSessionLocal()  # ❌ 同步Session在异步上下文中
    try:
        user = db.query(User).filter(User.token == token).first()
        return user
    finally:
        db.close()  # 异常时可能未执行

# 修改后（安全）
from fastapi_app.core.database import get_async_session

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_async_session)
):
    result = await session.execute(
        select(User).where(User.token == token)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user
```

**步骤 2：修复 stock_service.py 中9处同步Session使用**

```python
# 将所有方法改为 async
class StockService:
    async def get_stock(self, product_id: int, session: AsyncSession):
        result = await session.execute(
            select(Stock).where(Stock.product_id == product_id)
        )
        return result.scalar_one_or_none()
    
    async def update_stock(self, product_id: int, quantity: int, session: AsyncSession):
        # ... 使用 session.execute()
        await session.commit()
```

**步骤 3：修改数据库配置，替换 aiomysql 为 asyncmy**

修改 `fastapi_app/core/database.py`：

```python
# 修改前
DATABASE_URL = f"mysql+aiomysql://{user}:{password}@{host}:{port}/{db}"

# 修改后
DATABASE_URL = f"mysql+asyncmy://{user}:{password}@{host}:{port}/{db}"
```

修改 `requirements/base.txt`：

```diff
-aiomysql>=0.2.0
+asyncmy==0.2.9
```

**验证标准**：
- [ ] `grep -r "SyncSessionLocal" --include="*.py"` 仅在 database.py 定义处出现
- [ ] 所有 service 层方法改为 async
- [ ] `pytest fastapi_app/tests/` 异步测试全部通过
- [ ] 无 `DeprecationWarning: Using synchronous Session in async context`

---

### 2.3 #3 精简连接池（30连接 → 15连接）

**问题描述**：同一进程内3个独立连接池指向同一MySQL实例，最大并发30连接。

**具体步骤**：

**步骤 1：修改 database.py 连接池配置**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import create_engine, sessionmaker

# 同步池：从 10+5 缩减到 5+2
sync_engine = create_engine(
    DATABASE_URL_SYNC,
    pool_size=5,           # 原 10
    max_overflow=2,        # 原 5
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True
)

# 异步池：从 10+5 缩减到 10+5（保持不变，因为异步处理高并发）
async_engine = create_async_engine(
    DATABASE_URL_ASYNC,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True
)
```

**步骤 2：验证连接数**

```sql
-- MySQL 中执行，确认连接数
SHOW STATUS LIKE 'Threads_connected';
SELECT COUNT(*) FROM information_schema.processlist WHERE db = 'erp_system';
```

**验证标准**：
- [ ] 同步池配置 pool_size=5, max_overflow=2
- [ ] 异步池配置 pool_size=10, max_overflow=5
- [ ] 总最大连接数 = 5+2+10+5 = 22（原30）
- [ ] MySQL `Threads_connected` 稳定在 < 15

---

### 2.4 #12 提取 escape_like() 公共工具函数

**问题描述**：`escape_like()` 在 4 个文件中重复定义。

**具体步骤**：

**步骤 1：创建统一工具模块**

```python
# fastapi_app/utils/string_utils.py
def escape_like(value: str) -> str:
    """转义 SQL LIKE 查询中的特殊字符"""
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
```

**步骤 2：删除 4 个文件中的重复定义，替换为统一引用**

```python
# 修改前（在每个文件中删除）
def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

# 修改后
from fastapi_app.utils.string_utils import escape_like
```

**验证标准**：
- [ ] `grep -r "def escape_like" --include="*.py"` 仅在 `string_utils.py` 出现1次
- [ ] 所有使用处已改为 import 引用

---

## 3. P1 重要优化（P0完成后执行）

### 3.1 #6 权限检查增加Redis缓存

**问题描述**：`app/utils/permission_decorators.py:38` 每次请求查询数据库获取用户权限。

**具体步骤**：

**步骤 1：创建权限缓存中间件**

```python
# fastapi_app/middleware/permission_cache.py
import json
from fastapi import Request, HTTPException
from fastapi_app.core.redis_client import redis_client

PERMISSION_CACHE_TTL = 300  # 5分钟

async def get_user_permissions(user_id: int) -> dict:
    """从缓存获取用户权限"""
    cache_key = f"user_perms:{user_id}"
    
    # 尝试从 Redis 获取
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # 缓存未命中，从数据库查询
    from fastapi_app.shared_models import User
    from fastapi_app.core.database import get_async_session
    
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        permissions = user.get_permissions()  # 获取权限列表
        await redis_client.setex(
            cache_key, 
            PERMISSION_CACHE_TTL, 
            json.dumps(permissions)
        )
        return permissions

async def clear_user_permission_cache(user_id: int):
    """清除用户权限缓存（角色变更时调用）"""
    cache_key = f"user_perms:{user_id}"
    await redis_client.delete(cache_key)
```

**步骤 2：在 FastAPI Depends 链中使用**

```python
# fastapi_app/api/deps.py
from fastapi_app.middleware.permission_cache import get_user_permissions

async def require_permission(permission: str):
    async def check_permission(
        current_user = Depends(get_current_user)
    ):
        perms = await get_user_permissions(current_user.id)
        if permission not in perms:
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user
    return check_permission
```

**步骤 3：角色变更时清除缓存**

```python
# 在角色更新API中
async def update_user_role(user_id: int, new_role: str):
    # ... 更新角色
    await clear_user_permission_cache(user_id)
```

**验证标准**：
- [ ] 首次请求权限查询数据库
- [ ] 后续请求从 Redis 缓存获取（TTL 300s）
- [ ] 角色变更后缓存立即失效
- [ ] Prometheus 指标显示 `permission_cache_hit_rate` > 90%

---

### 3.2 #20 重构 nav 上下文处理器

**问题描述**：`app/__init__.py:230-312` 80+ 行业务逻辑嵌入 context_processor。

**具体步骤**：

**步骤 1：提取为服务层**

```python
# fastapi_app/services/nav_service.py
from typing import Dict, Any, List
from fastapi_app.shared_models import User
from fastapi_app.middleware.permission_cache import get_user_permissions

class NavService:
    """导航菜单服务"""
    
    @staticmethod
    async def get_nav_data(user_id: int) -> Dict[str, Any]:
        """获取导航菜单数据"""
        permissions = await get_user_permissions(user_id)
        
        return {
            "nav_items": NavService._build_nav_items(permissions),
            "unread_count": await NavService._get_unread_count(user_id),
            "pending_approvals": await NavService._get_pending_approvals(user_id),
        }
    
    @staticmethod
    def _build_nav_items(permissions: List[str]) -> List[Dict]:
        """根据权限构建导航项"""
        all_items = [
            {"name": "产品管理", "url": "/products", "perm": "product:view"},
            {"name": "订单管理", "url": "/orders", "perm": "order:view"},
            {"name": "库存管理", "url": "/stock", "perm": "stock:view"},
            # ...
        ]
        return [item for item in all_items if item["perm"] in permissions]
    
    @staticmethod
    async def _get_unread_count(user_id: int) -> int:
        """获取未读通知数"""
        # 从数据库或Redis获取
        pass
    
    @staticmethod
    async def _get_pending_approvals(user_id: int) -> int:
        """获取待审批数"""
        # 从数据库获取
        pass
```

**步骤 2：在 FastAPI 中替换 context_processor**

```python
# 旧代码（app/__init__.py 中的80+行context_processor）
# @app.context_processor
# def nav():
#     ... 80行代码 ...

# 新代码（FastAPI Jinja2Templates）
@app.get("/{path:path}")
async def render_page(
    request: Request,
    path: str,
    current_user = Depends(get_current_user)
):
    nav_data = await NavService.get_nav_data(current_user.id)
    return templates.TemplateResponse(
        f"{path}.html",
        {"request": request, **nav_data}
    )
```

**验证标准**：
- [ ] `app/__init__.py` 中的 context_processor 已移除
- [ ] NavService 单元测试覆盖
- [ ] 页面导航数据正确显示

---

### 3.3 #9 建立 CI/CD 流水线

**具体步骤**：

**步骤 1：创建 GitHub Actions 工作流**

```yaml
# .github/workflows/ci-cd.yml
name: ERP CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  PYTHON_VERSION: '3.13'
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: pip
    
    - name: Install lint tools
      run: pip install ruff mypy
    
    - name: Run ruff
      run: ruff check .
    
    - name: Run mypy
      run: mypy fastapi_app/

  test:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.4
        env:
          MYSQL_ROOT_PASSWORD: test
          MYSQL_DATABASE: erp_test
        ports:
          - 3306:3306
        options: >-
          --health-cmd="mysqladmin ping"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=3
      
      redis:
        image: redis:8.4-alpine
        ports:
          - 6379:6379

    steps:
    - uses: actions/checkout@v4
    
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: pip
    
    - name: Install dependencies
      run: |
        pip install -r requirements/base.txt
        pip install -r requirements/dev.txt
    
    - name: Run tests
      run: |
        pytest tests/ fastapi_app/tests/ -v \
          --cov=app \
          --cov=fastapi_app \
          --cov-report=xml \
          --cov-report=html
    
    - name: Upload coverage
      uses: codecov/codecov-action@v4
      with:
        file: coverage.xml

  security-scan:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
    
    - name: Install bandit
      run: pip install bandit
    
    - name: Run security scan
      run: bandit -r . -f json -o bandit-results.json || true
    
    - name: Upload results
      uses: actions/upload-artifact@v4
      with:
        name: security-results
        path: bandit-results.json

  build:
    needs: [lint, test, security-scan]
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Build Docker image
      run: docker build -t ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }} .
    
    - name: Login to registry
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
    
    - name: Push Docker image
      run: docker push ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}

  deploy-staging:
    needs: build
    if: github.ref == 'refs/heads/develop'
    runs-on: ubuntu-latest
    environment: staging
    
    steps:
    - name: Deploy to staging
      run: |
        # SSH to staging server and deploy
        echo "Deploying to staging..."

  deploy-production:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production
    
    steps:
    - name: Deploy to production
      run: |
        # SSH to production server and deploy
        echo "Deploying to production..."
```

**步骤 2：创建 .dockerignore**

```
# .dockerignore
.git
.gitignore
__pycache__
*.pyc
*.pyo
.pytest_cache
.mypy_cache
.ruff_cache
backups/
.env
.env.*
*.md
!requirements*.txt
docs/
tests/
*.test.*
.dockerignore
Dockerfile
docker-compose*.yml
.github/
.vscode/
.trae/
desktop/
*.log
```

**验证标准**：
- [ ] push 到 develop 分支自动触发 lint + test + build
- [ ] 测试覆盖率 > 70%
- [ ] bandit 安全扫描无 P0 发现
- [ ] Docker 镜像体积 < 500MB（使用 .dockerignore）

---

## 4. P2 次要优化（P1完成后执行）

### 4.1 #13 Redis密码迁移到Docker Secrets

**步骤 1：创建 Docker Secret**

```bash
# 在 Docker Swarm 或使用 docker secret
echo "your_redis_password" | docker secret create redis_password -
```

**步骤 2：修改 docker-compose.yml**

```yaml
# 修改前
redis:
  command: redis-server --requirepass hardcoded_password

# 修改后
redis:
  secrets:
    - redis_password
  command: >
    redis-server
    --requirepass "$$(cat /run/secrets/redis_password)"
    --maxmemory 256mb
    --maxmemory-policy allkeys-lru
    --appendonly yes

secrets:
  redis_password:
    file: ./secrets/redis_password.txt
```

**步骤 3：确保密码文件不被提交到Git**

```
# .gitignore
secrets/
*.secret
*.secret.*
```

---

### 4.2 #17 配置 Alertmanager 接收方

**步骤 1：修改 config/alert_rules.yml**

```yaml
# 修改前
alerting:
  alertmanagers:
  - static_configs:
    - targets: []

# 修改后
alerting:
  alertmanagers:
  - static_configs:
    - targets:
      - alertmanager:9093
```

**步骤 2：添加 alertmanager 配置**

```yaml
# config/alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'web.hook'

receivers:
- name: 'web.hook'
  webhook_configs:
  - url: 'http://your-webhook-url/alerts'
  
  # 或配置邮件
- name: 'email'
  email_configs:
  - to: 'admin@yourcompany.com'
    from: 'alertmanager@yourcompany.com'
    smarthost: 'smtp.yourcompany.com:587'
    auth_username: 'alertmanager@yourcompany.com'
    auth_password: 'email_password'
```

---

### 4.3 #4 MySQL 8.0 → 8.4 LTS 升级

**步骤 1：数据备份**

```bash
# 完整备份
docker exec erp-db mysqldump -u root -p --all-databases \
  --single-transaction \
  --routines \
  --triggers \
  > backups/erp-full-backup-$(date +%Y%m%d).sql

# 验证备份
mysql < backups/erp-full-backup-*.sql --dry-run
```

**步骤 2：修改 docker-compose.yml**

```yaml
# 修改前
db:
  image: mysql:8.0

# 修改后
db:
  image: mysql:8.4.8
  command: >
    --default-authentication-plugin=caching_sha2_password
    --character-set-server=utf8mb4
    --collation-server=utf8mb4_unicode_ci
    --max-connections=100
    --innodb-buffer-pool-size=512M
```

**步骤 3：执行升级**

```bash
# 停止服务
docker-compose down

# 启动新版本（数据持久化在volume中）
docker-compose up -d db

# 执行升级脚本（8.0 → 8.4 兼容模式）
docker exec erp-db mysql_upgrade -u root -p

# 验证
docker exec erp-db mysql -u root -p -e "SELECT VERSION();"
# 应输出 8.4.8
```

**验证标准**：
- [ ] 备份文件已生成并可恢复
- [ ] `SELECT VERSION()` 返回 8.4.8
- [ ] 所有表和数据正常
- [ ] 应用连接正常

---

## 5. 实施时间表与依赖关系

### 5.1 Phase 依赖图

```
Phase 1 (核心) ← 必须最先完成
  ├── #1 统一模型层
  ├── #2 修复异步Session
  ├── #3 精简连接池
  └── #12 提取escape_like
        ↓
Phase 2 (迁移) ← 依赖 Phase 1
  ├── #6 权限缓存
  └── #20 重构nav处理器
        ↓
Phase 3 (清理) ← 依赖 Phase 2
  ├── #5 移除Flask进程管理
  └── #19 消除SSRF风险
        ↓
Phase 4 (基础设施) ← 可与Phase 2/3并行，但#4需在Phase 3后
  ├── #4 MySQL升级
  ├── #10 .dockerignore
  ├── #11 Redis配置挂载
  ├── #13 Docker Secrets
  └── #17 Alertmanager配置
        ↓
Phase 5 (前端+CI/CD) ← 可与Phase 4并行
  ├── #7 启用api-client.js
  ├── #8 提取ws-client.js
  ├── #9 CI/CD流水线
  ├── #14 统一Tab系统
  ├── #15 加载enhanced_ui.js
  ├── #16 拆分style.css
  └── #18 引入Vite
```

### 5.2 核心路径

```
Phase 1 → Phase 2 → Phase 3 → Phase 4
                              ↘ Phase 5 (可与Phase 4并行)
```

**最短路径**：Phase 1 + Phase 2 + Phase 3（解决P0+核心P1）  
**完整路径**：Phase 1-5 全部完成

---

## 6. 验证标准与回滚方案

### 6.1 每阶段验证清单

**Phase 1 验证**：
- [ ] `app/models/` 已删除
- [ ] 所有引用已替换为 `fastapi_app.shared_models`
- [ ] 同步Session在异步上下文中已修复（grep无结果）
- [ ] 连接池配置 pool_size=5+2 (sync) + 10+5 (async)
- [ ] `escape_like` 仅1处定义
- [ ] 全部测试通过

**Phase 2 验证**：
- [ ] 权限查询命中 Redis 缓存
- [ ] nav 数据正确显示
- [ ] context_processor 已移除

**Phase 3 验证**：
- [ ] 单一 Uvicorn 进程启动正常
- [ ] Flask 代理转发已移除
- [ ] 单端口 5002 正常工作

**Phase 4 验证**：
- [ ] MySQL `SELECT VERSION()` = 8.4.8
- [ ] Redis 生产配置生效
- [ ] Alertmanager 告警正常发送
- [ ] Docker 镜像无无关文件（< 500MB）

**Phase 5 验证**：
- [ ] api-client.js 正常加载
- [ ] ws-client.js 多页面共享
- [ ] CI 绿灯
- [ ] Vite 构建成功

### 6.2 回滚方案

**触发条件**：
- 错误率 > 1%
- 响应时间 P99 > 1000ms
- 关键业务功能不可用
- 数据一致性问题

**回滚步骤**：
```
1. 停止新版服务（30s）
2. 恢复旧版 Docker 镜像 / 代码
3. 恢复 MySQL 8.0（如有备份）
4. 验证核心功能（5min）
5. 通知相关方
```

**回滚时间目标**: < 10 分钟

### 6.3 数据安全

| 措施 | 频率 | 保留 |
|------|------|------|
| 全量备份 | 迁移前 1 次 | 永久 |
| 每日备份 | 每天 02:00 | 30 天 |
| 异地备份 | 每日同步 | 90 天 |
| 恢复演练 | 迁移前 1 次 | 记录结果 |

---

**声明**: 本方案基于 final_report_v6.md (v6.0) 和 trae.md v3.0 的分析结果制定。所有优化措施均可独立验证，支持分阶段回滚。
