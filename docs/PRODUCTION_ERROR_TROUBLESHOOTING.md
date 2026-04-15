# 生产环境错误排查指南

## ⚠️ 问题现象

**错误信息**: Internal Server Error

**原因**: 生产环境 (`FLASK_ENV=production`) 会隐藏错误详情，只显示通用错误信息。

---

## 🔍 快速诊断步骤

### 步骤1: 切换到开发环境查看详细错误

```powershell
# 1. 停止当前服务 (Ctrl+C)

# 2. 切换到开发环境
python switch_env.py development

# 3. 启动开发服务器
python run.py

# 4. 访问页面，查看详细错误信息
```

---

## 🚨 常见原因分析

### 1. HTTPS配置问题（最可能）

**生产环境配置**:
```env
SESSION_COOKIE_SECURE=true
PREFERRED_URL_SCHEME=https
```

**问题**: 这些配置需要HTTPS，但您可能使用的是HTTP

**解决方案**:
```env
# 修改 .env.production
SESSION_COOKIE_SECURE=false
PREFERRED_URL_SCHEME=http
```

---

### 2. Redis连接问题

**检查Redis服务**:
```powershell
# 检查Redis服务状态
Get-Service Redis

# 测试Redis连接
redis-cli -a "ERP_Redis_2026_Secure_Password" PING
```

---

### 3. 数据库连接问题

**检查数据库**:
```powershell
# 测试数据库连接
mysql -u root -p110110 -e "SELECT 1"
```

---

## ✅ 推荐解决方案

### 方案1: 切换到开发环境（推荐）

```powershell
# 1. 停止当前服务 (Ctrl+C)
# 2. 切换环境
python switch_env.py development
# 3. 启动开发服务器
python run.py
# 4. 查看详细错误信息
```

---

### 方案2: 修复生产环境配置

**修改 `.env.production`**:
```env
# 将这两行改为:
SESSION_COOKIE_SECURE=false
PREFERRED_URL_SCHEME=http
```

**重新应用配置**:
```powershell
python switch_env.py production
python start_production.py
```

---

## 📋 立即操作

**最快解决方法**:

```powershell
# 停止当前服务 (Ctrl+C)
# 切换到开发环境
python switch_env.py development
# 启动开发服务器
python run.py
```

这样可以看到详细的错误信息，便于诊断问题。

---

**创建时间**: 2026-03-28  
**状态**: 待诊断
