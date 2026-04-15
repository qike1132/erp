# Redis连接失败故障排查指南

## 问题现象
```
[WARNING] Redis连接失败，将使用内存缓存: Error 10061 connecting to localhost:6379. 由于目标计算机积极拒绝，无法连接。
```

---

## 一、故障排查步骤

### 1. 检查Redis服务是否安装

**Windows系统检查**:
```powershell
# 方法1: 检查Redis可执行文件
where redis-server
where redis-cli

# 方法2: 检查Redis服务
Get-Service *redis*

# 方法3: 检查Redis安装目录
dir "C:\Program Files\Redis"
dir "C:\Redis"
```

**Linux系统检查**:
```bash
# 检查Redis服务
systemctl status redis
systemctl status redis-server

# 检查Redis可执行文件
which redis-server
which redis-cli
```

**预期结果**:
- 如果未找到Redis，说明Redis未安装
- 需要先安装Redis

---

### 2. 检查Redis服务运行状态

**Windows系统**:
```powershell
# 检查Redis服务状态
Get-Service *redis*

# 检查Redis进程
Get-Process redis*

# 检查端口占用
netstat -ano | findstr :6379
```

**Linux系统**:
```bash
# 检查Redis服务状态
systemctl status redis

# 检查Redis进程
ps aux | grep redis

# 检查端口占用
netstat -tulnp | grep 6379
lsof -i :6379
```

**预期结果**:
- Redis服务状态应为 "Running"
- 应该看到redis-server进程
- 端口6379应该被监听

---

### 3. 检查网络连接

**测试本地连接**:
```powershell
# 测试Redis端口连通性
Test-NetConnection -ComputerName localhost -Port 6379

# 或使用telnet
telnet localhost 6379

# 使用redis-cli测试
redis-cli ping
```

**测试远程连接**:
```powershell
# 测试远程Redis服务器
Test-NetConnection -ComputerName 192.168.1.100 -Port 6379

# 使用redis-cli测试远程连接
redis-cli -h 192.168.1.100 -p 6379 ping
```

**预期结果**:
- TcpTestSucceeded : True
- redis-cli ping 返回 PONG

---

### 4. 检查防火墙设置

**Windows防火墙**:
```powershell
# 检查防火墙状态
Get-NetFirewallProfile

# 检查Redis相关规则
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*redis*"}

# 添加Redis防火墙规则（如果需要）
New-NetFirewallRule -DisplayName "Redis" -Direction Inbound -Protocol TCP -LocalPort 6379 -Action Allow
```

**Linux防火墙**:
```bash
# 检查防火墙状态
sudo ufw status

# 检查iptables规则
sudo iptables -L -n | grep 6379

# 添加Redis防火墙规则（如果需要）
sudo ufw allow 6379/tcp
sudo iptables -A INPUT -p tcp --dport 6379 -j ACCEPT
```

---

### 5. 检查Redis配置文件

**查找Redis配置文件**:
```powershell
# Windows
dir "C:\Program Files\Redis\redis.windows.conf"
dir "C:\Redis\redis.windows.conf"

# Linux
/etc/redis/redis.conf
/etc/redis.conf
```

**关键配置项检查**:

#### bind参数
```conf
# 默认配置（只允许本地连接）
bind 127.0.0.1

# 允许所有连接（不安全，仅用于测试）
bind 0.0.0.0

# 允许特定IP连接
bind 127.0.0.1 192.168.1.100
```

#### protected-mode参数
```conf
# 保护模式开启（默认，推荐）
protected-mode yes

# 保护模式关闭（仅用于测试，不安全）
protected-mode no
```

#### port参数
```conf
# 默认端口
port 6379

# 自定义端口
port 6380
```

#### requirepass参数（密码）
```conf
# 无密码（默认）
# requirepass foobared

# 设置密码
requirepass your_strong_password_here
```

#### daemonize参数（Linux）
```conf
# 后台运行
daemonize yes

# 前台运行
daemonize no
```

---

### 6. 检查客户端连接参数

**Python应用配置检查**:
```python
# 检查.env文件
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# 检查连接代码
import redis
r = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    password=None,
    decode_responses=True
)
```

---

## 二、常见问题及解决方案

### 问题1: Redis未安装

**解决方案**:

#### Windows安装Redis

**方法1: 使用安装包**
1. 下载Redis for Windows:
   ```
   https://github.com/microsoftarchive/redis/releases
   ```

2. 安装步骤:
   ```powershell
   # 解压安装包
   Expand-Archive redis-windows.zip -DestinationPath C:\Redis
   
   # 安装Redis服务
   cd C:\Redis
   redis-server.exe --service-install redis.windows.conf
   
   # 启动Redis服务
   redis-server.exe --service-start
   
   # 验证安装
   redis-cli ping
   ```

**方法2: 使用Chocolatey**
```powershell
# 安装Chocolatey（如果未安装）
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

# 安装Redis
choco install redis-64 -y

# 启动Redis服务
redis-server

# 验证安装
redis-cli ping
```

**方法3: 使用Docker（推荐）**
```powershell
# 安装Docker Desktop（如果未安装）
# 下载: https://www.docker.com/products/docker-desktop

# 运行Redis容器
docker run -d -p 6379:6379 --name redis redis:latest

# 验证运行
docker ps
docker exec -it redis redis-cli ping
```

#### Linux安装Redis

**Ubuntu/Debian**:
```bash
# 更新包索引
sudo apt update

# 安装Redis
sudo apt install redis-server -y

# 启动Redis服务
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 验证安装
redis-cli ping
```

**CentOS/RHEL**:
```bash
# 安装EPEL源
sudo yum install epel-release -y

# 安装Redis
sudo yum install redis -y

# 启动Redis服务
sudo systemctl start redis
sudo systemctl enable redis

# 验证安装
redis-cli ping
```

---

### 问题2: Redis服务未运行

**解决方案**:

#### Windows系统
```powershell
# 启动Redis服务
redis-server.exe --service-start

# 或直接运行（前台）
redis-server.exe redis.windows.conf

# 检查服务状态
Get-Service *redis*
```

#### Linux系统
```bash
# 启动Redis服务
sudo systemctl start redis

# 或使用service命令
sudo service redis-server start

# 检查服务状态
sudo systemctl status redis
```

---

### 问题3: 防火墙阻止连接

**解决方案**:

#### Windows防火墙
```powershell
# 添加入站规则
New-NetFirewallRule -DisplayName "Redis Server" -Direction Inbound -Protocol TCP -LocalPort 6379 -Action Allow

# 添加出站规则
New-NetFirewallRule -DisplayName "Redis Client" -Direction Outbound -Protocol TCP -RemotePort 6379 -Action Allow

# 验证规则
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*Redis*"}
```

#### Linux防火墙
```bash
# UFW防火墙
sudo ufw allow 6379/tcp
sudo ufw reload

# iptables防火墙
sudo iptables -A INPUT -p tcp --dport 6379 -j ACCEPT
sudo iptables -A OUTPUT -p tcp --dport 6379 -j ACCEPT
sudo service iptables save

# firewalld防火墙
sudo firewall-cmd --permanent --add-port=6379/tcp
sudo firewall-cmd --reload
```

---

### 问题4: bind配置限制连接

**解决方案**:

**修改redis.conf配置文件**:
```conf
# 允许所有连接（不安全，仅用于开发环境）
bind 0.0.0.0

# 或允许特定IP
bind 127.0.0.1 192.168.1.100

# 同时关闭保护模式（如果bind设置为0.0.0.0）
protected-mode no
```

**重启Redis服务**:
```powershell
# Windows
redis-server.exe --service-stop
redis-server.exe --service-start

# Linux
sudo systemctl restart redis
```

---

### 问题5: 密码认证失败

**解决方案**:

**设置Redis密码**:
```conf
# 编辑redis.conf
requirepass your_strong_password_here
```

**客户端连接配置**:
```python
# Python应用
import redis
r = redis.Redis(
    host='localhost',
    port=6379,
    password='your_strong_password_here',
    decode_responses=True
)
```

**命令行连接**:
```bash
redis-cli -a your_strong_password_here
```

---

### 问题6: 端口被占用

**解决方案**:

**检查端口占用**:
```powershell
# Windows
netstat -ano | findstr :6379

# Linux
netstat -tulnp | grep 6379
lsof -i :6379
```

**结束占用进程**:
```powershell
# Windows（PID为进程ID）
taskkill /PID <PID> /F

# Linux
kill -9 <PID>
```

**或修改Redis端口**:
```conf
# 编辑redis.conf
port 6380
```

---

## 三、验证连接成功的方法

### 1. 使用redis-cli验证

```powershell
# 本地连接测试
redis-cli ping
# 预期输出: PONG

# 带密码连接测试
redis-cli -a your_password ping

# 指定主机和端口
redis-cli -h localhost -p 6379 ping

# 远程连接测试
redis-cli -h 192.168.1.100 -p 6379 ping
```

### 2. 使用Python验证

```python
import redis

try:
    # 创建连接
    r = redis.Redis(
        host='localhost',
        port=6379,
        db=0,
        decode_responses=True
    )
    
    # 测试连接
    result = r.ping()
    print(f"Redis连接成功: {result}")
    
    # 设置和获取值
    r.set('test_key', 'test_value')
    value = r.get('test_key')
    print(f"测试值: {value}")
    
except redis.ConnectionError as e:
    print(f"Redis连接失败: {e}")
except Exception as e:
    print(f"错误: {e}")
```

### 3. 使用Telnet验证

```powershell
# 连接Redis
telnet localhost 6379

# 输入命令（手动输入）
PING
# 预期输出: +PONG

# 设置值
SET test_key test_value
# 预期输出: +OK

# 获取值
GET test_key
# 预期输出: $10
# test_value
```

### 4. 使用PowerShell验证

```powershell
# 测试TCP连接
Test-NetConnection -ComputerName localhost -Port 6379

# 预期输出:
# TcpTestSucceeded : True
```

---

## 四、最佳实践建议

### 1. 开发环境配置

**推荐配置**:
```conf
# redis.conf
bind 127.0.0.1
protected-mode yes
port 6379
# requirepass（开发环境可不设置密码）
```

**优点**:
- 安全性高
- 配置简单
- 性能良好

### 2. 生产环境配置

**推荐配置**:
```conf
# redis.conf
bind 127.0.0.1 <内网IP>
protected-mode yes
port 6379
requirepass <强密码>
maxmemory 2gb
maxmemory-policy allkeys-lru
```

**优点**:
- 高安全性
- 密码保护
- 内存控制

### 3. 监控和维护

**定期检查**:
```powershell
# 检查Redis状态
redis-cli info

# 检查内存使用
redis-cli info memory

# 检查连接数
redis-cli info clients

# 监控Redis性能
redis-cli --stat
```

---

## 五、故障排查清单

- [ ] Redis是否已安装
- [ ] Redis服务是否运行
- [ ] 端口6379是否监听
- [ ] 防火墙是否允许连接
- [ ] bind配置是否正确
- [ ] protected-mode配置是否正确
- [ ] 密码配置是否正确
- [ ] 客户端连接参数是否正确
- [ ] 网络连接是否通畅
- [ ] Redis日志是否有错误

---

## 六、快速解决方案

### 最快的解决方案（Docker）

```powershell
# 1. 安装Docker Desktop
# 下载: https://www.docker.com/products/docker-desktop

# 2. 运行Redis容器
docker run -d -p 6379:6379 --name redis redis:latest

# 3. 验证连接
docker exec -it redis redis-cli ping
```

### 最快的解决方案（Windows服务）

```powershell
# 1. 下载Redis
# https://github.com/microsoftarchive/redis/releases

# 2. 安装并启动
redis-server.exe --service-install
redis-server.exe --service-start

# 3. 验证
redis-cli ping
```

---

**文档生成时间**: 2026-03-28  
**适用系统**: Windows/Linux  
**Redis版本**: 5.0+
