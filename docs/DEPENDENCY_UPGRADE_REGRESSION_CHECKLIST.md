# 依赖升级回归测试清单

> **关联变更**：P0-01 关键依赖安全漏洞升级  
> **版本变更**：
> - fastapi 0.136.0 → 0.137.1
> - python-multipart 0.0.26 → 0.0.32
> - PyJWT 2.12.1 → 2.13.0
> - redis[hiredis] 7.4.0 → 7.4.1
> - axios 1.7.9 → 1.18.0
> - Redis 服务端镜像 7-alpine → 7.4.9-alpine

## 一、自动检查项

| 检查项 | 命令 | 通过标准 |
|---|---|---|
| Python 语法检查 | `python -m py_compile fastapi_app/main.py` | EXIT=0 |
| Python 静态检查 | `python -m ruff check fastapi_app/ --select E9,F4,F8,F6` | 无新增错误 |
| 依赖漏洞扫描 | `python -m pip_audit --desc` | 无 high/critical 漏洞 |
| 前端类型检查 | `cd frontend-vite && npm run type-check` | EXIT=0 |
| 前端构建 | `cd frontend-vite && npm run build` | EXIT=0 |
| 前端漏洞扫描 | `cd frontend-vite && npm audit --audit-level=high` | 无 high/critical 漏洞 |

## 二、核心功能回归测试

### 2.1 认证与授权（FastAPI / Starlette / PyJWT）

| # | 测试场景 | 操作步骤 | 预期结果 |
|---|---|---|---|
| 1 | 用户登录 | POST /api/v1/auth/login | 返回 access_token 和 refresh_token |
| 2 | Token 刷新 | POST /api/v1/auth/refresh | 返回新的 access_token |
| 3 | 无效 Token 拒绝 | 使用过期/伪造 Token 访问受保护接口 | 返回 401 Unauthorized |
| 4 | 权限控制 | 普通用户访问管理员接口 | 返回 403 Forbidden |
| 5 | JWT 吊销 | 登出后访问原 Token | 返回 401 |
| 6 | 密码复杂度校验 | 使用弱密码注册 | 返回 422 并提示规则 |

### 2.2 文件上传（python-multipart / Starlette）

| # | 测试场景 | 操作步骤 | 预期结果 |
|---|---|---|---|
| 7 | 正常上传图片 | POST 产品/皮套图片 | 返回文件 URL，文件可访问 |
| 8 | 上传 Excel | POST 批量导入订单/库存 | 正确解析并返回结果 |
| 9 | 上传过大文件 | 上传超过限制的文件 | 返回 413 或友好错误 |
| 10 | 非法文件类型 | 上传非白名单文件 | 返回 422 或 400 |

### 2.3 WebSocket 与实时通知（FastAPI / Starlette）

| # | 测试场景 | 操作步骤 | 预期结果 |
|---|---|---|---|
| 11 | WebSocket 连接 | 建立 /api/v1/ws/notifications 连接 | 连接成功，收到 welcome 消息 |
| 12 | 心跳机制 | 连接后等待 30/60 秒 | 自动保活，无异常断开 |
| 13 | 订单状态变更通知 | 修改订单状态 | WebSocket 客户端收到通知 |
| 14 | 多端登录 | 同一用户多浏览器登录 | 各自收到通知，无冲突 |

### 2.4 缓存与会话（Redis 客户端 + 服务端）

| # | 测试场景 | 操作步骤 | 预期结果 |
|---|---|---|---|
| 15 | Redis 连接 | 启动后端服务 | 无 Redis 连接错误 |
| 16 | 缓存读取 | 重复访问同一查询接口 | 第二次命中缓存，响应更快 |
| 17 | 缓存失效 | 数据修改后访问原缓存 | 返回最新数据 |
| 18 | Celery 任务 | 提交异步任务（如导出） | 任务成功执行并返回结果 |
| 19 | Pub/Sub 事件 | 触发领域事件 | 跨进程订阅者收到事件 |

### 2.5 HTTP 请求（axios）

| # | 测试场景 | 操作步骤 | 预期结果 |
|---|---|---|---|
| 20 | 正常 API 请求 | 登录后访问任意接口 | 请求成功，数据正确 |
| 21 | 请求/响应拦截 | Token 过期后自动刷新 | 刷新后重试原请求 |
| 22 | 错误处理 | 访问不存在接口 | 前端显示友好错误提示 |
| 23 | 文件下载 | 导出 Excel/PDF | 文件正常下载 |
| 24 | 超时处理 | 模拟慢网络 | 显示超时提示，无白屏 |

### 2.6 CORS 与中间件（FastAPI / Starlette）

| # | 测试场景 | 操作步骤 | 预期结果 |
|---|---|---|---|
| 25 | 跨域请求 | 前端调用后端 API | 预检请求通过 |
| 26 | 自定义请求头 | 上传时携带 X-Request-ID | 服务端正确接收 |
| 27 | 中间件日志 | 访问任意接口 | 日志格式正常，无异常 |

## 三、回归测试执行记录

| 日期 | 执行人 | 环境 | 自动检查 | 核心功能 | 备注 |
|---|---|---|---|---|---|
| 2026-06-18 | AI 助手 | 本地 | 已通过 | 待人工 | 自动检查项全部通过 |
| | | | | | |

## 四、异常处理

若在回归测试中发现异常：

1. 立即记录异常现象、复现步骤、错误日志
2. 回滚相关依赖版本（保留 `requirements/base.txt.bak` 和 `package-lock.json.bak`）
3. 在 Issue 跟踪系统中创建缺陷单
4. 修复后重新执行本清单

## 五、参考链接

- [requirements/base.txt](file:///d:/erp_system/requirements/base.txt)
- [frontend-vite/package.json](file:///d:/erp_system/frontend-vite/package.json)
- [docker-compose.yml](file:///d:/erp_system/docker-compose.yml)
- [k8s/infra.yaml](file:///d:/erp_system/k8s/infra.yaml)
