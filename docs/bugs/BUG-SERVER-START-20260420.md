# BUG-SERVER-START-20260420 修复记录

- **修复时间**: 2026-04-20
- **Git Commit**: 当前分支 new-main
- **根因分析**: 服务器启动失败由 4 个独立问题共同导致：

## BUG 1: get_current_user 缺少 async 关键字 (P0 - 阻断性)
- **文件**: `fastapi_app/core/deps.py:76`
- **现象**: `SyntaxError: 'await' outside async function`
- **根因**: `def get_current_user(request: Request):` 使用了 `await run_in_threadpool()` 但函数定义缺少 `async` 关键字
- **修复**: 改为 `async def get_current_user(request: Request):`
- **连带修复**: `fastapi_app/main.py:513` 的 `_get_optional_user` 也需改为 `async def` 并使用 `await get_current_user(request)`

## BUG 2: CustomerOrder 导入不存在 (P0 - 阻断性)
- **文件**: `fastapi_app/services/order_service.py:19`
- **现象**: `ImportError: cannot import name 'CustomerOrder' from 'fastapi_app.shared_models'`
- **根因**: commit d976507 (1.4.1) 中错误添加了 `CustomerOrder` 导入，该模型从未定义过
- **修复**: 从导入列表中移除 `CustomerOrder`（该名称在模块内未被使用）

## BUG 3: TemplateResponse API 签名变更 (P0 - 功能性)
- **文件**: `fastapi_app/api/v1/endpoints/pages.py:91,168,178`
- **现象**: `TypeError: unhashable type: 'dict'` 导致所有页面返回 500
- **根因**: Starlette 新版 `TemplateResponse` 签名从 `(name, context)` 变为 `(request, name, context)`。旧调用 `TemplateResponse("login.html", ctx)` 将 ctx 字典误传为 `name` 参数，dict 作为 Jinja2 缓存键的一部分引发 TypeError
- **修复**: 3 处调用均添加 `request` 参数，如 `TemplateResponse(request, "login.html", ctx)`

## BUG 4: 缺失依赖 (P1 - 环境性)
- **现象**: `orjson` 和 `asyncmy` 未安装
- **根因**: 虚拟环境 `.venv313` 中缺少 `requirements/base.txt` 中声明的 `orjson` 和 `asyncmy`
- **修复**: `pip install orjson asyncmy`
- **影响**: 缺少 orjson 导致所有 API 响应 500；缺少 asyncmy 导致登录等异步 DB 接口不可用

## 验证结果
- L1 (单元): 模块导入、函数签名验证 PASS
- L2 (集成): 数据库连接 PASS，Redis 需认证（非阻断）
- L3 (契约): /api/health 200, /login 200, /api/docs 200, /api/openapi.json 200
- L4 (E2E): 登录 API 错误凭据返回 401 PASS
- L5 (安全): Bandit 扫描 0 HIGH, 17 MEDIUM, 456 LOW

## 影响范围
- 服务器完全无法启动（BUG 1+2 阻断模块导入）
- 服务器启动后页面全部 500（BUG 3）
- 异步 DB 功能不可用（BUG 4 asyncmy 缺失）
