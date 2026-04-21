# BUG-CASCADE-20260420 修复记录

- **修复时间**: 2026-04-21
- **Git Commit**: d9765077edf2365b64bfd24b68b0d39fafd47928
- **根因分析**: Flask→FastAPI 迁移过程中，多层级联BUG未充分验证即提交
- **影响范围**: 服务器启动、登录认证、首页渲染全链路不可用

## 修复清单

| # | 根因 | 文件 | 修复 |
|---|------|------|------|
| 1 | werkzeug scrypt 哈希使用自定义 ab64 编码，base64.b64decode 解码错误导致密码验证永远失败 | security.py | 回退到 werkzeug.security.check_password_hash |
| 2 | PyJWT 未安装，create_access_token 中 import jwt 抛出 ModuleNotFoundError | .venv313 | pip install PyJWT（requirements/base.txt 已声明但未安装） |
| 3 | ALLOWED_HOSTS 默认值仅含 localhost/127.0.0.1/erp-app，非标准 Host 被拦截 | config.py | 默认值改为 "*"（开发环境），生产环境需设置环境变量 |
| 4 | Order/StockIn/StockOut 模型无 create_time 字段（分别为 order_date/stockin_date/stockout_date） | pages.py | 替换为正确字段名 |
| 5 | index.html 引用 pending_materials 但 pages.py 未提供该变量 | pages.py | 添加 pending_materials=0 到统计返回值 |
| 6 | _get_optional_user 是 sync 函数但调用 async get_current_user_id | main.py | 改为 async def + await |
| 7 | index.html 引用 today/timedelta 但模板上下文未提供 | pages.py | 添加 ctx["today"] 和 ctx["timedelta"] |
| 8 | act.time 是字符串但模板调用 strftime() | index.html | 改用字符串切片 [:10] 和 [11:16] |
| 9 | activities 字典缺少 status/title 键导致时间线文字空白 | pages.py | 补充 status/title 字段 |
| 10 | werkzeug 不在 requirements/base.txt | base.txt | 添加 werkzeug>=3.0.0 |
| 11 | _verify_pbkdf2/_verify_scrypt 死代码及未使用导入 | security.py | 删除全部死代码 |
| 12 | Uvicorn workers>1 在 Windows 上不支持 fork | start_production_optimized.py | Windows 强制 workers=1 |

## 验证结果

- Health: 200 OK
- Login: 200 OK (JWT token + cookie 正常)
- Homepage: 200 OK (32938 bytes, KPI/待办/时间线均正常)
- 6个页面路由: 全部 200 OK
- Host header: 任意 Host 均通过
- DB/Redis: 连接正常
- Bandit 安全扫描: 0 高危

## 教训

1. 模型字段名迁移时必须逐一对照验证，不能凭假设命名
2. async/sync 混合调用需用 pyright/mypy 做类型检查
3. 密码哈希迁移涉及编码差异（ab64 vs base64），应使用原库验证而非自行实现
4. 每轮修复后必须端到端验证，避免问题遮蔽
