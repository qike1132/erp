# BUG-MIGRATION-AUDIT-2026 修复记录

- **修复时间**: 2026-04-19
- **Git Commit**: d9765077edf2 (修复前基线)
- **根因分析**: Flask→FastAPI 全量迁移遗留 23+ 个缺陷，涵盖安全漏洞、事件循环阻塞、模板渲染崩溃、配置残留等
- **影响范围**: 全栈 — 认证/CSRF/数据库/模板/部署/测试

## 修复清单

### P0 (3项 — 阻断级)

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| P0-03 | index.html `session.get('username')` 导致首页崩溃 | 改为 `{{ username or '用户' }}` | templates/index.html:10 |
| P0-01 | werkzeug 哈希不兼容导致全量旧用户锁定 | 增加 pbkdf2/scrypt 验证 + 登录时自动迁移到 bcrypt | security.py, auth.py |
| P0-02 | 同步 DB 查询阻塞异步事件循环 | `get_current_user_id` 改为 async + `run_in_threadpool` 包装 | deps.py, main.py |

### P1 (5项 — 严重级)

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| P1-01 | CSRF cookie_secure 硬编码 False | 从环境变量 CSRF_COOKIE_SECURE 动态读取 | main.py:179 |
| P1-02 | 双层 CSRF 保护叠加冲突 | 移除自定义 Origin/Referer 中间件，保留 starlette-csrf | main.py |
| P1-03 | utils/ 9+ 文件 Flask 裸导入 | 全部添加 try/except ImportError 保护 | utils/*.py |
| P1-04 | JWT payload 冗余存储权限列表 | 仅保留 sub + username，权限通过 DB 实时查询 | auth.py:165-170 |
| P1-05 | FLASK_ENV 生产检查失效 | 改为 APP_ENV | config.py:97 |

### P2 (9项 — 重要级)

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| P2-01 | CORS 默认值含已移除的 5003 端口 | 移除 http://localhost:5003 | config.py:68 |
| P2-02 | utils/logger.py 期望 Flask app | setup_logging(app) 改为可选参数 | utils/logger.py:45 |
| P2-03 | alembic.ini 残留 flask_migrate | 移除 [logger_flask_migrate] 段 | migrations/alembic.ini |
| P2-04 | prometheus.yml flask job_name | 移除 Flask 指标采集任务 | config/prometheus.yml |
| P2-05 | test.txt 残留 pytest-flask | 移除 | requirements/test.txt:15 |
| P2-06 | tests/ 14 文件 Flask 导入 | 全部添加 try/except 保护 + 替换 werkzeug 为 security.py | tests/*.py |
| P2-07 | passlib 冗余依赖 | 移除 passlib[bcrypt]（security.py 仅用 bcrypt） | requirements/base.txt |
| P2-08 | dispose_async_engines 吞异常 | 添加日志记录 | database.py:121-123 |
| P2-09 | WebSocket query auth 过度捕获 | 合并为 (ValueError, KeyError, HTTPException) | main.py:350-353 |

### P3 (3项 — 次要级)

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| P3-01 | typing.List 应使用 list[str] | 移除 typing.List，使用内置类型 | config.py |
| P3-02 | SESSION_COOKIE_MAX_AGE Flask 命名 | 改为 COOKIE_MAX_AGE | config.py, auth.py |
| P3-03 | 数据库配置注释残留 Flask | 更新注释 | config.py |

## 验证结果

- Python 编译检查: 全部通过 (py_compile 0 errors)
- Linter 检查: 无警告
- 关键文件 7/7 验证项全部 PASS:
  1. fastapi_app/ 无 Flask/werkzeug/jose 导入
  2. templates/ 无 session/url_for/csrf_token 模式
  3. deps.py 使用 async + run_in_threadpool
  4. security.py 包含 needs_rehash + _verify_pbkdf2
  5. main.py 无自定义 csrf_protection 中间件
  6. auth.py JWT 仅含 sub + username
  7. config.py 使用 COOKIE_MAX_AGE + APP_ENV
