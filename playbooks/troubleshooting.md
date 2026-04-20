# 故障排查手册

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
