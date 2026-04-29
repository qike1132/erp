# ERP系统环境配置指南

## 📋 环境说明

ERP系统支持两种运行环境：

### 🟢 开发环境 (Development)
- **用途**: 本地开发、调试、测试
- **特点**: 自动重载、详细错误信息、调试模式
- **启动**: `python run.py`
- **配置文件**: `.env.development`

### 🔴 生产环境 (Production)
- **用途**: 正式部署、生产运行
- **特点**: 高性能、高安全、稳定可靠
- **启动**: `python start_production.py`
- **配置文件**: `.env.production`

---

## 🚀 快速开始

### 方法1: 使用环境切换脚本（推荐）

```powershell
# 切换到开发环境
python switch_env.py development

# 切换到生产环境
python switch_env.py production

# 查看当前环境
python switch_env.py show
```

### 方法2: 手动切换

```powershell
# 切换到开发环境
copy .env.development .env

# 切换到生产环境
copy .env.production .env
```

---

## 📁 配置文件说明

### 配置文件列表

```
.env                 # 当前使用的配置文件
.env.development     # 开发环境配置模板
.env.production      # 生产环境配置模板
.env.backup          # 配置备份文件（自动生成）
```

---

## ⚙️ 环境配置对比

| 配置项 | 开发环境 | 生产环境 |
|--------|---------|---------|
| **FLASK_ENV** | development | production |
| **FLASK_DEBUG** | 1 | 0 |
| **DB_POOL_SIZE** | 10 | 20 |
| **DB_MAX_OVERFLOW** | 5 | 10 |
| **SESSION_COOKIE_SECURE** | false | true |
| **PREFERRED_URL_SCHEME** | http | https |
| **服务器** | Flask开发服务器 | Waitress生产服务器 |
| **线程数** | 单线程 | 8线程 |
| **自动重载** | ✅ 支持 | ❌ 不支持 |
| **错误详情** | ✅ 显示 | ❌ 隐藏 |

---

## 🎯 使用场景

### 开发环境适用场景

```
✅ 本地开发新功能
✅ 调试代码问题
✅ 测试新特性
✅ 学习和实验
✅ 快速迭代开发
```

**启动命令**:
```powershell
# 1. 切换到开发环境
python switch_env.py development

# 2. 启动开发服务器
python run.py
```

---

### 生产环境适用场景

```
✅ 正式部署上线
✅ 生产环境运行
✅ 多用户访问
✅ 高并发场景
✅ 安全性要求高
```

**启动命令**:
```powershell
# 1. 切换到生产环境
python switch_env.py production

# 2. 启动生产服务器
python start_production.py
```

---

## 🔧 详细配置说明

### 开发环境配置 (.env.development)

```env
# Flask环境
FLASK_ENV=development
FLASK_DEBUG=1

# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_USER=erp_app
DB_PASSWORD=
DB_NAME=erp_system

# 数据库连接池（较小）
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5

# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=ERP_Redis_2026_Secure_Password
CACHE_TYPE=RedisCache

# 安全配置
SESSION_COOKIE_SECURE=false
PREFERRED_URL_SCHEME=http
```

---

### 生产环境配置 (.env.production)

```env
# Flask环境
FLASK_ENV=production
FLASK_DEBUG=0

# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_USER=erp_app
DB_PASSWORD=
DB_NAME=erp_system

# 数据库连接池（较大）
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=ERP_Redis_2026_Secure_Password
CACHE_TYPE=RedisCache

# 安全配置
SESSION_COOKIE_SECURE=true
PREFERRED_URL_SCHEME=https
```

---

## 📊 性能对比

### 开发环境性能

```
启动速度: 快（约2-3秒）
内存占用: 低（约100-200MB）
并发处理: 单线程
响应时间: 较慢（调试开销）
适用场景: 开发调试
```

### 生产环境性能

```
启动速度: 中等（约5-8秒）
内存占用: 中等（约300-500MB）
并发处理: 8线程
响应时间: 快（无调试开销）
适用场景: 生产部署
```

---

## 🔒 安全性对比

### 开发环境安全

```
⚠️ 调试模式开启
⚠️ 显示错误详情
⚠️ 自动重载功能
⚠️ 不要求HTTPS
⚠️ 适合本地开发
```

### 生产环境安全

```
✅ 调试模式关闭
✅ 隐藏错误详情
✅ 要求HTTPS连接
✅ 安全Cookie设置
✅ 适合公网部署
```

---

## 🚨 注意事项

### 切换环境前

1. **停止当前服务**
   ```powershell
   # 按 Ctrl+C 停止当前运行的服务
   ```

2. **保存工作进度**
   - 确保代码已提交
   - 确保数据已保存

3. **切换环境**
   ```powershell
   python switch_env.py <环境类型>
   ```

---

### 生产环境部署前检查

```
✅ FLASK_ENV=production
✅ FLASK_DEBUG=0
✅ SECRET_KEY已设置
✅ 数据库密码正确
✅ Redis密码正确
✅ HTTPS证书配置
✅ 防火墙规则配置
```

---

## 📝 常见问题

### Q1: 如何知道当前使用的是哪个环境？

```powershell
# 方法1: 使用切换脚本
python switch_env.py show

# 方法2: 查看配置文件
type .env | findstr FLASK_ENV
```

---

### Q2: 切换环境后需要重启服务吗？

**是的，必须重启服务才能生效**:
```powershell
# 1. 停止当前服务 (Ctrl+C)
# 2. 切换环境
python switch_env.py <环境类型>
# 3. 重新启动服务
python run.py  # 或 python start_production.py
```

---

### Q3: 可以自定义配置吗？

**可以**，直接编辑对应的配置文件：
- 开发环境: `.env.development`
- 生产环境: `.env.production`

修改后使用切换脚本应用：
```powershell
python switch_env.py <环境类型>
```

---

### Q4: 配置文件丢失怎么办？

**恢复方法**:
```powershell
# 从备份恢复
copy .env.backup .env

# 或重新创建
python switch_env.py development  # 或 production
```

---

## 🎯 最佳实践

### 开发阶段

```
1. 使用开发环境
2. 开启调试模式
3. 使用自动重载
4. 查看详细错误
5. 快速迭代开发
```

### 测试阶段

```
1. 使用开发环境
2. 测试所有功能
3. 修复发现的问题
4. 准备生产部署
```

### 生产部署

```
1. 切换到生产环境
2. 检查配置正确性
3. 启动生产服务器
4. 监控运行状态
5. 定期备份数据
```

---

## 📞 技术支持

如有问题，请查看：
- 配置文件: `.env.development` 和 `.env.production`
- 启动脚本: `run.py` 和 `start_production.py`
- 切换脚本: `switch_env.py`

---

**文档版本**: 1.0.0  
**更新时间**: 2026-03-28  
**适用系统**: Windows/Linux/macOS
