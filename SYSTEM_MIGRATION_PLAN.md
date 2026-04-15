# ERP系统全面迁移方案

**项目名称**: 滨发协同系统 (ERP) 系统迁移  
**方案版本**: v1.0  
**制定日期**: 2026-04-09  
**适用规模**: 20人工厂团队  
**核心原则**: 业务连续性优先、数据完整性保障、零宕机迁移

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [迁移目标与原则](#2-迁移目标与原则)
3. [前端架构选型与技术栈](#3-前端架构选型与技术栈)
4. [后端API架构设计与技术选型](#4-后端api架构设计与技术选型)
5. [迁移实施步骤](#5-迁移实施步骤)
6. [数据迁移策略](#6-数据迁移策略)
7. [风险评估与应对措施](#7-风险评估与应对措施)
8. [回滚机制设计](#8-回滚机制设计)
9. [系统验证与性能测试计划](#9-系统验证与性能测试计划)
10. [项目组织与时间计划](#10-项目组织与时间计划)
11. [附录](#附录)

---

## 1. 执行摘要

### 1.1 迁移概述

本方案旨在将现有ERP系统从Flask单体架构迁移到Flask + FastAPI混合架构，实现前后端分离，提升系统性能和可维护性。

### 1.2 核心目标

| 目标 | 描述 | 优先级 |
|-----|------|--------|
| 业务连续性 | 迁移期间所有功能正常运行 | P0 |
| 数据完整性 | 数据零丢失、零损坏 | P0 |
| 零宕机 | 用户无感知迁移 | P0 |
| 功能对等 | 新系统功能与旧系统完全一致 | P0 |
| 性能提升 | API响应时间提升20%以上 | P1 |
| 可维护性 | 代码结构更清晰，便于维护 | P1 |

### 1.3 迁移策略

```
┌─────────────────────────────────────────────────────────────┐
│                    迁移策略总览                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  策略: 渐进式双轨运行 + 灰度切换                             │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 阶段1: 双轨并行                                      │   │
│  │   ├── 旧系统: 完全运行                               │   │
│  │   └── 新系统: 开发测试                               │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 阶段2: 功能切换                                      │   │
│  │   ├── 旧系统: 运行未迁移功能                         │   │
│  │   └── 新系统: 运行已迁移功能                         │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 阶段3: 完全切换                                      │   │
│  │   ├── 旧系统: 热备状态                               │   │
│  │   └── 新系统: 全量运行                               │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 阶段4: 稳定运行                                      │   │
│  │   ├── 旧系统: 下线                                   │   │
│  │   └── 新系统: 正常运行                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.4 关键指标

| 指标 | 目标值 | 验收标准 |
|-----|-------|---------|
| 系统可用性 | 99.9% | 迁移期间 |
| 数据完整性 | 100% | 零丢失 |
| 功能覆盖率 | 100% | 所有功能可用 |
| 响应时间 | <200ms | P95 |
| 回滚时间 | <10分钟 | 紧急情况 |

---

## 2. 迁移目标与原则

### 2.1 迁移目标

#### 2.1.1 技术目标

```
技术目标:
├── 架构升级
│   ├── 从单体架构升级为模块化架构
│   ├── 实现前后端分离
│   └── 引入异步处理能力
│
├── 技术栈现代化
│   ├── 引入 FastAPI 作为 API 服务层
│   ├── 使用 Pydantic 进行数据验证
│   └── 采用 JWT 认证机制
│
└── 性能优化
    ├── API 响应时间提升 20%+
    ├── 并发处理能力提升 100%+
    └── 资源利用率优化
```

#### 2.1.2 业务目标

```
业务目标:
├── 保持业务连续性
│   ├── 所有功能正常运行
│   ├── 用户体验无影响
│   └── 业务流程无中断
│
├── 数据安全保障
│   ├── 数据零丢失
│   ├── 数据零损坏
│   └── 数据一致性保证
│
└── 为未来扩展做准备
    ├── 支持更大规模用户
    ├── 支持更多业务功能
    └── 支持移动端接入
```

### 2.2 迁移原则

| 原则 | 描述 | 执行要求 |
|-----|------|---------|
| **业务优先** | 业务连续性高于技术升级 | 任何影响业务的操作需审批 |
| **数据安全** | 数据完整性不可妥协 | 所有数据操作需备份验证 |
| **渐进式** | 分阶段、可回滚 | 每阶段独立可验证 |
| **双轨运行** | 新旧系统并行 | 确保随时可切换 |
| **充分测试** | 测试覆盖所有场景 | 测试不通过不发布 |
| **文档先行** | 文档指导实施 | 无文档不开发 |

### 2.3 迁移范围

#### 2.3.1 在迁移范围内

```
迁移范围:
├── 后端服务
│   ├── Flask 页面渲染服务 (保留)
│   ├── FastAPI API 服务 (新增)
│   └── 认证服务 (升级为 JWT)
│
├── 数据层
│   ├── 数据库结构 (保持不变)
│   ├── ORM 层 (升级 SQLAlchemy 2.0)
│   └── 缓存层 (保持不变)
│
├── 前端
│   ├── 页面模板 (保持不变)
│   ├── JavaScript 交互 (适配 JWT)
│   └── CSS 样式 (保持不变)
│
└── 基础设施
    ├── Nginx 配置 (升级)
    ├── Docker 部署 (新增)
    └── 监控告警 (升级)
```

#### 2.3.2 不在迁移范围内

```
不在迁移范围:
├── 数据库结构变更
├── 业务逻辑重构
├── 前端框架更换
└── 第三方系统对接
```

---

## 3. 前端架构选型与技术栈

### 3.1 前端架构选型

#### 3.1.1 选型决策

| 方案 | 优点 | 缺点 | 推荐度 |
|-----|------|------|-------|
| **保持现有架构** | 风险低、成本低、无学习成本 | 无技术提升 | ⭐⭐⭐⭐⭐ |
| Vue 3 重构 | 现代化、体验好 | 成本高、风险高 | ⭐⭐ |
| React 重构 | 生态丰富、组件化 | 成本高、学习曲线陡 | ⭐⭐ |
| 混合架构 | 渐进式升级 | 复杂度增加 | ⭐⭐⭐ |

**决策: 保持现有前端架构，仅做必要的JWT适配**

#### 3.1.2 选型理由

```
保持现有前端架构的理由:
┌─────────────────────────────────────────────────────────────┐
│  1. 业务连续性                                               │
│     ├── 用户无需重新学习操作                                 │
│     ├── 无界面变化带来的适应成本                             │
│     └── 降低迁移风险                                         │
│                                                             │
│  2. 成本控制                                                 │
│     ├── 前端重构成本约 20-30万元                             │
│     ├── 保持现有架构成本约 2-3万元                           │
│     └── 成本节省 90%                                         │
│                                                             │
│  3. 风险控制                                                 │
│     ├── 前端重构风险高                                       │
│     ├── 保持现有架构风险低                                   │
│     └── 符合渐进式迁移原则                                   │
│                                                             │
│  4. 20人规模适配                                             │
│     ├── 当前前端完全满足需求                                 │
│     ├── 无性能瓶颈                                           │
│     └── 无用户体验问题                                       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 前端技术栈

#### 3.2.1 保持的技术栈

| 技术 | 版本 | 用途 | 状态 |
|-----|------|------|------|
| Jinja2 | 3.x | 服务端模板渲染 | 保持 |
| Bootstrap | 5.x | UI框架 | 保持 |
| jQuery | 3.x | DOM操作 | 保持 |
| 原生JavaScript | ES6+ | 交互逻辑 | 保持 |
| DataTables | 1.x | 表格组件 | 保持 |
| Select2 | 4.x | 下拉选择 | 保持 |

#### 3.2.2 需要调整的部分

```
前端调整内容:
┌─────────────────────────────────────────────────────────────┐
│  1. 认证适配                                                 │
│     ├── 新增 JWT Token 存储与管理                            │
│     ├── 修改 API 请求拦截器，添加 Token                      │
│     └── 处理 Token 过期刷新逻辑                              │
│                                                             │
│  2. API调用适配                                              │
│     ├── API 路径可能变化                                     │
│     ├── 错误响应格式适配                                     │
│     └── 请求头调整                                           │
│                                                             │
│  3. 错误处理                                                 │
│     ├── 401 未授权处理                                       │
│     ├── 403 权限不足处理                                     │
│     └── 422 验证错误处理                                     │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 前端改造方案

#### 3.3.1 JWT Token 管理模块

```javascript
// static/js/auth.js - 新增认证管理模块

const AuthManager = {
    TOKEN_KEY: 'erp_access_token',
    REFRESH_KEY: 'erp_refresh_token',
    USER_KEY: 'erp_user_info',

    init() {
        this.setupAxiosInterceptor();
        this.checkTokenExpiry();
    },

    setTokens(accessToken, refreshToken, userInfo) {
        localStorage.setItem(this.TOKEN_KEY, accessToken);
        localStorage.setItem(this.REFRESH_KEY, refreshToken);
        if (userInfo) {
            localStorage.setItem(this.USER_KEY, JSON.stringify(userInfo));
        }
    },

    getAccessToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    getRefreshToken() {
        return localStorage.getItem(this.REFRESH_KEY);
    },

    getUserInfo() {
        const info = localStorage.getItem(this.USER_KEY);
        return info ? JSON.parse(info) : null;
    },

    clearTokens() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.REFRESH_KEY);
        localStorage.removeItem(this.USER_KEY);
    },

    async refreshAccessToken() {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) {
            this.redirectToLogin();
            return false;
        }

        try {
            const response = await fetch('/api/auth/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${refreshToken}`
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.setTokens(data.access_token, data.refresh_token);
                return true;
            }
        } catch (error) {
            console.error('Token refresh failed:', error);
        }

        this.clearTokens();
        this.redirectToLogin();
        return false;
    },

    setupAxiosInterceptor() {
        $.ajaxSetup({
            beforeSend: (xhr, settings) => {
                const token = this.getAccessToken();
                if (token && settings.url.startsWith('/api/')) {
                    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
                }
            },
            error: (xhr, textStatus, errorThrown) => {
                if (xhr.status === 401) {
                    this.handleUnauthorized();
                } else if (xhr.status === 403) {
                    this.handleForbidden();
                } else if (xhr.status === 422) {
                    this.handleValidationError(xhr.responseJSON);
                }
            }
        });
    },

    handleUnauthorized() {
        this.refreshAccessToken().then(success => {
            if (!success) {
                GlobalNotification.error('登录已过期，请重新登录');
                setTimeout(() => this.redirectToLogin(), 1500);
            }
        });
    },

    handleForbidden() {
        GlobalNotification.error('权限不足，无法执行此操作');
    },

    handleValidationError(errors) {
        if (errors && errors.detail) {
            const details = Array.isArray(errors.detail) ? errors.detail : [errors.detail];
            details.forEach(err => {
                const field = err.loc ? err.loc.join('.') : '';
                GlobalNotification.error(`${field}: ${err.msg}`);
            });
        }
    },

    redirectToLogin() {
        window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
    },

    checkTokenExpiry() {
        setInterval(() => {
            const token = this.getAccessToken();
            if (token) {
                const payload = this.parseJwt(token);
                if (payload && payload.exp * 1000 < Date.now() + 5 * 60 * 1000) {
                    this.refreshAccessToken();
                }
            }
        }, 60000);
    },

    parseJwt(token) {
        try {
            const base64Url = token.split('.')[1];
            const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
            return JSON.parse(window.atob(base64));
        } catch (e) {
            return null;
        }
    }
};

$(document).ready(function() {
    AuthManager.init();
});
```

#### 3.3.2 API 调用适配

```javascript
// static/js/api-client.js - API 客户端封装

class APIClient {
    constructor(baseUrl = '/api') {
        this.baseUrl = baseUrl;
    }

    async request(method, endpoint, data = null, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const token = AuthManager.getAccessToken();

        const config = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                ...(token && { 'Authorization': `Bearer ${token}` })
            },
            ...options
        };

        if (data && ['POST', 'PUT', 'PATCH'].includes(method)) {
            config.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(url, config);
            return await this.handleResponse(response);
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    async handleResponse(response) {
        if (response.ok) {
            return await response.json();
        }

        if (response.status === 401) {
            const refreshed = await AuthManager.refreshAccessToken();
            if (refreshed) {
                // 重试请求
                return await this.request(this.lastMethod, this.lastEndpoint, this.lastData);
            }
            throw new Error('Unauthorized');
        }

        if (response.status === 422) {
            const errors = await response.json();
            throw new ValidationError(errors);
        }

        throw new Error(`HTTP ${response.status}`);
    }

    get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        return this.request('GET', url);
    }

    post(endpoint, data) {
        return this.request('POST', endpoint, data);
    }

    put(endpoint, data) {
        return this.request('PUT', endpoint, data);
    }

    patch(endpoint, data) {
        return this.request('PATCH', endpoint, data);
    }

    delete(endpoint) {
        return this.request('DELETE', endpoint);
    }

    async upload(endpoint, formData) {
        const token = AuthManager.getAccessToken();
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'POST',
            headers: {
                ...(token && { 'Authorization': `Bearer ${token}` })
            },
            body: formData
        });
        return this.handleResponse(response);
    }
}

const api = new APIClient();
```

### 3.4 前端改造工作量

| 改造项 | 工作量 | 优先级 |
|-------|-------|-------|
| JWT Token 管理模块 | 2人天 | P0 |
| API 调用适配 | 3人天 | P0 |
| 错误处理适配 | 1人天 | P0 |
| 登录流程改造 | 1人天 | P0 |
| 测试验证 | 2人天 | P0 |
| **合计** | **9人天** | - |

---

## 4. 后端API架构设计与技术选型

### 4.1 后端架构设计

#### 4.1.1 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│                    后端目标架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                     ┌─────────────┐                         │
│                     │    Nginx    │                         │
│                     │  (反向代理)  │                         │
│                     └──────┬──────┘                         │
│                            │                                │
│            ┌───────────────┴───────────────┐               │
│            ▼                               ▼               │
│    ┌───────────────┐               ┌───────────────┐       │
│    │    Flask      │               │   FastAPI     │       │
│    │   (Port 5001) │               │  (Port 5002)  │       │
│    │               │               │               │       │
│    │ ┌───────────┐ │               │ ┌───────────┐ │       │
│    │ │ 页面渲染  │ │               │ │ REST API  │ │       │
│    │ │ 表单处理  │ │               │ │ 异步任务  │ │       │
│    │ │ Session   │ │               │ │ JWT认证   │ │       │
│    │ └───────────┘ │               │ └───────────┘ │       │
│    └───────┬───────┘               └───────┬───────┘       │
│            │                               │               │
│            └───────────────┬───────────────┘               │
│                            ▼                                │
│                   ┌────────────────┐                       │
│                   │   共享服务层    │                       │
│                   │ ┌────────────┐ │                       │
│                   │ │ 数据模型   │ │                       │
│                   │ │ 缓存服务   │ │                       │
│                   │ │ 认证服务   │ │                       │
│                   │ │ 工具函数   │ │                       │
│                   │ └────────────┘ │                       │
│                   └───────┬────────┘                       │
│                           ▼                                 │
│            ┌──────────────┴──────────────┐                 │
│            ▼                             ▼                 │
│    ┌─────────────┐               ┌─────────────┐           │
│    │    MySQL    │               │    Redis    │           │
│    └─────────────┘               └─────────────┘           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 4.1.2 服务职责划分

| 服务 | 职责 | 技术栈 |
|-----|------|-------|
| Flask | 页面渲染、表单处理、Session认证 | Flask 2.3.x |
| FastAPI | RESTful API、异步处理、JWT认证 | FastAPI 0.100+ |
| 共享层 | 数据模型、缓存、认证工具 | SQLAlchemy 2.0 |

### 4.2 技术选型

#### 4.2.1 核心技术栈

| 领域 | 技术 | 版本 | 选型理由 |
|-----|------|------|---------|
| **Web框架** | Flask | 2.3.x | 保持现有，页面渲染 |
| **API框架** | FastAPI | 0.100+ | 高性能、异步支持、自动文档 |
| **ORM** | SQLAlchemy | 2.0 | 异步支持、类型提示 |
| **数据验证** | Pydantic | 2.x | FastAPI原生支持 |
| **认证** | JWT | - | 无状态、跨服务共享 |
| **缓存** | Redis | 7.0 | 高性能、支持分布式 |
| **数据库** | MySQL | 8.0 | 保持现有 |
| **容器** | Docker | 24.x | 标准化部署 |
| **反向代理** | Nginx | 1.24 | 高性能、负载均衡 |

#### 4.2.2 FastAPI 项目结构

```
fastapi_service/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 应用入口
│   ├── config.py               # 配置管理
│   │
│   ├── api/                    # API 路由
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── endpoints/
│   │   │   │   ├── auth.py     # 认证相关
│   │   │   │   ├── products.py # 产品API
│   │   │   │   ├── orders.py   # 订单API
│   │   │   │   ├── stock.py    # 库存API
│   │   │   │   ├── users.py    # 用户API
│   │   │   │   └── reports.py  # 报表API
│   │   │   └── router.py       # 路由汇总
│   │   └── deps.py             # 依赖注入
│   │
│   ├── core/                   # 核心模块
│   │   ├── __init__.py
│   │   ├── security.py         # 安全相关
│   │   ├── config.py           # 配置
│   │   └── logging.py          # 日志
│   │
│   ├── models/                 # 数据模型 (共享)
│   │   ├── __init__.py
│   │   └── ...                 # 从共享模块导入
│   │
│   ├── schemas/                # Pydantic 模型
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── product.py
│   │   ├── order.py
│   │   └── stock.py
│   │
│   ├── services/               # 业务逻辑
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── product.py
│   │   ├── order.py
│   │   └── stock.py
│   │
│   └── utils/                  # 工具函数
│       ├── __init__.py
│       ├── cache.py
│       └── helpers.py
│
├── tests/                      # 测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_products.py
│   └── ...
│
├── alembic/                    # 数据库迁移
│   └── ...
│
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### 4.3 核心代码设计

#### 4.3.1 FastAPI 应用入口

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    setup_logging()
    yield
    # 关闭时执行


app = FastAPI(
    title="ERP API",
    description="滨发协同系统 API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# 中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# 注册路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "2.0.0"}
```

#### 4.3.2 认证模块

```python
# app/core/security.py
from datetime import datetime, timedelta
from typing import Optional, List
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class TokenPayload(BaseModel):
    sub: int
    username: str
    permissions: List[str] = []
    exp: datetime


def create_access_token(
    user_id: int,
    username: str,
    permissions: List[str],
    expires_delta: Optional[timedelta] = None
) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=8))
    payload = {
        "sub": user_id,
        "username": username,
        "permissions": permissions,
        "exp": expire
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    payload = {"sub": user_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> Optional[TokenPayload]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return TokenPayload(**payload)
    except JWTError:
        return None


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception
    return payload


def require_permission(permission: str):
    async def permission_checker(
        user: TokenPayload = Depends(get_current_user)
    ) -> TokenPayload:
        if permission not in user.permissions and "*" not in user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足"
            )
        return user
    return permission_checker
```

#### 4.3.3 API 路由示例

```python
# app/api/v1/endpoints/products.py
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_permission
from app.schemas.product import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
    ProductListResponse
)
from app.services.product import ProductService

router = APIRouter()


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user = Depends(require_permission("product_view"))
):
    """获取产品列表"""
    service = ProductService(db)
    return await service.get_list(
        page=page,
        page_size=page_size,
        keyword=keyword
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(require_permission("product_view"))
):
    """获取产品详情"""
    service = ProductService(db)
    product = await service.get_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")
    return product


@router.post("/products", response_model=ProductResponse)
async def create_product(
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user = Depends(require_permission("product_manage"))
):
    """创建产品"""
    service = ProductService(db)
    return await service.create(product_in)


@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user = Depends(require_permission("product_manage"))
):
    """更新产品"""
    service = ProductService(db)
    product = await service.update(product_id, product_in)
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")
    return product


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(require_permission("product_manage"))
):
    """删除产品"""
    service = ProductService(db)
    await service.delete(product_id)
    return {"success": True}
```

### 4.4 API 迁移清单

| 模块 | API数量 | 优先级 | 预计工时 |
|-----|--------|-------|---------|
| 认证授权 | 5 | P0 | 3人天 |
| 产品管理 | 8 | P0 | 4人天 |
| 订单管理 | 10 | P0 | 5人天 |
| 库存管理 | 12 | P0 | 6人天 |
| 用户管理 | 6 | P1 | 3人天 |
| 报表统计 | 7 | P1 | 4人天 |
| 批量操作 | 5 | P1 | 3人天 |
| 其他API | 15 | P2 | 6人天 |
| **合计** | **68** | - | **34人天** |

---

## 5. 迁移实施步骤

### 5.1 总体实施计划

```
┌─────────────────────────────────────────────────────────────┐
│                    迁移实施总计划                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  阶段0: 准备阶段 (第1-2周)                                   │
│  ├── 环境准备                                               │
│  ├── 团队培训                                               │
│  └── 文档编写                                               │
│                                                             │
│  阶段1: 基础设施搭建 (第3-4周)                               │
│  ├── 共享模块抽取                                           │
│  ├── FastAPI 基础框架                                       │
│  └── 认证系统升级                                           │
│                                                             │
│  阶段2: 核心API迁移 (第5-8周)                                │
│  ├── 产品API                                                │
│  ├── 订单API                                                │
│  └── 库存API                                                │
│                                                             │
│  阶段3: 扩展API迁移 (第9-10周)                               │
│  ├── 用户API                                                │
│  ├── 报表API                                                │
│  └── 其他API                                                │
│                                                             │
│  阶段4: 前端适配 (第11-12周)                                 │
│  ├── JWT适配                                                │
│  ├── API调用适配                                            │
│  └── 测试验证                                               │
│                                                             │
│  阶段5: 集成测试 (第13-14周)                                 │
│  ├── 功能测试                                               │
│  ├── 性能测试                                               │
│  └── 安全测试                                               │
│                                                             │
│  阶段6: 灰度发布 (第15-16周)                                 │
│  ├── 10%流量                                                │
│  ├── 50%流量                                                │
│  └── 100%流量                                               │
│                                                             │
│  总工期: 约16周 (4个月)                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 详细实施步骤

#### 阶段0: 准备阶段 (第1-2周)

```
第1周:
┌─────────────────────────────────────────────────────────────┐
│ 任务                    │ 负责人   │ 产出                   │
├─────────────────────────┼─────────┼───────────────────────┤
│ 开发环境搭建            │ 运维     │ 开发服务器、数据库     │
│ 测试环境搭建            │ 运维     │ 测试服务器、数据库     │
│ Docker环境配置          │ 运维     │ Docker Compose配置     │
│ 项目仓库初始化          │ 架构师   │ Git仓库、分支策略      │
└─────────────────────────────────────────────────────────────┘

第2周:
┌─────────────────────────────────────────────────────────────┐
│ 任务                    │ 负责人   │ 产出                   │
├─────────────────────────┼─────────┼───────────────────────┤
│ FastAPI培训             │ 架构师   │ 培训文档、示例代码     │
│ Pydantic培训            │ 架构师   │ 培训文档、示例代码     │
│ 迁移方案评审            │ 全员     │ 评审报告、修订方案     │
│ 详细设计文档            │ 架构师   │ 设计文档               │
└─────────────────────────────────────────────────────────────┘
```

#### 阶段1: 基础设施搭建 (第3-4周)

```
第3周:
┌─────────────────────────────────────────────────────────────┐
│ 任务                    │ 工作内容                               │
├─────────────────────────┼───────────────────────────────────┤
│ 共享模块抽取            │ 创建 shared/ 目录                     │
│                         │ 抽取数据模型到 shared/models/         │
│                         │ 抽取缓存工具到 shared/cache/          │
│                         │ 抽取工具函数到 shared/utils/          │
├─────────────────────────┼───────────────────────────────────┤
│ FastAPI项目创建         │ 创建项目结构                          │
│                         │ 配置文件编写                          │
│                         │ 数据库连接配置                        │
│                         │ Redis连接配置                         │
└─────────────────────────────────────────────────────────────┘

第4周:
┌─────────────────────────────────────────────────────────────┐
│ 任务                    │ 工作内容                               │
├─────────────────────────┼───────────────────────────────────┤
│ JWT认证实现             │ JWT生成/验证函数                      │
│                         │ Token刷新机制                         │
│                         │ 权限检查依赖                          │
├─────────────────────────┼───────────────────────────────────┤
│ Flask认证升级           │ 登录时生成JWT Token                   │
│                         │ Session + JWT双轨支持                 │
│                         │ 权限检查适配                          │
├─────────────────────────┼───────────────────────────────────┤
│ Nginx配置               │ 路由分发配置                          │
│                         │ 负载均衡配置                          │
│                         │ SSL证书配置                           │
└─────────────────────────────────────────────────────────────┘
```

#### 阶段2: 核心API迁移 (第5-8周)

```
第5-6周: 产品API + 订单API
┌─────────────────────────────────────────────────────────────┐
│ API                     │ 工作内容                               │
├─────────────────────────┼───────────────────────────────────┤
│ GET /api/v1/products    │ 产品列表查询                          │
│ GET /api/v1/products/{id}│ 产品详情                             │
│ POST /api/v1/products   │ 创建产品                              │
│ PUT /api/v1/products/{id}│ 更新产品                             │
│ DELETE /api/v1/products/{id}│ 删除产品                          │
│ GET /api/v1/products/search│ 产品搜索                          │
│ GET /api/v1/orders      │ 订单列表                              │
│ POST /api/v1/orders     │ 创建订单                              │
│ ...                     │ ...                                   │
└─────────────────────────────────────────────────────────────┘

第7-8周: 库存API + 测试
┌─────────────────────────────────────────────────────────────┐
│ API                     │ 工作内容                               │
├─────────────────────────┼───────────────────────────────────┤
│ GET /api/v1/stock/in    │ 入库列表                              │
│ POST /api/v1/stock/in   │ 创建入库                              │
│ GET /api/v1/stock/out   │ 出库列表                              │
│ POST /api/v1/stock/out  │ 创建出库                              │
│ ...                     │ ...                                   │
├─────────────────────────┼───────────────────────────────────┤
│ 单元测试                │ pytest测试用例                        │
│ 集成测试                │ API集成测试                           │
└─────────────────────────────────────────────────────────────┘
```

#### 阶段3-6: 后续阶段

详见完整方案文档...

### 5.3 双轨运行机制

```
双轨运行期间:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  用户请求                                                   │
│      │                                                      │
│      ▼                                                      │
│  ┌─────────┐                                                │
│  │  Nginx  │                                                │
│  └────┬────┘                                                │
│       │                                                     │
│       ├──────────────────────┐                              │
│       ▼                      ▼                              │
│  ┌─────────┐           ┌─────────┐                         │
│  │  Flask  │           │ FastAPI │                         │
│  │ (旧系统) │           │ (新系统) │                         │
│  │         │           │         │                         │
│  │ 页面    │           │ API     │                         │
│  │ Session │           │ JWT     │                         │
│  └────┬────┘           └────┬────┘                         │
│       │                     │                               │
│       │    ┌─────────┐      │                               │
│       └───▶│  MySQL  │◀─────┘                               │
│            │  Redis  │                                      │
│            └─────────┘                                      │
│                                                             │
│  路由规则:                                                   │
│  ├── /              → Flask (页面)                          │
│  ├── /login         → Flask (登录页面)                      │
│  ├── /api/v1/*      → FastAPI (新API)                      │
│  └── /api/*         → Flask (旧API，逐步迁移)               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 数据迁移策略

### 6.1 数据迁移原则

| 原则 | 描述 | 执行要求 |
|-----|------|---------|
| 零丢失 | 所有数据必须完整迁移 | 逐条校验 |
| 零损坏 | 数据内容不可改变 | MD5校验 |
| 一致性 | 关联数据保持一致 | 外键检查 |
| 可回滚 | 随时可回退到原状态 | 备份保留 |

### 6.2 数据迁移方案

#### 6.2.1 数据库结构处理

```
数据库结构策略:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  决策: 保持数据库结构不变                                    │
│                                                             │
│  理由:                                                       │
│  1. 降低迁移风险                                            │
│  2. 减少迁移工作量                                          │
│  3. 避免数据转换错误                                        │
│  4. 便于回滚                                                │
│                                                             │
│  影响:                                                       │
│  ├── ORM层需要适配 (SQLAlchemy 2.0)                         │
│  ├── 模型定义需要更新 (类型提示)                            │
│  └── 数据库操作代码需要适配                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 6.2.2 ORM 层迁移

```python
# 当前 Flask-SQLAlchemy 模型
from app import db

class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

# 迁移后 SQLAlchemy 2.0 模型 (共享)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String
from shared.models.base import Base

class Product(Base):
    __tablename__ = 'product'
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Flask 使用
    # FastAPI 使用
```

### 6.3 数据备份策略

#### 6.3.1 备份计划

| 备份类型 | 频率 | 保留时间 | 存储位置 |
|---------|------|---------|---------|
| 全量备份 | 每日 | 30天 | 异地存储 |
| 增量备份 | 每小时 | 7天 | 本地存储 |
| 实时备份 | 实时 | 24小时 | 主从复制 |

#### 6.3.2 备份脚本

```bash
#!/bin/bash
# backup.sh - 数据库备份脚本

BACKUP_DIR="/backup/mysql"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="erp"
DB_USER="backup_user"
DB_PASS="backup_password"

# 创建备份目录
mkdir -p $BACKUP_DIR

# 全量备份
mysqldump -u$DB_USER -p$DB_PASS --single-transaction \
    --routines --triggers --events \
    $DB_NAME | gzip > $BACKUP_DIR/full_$DATE.sql.gz

# 验证备份
if [ $? -eq 0 ]; then
    echo "[$(date)] Backup completed: full_$DATE.sql.gz"
    # 计算MD5
    md5sum $BACKUP_DIR/full_$DATE.sql.gz > $BACKUP_DIR/full_$DATE.md5
else
    echo "[$(date)] Backup failed!"
    exit 1
fi

# 清理旧备份 (保留30天)
find $BACKUP_DIR -name "full_*.sql.gz" -mtime +30 -delete
find $BACKUP_DIR -name "full_*.md5" -mtime +30 -delete
```

### 6.4 数据一致性保障

#### 6.4.1 一致性检查机制

```python
# scripts/data_consistency_check.py

import hashlib
from sqlalchemy import create_engine, text
from shared.models import Base

class DataConsistencyChecker:
    def __init__(self, db_url):
        self.engine = create_engine(db_url)
    
    def check_table_count(self, table_name):
        """检查表记录数"""
        with self.engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            return result.scalar()
    
    def check_table_checksum(self, table_name):
        """检查表数据校验和"""
        with self.engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT MD5(GROUP_CONCAT(
                    CONCAT_WS('|', id, name, create_time, update_time)
                    ORDER BY id
                )) as checksum
                FROM {table_name}
            """))
            return result.scalar()
    
    def verify_migration(self, source_url, target_url):
        """验证迁移数据一致性"""
        source_checker = DataConsistencyChecker(source_url)
        target_checker = DataConsistencyChecker(target_url)
        
        tables = ['product', 'order', 'stock_in', 'stock_out', 'user']
        results = []
        
        for table in tables:
            source_count = source_checker.check_table_count(table)
            target_count = target_checker.check_table_count(table)
            
            if source_count != target_count:
                results.append({
                    'table': table,
                    'status': 'FAILED',
                    'source_count': source_count,
                    'target_count': target_count
                })
            else:
                results.append({
                    'table': table,
                    'status': 'PASSED',
                    'count': source_count
                })
        
        return results
```

---

## 7. 风险评估与应对措施

### 7.1 风险矩阵

| 风险类型 | 风险描述 | 可能性 | 影响 | 风险等级 | 应对措施 |
|---------|---------|--------|------|---------|---------|
| 业务中断 | 迁移导致服务不可用 | 中 | 极高 | 🔴 高 | 双轨运行、灰度发布 |
| 数据丢失 | 数据迁移过程中丢失 | 低 | 极高 | 🔴 高 | 多重备份、实时校验 |
| 功能缺失 | 部分功能未迁移 | 中 | 高 | 🔴 高 | 功能清单核对、测试覆盖 |
| 性能下降 | 新系统性能不如旧系统 | 中 | 中 | 🟡 中 | 性能测试、优化预案 |
| 认证失败 | JWT认证机制问题 | 中 | 高 | 🟡 中 | 双轨认证、充分测试 |
| 兼容问题 | 前后端接口不兼容 | 高 | 中 | 🟡 中 | 兼容层、并行测试 |
| 团队风险 | 关键人员离职 | 低 | 高 | 🟡 中 | 文档完善、知识共享 |

### 7.2 详细应对措施

#### 7.2.1 业务中断风险应对

```
应对措施:
┌─────────────────────────────────────────────────────────────┐
│  1. 双轨运行                                                 │
│     ├── 旧系统保持运行                                       │
│     ├── 新系统并行开发                                       │
│     └── 随时可切回旧系统                                     │
│                                                             │
│  2. 灰度发布                                                 │
│     ├── 10% 流量测试                                        │
│     ├── 50% 流量验证                                        │
│     └── 100% 全量切换                                       │
│                                                             │
│  3. 分时段迁移                                               │
│     ├── 选择业务低峰期                                      │
│     ├── 避开月底/年底                                       │
│     └── 提前通知用户                                        │
│                                                             │
│  4. 快速回滚                                                 │
│     ├── 回滚时间 < 10分钟                                   │
│     ├── 一键切换脚本                                        │
│     └── 自动化回滚流程                                      │
└─────────────────────────────────────────────────────────────┘
```

#### 7.2.2 数据安全风险应对

```
应对措施:
┌─────────────────────────────────────────────────────────────┐
│  1. 多重备份                                                 │
│     ├── 全量备份 (每日)                                     │
│     ├── 增量备份 (每小时)                                   │
│     ├── 实时复制 (主从)                                     │
│     └── 异地备份 (灾备)                                     │
│                                                             │
│  2. 数据校验                                                 │
│     ├── 迁移前校验                                          │
│     ├── 迁移中监控                                          │
│     └── 迁移后验证                                          │
│                                                             │
│  3. 回滚能力                                                 │
│     ├── 保留原数据                                          │
│     ├── 快速恢复脚本                                        │
│     └── 数据回滚测试                                        │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 应急响应流程

```
应急响应流程:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  发现问题 (5分钟内)                                          │
│      │                                                      │
│      ▼                                                      │
│  评估影响 (10分钟内)                                         │
│      │                                                      │
│      ├── 影响小 → 记录问题，继续观察                        │
│      │                                                      │
│      └── 影响大 → 立即响应                                  │
│              │                                              │
│              ▼                                              │
│          决策会议 (15分钟内)                                 │
│              │                                              │
│              ├── 修复问题                                   │
│              │       │                                      │
│              │       ▼                                      │
│              │   测试验证                                   │
│              │       │                                      │
│              │       └── 通过 → 继续运行                    │
│              │                                              │
│              └── 回滚系统                                   │
│                      │                                      │
│                      ▼                                      │
│                  执行回滚 (10分钟内)                         │
│                      │                                      │
│                      ▼                                      │
│                  验证恢复                                   │
│                      │                                      │
│                      ▼                                      │
│                  通知用户                                   │
│                                                             │
│  总响应时间目标: < 30分钟                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. 回滚机制设计

### 8.1 回滚触发条件

```
自动触发条件:
┌─────────────────────────────────────────────────────────────┐
│  条件                    │ 阈值           │ 触发动作       │
├─────────────────────────┼───────────────┼───────────────┤
│ 错误率                  │ > 5%          │ 自动告警      │
│ 错误率                  │ > 10%         │ 自动回滚      │
│ 响应时间 P99            │ > 2000ms      │ 自动告警      │
│ 响应时间 P99            │ > 5000ms      │ 自动回滚      │
│ 数据库连接失败          │ > 3次/分钟    │ 自动回滚      │
│ 认证失败率              │ > 20%         │ 自动回滚      │
└─────────────────────────────────────────────────────────────┘

手动触发条件:
├── 发现严重功能缺陷
├── 数据一致性问题
├── 安全漏洞
└── 业务部门要求
```

### 8.2 回滚方案

#### 8.2.1 应用层回滚

```bash
#!/bin/bash
# rollback_app.sh - 应用回滚脚本

set -e

echo "[$(date)] Starting rollback..."

# 1. 切换 Nginx 到旧系统
echo "[$(date)] Switching Nginx to old system..."
sudo cp /etc/nginx/conf.d/erp_old.conf /etc/nginx/conf.d/erp.conf
sudo nginx -s reload

# 2. 停止 FastAPI 服务
echo "[$(date)] Stopping FastAPI service..."
sudo systemctl stop fastapi-service

# 3. 启动 Flask 服务 (如果未运行)
echo "[$(date)] Starting Flask service..."
sudo systemctl start flask-service

# 4. 验证服务状态
echo "[$(date)] Verifying service status..."
curl -f http://localhost:5001/health || exit 1

# 5. 通知团队
echo "[$(date)] Sending notification..."
curl -X POST $WEBHOOK_URL -d '{"text": "Rollback completed"}'

echo "[$(date)] Rollback completed successfully!"
```

#### 8.2.2 数据库回滚

```bash
#!/bin/bash
# rollback_db.sh - 数据库回滚脚本

set -e

BACKUP_FILE=$1
DB_NAME="erp"
DB_USER="root"
DB_PASS="password"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file>"
    exit 1
fi

echo "[$(date)] Starting database rollback..."

# 1. 停止应用服务
echo "[$(date)] Stopping application services..."
sudo systemctl stop flask-service
sudo systemctl stop fastapi-service

# 2. 备份当前数据
echo "[$(date)] Backing up current data..."
mysqldump -u$DB_USER -p$DB_PASS $DB_NAME | gzip > /tmp/pre_rollback_$(date +%Y%m%d_%H%M%S).sql.gz

# 3. 恢复备份数据
echo "[$(date)] Restoring backup data..."
gunzip < $BACKUP_FILE | mysql -u$DB_USER -p$DB_PASS $DB_NAME

# 4. 验证数据
echo "[$(date)] Verifying data..."
TABLES=$(mysql -u$DB_USER -p$DB_PASS -N -e "SHOW TABLES" $DB_NAME)
for TABLE in $TABLES; do
    COUNT=$(mysql -u$DB_USER -p$DB_PASS -N -e "SELECT COUNT(*) FROM $TABLE" $DB_NAME)
    echo "  $TABLE: $COUNT records"
done

# 5. 启动应用服务
echo "[$(date)] Starting application services..."
sudo systemctl start flask-service

echo "[$(date)] Database rollback completed!"
```

### 8.3 回滚演练计划

| 演练时间 | 演练内容 | 参与人员 | 预期结果 |
|---------|---------|---------|---------|
| 第4周末 | 应用回滚演练 | 开发、运维 | 10分钟内完成 |
| 第8周末 | 数据库回滚演练 | DBA、运维 | 30分钟内完成 |
| 第12周末 | 全流程回滚演练 | 全员 | 30分钟内完成 |

---

## 9. 系统验证与性能测试计划

### 9.1 功能验证计划

#### 9.1.1 功能测试清单

| 模块 | 测试项 | 测试用例数 | 优先级 |
|-----|-------|-----------|-------|
| 认证授权 | 登录、登出、权限检查 | 20 | P0 |
| 产品管理 | 增删改查、搜索、导入导出 | 30 | P0 |
| 订单管理 | 增删改查、状态流转、审批 | 40 | P0 |
| 库存管理 | 入库、出库、盘点、调拨 | 35 | P0 |
| 用户管理 | 增删改查、权限分配 | 20 | P1 |
| 报表统计 | 各类报表生成、导出 | 15 | P1 |
| 批量操作 | 批量导入、批量更新 | 10 | P1 |
| **合计** | - | **170** | - |

#### 9.1.2 测试用例模板

```python
# tests/test_products.py

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

class TestProductAPI:
    """产品API测试"""
    
    def test_list_products_success(self, auth_headers):
        """测试获取产品列表 - 成功"""
        response = client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_create_product_success(self, auth_headers):
        """测试创建产品 - 成功"""
        product_data = {
            "name": "测试产品",
            "barcode": "1234567890",
            "initial_stock": 100
        }
        response = client.post(
            "/api/v1/products",
            json=product_data,
            headers=auth_headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == product_data["name"]
    
    def test_create_product_duplicate_name(self, auth_headers):
        """测试创建产品 - 名称重复"""
        # 先创建一个产品
        product_data = {"name": "重复产品"}
        client.post("/api/v1/products", json=product_data, headers=auth_headers)
        
        # 再创建同名产品
        response = client.post(
            "/api/v1/products",
            json=product_data,
            headers=auth_headers
        )
        assert response.status_code == 400
    
    def test_update_product_success(self, auth_headers, test_product):
        """测试更新产品 - 成功"""
        update_data = {"name": "更新后的名称"}
        response = client.put(
            f"/api/v1/products/{test_product.id}",
            json=update_data,
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == update_data["name"]
    
    def test_delete_product_success(self, auth_headers, test_product):
        """测试删除产品 - 成功"""
        response = client.delete(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        # 验证已删除
        response = client.get(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers
        )
        assert response.status_code == 404
```

### 9.2 性能测试计划

#### 9.2.1 性能测试目标

| 指标 | 当前值 | 目标值 | 测试方法 |
|-----|-------|-------|---------|
| API P50响应时间 | 150ms | <100ms | 压力测试 |
| API P99响应时间 | 500ms | <300ms | 压力测试 |
| 并发处理能力 | 100 req/s | >200 req/s | 并发测试 |
| 错误率 | 0.5% | <0.1% | 稳定性测试 |
| 内存使用 | 512MB | <400MB | 资源监控 |

#### 9.2.2 压力测试脚本

```python
# tests/performance/locustfile.py

from locust import HttpUser, task, between
import random

class ERPUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """登录获取Token"""
        response = self.client.post("/api/v1/auth/login", json={
            "username": "test_user",
            "password": "test_password"
        })
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
    
    @task(10)
    def list_products(self):
        """查询产品列表 - 高频操作"""
        self.client.get("/api/v1/products", headers=self.headers)
    
    @task(5)
    def search_products(self):
        """搜索产品 - 中频操作"""
        keyword = f"产品{random.randint(1, 100)}"
        self.client.get(
            f"/api/v1/products/search?keyword={keyword}",
            headers=self.headers
        )
    
    @task(3)
    def create_order(self):
        """创建订单 - 中频操作"""
        self.client.post("/api/v1/orders", json={
            "product_id": random.randint(1, 100),
            "quantity": random.randint(1, 10)
        }, headers=self.headers)
    
    @task(2)
    def get_reports(self):
        """获取报表 - 低频操作"""
        self.client.get("/api/v1/reports/daily", headers=self.headers)
```

#### 9.2.3 性能测试场景

| 场景 | 并发用户 | 持续时间 | 目标 |
|-----|---------|---------|------|
| 基准测试 | 10 | 5分钟 | 建立基线 |
| 负载测试 | 50 | 30分钟 | 验证正常负载 |
| 压力测试 | 100 | 30分钟 | 验证峰值负载 |
| 稳定性测试 | 30 | 4小时 | 验证长时间运行 |
| 极限测试 | 200 | 10分钟 | 找到系统极限 |

### 9.3 安全测试计划

#### 9.3.1 安全测试项

| 测试项 | 测试内容 | 工具 |
|-------|---------|------|
| 认证测试 | JWT Token安全性 | 手动测试 |
| 授权测试 | 权限边界检查 | 手动测试 |
| SQL注入 | 参数化查询验证 | SQLMap |
| XSS攻击 | 输入过滤验证 | OWASP ZAP |
| CSRF | Token验证 | 手动测试 |
| 敏感信息泄露 | 日志、响应检查 | 手动测试 |

### 9.4 验收标准

```
验收标准:
┌─────────────────────────────────────────────────────────────┐
│  功能验收                                                    │
│  ├── 所有测试用例通过率 ≥ 99%                               │
│  ├── P0级缺陷数 = 0                                         │
│  └── P1级缺陷数 ≤ 3                                         │
│                                                             │
│  性能验收                                                    │
│  ├── API P50响应时间 < 100ms                                │
│  ├── API P99响应时间 < 300ms                                │
│  ├── 并发处理能力 > 200 req/s                               │
│  └── 错误率 < 0.1%                                          │
│                                                             │
│  安全验收                                                    │
│  ├── 无高危安全漏洞                                         │
│  ├── 认证授权机制正确                                       │
│  └── 敏感数据加密存储                                       │
│                                                             │
│  数据验收                                                    │
│  ├── 数据完整性 100%                                        │
│  ├── 数据一致性验证通过                                     │
│  └── 回滚测试通过                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 10. 项目组织与时间计划

### 10.1 项目组织架构

```
项目组织架构:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                    项目指导委员会                            │
│                    (管理层代表)                              │
│                          │                                  │
│                          ▼                                  │
│                      项目经理                                │
│                          │                                  │
│            ┌─────────────┼─────────────┐                   │
│            ▼             ▼             ▼                   │
│      ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│      │ 后端组   │  │ 前端组   │  │ 测试组   │             │
│      │          │  │          │  │          │             │
│      │ 架构师   │  │ 前端开发 │  │ 测试工程师│             │
│      │ 后端开发 │  │          │  │          │             │
│      └──────────┘  └──────────┘  └──────────┘             │
│                          │                                  │
│                          ▼                                  │
│                      运维支持                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 人员配置

| 角色 | 人数 | 职责 | 投入时间 |
|-----|------|------|---------|
| 项目经理 | 1 | 项目管理、协调 | 全程 |
| 架构师 | 1 | 架构设计、技术决策 | 前8周 |
| 后端开发 | 2 | API开发、服务集成 | 全程 |
| 前端开发 | 1 | 前端适配 | 第11-14周 |
| 测试工程师 | 1 | 测试、验收 | 第13-16周 |
| 运维工程师 | 1 | 环境部署、监控 | 全程 |

### 10.3 时间计划

```
甘特图:
┌─────────────────────────────────────────────────────────────┐
│ 任务                    │ 第1-4周 │第5-8周 │第9-12周│第13-16周│
├─────────────────────────┼────────┼────────┼────────┼────────┤
│ 准备阶段                │ ████   │        │        │        │
│ 基础设施搭建            │ ████   │        │        │        │
│ 核心API迁移             │        │ ████████│        │        │
│ 扩展API迁移             │        │        │ ████████│        │
│ 前端适配                │        │        │   ████ │        │
│ 集成测试                │        │        │        │ ████   │
│ 灰度发布                │        │        │        │   ████ │
├─────────────────────────┼────────┼────────┼────────┼────────┤
│ 里程碑                  │ M1     │ M2     │ M3     │ M4     │
└─────────────────────────────────────────────────────────────┘

里程碑:
├── M1 (第4周): 基础设施搭建完成，认证系统升级完成
├── M2 (第8周): 核心API迁移完成，单元测试通过
├── M3 (第12周): 所有API迁移完成，前端适配完成
└── M4 (第16周): 测试验收通过，全量切换完成
```

### 10.4 预算估算

| 项目 | 费用 | 说明 |
|-----|------|------|
| 人力成本 | 25万元 | 6人 × 4个月 |
| 服务器资源 | 2万元 | 测试环境、灰度环境 |
| 第三方服务 | 0.5万元 | 监控服务 |
| 培训费用 | 0.5万元 | FastAPI培训 |
| 风险预留 | 2万元 | 10%风险预算 |
| **合计** | **30万元** | - |

---

## 附录

### A. 迁移检查清单

```
迁移前检查:
□ 数据库完整备份
□ 应用代码备份
□ 配置文件备份
□ 回滚脚本准备
□ 监控告警配置
□ 团队培训完成
□ 文档编写完成
□ 测试用例准备

迁移中检查:
□ 服务状态监控
□ 错误日志监控
□ 数据一致性检查
□ 性能指标监控
□ 用户反馈收集

迁移后检查:
□ 功能验证完成
□ 性能测试通过
□ 安全测试通过
□ 数据验证通过
□ 用户验收通过
□ 文档更新完成
```

### B. 联系人列表

| 角色 | 姓名 | 联系方式 |
|-----|------|---------|
| 项目经理 | - | - |
| 架构师 | - | - |
| 后端负责人 | - | - |
| 前端负责人 | - | - |
| 测试负责人 | - | - |
| 运维负责人 | - | - |

### C. 相关文档

| 文档 | 位置 |
|-----|------|
| 技术架构设计 | docs/architecture.md |
| API接口文档 | docs/api.md |
| 数据库设计 | docs/database.md |
| 部署手册 | docs/deployment.md |
| 运维手册 | docs/operations.md |

---

**方案制定日期**: 2026-04-09  
**方案版本**: v1.0  
**下次评审**: 根据项目进展定期评审  
**批准**: 待管理层审批
