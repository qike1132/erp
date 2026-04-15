
# FastAPI 供应商汇总服务

## 概述

这是ERP系统的FastAPI微服务，专门处理采购中心的供应商汇总功能。

## 目录结构

```
fastapi_app/
├── __init__.py
├── main.py                    # FastAPI应用入口
├── api/
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       ├── router.py         # 路由汇总
│       └── endpoints/
│           ├── __init__.py
│           └── purchase_center.py  # 采购中心API
├── core/
│   ├── __init__.py
│   ├── config.py             # 配置管理
│   └── logger.py             # 日志配置
├── schemas/
│   ├── __init__.py
│   └── purchase.py           # Pydantic数据模型
├── services/
│   └── __init__.py
└── utils/
    └── __init__.py
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r fastapi_requirements.txt
```

### 2. 启动服务

```bash
# 开发模式（带热重载）
python -m fastapi_app.main

# 或者使用uvicorn直接启动
uvicorn fastapi_app.main:app --reload --host 0.0.0.0 --port 5002
```

### 3. 访问文档

启动后访问以下地址查看API文档：
- Swagger UI: http://localhost:5002/api/docs
- ReDoc: http://localhost:5002/api/redoc

## API接口

### 供应商汇总接口

**POST** `/api/v1/purchase-center/orders/supplier-summary-by-vendor`

按供应商维度汇总采购订单。

请求体：
```json
{
  "ids": [1, 2, 3],
  "format": "print"
}
```

响应：
```json
{
  "success": true,
  "suppliers": [...],
  "supplier_count": 2,
  "order_count": 3,
  "html": "&lt;html&gt;...&lt;/html&gt;"
}
```

### 演示接口

**GET** `/api/v1/purchase-center/orders/supplier-summary-demo`

返回模拟数据，用于测试。

### 健康检查

**GET** `/api/health`

检查服务状态。

## 与现有Flask系统集成

### 共享数据库连接

在实际使用中，需要配置与现有Flask系统共享的数据库会话。可以参考以下步骤：

1. 创建共享的数据库配置模块
2. 使用SQLAlchemy 2.0的异步会话
3. 在FastAPI中复用现有的模型定义

### 数据模型共享

当前实现为了保持独立性，保留了逻辑框架。在实际集成时：

```python
# 从现有Flask应用导入模型
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem

# 或者创建共享模型目录
from shared_models.purchase_order import PurchaseOrder, PurchaseOrderItem
```

## 配置

环境变量配置（参考 `.env` 文件）：

```env
# 数据库
DATABASE_URL=mysql+pymysql://user:pass@host:port/db

# Redis
REDIS_URL=redis://localhost:6379/0

# 安全
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

## 开发规范

### 保存规则

所有FastAPI API遵循以下保存规则：

1. **目录结构**：
   - 所有API路由放在 `fastapi_app/api/v1/endpoints/`
   - Pydantic模型放在 `fastapi_app/schemas/`
   - 业务逻辑放在 `fastapi_app/services/`
   - 工具函数放在 `fastapi_app/utils/`

2. **命名规范**：
   - 路由文件：模块名 + `.py`
   - 路由函数：动词 + 名词
   - Schema类：功能 + `Request`/`Response`

3. **代码规范**：
   - 使用类型提示
   - 使用Pydantic进行数据验证
   - 使用依赖注入进行权限检查
   - 统一的错误处理
   - 详细的日志记录

4. **API设计**：
   - RESTful风格
   - 版本化（/api/v1/）
   - 自动文档生成
   - 统一响应格式

## 下一步

1. 配置与现有Flask系统的数据库连接共享
2. 实现完整的权限依赖注入
3. 添加更多采购中心API
4. 编写单元测试
5. 配置CI/CD

