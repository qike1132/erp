# Redis for Windows 完整配置指南

**配置时间**: 2026-03-28  
**适用版本**: Redis 3.0+ for Windows  
**配置目标**: 生产就绪的Redis服务  

---

## 一、配置概览

### 1.1 配置目标

```
✅ 服务自动启动
✅ 内存限制管理
✅ 密码安全保护
✅ 数据持久化
✅ 网络访问控制
✅ 性能优化
```

### 1.2 配置文件位置

```
默认位置:
C:\Program Files\Redis\redis.windows.conf
或
C:\Redis\redis.windows.conf
```

---

## 二、完整配置文件

### 2.1 创建优化配置文件

**创建文件**: `redis.production.conf`

```conf
# ============================================
# Redis for Windows 生产环境配置
# ============================================

# --------------------------------------------
# 网络配置
# --------------------------------------------

# 绑定IP地址
# 本地访问: bind 127.0.0.1
# 局域网访问: bind 127.0.0.1 192.168.0.95
# 所有接口: bind 0.0.0.0 (不推荐)
bind 127.0.0.1 192.168.0.95

# 监听端口
port 6379

# 保护模式
# yes: 只允许本地访问（推荐）
# no: 允许远程访问（需要设置密码）
protected-mode yes

# TCP连接队列
tcp-keepalive 300
tcp-backlog 511

# 超时设置（0表示禁用）
timeout 0

# --------------------------------------------
# 通用配置
# --------------------------------------------

# 守护进程模式（Windows下无效，保留配置）
daemonize no

# PID文件（Windows下无效）
pidfile redis.pid

# 日志级别
# debug: 详细信息
# verbose: 包含很多不太有用的信息
# notice: 适度冗长（适合生产环境）
# warning: 仅记录重要/关键信息
loglevel notice

# 日志文件位置
logfile "redis.log"

# 数据库数量
databases 16

# --------------------------------------------
# 快照持久化（RDB）
# --------------------------------------------

# RDB快照规则
# 900秒内至少1个key变化
save 900 1
# 300秒内至少10个key变化
save 300 10
# 60秒内至少10000个key变化
save 60 10000

# RDB文件名
dbfilename dump.rdb

# 数据目录
dir ./

# RDB压缩
rdbcompression yes

# RDB校验
rdbchecksum yes

# RDB写入失败时停止写入
stop-writes-on-bgsave-error yes

# --------------------------------------------
# AOF持久化
# --------------------------------------------

# 启用AOF
appendonly yes

# AOF文件名
appendfilename "appendonly.aof"

# AOF同步策略
# always: 每次写入都同步（最安全，最慢）
# everysec: 每秒同步一次（推荐）
# no: 由操作系统决定（最快，最不安全）
appendfsync everysec

# AOF重写期间是否禁用fsync
no-appendfsync-on-rewrite no

# AOF文件大小触发重写的百分比
auto-aof-rewrite-percentage 100

# AOF文件触发重写的最小大小
auto-aof-rewrite-min-size 64mb

# AOF文件损坏时是否继续加载
aof-load-truncated yes

# --------------------------------------------
# 内存管理
# --------------------------------------------

# 最大内存限制
maxmemory 2gb

# 内存淘汰策略
# volatile-lru: 从设置了过期时间的数据集中淘汰最近最少使用的key
# allkeys-lru: 从所有数据集中淘汰最近最少使用的key
# volatile-lfu: 从设置了过期时间的数据集中淘汰最不经常使用的key
# allkeys-lfu: 从所有数据集中淘汰最不经常使用的key
# volatile-random: 从设置了过期时间的数据集中随机淘汰key
# allkeys-random: 从所有数据集中随机淘汰key
# volatile-ttl: 从设置了过期时间的数据集中淘汰即将过期的key
# noeviction: 不淘汰任何key，内存满时返回错误
maxmemory-policy allkeys-lru

# 内存淘汰样本数量
maxmemory-samples 5

# --------------------------------------------
# 安全配置
# --------------------------------------------

# 访问密码（必须设置）
requirepass ERP_Redis_2026_Secure_Password

# 重命名危险命令（可选）
# rename-command FLUSHDB ""
# rename-command FLUSHALL ""
# rename-command KEYS ""
# rename-command CONFIG ""

# --------------------------------------------
# 客户端配置
# --------------------------------------------

# 最大客户端连接数
maxclients 10000

# 客户端输出缓冲区限制
client-output-buffer-limit normal 0 0 0
client-output-buffer-limit replica 256mb 64mb 60
client-output-buffer-limit pubsub 32mb 8mb 60

# --------------------------------------------
# 慢查询日志
# --------------------------------------------

# 慢查询日志长度
slowlog-max-len 128

# 慢查询阈值（微秒）
slowlog-log-slower-than 10000

# --------------------------------------------
# 高级配置
# --------------------------------------------

# Hash数据结构优化
hash-max-ziplist-entries 512
hash-max-ziplist-value 64

# List数据结构优化
list-max-ziplist-size -2
list-compress-depth 0

# Set数据结构优化
set-max-intset-entries 512

# Sorted Set数据结构优化
zset-max-ziplist-entries 128
zset-max-ziplist-value 64

# HyperLogLog优化
hll-sparse-max-bytes 3000

# Lua脚本执行时间限制（毫秒）
lua-time-limit 5000

# --------------------------------------------
# Windows特定配置
# --------------------------------------------

# Windows服务名称
service-name Redis

# Windows服务显示名称
service-display-name "Redis Server"

# Windows服务描述
service-description "Redis In-Memory Data Store"

# 最大内存使用百分比（Windows）
maxmemory-percent 80
```

---

## 三、配置步骤

### 3.1 创建配置文件

```powershell
# 1. 备份原始配置
Copy-Item "C:\Program Files\Redis\redis.windows.conf" "C:\Program Files\Redis\redis.windows.conf.backup"

# 2. 创建生产配置文件
# 将上面的配置内容保存到:
# C:\Program Files\Redis\redis.production.conf
```

---

### 3.2 配置Redis服务自动启动

**方法1: 使用sc命令**

```powershell
# 以管理员身份运行PowerShell

# 检查Redis服务状态
Get-Service *redis*

# 如果服务已存在，先删除
redis-server --service-uninstall

# 使用新配置安装服务
redis-server --service-install "C:\Program Files\Redis\redis.production.conf" --service-name Redis

# 设置服务为自动启动
sc config Redis start= auto

# 启动服务
redis-server --service-start --service-name Redis

# 验证服务状态
Get-Service Redis
```

**方法2: 使用PowerShell**

```powershell
# 设置服务启动类型为自动
Set-Service -Name Redis -StartupType Automatic

# 启动服务
Start-Service Redis

# 验证服务状态
Get-Service Redis | Select-Object Name, Status, StartType
```

**方法3: 使用注册表**

```powershell
# 设置服务自动启动
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\Redis" -Name "Start" -Value 2

# 验证设置
Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\Redis" -Name "Start"
```

---

### 3.3 验证配置文件

```powershell
# 检查配置文件语法
redis-server --test-memory 100

# 查看当前配置
redis-cli CONFIG GET "*"

# 查看特定配置
redis-cli CONFIG GET maxmemory
redis-cli CONFIG GET requirepass
redis-cli CONFIG GET bind
redis-cli CONFIG GET appendonly
```

---

## 四、配置验证

### 4.1 服务状态检查

```powershell
# 方法1: 使用Get-Service
Get-Service Redis | Format-Table Name, Status, StartType -AutoSize

# 方法2: 使用sc命令
sc query Redis

# 方法3: 使用net命令
net start | findstr Redis

# 方法4: 检查进程
Get-Process redis* | Format-Table Id, ProcessName, CPU, WorkingSet -AutoSize

# 方法5: 检查端口
netstat -ano | findstr :6379
```

**预期输出**:
```
Name   Status  StartType
----   ------  ---------
Redis  Running Automatic
```

---

### 4.2 配置参数验证

```powershell
# 连接Redis（需要密码）
redis-cli -a "ERP_Redis_2026_Secure_Password"

# 在redis-cli中执行:
127.0.0.1:6379> CONFIG GET maxmemory
1) "maxmemory"
2) "2147483648"  # 2GB

127.0.0.1:6379> CONFIG GET maxmemory-policy
1) "maxmemory-policy"
2) "allkeys-lru"

127.0.0.1:6379> CONFIG GET appendonly
1) "appendonly"
2) "yes"

127.0.0.1:6379> CONFIG GET save
1) "save"
2) "900 1 300 10 60 10000"

127.0.0.1:6379> CONFIG GET bind
1) "bind"
2) "127.0.0.1 192.168.0.95"
```

---

### 4.3 持久化验证

```powershell
# 检查RDB文件
dir "C:\Program Files\Redis\dump.rdb"

# 检查AOF文件
dir "C:\Program Files\Redis\appendonly.aof"

# 检查持久化状态
redis-cli -a "ERP_Redis_2026_Secure_Password" INFO persistence
```

**预期输出**:
```
rdb_last_bgsave_status:ok
aof_enabled:1
aof_last_rewrite_time_sec:0
aof_last_bgrewrite_status:ok
```

---

## 五、基本操作测试

### 5.1 连接测试

```powershell
# 测试连接
redis-cli -a "ERP_Redis_2026_Secure_Password" PING

# 预期输出: PONG
```

---

### 5.2 数据操作测试

```powershell
# 连接Redis
redis-cli -a "ERP_Redis_2026_Secure_Password"

# 字符串操作
127.0.0.1:6379> SET test_key "Hello Redis"
OK
127.0.0.1:6379> GET test_key
"Hello Redis"
127.0.0.1:6379> DEL test_key
(integer) 1

# Hash操作
127.0.0.1:6379> HSET user:1 name "张三" age 30
(integer) 2
127.0.0.1:6379> HGET user:1 name
"张三"
127.0.0.1:6379> HGETALL user:1
1) "name"
2) "张三"
3) "age"
4) "30"

# List操作
127.0.0.1:6379> LPUSH mylist "item1" "item2" "item3"
(integer) 3
127.0.0.1:6379> LRANGE mylist 0 -1
1) "item3"
2) "item2"
3) "item1"

# Set操作
127.0.0.1:6379> SADD myset "member1" "member2" "member3"
(integer) 3
127.0.0.1:6379> SMEMBERS myset
1) "member1"
2) "member2"
3) "member3"

# Sorted Set操作
127.0.0.1:6379> ZADD myzset 1 "one" 2 "two" 3 "three"
(integer) 3
127.0.0.1:6379> ZRANGE myzset 0 -1 WITHSCORES
1) "one"
2) "1"
3) "two"
4) "2"
5) "three"
6) "3"

# 退出
127.0.0.1:6379> EXIT
```

---

### 5.3 持久化测试

```powershell
# 写入测试数据
redis-cli -a "ERP_Redis_2026_Secure_Password" SET persist_test "This data should persist"

# 触发RDB快照
redis-cli -a "ERP_Redis_2026_Secure_Password" BGSAVE

# 触发AOF重写
redis-cli -a "ERP_Redis_2026_Secure_Password" BGREWRITEAOF

# 检查持久化状态
redis-cli -a "ERP_Redis_2026_Secure_Password" LASTSAVE

# 重启Redis服务
redis-server --service-stop
redis-server --service-start

# 验证数据持久化
redis-cli -a "ERP_Redis_2026_Secure_Password" GET persist_test
# 预期输出: "This data should persist"
```

---

### 5.4 性能测试

```powershell
# 运行性能基准测试
redis-benchmark -a "ERP_Redis_2026_Secure_Password" -t set,get -n 100000 -q

# 预期输出类似:
# SET: 100000 requests completed in 1.23 seconds
# GET: 100000 requests completed in 1.20 seconds
```

---

## 六、监控和维护

### 6.1 实时监控

```powershell
# 查看Redis信息
redis-cli -a "ERP_Redis_2026_Secure_Password" INFO

# 查看内存使用
redis-cli -a "ERP_Redis_2026_Secure_Password" INFO memory

# 查看客户端连接
redis-cli -a "ERP_Redis_2026_Secure_Password" INFO clients

# 查看持久化信息
redis-cli -a "ERP_Redis_2026_Secure_Password" INFO persistence

# 实时监控命令
redis-cli -a "ERP_Redis_2026_Secure_Password" MONITOR
```

---

### 6.2 日志查看

```powershell
# 查看Redis日志
Get-Content "C:\Program Files\Redis\redis.log" -Tail 50

# 实时查看日志
Get-Content "C:\Program Files\Redis\redis.log" -Wait

# 搜索错误日志
Select-String -Path "C:\Program Files\Redis\redis.log" -Pattern "error" -CaseSensitive
```

---

### 6.3 性能指标监控

```powershell
# 查看关键指标
redis-cli -a "ERP_Redis_2026_Secure_Password" --stat

# 查看慢查询日志
redis-cli -a "ERP_Redis_2026_Secure_Password" SLOWLOG GET 10

# 查看客户端列表
redis-cli -a "ERP_Redis_2026_Secure_Password" CLIENT LIST
```

---

## 七、Python应用集成

### 7.1 更新应用配置

**修改 `.env` 文件**:
```env
# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=ERP_Redis_2026_Secure_Password
CACHE_TYPE=RedisCache
CACHE_DEFAULT_TIMEOUT=300
```

---

### 7.2 Python连接测试

```python
import redis

# 创建连接
r = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    password='ERP_Redis_2026_Secure_Password',
    decode_responses=True
)

# 测试连接
try:
    result = r.ping()
    print(f"✅ Redis连接成功: {result}")
    
    # 测试基本操作
    r.set('test_key', 'test_value')
    value = r.get('test_key')
    print(f"✅ 数据操作成功: {value}")
    
    # 查看Redis信息
    info = r.info()
    print(f"✅ Redis版本: {info['redis_version']}")
    print(f"✅ 已用内存: {info['used_memory_human']}")
    print(f"✅ 连接客户端: {info['connected_clients']}")
    
except redis.AuthenticationError:
    print("❌ Redis认证失败: 密码错误")
except redis.ConnectionError as e:
    print(f"❌ Redis连接失败: {e}")
except Exception as e:
    print(f"❌ 错误: {e}")
```

---

### 7.3 Flask应用集成

```python
from flask import Flask
import redis

app = Flask(__name__)

# Redis配置
app.config['REDIS_HOST'] = 'localhost'
app.config['REDIS_PORT'] = 6379
app.config['REDIS_PASSWORD'] = 'ERP_Redis_2026_Secure_Password'

# 创建Redis连接
redis_client = redis.Redis(
    host=app.config['REDIS_HOST'],
    port=app.config['REDIS_PORT'],
    password=app.config['REDIS_PASSWORD'],
    decode_responses=True
)

@app.route('/')
def index():
    # 测试Redis连接
    redis_client.set('app_test', 'Flask Redis Integration')
    value = redis_client.get('app_test')
    return f'Redis连接成功: {value}'

if __name__ == '__main__':
    app.run(debug=True)
```

---

## 八、故障排查

### 8.1 服务无法启动

**检查步骤**:
```powershell
# 1. 检查配置文件语法
redis-server "C:\Program Files\Redis\redis.production.conf" --test-memory 100

# 2. 检查端口占用
netstat -ano | findstr :6379

# 3. 检查日志文件
Get-Content "C:\Program Files\Redis\redis.log"

# 4. 检查文件权限
icacls "C:\Program Files\Redis"

# 5. 尝试前台运行
redis-server "C:\Program Files\Redis\redis.production.conf"
```

---

### 8.2 无法连接Redis

**检查步骤**:
```powershell
# 1. 检查服务状态
Get-Service Redis

# 2. 检查端口监听
netstat -ano | findstr :6379

# 3. 测试本地连接
redis-cli -a "ERP_Redis_2026_Secure_Password" PING

# 4. 检查防火墙
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*Redis*"}

# 5. 检查bind配置
redis-cli CONFIG GET bind
```

---

### 8.3 内存不足

**检查和处理**:
```powershell
# 1. 查看内存使用
redis-cli -a "ERP_Redis_2026_Secure_Password" INFO memory

# 2. 查看大key
redis-cli -a "ERP_Redis_2026_Secure_Password" --bigkeys

# 3. 手动触发内存整理
redis-cli -a "ERP_Redis_2026_Secure_Password" MEMORY PURGE

# 4. 查看淘汰策略
redis-cli -a "ERP_Redis_2026_Secure_Password" CONFIG GET maxmemory-policy
```

---

## 九、配置清单

### 9.1 完成检查清单

- [ ] Redis服务已安装
- [ ] 配置文件已创建
- [ ] 服务设置为自动启动
- [ ] 内存限制已配置
- [ ] 密码保护已设置
- [ ] RDB持久化已启用
- [ ] AOF持久化已启用
- [ ] 网络绑定已配置
- [ ] 服务正常运行
- [ ] 可以正常连接
- [ ] 数据操作正常
- [ ] 持久化工作正常
- [ ] Python应用可以连接

---

### 9.2 安全检查清单

- [ ] 强密码已设置
- [ ] 保护模式已启用
- [ ] 危险命令已重命名（可选）
- [ ] 防火墙规则已配置
- [ ] 只绑定必要的IP
- [ ] 日志级别适当
- [ ] 定期备份数据文件

---

## 十、快速命令参考

### 10.1 服务管理

```powershell
# 启动服务
redis-server --service-start

# 停止服务
redis-server --service-stop

# 重启服务
redis-server --service-stop
redis-server --service-start

# 查看服务状态
Get-Service Redis

# 卸载服务
redis-server --service-uninstall
```

---

### 10.2 配置管理

```powershell
# 查看所有配置
redis-cli -a "password" CONFIG GET "*"

# 修改配置（运行时）
redis-cli -a "password" CONFIG SET maxmemory 4gb

# 重载配置
redis-cli -a "password" CONFIG REWRITE
```

---

### 10.3 数据管理

```powershell
# 清空所有数据
redis-cli -a "password" FLUSHALL

# 清空当前数据库
redis-cli -a "password" FLUSHDB

# 查看所有key
redis-cli -a "password" KEYS *

# 查看数据库大小
redis-cli -a "password" DBSIZE
```

---

**配置完成时间**: 预计15-20分钟  
**配置状态**: 生产就绪  
**下一步**: 集成到应用并监控运行状态
