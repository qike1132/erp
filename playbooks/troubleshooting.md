# 故障排查手册

## 登录后首页 500 — Jinja2 UndefinedError / AttributeError

### 症状
- 登录成功但访问首页返回 500
- 日志显示 `UndefinedError: 'pending_materials' is undefined` 或 `AttributeError: 'Order' has no attribute 'create_time'`

### 根因
- 模型字段名迁移错误：Order 用 `order_date`（非 `create_time`），StockIn 用 `stockin_date`，StockOut 用 `stockout_date`
- 模板变量未在路由上下文中提供

### 解决
- 参考 `docs/bugs/BUG-CASCADE-20260420.md`

## 登录返回 401 — werkzeug scrypt 哈希验证失败

### 症状
- 正确密码登录返回 401 "未登录"
- 数据库中密码哈希以 `scrypt:` 开头

### 根因
- werkzeug 使用自定义 ab64 编码（非标准 base64），自行实现的 `_verify_scrypt` 用 `base64.b64decode` 解码错误

### 解决
- 使用 `werkzeug.security.check_password_hash` 作为回退

## 服务器启动报 Invalid host header

### 症状
- 浏览器访问显示 "Invalid host header"

### 根因
- TrustedHostMiddleware 的 ALLOWED_HOSTS 默认值不包含当前访问主机名

### 解决
- 设置 `ALLOWED_HOSTS` 环境变量，或开发环境默认 `"*"` 允许所有主机

## 采购订单接口 500 AttributeError: 'PurchaseOrder' has no attribute 'total_amount'

### 症状
- 采购订单列表/详情/已完成列表接口返回 500
- 日志显示 `AttributeError: 'PurchaseOrder' object has no attribute 'total_amount'`

### 根因
PurchaseOrder 模型无 `total_amount` 列，service 层错误访问了不存在的属性

### 解决
使用 `sum(item.total_price for item in order.items)` 动态计算总金额
- 参考: docs/bugs/BUG-REGRESSION-20260421.md

## 采购单创建后 created_by 为 NULL

### 症状
- 创建采购单后数据库 created_by 字段为 NULL

### 根因
Service 层使用了不存在的 `creator_id` 而非模型定义的 `created_by`

### 解决
将 `creator_id=user_id` 改为 `created_by=user_id`
- 参考: docs/bugs/BUG-REGRESSION-20260421.md

## JavaScript TypeError: Cannot read properties of null

### 症状
- 浏览器控制台报 `TypeError: Cannot read properties of null (reading 'style'/'textContent'/'querySelector')`
- 页面功能局部失效（搜索/分页/筛选不工作）
- 通常在模板修改后出现

### 排查步骤
1. 打开浏览器 DevTools → Console，定位报错行号
2. 找到 `document.getElementById('xxx')` 调用，确认目标 HTML 元素是否存在
3. 检查最近是否修改/删除/重命名了模板中的对应 `id` 属性

### 解决方案
所有 `getElementById` 结果在使用前必须做 null 检查：
```javascript
// 错误写法
document.getElementById('myEl').style.display = 'none';

// 正确写法 1：辅助函数
const el = (id) => document.getElementById(id);
if (el('myEl')) el('myEl').style.display = 'none';

// 正确写法 2：变量 + null guard
const myEl = document.getElementById('myEl');
if (myEl) myEl.style.display = 'none';
```

### 通用规则
- `getElementById` 返回 `null` 时，后续的 `.style`/`.textContent`/`.querySelector` 等属性访问会导致 TypeError
- HTML `id` 在文档中必须唯一，互斥 Jinja2 分支中的重复 id 虽然运行时不冲突，但仍违反规范
- 服务端分页替换客户端分页时，必须同步清理 JS 中的客户端分页代码，否则产生死代码和 null 引用

---

## API 响应缓慢 - N+1 查询问题

### 症状
- 页面加载数秒，API 返回 200 但响应慢
- 数据库连接池快速耗尽
- SQLAlchemy 日志显示大量 SELECT 语句

### 排查步骤
1. 启用 SQLAlchemy echo 日志：在 `.env` 设置 `SQL_ECHO=true`
2. 观察 SQL 输出：如果同一类型 SELECT 大量重复，确认 N+1 问题
3. 定位触发 lazy load 的代码：检查循环内访问 relationship 属性

### 解决方案
在查询时使用 `selectinload` 或 `joinedload` 预加载关联关系：
```python
query = db.query(Product).options(
    selectinload(Product.material),
    selectinload(Product.fabrics),
)
```

### 通用规则
- 任何在循环中访问 ORM relationship 的场景，必须使用 eager loading
- `selectinload` 适用于集合关系（一对多），`joinedload` 适用于标量关系（多对一）
- 优先使用 `selectinload` 避免 JOIN 导致的笛卡尔积

## .xls 文件上传被拒绝

### 症状
- 上传 .xls 文件时返回错误：".xls 格式已不再支持（安全原因），请将文件另存为 .xlsx 格式后重新上传"

### 根因
- xlrd 1.2.0 存在 CVE-2019-19276 (XXE 漏洞)，已在本次修复中移除
- 系统仅支持 .xlsx 格式（使用 openpyxl）

### 解决
- 将 .xls 文件在 Excel 中另存为 .xlsx 格式后重新上传

## Host Header 导致 400 Bad Request

### 症状
- 访问系统时返回 400 错误，提示 Host 不合法

### 根因
- FastAPI TrustedHostMiddleware 拒绝 Host 不在 ALLOWED_HOSTS 中的请求
- Nginx default_server 拒绝未知 Host (返回 444 断开连接)

### 解决
- 在 .env 或环境变量中设置 `ALLOWED_HOSTS=your-domain.com,www.your-domain.com`
- 确保 Nginx 代理时 Host 头正确传递

## 旧密码无法验证（bcrypt 迁移后）

### 症状
- 迁移后旧用户的密码验证失败

### 根因
- 旧密码使用 werkzeug (pbkdf2/scrypt) 哈希，新密码使用 bcrypt
- fastapi_app/core/security.py 的 verify_password 同时兼容两种格式

### 解决
- 正常情况下旧密码仍可验证（兼容逻辑）
- 用户修改密码后将自动升级为 bcrypt 哈希

## 服务器启动失败 - 端口 5002 被占用

### 症状
- 启动调试/生产模式时报 `[Errno 10048] 通常每个套接字地址只允许使用一次`
- 或报 `[WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试`

### 根因
- 旧 Python 进程仍在占用 5002 端口（未正常退出）
- Windows 上 Uvicorn `workers > 1` 不支持（无 fork），导致权限错误

### 解决
1. 查找占用端口的进程: `netstat -ano | findstr :5002`
2. 终止旧进程: `Stop-Process -Id <PID> -Force`
3. 重新启动服务器
4. Windows 环境下生产模式自动使用单 Worker（已内置检测）

## 导航链接 404 — Flask 端点名未映射为 FastAPI 路径

### 症状
- 首页侧边栏导航点击后返回 404
- 浏览器地址栏显示 `material.calculator`、`product.products`、`supplier.suppliers` 等 Flask 端点名格式

### 根因
- 数据库 `permission.url` 列存储的是 Flask `url_for` 端点名（如 `product.products`）
- `nav_context.py` 将 `item.url` 直接传给模板作为 `href`
- FastAPI 没有注册这些 dot-notation 路径，导致 404

### 解决
- `nav_context.py` 已添加 `FLASK_TO_FASTAPI_URL_MAP` 映射表，在构建导航数据时自动转换
- 服务启动时自动清除旧缓存（`invalidate_nav_cache()`），确保映射立即生效
- 若映射缺失新端点，在 `FLASK_TO_FASTAPI_URL_MAP` 字典中添加对应条目即可
