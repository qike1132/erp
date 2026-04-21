# Comate 项目上下文

## 项目概要

**项目名称**: 滨发协同系统 (BinFa ERP)
**项目类型**: 双框架 ERP 系统 (Flask + FastAPI)
**当前版本**: 1.4.1
**迁移状态**: Flask → FastAPI 迁移进行中

## 技术栈

### 后端
- **Web 框架**: Flask (port 5003, legacy) + FastAPI (port 5002, primary API)
- **ORM**: SQLAlchemy 2.0 (Flask-SQLAlchemy + 纯 SQLAlchemy 2.0 双模型系统)
- **异步 DB 驱动**: asyncmy (替代 aiomysql)
- **同步 DB 驱动**: pymysql
- **验证**: Pydantic v2 + pydantic-settings
- **任务队列**: Celery + Redis
- **数据库**: MySQL 8.0 (utf8mb4)
- **缓存**: Redis 7.2

### 前端
- **模板引擎**: Jinja2 (服务端渲染)
- **CSS 框架**: Bootstrap 5
- **图标**: Font Awesome
- **JavaScript**: 原生 JS (按模块: order.js, product.js, finance.js 等)

### 基础设施
- **容器化**: Docker + docker-compose
- **反向代理**: Nginx 1.27-alpine
- **监控**: Prometheus + Grafana
- **OCR**: RapidOCR + RapidTable (离线识别)

## 关键架构决策

### 双框架共存模式
- Flask 为主进程，FastAPI 为子进程 (run.py)
- 开发环境: Flask 代理 `/api/v1/` 到 FastAPI
- 生产环境: Nginx 直接路由 `/api/v1/` 到 FastAPI

### 双模型系统
- `app/models/`: Flask-SQLAlchemy 模型 (db.Model)
- `fastapi_app/shared_models/`: 纯 SQLAlchemy 2.0 模型 (DeclarativeBase)
- 两者映射相同表结构，shared_models 使用现代 Mapped/mapped_column 语法

### 共享业务逻辑
- `fastapi_app/shared/`: 框架无关的核心业务逻辑
- `stock_crud_service.py`: 跨框架库存 CRUD (646行)
- `stock_concurrency.py`: 悲观锁 (SELECT FOR UPDATE) + 乐观锁

## 项目目录结构

```
d:\erp_system\
├── app/                    # Flask 应用 (legacy)
│   ├── routes/             # 20+ Blueprint
│   ├── models/             # 27 个 Flask-SQLAlchemy 模型
│   ├── services/           # Flask 业务逻辑
│   └── utils/              # 工具函数
├── fastapi_app/            # FastAPI 应用 (primary)
│   ├── api/v1/endpoints/   # 22 个 API 端点
│   ├── core/               # 配置、数据库、依赖注入
│   ├── schemas/            # Pydantic 模式
│   ├── services/           # 24 个服务 (含 OCR 1221行)
│   ├── shared/             # 跨框架共享逻辑
│   ├── shared_models/      # 纯 SQLAlchemy 2.0 模型
│   └── tasks/              # Celery 异步任务
├── templates/              # Jinja2 模板 (双框架共享)
├── static/                 # 静态资源
├── utils/                  # 跨框架工具模块
├── memory/                 # AI 记忆持久化
├── skills/                 # Comate 技能定义
└── agents/                 # AI 代理角色定义
```

## 编码规范

### Python
- 使用 `async/await` 异步模式 (FastAPI 端)
- Pydantic v2 进行请求/响应验证
- Service 层封装业务逻辑，与路由层分离
- 共享逻辑放 `fastapi_app/shared/`，不依赖框架

### JavaScript
- 所有 DOM 操作必须在 `DOMContentLoaded` 中
- 动态属性访问必须验证类型 (`typeof fn === 'function'`)
- 使用 Bootstrap 5 原生组件，不引入额外 UI 库

### SQL
- 软删除模型查询必须过滤 `is_deleted = False`
- 分页参数 endpoint/service 默认值必须一致
- 同一筛选条件不重复写 (DRY)

## 常见陷阱

1. **双模型同步**: 修改表结构时必须同时更新 `app/models/` 和 `fastapi_app/shared_models/`
2. **传递依赖遮蔽**: 直接 import 的包必须在 `requirements/base.txt` 显式声明，不可依赖传递依赖
3. **HTTPException 不可用于重定向**: 3xx 状态码必须用 `RedirectResponse`
4. **LIKE 注入防护**: 所有接收用户输入的 LIKE 调用必须使用转义函数，100% 覆盖率
5. **导航缓存**: 修改导航数据后需清除 Redis + 内存两级缓存
6. **Celery 任务**: 异步任务结果通过 Redis + 轮询端点获取

## 开发工作流

1. 启动: `python run.py` (同时启动 Flask + FastAPI)
2. 数据库迁移: `alembic revision --autogenerate` + `alembic upgrade head`
3. 测试: `pytest tests/`
4. 部署: `docker-compose up -d`
