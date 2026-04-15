# Redis for Windows 安装指南

**安装时间**: 2026-03-28  
**适用系统**: Windows 10/11, Windows Server 2016+  
**Redis版本**: 3.0+  

---

## 一、安装方法选择

### 方法1: 使用安装包（推荐新手）

**优点**: 
- ✅ 图形化界面
- ✅ 自动配置服务
- ✅ 简单快捷

**缺点**:
- ⚠️ 版本可能较旧

---

### 方法2: 使用Chocolatey（推荐开发者）

**优点**:
- ✅ 命令行安装
- ✅ 自动管理
- ✅ 易于更新

**缺点**:
- ⚠️ 需要先安装Chocolatey

---

### 方法3: 使用Scoop（推荐高级用户）

**优点**:
- ✅ 轻量级
- ✅ 无需管理员权限
- ✅ 版本管理灵活

**缺点**:
- ⚠️ 需要先安装Scoop

---

## 二、方法1: 使用安装包安装

### 步骤1: 下载Redis for Windows

**下载地址**:
```
官方推荐:
https://github.com/microsoftarchive/redis/releases

选择版本:
- Redis-x64-3.0.504.msi (推荐)
- Redis-x64-3.0.504.zip (便携版)
```

**下载步骤**:
1. 打开上述链接
2. 找到最新版本（通常是3.0.504）
3. 下载 `.msi` 安装包（推荐）或 `.zip` 压缩包

---

### 步骤2: 安装Redis

**MSI安装包方式**:

```powershell
# 1. 双击下载的 .msi 文件
# Redis-x64-3.0.504.msi

# 2. 安装向导
# - 欢迎界面: 点击 Next
# - 许可协议: 勾选 I accept，点击 Next
# - 安装位置: 默认 C:\Program Files\Redis\，点击 Next
# - 服务配置:
#   ✓ 勾选 "Add Redis to PATH"
#   ✓ 勾选 "Install as Windows Service"
#   ✓ 端口保持默认 6379
#   ✓ 防火墙例外: 可选
# - 点击 Install 开始安装
# - 完成后点击 Finish
```

**ZIP压缩包方式**:

```powershell
# 1. 解压文件
Expand-Archive Redis-x64-3.0.504.zip -DestinationPath C:\Redis

# 2. 进入目录
cd C:\Redis

# 3. 测试运行（前台）
.\redis-server.exe redis.windows.conf

# 4. 安装为Windows服务
.\redis-server.exe --service-install redis.windows.conf

# 5. 启动服务
.\redis-server.exe --service-start
```

---

### 步骤3: 验证安装

```powershell
# 方法1: 使用redis-cli
redis-cli ping
# 预期输出: PONG

# 方法2: 检查服务状态
Get-Service *redis*
# 预期输出: Status: Running

# 方法3: 检查端口
netstat -ano | findstr :6379
# 预期输出: 0.0.0.0:6379 LISTENING

# 方法4: 测试数据操作
redis-cli
127.0.0.1:6379> SET test "Hello Redis"
OK
127.0.0.1:6379> GET test
"Hello Redis"
127.0.0.1:6379> EXIT
```

---

## 三、方法2: 使用Chocolatey安装

### 步骤1: 安装Chocolatey（如果未安装）

```powershell
# 以管理员身份运行PowerShell
Set-ExecutionPolicy Bypass -Scope Process -Force

# 安装Chocolatey
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

# 验证安装
choco --version
```

---

### 步骤2: 使用Chocolatey安装Redis

```powershell
# 安装Redis
choco install redis-64 -y

# 验证安装
redis-server --version
redis-cli --version
```

---

### 步骤3: 启动Redis服务

```powershell
# 方法1: 作为服务运行
redis-server --service-install
redis-server --service-start

# 方法2: 前台运行（测试用）
redis-server

# 验证
redis-cli ping
```

---

## 四、方法3: 使用Scoop安装

### 步骤1: 安装Scoop（如果未安装）

```powershell
# 设置执行策略
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

# 安装Scoop
irm get.scoop.sh | iex

# 验证安装
scoop --version
```

---

### 步骤2: 使用Scoop安装Redis

```powershell
# 安装Redis
scoop install redis

# 验证安装
redis-server --version
redis-cli --version
```

---

### 步骤3: 启动Redis

```powershell
# 启动Redis服务器
redis-server

# 在新终端验证
redis-cli ping
```

---

## 五、配置Redis

### 5.1 修改配置文件

**配置文件位置**:
```
C:\Program Files\Redis\redis.windows.conf
或
C:\Redis\redis.windows.conf
```

**常用配置修改**:

```conf
# 1. 设置密码（推荐）
# 找到 # requirepass foobared
# 修改为:
requirepass your_strong_password_here

# 2. 设置最大内存
maxmemory 2gb
maxmemory-policy allkeys-lru

# 3. 允许远程连接（可选）
# 找到 bind 127.0.0.1
# 修改为:
bind 0.0.0.0

# 4. 关闭保护模式（如果bind设置为0.0.0.0）
protected-mode no

# 5. 启用持久化
appendonly yes
appendfilename "appendonly.aof"

# 6. 设置日志级别
loglevel notice
logfile "redis.log"
```

---

### 5.2 重启Redis服务

```powershell
# 重启服务使配置生效
redis-server --service-stop
redis-server --service-start

# 或使用Windows服务管理
Restart-Service Redis
```

---

### 5.3 配置防火墙（如果需要远程访问）

```powershell
# 添加防火墙规则
New-NetFirewallRule -DisplayName "Redis Server" -Direction Inbound -Protocol TCP -LocalPort 6379 -Action Allow

# 验证规则
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*Redis*"}
```

---

## 六、服务管理命令

### 6.1 Windows服务管理

```powershell
# 启动服务
redis-server --service-start
# 或
Start-Service Redis

# 停止服务
redis-server --service-stop
# 或
Stop-Service Redis

# 重启服务
redis-server --service-stop
redis-server --service-start
# 或
Restart-Service Redis

# 查看服务状态
Get-Service Redis
```

---

### 6.2 服务卸载

```powershell
# 卸载Redis服务
redis-server --service-uninstall

# 使用Chocolatey卸载
choco uninstall redis-64 -y

# 使用Scoop卸载
scoop uninstall redis
```

---

## 七、测试Redis功能

### 7.1 基本操作测试

```powershell
# 连接Redis
redis-cli

# 如果设置了密码
redis-cli -a your_password

# 基本操作
127.0.0.1:6379> PING
PONG

127.0.0.1:6379> SET mykey "Hello Redis"
OK

127.0.0.1:6379> GET mykey
"Hello Redis"

127.0.0.1:6379> DEL mykey
(integer) 1

127.0.0.1:6379> GET mykey
(nil)

127.0.0.1:6379> EXIT
```

---

### 7.2 性能测试

```powershell
# 运行性能测试
redis-benchmark -t set,get -n 100000 -q

# 预期输出类似:
# SET: 100000 requests completed in 1.23 seconds
# GET: 100000 requests completed in 1.20 seconds
```

---

### 7.3 监控Redis

```powershell
# 查看Redis信息
redis-cli info

# 查看内存使用
redis-cli info memory

# 查看客户端连接
redis-cli info clients

# 实时监控命令
redis-cli monitor
```

---

## 八、常见问题解决

### 问题1: 端口被占用

**检查端口占用**:
```powershell
netstat -ano | findstr :6379
```

**解决方案**:
```powershell
# 方法1: 结束占用进程
taskkill /PID <PID> /F

# 方法2: 修改Redis端口
# 编辑 redis.windows.conf
port 6380
```

---

### 问题2: 服务无法启动

**检查日志**:
```powershell
# 查看Redis日志
Get-Content "C:\Program Files\Redis\redis.log"

# 查看Windows事件日志
Get-EventLog -LogName Application -Source Redis
```

**解决方案**:
```powershell
# 检查配置文件语法
redis-server --service-install redis.windows.conf --service-name RedisTest

# 检查文件权限
icacls "C:\Program Files\Redis"
```

---

### 问题3: 无法远程连接

**检查配置**:
```powershell
# 确认bind设置
redis-cli CONFIG GET bind

# 确认protected-mode
redis-cli CONFIG GET protected-mode
```

**解决方案**:
```conf
# 修改 redis.windows.conf
bind 0.0.0.0
protected-mode no

# 重启服务
redis-server --service-stop
redis-server --service-start
```

---

## 九、Python应用集成

### 9.1 安装Redis Python客户端

```powershell
pip install redis
```

---

### 9.2 Python连接示例

```python
import redis

# 创建连接
r = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    password='your_password',  # 如果设置了密码
    decode_responses=True
)

# 测试连接
try:
    result = r.ping()
    print(f"Redis连接成功: {result}")
    
    # 设置值
    r.set('test_key', 'test_value')
    
    # 获取值
    value = r.get('test_key')
    print(f"测试值: {value}")
    
except redis.ConnectionError as e:
    print(f"Redis连接失败: {e}")
```

---

### 9.3 Flask应用集成

```python
from flask import Flask
from flask_redis import FlaskRedis

app = Flask(__name__)
app.config['REDIS_URL'] = 'redis://localhost:6379/0'

redis_store = FlaskRedis(app)

@app.route('/')
def index():
    redis_store.set('key', 'value')
    return redis_store.get('key')

if __name__ == '__main__':
    app.run()
```

---

## 十、安装验证清单

- [ ] Redis服务已安装
- [ ] Redis服务正在运行
- [ ] 端口6379正在监听
- [ ] redis-cli可以连接
- [ ] PING命令返回PONG
- [ ] 可以执行SET/GET操作
- [ ] Python客户端可以连接
- [ ] 配置文件已修改（可选）
- [ ] 防火墙规则已配置（可选）

---

## 十一、快速安装命令总结

```powershell
# 方法1: MSI安装包（推荐）
# 1. 下载: https://github.com/microsoftarchive/redis/releases
# 2. 双击安装
# 3. 验证: redis-cli ping

# 方法2: Chocolatey
choco install redis-64 -y
redis-server --service-install
redis-server --service-start
redis-cli ping

# 方法3: Scoop
scoop install redis
redis-server
redis-cli ping
```

---

**安装完成时间**: 预计5-10分钟  
**推荐方法**: MSI安装包（新手）或 Chocolatey（开发者）  
**下一步**: 配置Redis并集成到应用中
