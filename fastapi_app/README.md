# 滨发协同系统 - FastAPI 后端服务

ERP 系统的 FastAPI 后端，覆盖订单、产品、库存、采购、生产、板房打样（按客户分类打样）、审批、报表、备份等业务模块。全异步架构，支持浏览器 Web 端与 Capacitor 移动端。

## 技术栈

- **框架**: FastAPI（全异步）+ SQLAlchemy 2.0（asyncpg 驱动）
- **数据库**: PostgreSQL 16（可选只读副本 + PgBouncer 连接池）
- **缓存/消息**: Redis（缓存 / Celery Broker / Celery Results 三实例拆分）
- **任务队列**: Celery（通用 worker + gevent I/O worker）+ ARQ
- **实时通知**: WebSocket + FCM 推送
- **可观测性**: Prometheus + OpenTelemetry + Sentry + 结构化日志
- **对象存储**: MinIO/S3（本地文件系统可切换）

## 目录结构

```
fastapi_app/
├── main.py                    # 应用入口（lifespan、异常处理、中间件注册）
├── api/
│   ├── ws.py                  # WebSocket 实时通知端点
│   ├── v1/                    # 业务 API v1
│   │   ├── router.py          # 路由汇总（统一注册认证依赖）
│   │   └── endpoints/         # 33 个业务端点模块（认证、订单、库存、采购…）
│   └── v2/                    # API v2 版本策略示例（Sunset/Deprecation 头）
├── core/                      # 基础设施
│   ├── config.py              # pydantic-settings 配置（含生产安全校验）
│   ├── database.py            # 异步引擎/会话、连接池动态计算、读写分离
│   ├── deps.py                # JWT 双模式认证、权限依赖工厂、token 黑名单
│   ├── security.py            # Argon2id 密码哈希（兼容旧格式迁移）
│   ├── middleware.py          # CSRF/CORS/TrustedHost/CSP/限流/链路追踪
│   ├── cache.py / redis_wrapper.py / purchase_cache.py
│   ├── exceptions.py          # AppError 体系 + db_transaction 事务上下文
│   ├── celery_app.py          # Celery 应用与任务路由
│   ├── metrics.py / telemetry.py / slow_query.py / health.py
│   └── ...                    # 限流、审计、状态机、事件总线、号码生成等
├── schemas/                   # Pydantic 请求/响应模型
├── services/                  # 业务逻辑层（按业务域拆分，含 Facade 兼容层）
├── shared_models/             # 纯 SQLAlchemy 2.0 声明式模型（全量注册）
├── utils/                     # 工具函数
├── tasks/                     # 异步任务
├── tests/                     # 后端测试
└── static/                    # 上传文件挂载目录（uploads/files/releases）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements/dev.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 必填: SECRET_KEY（≥32字符强随机）、DB_PASSWORD、REDIS_PASSWORD（生产）
```

### 3. 启动服务

```bash
python start.py --dev          # 开发模式（FastAPI reload，端口 5002）
python start.py --prod         # 生产模式
python start.py --backend-only # 仅后端
```

或直接：

```bash
uvicorn fastapi_app.main:app --host 0.0.0.0 --port 5002 --reload
```

### 4. 访问文档

开发环境（`APP_ENV != production`）：
- Swagger UI: `http://localhost:5002/api/docs`
- ReDoc: `http://localhost:5002/api/redoc`
- 健康检查: `GET /api/health`

> 生产环境自动关闭文档端点，防止暴露 API 结构。

## API 约定

- 前缀：`/api/v1`（业务端点默认需登录，路由级统一注入 `get_current_user_id`）
- 认证：`Authorization: Bearer <JWT>`（移动端/API）或 httpOnly Cookie（浏览器）
- 权限：`require_permission("xxx_manage")` / `require_superuser()` 依赖工厂
- 统一响应：`{"success": true/false, "detail": ..., "code": ..., "request_id": ..., "timestamp": ...}`
- 分页：`page` + `per_page`（默认 20，上限 100）
- 限流：登录端点分层限流（1 分钟 5 次 + 5 分钟 10 次），其他端点按用户/ IP

## 主要业务模块

| 模块 | 端点前缀 | 说明 |
|---|---|---|
| 认证与上传 | `/api/v1/auth` | 登录/登出/刷新/用户信息/图片上传 |
| 订单 | `/api/v1/orders` | 订单 CRUD、审批流、库存扣减（FIFO） |
| 产品 | `/api/v1/products` | 产品与物料/面料/配件 BOM |
| 库存 | `/api/v1/stock` | 出入库、退货、盘点 |
| 采购 | `/api/v1/purchase-center`、`/api/v1/plans` | 采购订单/计划/供应商汇总 |
| 生产 | `/api/v1/production-plans`、`/api/v1/daily-production` | 排产计划与生产报表 |
| 板房打样 | `/api/v1/pattern-room` | 按客户分类打样（客户分组+部位布料+版本快照） |
| 审批 | `/api/v1/approvals` | 审批流 |
| 报表 | `/api/v1/reports` | 报表统计 |
| 备份 | `/api/v1/backup` | 数据库备份/恢复/演练 |
| 通知 | `/api/v1/notifications` + `/ws/notifications` | WebSocket 实时通知 |
| 批量导入 | `/api/v1/batch` | Excel 批量导入 |
| OCR | `/api/v1/ocr-import` | PDF 出货单 OCR 识别导入 |

## 开发规范

1. **目录职责**：路由放 `api/v1/endpoints/`，Pydantic 模型放 `schemas/`，业务逻辑放 `services/`，ORM 模型放 `shared_models/`，工具函数放 `utils/`
2. **事务边界**：服务层使用 `flush()` 而非 `commit()`，由 `get_async_db` 依赖统一控制；需要精确控制时使用 `db_transaction` 上下文
3. **缓存失效/事件发布**：注册到 `db.info['post_commit_callbacks']`，事务成功后才执行
4. **错误处理**：业务异常抛 `AppError` 子类；`ValueError` → 400；`SQLAlchemyError` → 500（统一脱敏）
5. **安全**：密码 Argon2id；JWT 支持 HS256/RS256；token 黑名单走 Redis + 本地 LRU 降级；上传文件校验魔数
6. **命名**：路由文件 = 模块名；路由函数 = 动词 + 名词；Schema = 功能 + Request/Response

## 测试与质量

```bash
pytest                          # 全量测试（tests/ 与 fastapi_app/tests/）
pytest tests/test_pattern_room.py  # 单模块测试
ruff check fastapi_app/         # 代码规范
mypy                            # 类型检查（mypy.ini 限定了检查范围）
bandit -c bandit.yaml -r fastapi_app/  # 安全扫描
```

## 数据库迁移

```bash
alembic -c migrations/alembic.ini upgrade head   # 应用迁移
alembic -c migrations/alembic.ini revision --autogenerate -m "描述"  # 生成迁移
```

## 部署

本系统为**内网 Windows 原生部署**，通过 NSSM 托管服务，**不使用容器、不由 CI 部署**。

- **服务托管**：`erp-prod`（uvicorn `:5002` + nginx `:3000`）/ `erp-arq` / `erp-redis` / `erp-redis-broker`
  （`nssm.exe` 位于 `C:\nssm\`，**不在 PATH**）
- **操作步骤与提权要求**：见 `docs/runbooks/service-lifecycle.md`
- **数据库迁移**：`python -m alembic -c migrations/alembic.ini upgrade head`
- **环境变量**：见根目录 `.env.example`（真实值在 `.env`，不入库）

> 说明：历史上的 `deploy-windows.ps1` / `deploy_nginx.ps1` 已作为过时脚本删除
> （commit `15e13a79`）；CI 中的部署 job 亦已移除——托管 runner 无法访问内网生产机。
> 异步任务队列使用 **ARQ**（不是 Celery），由 `erp-arq` 服务承载。
