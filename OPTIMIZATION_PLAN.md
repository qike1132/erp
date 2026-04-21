# 滨发协同系统（ERP）— 可执行优化方案

**版本**: v1.0  
**日期**: 2026-04-20  
**依据**: final_report_v6.md 分析结论 + 代码库实际验证  
**项目路径**: d:\erp_system

---

## 目录

1. [问题总览与优先级](#1-问题总览与优先级)
2. [P0 核心优化（灾难级）](#2-p0-核心优化灾难级)
3. [P1 重要优化（严重）](#3-p1-重要优化严重)
4. [P2 次要优化（中等）](#4-p2-次要优化中等)
5. [基础设施升级方案](#5-基础设施升级方案)
6. [实施路线图](#6-实施路线图)

---

## 1. 问题总览与优先级

基于 final_report_v6.md 识别的 20 个问题，按影响程度和修复紧迫性重新排序为可执行方案：

| 优先级 | 问题 | 影响 | 修复难度 | 建议阶段 |
|--------|------|------|---------|---------|
| **P0-1** | 27+29 模型文件重复 | 维护成本翻倍，数据不一致风险 | 中 | Phase 1 |
| **P0-2** | SyncSession 阻塞异步事件循环 | 连接泄漏，性能瓶颈 | 低 | Phase 1 |
| **P0-3** | 连接池膨胀（3池=最多45连接） | 资源浪费，可能耗尽MySQL连接 | 低 | Phase 1 |
| **P0-4** | MySQL 8.0 EOL | 安全风险 | 中 | Phase 4 |
| **P1-5** | Flask subprocess 管理 Uvicorn | 进程架构反模式 | 高 | Phase 3 |
| **P1-6** | 权限检查无缓存 | 每次请求查库，O(N*M)遍历 | 低 | Phase 1 |
| **P1-7** | api-client.js 未在 base.html 加载 | 各页面裸 fetch()，重复代码 | 低 | Phase 5 |
| **P1-8** | WebSocket 客户端不共享 | 仅1页面使用实时通知 | 低 | Phase 5 |
| **P1-9** | 无 CI/CD 流水线 | 部署依赖手动 | 中 | Phase 5 |
| **P1-10** | 无 .dockerignore | 构建臃肿，可能泄露密钥 | 极低 | Phase 4 |
| **P1-11** | Redis 生产配置未挂载 | AOF/maxmemory 未生效 | 极低 | Phase 4 |
| **P2-12** | escape_like() 4处重复 | 工具函数未统一 | 极低 | Phase 1 |
| **P2-13** | Redis 密码硬编码 | 安全隐患 | 低 | Phase 4 |
| **P2-14** | Tab 系统未统一 | 组件化程度低 | 低 | Phase 5 |
| **P2-15** | enhanced_ui.js 未加载 | 415行UI工具闲置 | 极低 | Phase 5 |
| **P2-16** | style.css 2020行 | 全模块混合难维护 | 中 | Phase 5 |
| **P2-17** | Alertmanager 接收方为空 | 告警不会发送 | 极低 | Phase 4 |
| **P2-18** | 前端无构建工具 | 无压缩/Tree-shaking | 中 | Phase 5 |
| **P2-19** | Flask 代理 SSRF 防护不完整 | 路径遍历风险 | 低 | Phase 2 |
| **P2-20** | nav 上下文处理器过于庞大 | 80+行业务逻辑混入 context_processor | 中 | Phase 2 |

---

## 2. P0 核心优化（灾难级）

### 2.1 P0-1：消除模型重复（27+29 → 29）

**现状**：`app/models/` 27个Flask-SQLAlchemy模型 与 `fastapi_app/shared_models/` 29个纯SQLAlchemy 2.0模型映射同一组表。`has_permission()` 方法逐字复制。

**具体执行步骤**：

#### Step 1：以 `fastapi_app/shared_models/` 为唯一模型源

```bash
# 不直接删除 app/models/，先让 Flask 路由引用 shared_models
# 目标结构：
# fastapi_app/shared_models/  ← 唯一模型源（29个文件）
# app/models/                 ← 删除（27个文件）
```

#### Step 2：修改 Flask 路由的模型导入

**文件**: `app/routes/*.py`（23个路由文件）

```python
# 修改前（每个路由文件的头部）:
from app.models.user import User
from app.models.order import Order
from app.models.product import Product

# 修改后:
from fastapi_app.shared_models.user import User
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.product import Product
```

#### Step 3：补齐 shared_models 缺失的方法

当前 `fastapi_app/shared_models/user.py` 缺少 `get_all_permissions`、`masked_phone`、`to_dict`。需从 Flask 模型迁移：

```python
# 添加到 fastapi_app/shared_models/user.py

def get_all_permissions(self) -> list:
    """获取用户所有权限名称（含子权限）"""
    permissions = []
    for p in self.permissions:
        permissions.append(p.name)
        for child in p.children:
            permissions.append(child.name)
    return permissions

@property
def masked_phone(self) -> str:
    """手机号脱敏"""
    if self.phone and len(self.phone) == 11:
        return self.phone[:3] + '****' + self.phone[7:]
    return self.phone or ''
```

#### Step 4：用 Pydantic Schema 替代 to_dict()

```python
# 不再在每个模型中定义 to_dict()，使用 Pydantic Schema 序列化
# 在 fastapi_app/schemas/ 中已有 16 个 schema 文件
# 逐步将各模型的 to_dict() 迁移到对应的 Pydantic Schema

# 示例：fastapi_app/schemas/user.py
class UserResponse(BaseModel):
    id: int
    username: str
    phone: str | None
    status: int
    
    model_config = ConfigDict(from_attributes=True)
```

#### Step 5：删除 `app/models/` 全部文件

```bash
# 确认所有导入已切换后
rm -rf app/models/
# 或保留 __init__.py 做重导出过渡期
```

**验证标准**：`pytest tests/ fastapi_app/tests/ -v` 全部通过

---

### 2.2 P0-2：修复 SyncSession 阻塞异步事件循环

**现状**：`fastapi_app/core/deps.py:145-161` 在 async 函数中直接创建 SyncSession 阻塞事件循环；`stock_service.py` 中 session.commit()/rollback() 仍在事件循环中同步调用。

**具体执行步骤**：

#### Step 1：修复 `get_current_user` 的 Session 使用

**文件**: `fastapi_app/core/deps.py`

```python
# 修改前（当前代码，约 line 145-161）:
db = SyncSessionLocal()
try:
    user = db.execute(sa_select(User.id, User.status).where(User.id == user_id)).first()
    if not user or not user.status:
        raise HTTPException(...)
finally:
    db.close()

# 修改后 — 使用 AsyncSession:
async def get_current_user(token: str = Depends(oauth2_scheme), 
                           db: AsyncSession = Depends(get_async_db)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    user_id = payload.get("sub")
    result = await db.execute(sa_select(User.id, User.status).where(User.id == user_id))
    user = result.first()
    if not user or not user.status:
        raise HTTPException(status_code=401, detail="用户无效或已禁用")
    return user_id
```

#### Step 2：修复 stock_service 的 commit/rollback 阻塞

**文件**: `fastapi_app/services/stock_service.py`

```python
# 修改前（当前模式，9处重复）:
loop = asyncio.get_running_loop()
session = SyncSessionLocal()
try:
    stockin = await loop.run_in_executor(None, _sync_create_stockin, session, ...)
    session.commit()  # ← 阻塞事件循环
except Exception:
    session.rollback()  # ← 阻塞事件循环
finally:
    session.close()

# 修改后 — 全部使用 AsyncSession:
async def create_stockin(db: AsyncSession, product_id: int, quantity: int, ...):
    stockin = StockIn(product_id=product_id, quantity=quantity, ...)
    db.add(stockin)
    await db.commit()
    await db.refresh(stockin)
    return stockin
```

**验证标准**：代码中不再有 `SyncSessionLocal()` 在 async 函数中的直接使用

---

### 2.3 P0-3：精简连接池（3池45连接 → 2池15连接）

**现状**：3个独立连接池，每个 pool_size=10 + max_overflow=5 = 最大15连接/池，3池合计最多45连接。

**具体执行步骤**：

#### Step 1：修改 FastAPI 连接池配置

**文件**: `fastapi_app/core/database.py`

```python
# 修改前:
def _get_pool_config() -> dict:
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
        ...
    }

# 修改后 — 降低连接数：
def _get_pool_config() -> dict:
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),    # 10 → 5
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),  # 维持5
        ...
    }
```

#### Step 2：迁移完成后删除 Flask 连接池

Phase 3 移除 Flask 后，自然消除 Flask-SQLAlchemy 的连接池。

**最终状态**：2个池（同步5+异步10）= 最多15+5=20连接，远低于当前的45。

**验证标准**：MySQL `SHOW PROCESSLIST` 连接数显著下降

---

## 3. P1 重要优化（严重）

### 3.1 P1-6：权限检查增加 Redis 缓存

**现状**：`app/utils/permission_decorators.py:38` 每次请求 `db.session.get(User, ...)` + `has_permission()` 遍历权限列表，O(N*M) 复杂度。

**具体执行步骤**：

**文件**: `app/utils/permission_decorators.py`

```python
# 修改后 — 增加 Redis 缓存:
from flask import current_app
import json

def api_permission_required(permission_name):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '未登录'}), 401
        
        user_id = session['user_id']
        cache_key = f'user_perms:{user_id}'
        
        # 尝试从 Redis 获取权限缓存
        redis_client = current_app.extensions.get('redis')
        cached_perms = redis_client.get(cache_key) if redis_client else None
        
        if cached_perms:
            permissions = json.loads(cached_perms)
        else:
            user = db.session.get(User, user_id)
            if not user or not user.status:
                return jsonify({'error': '用户无效'}), 401
            permissions = user.get_all_permissions()
            # 缓存5分钟
            if redis_client:
                redis_client.setex(cache_key, 300, json.dumps(permissions))
        
        if permission_name not in permissions:
            return jsonify({'error': '权限不足'}), 403
        
        return f(*args, **kwargs)
    return decorated_function
```

**权限变更时清除缓存**：在用户权限修改的路由中添加：

```python
redis_client.delete(f'user_perms:{user_id}')
```

**验证标准**：高频接口响应时间下降，Redis 中可见 `user_perms:*` 键

---

### 3.2 P1-7：在 base.html 中加载 api-client.js

**现状**：`api-client.js`（377行）仅 `purchase_plan_new.html` 加载，`base.html` 未加载。

**具体执行步骤**：

**文件**: `templates/base.html`

```html
<!-- 在已有脚本之后添加（约 line 151-154 区域）: -->
<script src="{{ url_for('static', filename='js/api-client.js') }}?v={{ config.get('ASSET_VERSION', '1') }}"></script>
```

**同步修改**：将各页面中裸 `fetch()` 调用逐步替换为 `apiClient.get()/post()`：

```javascript
// 修改前（各页面中的模式）:
fetch('/api/v1/stock/in', { method: 'POST', body: JSON.stringify(data) })

// 修改后:
apiClient.post('/stock/in', data)
```

---

### 3.3 P1-10：创建 .dockerignore

**现状**：项目根目录无 `.dockerignore`，`COPY . .` 会复制无关文件。

**具体执行步骤**：

**新建文件**: `.dockerignore`

```
.git
.gitignore
__pycache__
*.pyc
*.pyo
.env
.env.*
logs/
backups/
*.md
tests/
prometheus-data/
grafana-data/
node_modules/
frontend/
server_manager/
config/cloudflared/
*.xlsx
*.xls
.dockerignore
docker-compose*.yml
Dockerfile
```

**验证标准**：`docker build` 构建上下文大小显著减小

---

### 3.4 P1-11：Redis 生产配置挂载到 Docker

**现状**：`config/redis.production.conf` 已有完整生产配置（maxmemory、AOF等），但 docker-compose.yml 未引用。

**具体执行步骤**：

**文件**: `docker-compose.yml` Redis 服务

```yaml
# 修改前:
command: redis-server --requirepass ${REDIS_PASSWORD} --bind 0.0.0.0 --appendonly yes

# 修改后:
command: redis-server /usr/local/etc/redis/redis.conf
volumes:
  - ./config/redis.production.conf:/usr/local/etc/redis/redis.conf
  - redis-data:/data
```

同时修改 `config/redis.production.conf`，将硬编码密码改为环境变量引用：
```
# 修改前:
requirepass ERP_Redis_2026_Secure_Password

# 修改后（Redis不支持直接读取环境变量，用启动命令覆盖）:
# 删除 requirepass 行，在 docker-compose command 中追加:
command: redis-server /usr/local/etc/redis/redis.conf --requirepass ${REDIS_PASSWORD}
```

---

## 4. P2 次要优化（中等）

### 4.1 P2-12：统一 escape_like() 工具函数

**现状**：`escape_like()` 在4个文件中重复定义。

**执行步骤**：

**新建文件**: `app/utils/db_utils.py`

```python
def escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符"""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
```

在4个重复文件中替换为：
```python
from app.utils.db_utils import escape_like
```

### 4.2 P2-17：配置 Alertmanager 接收方

**现状**：5条告警规则已定义但 Alertmanager targets 为空。

**执行步骤**：

**文件**: `config/alertmanager.yml`（需新建或修改）

```yaml
route:
  receiver: 'erp-team'
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: 'erp-team'
    # 选择以下任一方式:
    # webhook_configs:
    #   - url: 'http://erp-app:5002/api/v1/alerts'
    # email_configs:
    #   - to: 'erp-team@company.com'
    #   - from: 'alertmanager@company.com'
    #     smarthost: 'smtp.company.com:587'
```

在 `docker-compose.yml` 的 prometheus 服务中添加：
```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']
```

### 4.3 P2-20：拆分 nav 上下文处理器

**现状**：`app/__init__.py:230-312` 有80+行业务逻辑嵌入 `context_processor`。

**执行步骤**：

**新建文件**: `app/utils/nav_context.py`

```python
def build_nav_context(user_id: int) -> dict:
    """构建导航上下文数据（从 context_processor 提取）"""
    # 将 80+ 行逻辑迁移到此函数
    ...
    return nav_context
```

**文件**: `app/__init__.py`

```python
# 修改后:
from app.utils.nav_context import build_nav_context

@app.context_processor
def inject_nav():
    user_id = session.get('user_id')
    if not user_id:
        return {}
    return build_nav_context(user_id)
```

---

## 5. 基础设施升级方案

### 5.1 MySQL 8.0 → 8.4 LTS

**执行步骤**：

```yaml
# docker-compose.yml 修改:
db:
  image: mysql:8.4  # 从 mysql:8.0 升级
  command: --mysql-native-password=ON  # 兼容模式
```

**前置操作**：
1. `mysqldump -u root -p erp > backup_before_84.sql`
2. 在 staging 环境测试所有 SQL 语句兼容性
3. 检查是否有使用 MySQL 8.0 特定行为（如窗口函数、CTE等）

### 5.2 Redis 7.2 → 8.4

```yaml
redis:
  image: redis:8.4-alpine  # 从 redis:7.2-alpine 升级
```

### 5.3 aiomysql → asyncmy

```
# requirements/base.txt 修改:
# 移除:
aiomysql>=0.2.0
# 添加:
asyncmy==0.2.9
```

**文件**: `fastapi_app/core/database.py`

```python
# 修改前:
async_db_url = sync_url.replace("mysql+pymysql", "mysql+aiomysql")

# 修改后:
async_db_url = sync_url.replace("mysql+pymysql", "mysql+asyncmy")
```

### 5.4 python-jose → PyJWT

```
# requirements/base.txt 修改:
# 移除:
python-jose[cryptography]>=3.3.0
# 添加:
PyJWT==2.10.1
```

**文件**: `fastapi_app/core/deps.py`

```python
# 修改前:
from jose import jwt, JWTError

# 修改后:
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
```

---

## 6. 实施路线图

```
Phase 1 — 统一数据模型层 + 修复 P0 问题
  ├── [P0-1] 合并 shared_models → 唯一模型源，删除 app/models/
  ├── [P0-2] 修复 SyncSession 阻塞异步事件循环
  ├── [P0-3] 精简连接池配置
  ├── [P1-6] 权限检查增加 Redis 缓存
  ├── [P2-12] 统一 escape_like() 工具函数
  ├── 替换 aiomysql → asyncmy
  └── 替换 python-jose → PyJWT
  验证: pytest tests/ fastapi_app/tests/ -v 全部通过

Phase 2 — Flask 路由逐步迁移至 FastAPI
  ├── [P2-19] 修复 Flask 代理 SSRF 防护
  ├── [P2-20] 拆分 nav 上下文处理器
  ├── API 端点迁移（stock、order、product 等优先）
  ├── 认证/权限统一到 FastAPI Depends 注入
  └── 页面渲染路由 → FastAPI Jinja2Templates
  验证: 每模块迁移后端到端测试通过

Phase 3 — 移除 Flask 依赖
  ├── 删除 Flask 及全部扩展包
  ├── 清理 run.py 双进程启动逻辑
  ├── 简化 Dockerfile（单端口 5002）
  └── JWT 统一认证
  验证: 单一 Uvicorn 启动正常

Phase 4 — 基础设施升级
  ├── [P0-4] MySQL 8.0 → 8.4 LTS
  ├── Redis 7.2 → 8.4
  ├── [P1-10] 新增 .dockerignore
  ├── [P1-11] Redis 生产配置挂载
  ├── [P2-13] 密码迁移至 Docker Secrets
  ├── [P2-17] 配置 Alertmanager 接收方
  └── Prometheus/Grafana 升级
  验证: 全部服务健康检查通过

Phase 5 — CI/CD + 前端优化
  ├── [P1-9] 建立 GitHub Actions 流水线
  ├── [P1-7] base.html 加载 api-client.js
  ├── [P1-8] 提取 ws-client.js 共享模块
  ├── [P2-14] Tab 系统统一使用
  ├── [P2-15] 加载 enhanced_ui.js
  ├── [P2-16] style.css 模块拆分
  ├── [P2-18] 引入 Vite 构建工具
  └── 测试验证
  验证: CI 绿灯，前端功能回归通过
```

### 关键依赖关系

```
Phase 1 (模型+P0修复) ← 必须最先，后续所有迁移依赖统一模型
    ↓
Phase 2 (路由迁移) ← 依赖 Phase 1 统一模型层
    ↓
Phase 3 (移除Flask) ← 依赖 Phase 2 全部路由迁移完成
    ↓
Phase 4 (基础设施) ← MySQL 升级需在 Phase 3 后；其他可与 Phase 2/3 并行
    ↓
Phase 5 (CI/CD+前端) ← 可与 Phase 4 并行
```

### 可立即执行的快捷修复（无需等待 Phase 排序）

以下优化可立即执行，无依赖关系：

| 编号 | 修复项 | 修改文件 | 预计影响 |
|------|--------|---------|---------|
| Quick-1 | 创建 `.dockerignore` | 新建 `.dockerignore` | 构建速度+镜像安全 |
| Quick-2 | Redis 配置挂载 | `docker-compose.yml` | AOF/maxmemory 生效 |
| Quick-3 | 统一 escape_like() | 新建 `app/utils/db_utils.py` + 4个文件 | 消除4处重复 |
| Quick-4 | 配置 Alertmanager 接收方 | `config/alertmanager.yml` | 告警可发送 |
| Quick-5 | 降低连接池 pool_size | `fastapi_app/core/database.py` | 连接数从45降至30 |

---

**声明**: 本方案基于 final_report_v6.md 识别的20个问题，结合代码库实际验证结果制定。所有代码修改建议均基于当前代码库状态，实施前应在 staging 环境充分测试。Phase 1 的 P0 问题修复应优先执行。
