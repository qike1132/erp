# 性能优化配置指南

## 概述
本文档说明如何启用和配置ERP系统的性能优化功能。

## 1. 测试覆盖率门禁

### 配置说明
测试覆盖率门禁已在 `pytest.ini` 中配置：
- **最小覆盖率**: 70%
- **分支覆盖**: 已启用
- **排除目录**: tests, migrations, __pycache__

### 使用方法
```bash
# 运行测试并检查覆盖率
pytest tests/ -v --cov=. --cov-report=html

# 查看覆盖率报告
open htmlcov/index.html
```

### CI/CD集成
覆盖率门禁会在CI/CD流程中自动执行，如果覆盖率低于70%，构建将失败。

---

## 2. Redis缓存系统

### 安装依赖
```bash
pip install redis
```

### 配置Redis
在 `.env` 文件中添加：
```env
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=your_password
CACHE_TYPE=redis
CACHE_DEFAULT_TIMEOUT=300
```

### 在应用中启用
在 `app/__init__.py` 中添加：
```python
from utils.redis_cache import init_redis_cache

# 初始化Redis缓存
init_redis_cache(app)
```

### 使用缓存装饰器
```python
from utils.redis_cache import redis_cached, cache_invalidate

# 缓存函数结果
@redis_cached('product_list', timeout=300)
def get_products():
    return Product.query.all()

# 清除缓存
@cache_invalidate('product_list')
def update_product(product_id, data):
    # 更新产品逻辑
    pass
```

### 预定义缓存配置
系统已预定义以下缓存键：
- `product_list`: 产品列表（5分钟）
- `product_detail:{id}`: 产品详情（10分钟）
- `stock_summary`: 库存摘要（1分钟）
- `order_list:{user_id}`: 用户订单列表（3分钟）
- `user_permissions:{user_id}`: 用户权限（30分钟）

---

## 3. 数据库查询优化

### 已添加的索引
以下索引已在数据库迁移中创建：

```sql
-- 产品表索引
CREATE INDEX idx_product_name ON product(name);
CREATE INDEX idx_product_barcode ON product(barcode);

-- 订单表索引
CREATE INDEX idx_order_date ON `order`(order_date);
CREATE INDEX idx_order_user ON `order`(user_id);
CREATE INDEX idx_order_status ON `order`(status);

-- 库存表索引
CREATE INDEX idx_stock_product ON inventory_log(product_id);
CREATE INDEX idx_stock_date ON inventory_log(created_at);
```

### 使用joinedload优化关联查询
```python
from sqlalchemy.orm import joinedload

# 优化前（N+1查询）
orders = Order.query.all()
for order in orders:
    print(order.product.name)  # 每次都会查询数据库

# 优化后（一次查询）
orders = Order.query.options(joinedload(Order.product)).all()
for order in orders:
    print(order.product.name)  # 不会额外查询
```

### 查询优化建议
1. **使用索引**: 确保WHERE、JOIN、ORDER BY字段有索引
2. **避免SELECT ***: 只查询需要的字段
3. **使用分页**: 大数据集使用paginate()
4. **批量操作**: 使用bulk操作替代循环

---

## 4. 请求压缩中间件

### 配置说明
在 `app/__init__.py` 中添加：
```python
from utils.compression import init_compression

# 初始化压缩中间件
init_compression(app)
```

### 配置选项
在 `config.py` 中添加：
```python
# 压缩配置
COMPRESSION_MIN_SIZE = 500  # 最小压缩大小（字节）
COMPRESSION_LEVEL = 6       # 压缩级别（1-9，6为推荐值）
```

### 支持的压缩类型
- text/html
- text/css
- text/javascript
- application/javascript
- application/json
- application/xml
- text/xml
- text/plain

### 效果
- **压缩率**: 通常可减少60-80%的传输大小
- **性能提升**: 减少网络传输时间，提升页面加载速度

---

## 5. CDN配置

### 配置说明
在 `.env` 文件中添加：
```env
CDN_DOMAIN=cdn.yourdomain.com
CDN_HTTPS=true
CDN_TIMESTAMP=true
CDN_DEBUG=false
```

### 在应用中启用
在 `app/__init__.py` 中添加：
```python
from utils.cdn_config import init_cdn

# 初始化CDN
init_cdn(app)
```

### 在模板中使用
```html
<!-- 使用CDN URL -->
<link rel="stylesheet" href="{{ cdn_url('static', 'css/style.css') }}">
<script src="{{ cdn_url('static', 'js/app.js') }}"></script>

<!-- 或使用简化方法 -->
<link rel="stylesheet" href="{{ static_url('css/style.css') }}">
<script src="{{ static_url('js/app.js') }}"></script>
```

### CDN缓存策略
建议配置以下缓存规则：
- **静态文件**: 缓存1年（带版本号）
- **图片**: 缓存30天
- **CSS/JS**: 缓存7天（带版本号）

---

## 6. 完整集成示例

### app/__init__.py
```python
from flask import Flask
from utils.redis_cache import init_redis_cache
from utils.compression import init_compression
from utils.cdn_config import init_cdn

def create_app(config_name='default'):
    app = Flask(__name__)
    
    # 加载配置
    app.config.from_object(config[config_name])
    
    # 初始化扩展
    db.init_app(app)
    
    # 性能优化初始化
    init_redis_cache(app)    # Redis缓存
    init_compression(app)     # 请求压缩
    init_cdn(app)            # CDN支持
    
    # 注册蓝图
    from app.routes import main, api, user
    app.register_blueprint(main)
    app.register_blueprint(api)
    app.register_blueprint(user)
    
    return app
```

### config.py
```python
class Config:
    # Redis配置
    REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
    REDIS_DB = int(os.environ.get('REDIS_DB', 0))
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')
    CACHE_TYPE = 'redis'
    CACHE_DEFAULT_TIMEOUT = 300
    
    # 压缩配置
    COMPRESSION_MIN_SIZE = 500
    COMPRESSION_LEVEL = 6
    
    # CDN配置
    CDN_DOMAIN = os.environ.get('CDN_DOMAIN', '')
    CDN_HTTPS = True
    CDN_TIMESTAMP = True
    CDN_DEBUG = False
```

---

## 7. 性能监控

### 监控指标
建议监控以下指标：
- **响应时间**: 平均响应时间 < 200ms
- **缓存命中率**: > 80%
- **数据库查询时间**: < 50ms
- **内存使用**: < 500MB
- **CPU使用**: < 50%

### 监控工具
- **Flask-DebugToolbar**: 开发环境性能分析
- **New Relic**: 生产环境APM监控
- **Redis监控**: 使用Redis命令 `INFO` 和 `MONITOR`
- **数据库监控**: 使用MySQL慢查询日志

---

## 8. 性能测试

### 运行性能测试
```bash
# 运行性能基准测试
pytest tests/performance/test_performance.py -v

# 运行负载测试（需要k6）
k6 run tests/performance/load_test.js
```

### 性能基准
- **登录响应**: < 100ms
- **产品查询**: < 50ms
- **订单创建**: < 150ms
- **页面加载**: < 200ms
- **并发用户**: 支持100+并发

---

## 9. 故障排查

### Redis连接失败
```bash
# 检查Redis服务状态
redis-cli ping

# 检查Redis配置
redis-cli config get maxmemory
```

### 缓存未生效
1. 检查Redis连接是否正常
2. 检查缓存键是否正确
3. 检查缓存是否被清除

### 压缩未生效
1. 检查Accept-Encoding头是否包含gzip
2. 检查响应大小是否超过最小阈值
3. 检查Content-Type是否在支持列表中

### CDN未生效
1. 检查CDN_DOMAIN配置是否正确
2. 检查CDN服务是否正常
3. 检查DNS解析是否正确

---

## 10. 最佳实践

1. **缓存策略**
   - 热点数据优先缓存
   - 设置合理的过期时间
   - 及时清除过期缓存

2. **数据库优化**
   - 定期分析慢查询
   - 合理使用索引
   - 避免N+1查询

3. **压缩配置**
   - 压缩级别设置为6（平衡压缩率和CPU）
   - 最小大小设置为500字节
   - 只压缩文本类型内容

4. **CDN使用**
   - 静态文件使用CDN
   - 动态内容不使用CDN
   - 配置合理的缓存策略

---

**更新时间**: 2026-03-28  
**版本**: 1.0.0
