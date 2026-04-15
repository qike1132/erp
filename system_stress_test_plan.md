# 滨发协同系统 - 全系统API及下载接口综合压力测试方案

> **文档版本**: v1.0
> **编制日期**: 2026-04-11
> **适用系统**: 滨发协同系统 API v2.0.0
> **技术栈**: Python 3.12 + FastAPI + MySQL + Redis
> **测试工具**: JMeter 5.6+ / K6 (备选)

---

## 目录

1. [测试目标与范围](#1-测试目标与范围)
2. [测试环境搭建规范](#2-测试环境搭建规范)
3. [测试工具选型与配置](#3-测试工具选型与配置)
4. [测试场景设计](#4-测试场景设计)
5. [测试执行流程](#5-测试执行流程)
6. [监控指标设定](#6-监控指标设定)
7. [风险评估与应急预案](#7-风险评估与应急预案)
8. [测试报告模板及分析方法](#8-测试报告模板及分析方法)
9. [执行明细与通过标准](#9-执行明细与通过标准)
10. [附录：JMeter脚本示例](#10-附录jmeter脚本示例)

---

## 1. 测试目标与范围

### 1.1 核心目标

| 目标类别 | 具体目标 | 验证方式 |
|---------|---------|---------|
| **性能基线** | 确定系统在正常负载下的响应时间和吞吐量基准值 | 常规负载测试 |
| **瓶颈识别** | 定位系统的性能瓶颈（CPU/内存/数据库/网络） | 压力测试 |
| **容量规划** | 确定系统最大承载能力及扩展阈值 | 极限压力测试 |
| **稳定性验证** | 验证系统长时间运行的稳定性及资源泄漏情况 | 耐久性测试 |
| **下载可靠性** | 验证文件下载的完整性、并发处理能力及限流机制 | 下载专项测试 |

### 1.2 测试范围界定

#### 1.2.1 API接口覆盖清单（15个模块）

| 序号 | 模块名称 | 路由前缀 | 接口数量(预估) | 优先级 |
|-----|---------|---------|---------------|-------|
| 1 | 采购中心 | `/api/v1/purchase-center` | ~15 | P0 |
| 2 | 产品管理 | `/api/v1/products` | ~12 | P0 |
| 3 | 订单管理 | `/api/v1/orders` | ~18 | P0 |
| 4 | 库存管理 | `/api/v1/stock` | ~14 | P0 |
| 5 | 用户管理 | `/api/v1/users` | ~8 | P0 |
| 6 | 客户管理 | `/api/v1/customers` | ~10 | P1 |
| 7 | 审批管理 | `/api/v1/approvals` | ~12 | P1 |
| 8 | 报表统计 | `/api/v1/reports` | ~8 | P0 |
| 9 | 批量导入 | `/api/v1/batch` | ~6 | P1 |
| 10 | 暂存订单 | `/api/v1/staging-orders` | ~10 | P1 |
| 11 | 暂存备货 | `/api/v1/staging-stockins` | ~8 | P1 |
| 12 | 暂存出货 | `/api/v1/staging-stockouts` | ~8 | P1 |
| 13 | 皮套管理 | `/api/v1/cases` | ~10 | P1 |
| 14 | 来料登记 | `/api/v1/material-registrations` | ~8 | P1 |
| 15 | 辅助接口 | `/api/v1/aux` | ~5 | P2 |

#### 1.2.2 下载接口覆盖范围

| 功能点 | 路由示例 | 文件类型 | 测试重点 |
|-------|---------|---------|---------|
| 采购单导出 | `POST /api/v1/purchase-center/export` | Excel (.xlsx) | 大数据量导出 |
| 批量模板下载 | `GET /api/v1/batch/template` | Excel (.xlsx) | 并发下载 |
| 报表导出 | `POST /api/v1/reports/export` | PDF/Excel | 复杂查询导出 |

#### 1.3 不包含的范围

- ❌ 前端页面渲染性能测试
- ❌ 数据库单独压测（仅监控）
- ❌ 第三方服务接口测试（如支付网关）
- ❌ 安全渗透测试（需独立方案）

---

## 2. 测试环境搭建规范

### 2.1 硬件配置要求

#### 2.1.1 生产环境参考配置

| 组件 | 配置规格 | 用途 |
|-----|---------|------|
| **应用服务器** | CPU: 4核 / 内存: 8GB / SSD: 100GB | 运行FastAPI服务 |
| **数据库服务器** | CPU: 8核 / 内存: 16GB / SSD: 200GB | MySQL 8.0+ |
| **Redis服务器** | CPU: 2核 / 内存: 4GB | 缓存与会话管理 |
| **负载均衡器** | Nginx 1.24+ | 反向代理与静态资源 |
| **测试机(压测端)** | CPU: 8核+ / 内存: 16GB+ / 千兆网卡 | 运行JMeter/K6 |

#### 2.1.2 测试环境最低配置

```
┌─────────────────────────────────────────────────────┐
│                   测试环境拓扑                       │
├──────────┬──────────┬──────────┬───────────────────┤
│  压测客户端 │  Nginx   │ FastAPI  │    MySQL + Redis   │
│ (JMeter)  │ :80/:443 │ :5002    │   :3306/:6379     │
│  8C/16G   │  LB      │  App     │     Data Layer     │
└──────────┴──────────┴──────────┴───────────────────┘
```

### 2.2 软件环境配置

| 软件 | 版本要求 | 安装路径 | 配置要点 |
|-----|---------|---------|---------|
| **操作系统** | Ubuntu 22.04 LTS / CentOS 8+ | - | 关闭防火墙或开放必要端口 |
| **Python** | 3.12.x | `/usr/bin/python3` | 已安装于Docker镜像 |
| **FastAPI** | 0.109+ | `/app/fastapi_app` | Uvicorn工作进程: 4 |
| **MySQL** | 8.0+ | 默认安装 | innodb_buffer_pool_size=4G |
| **Redis** | 7.0+ | 默认安装 | maxmemory=2gb |
| **Nginx** | 1.24+ | `/etc/nginx/` | worker_processes=auto |
| **JMeter** | 5.6+ | `/opt/apache-jmeter-5.6/` | HEAP=-Xms2g -Xmx4g |
| **Docker** | 24.0+ | - | Compose编排部署 |

### 2.3 Docker Compose 部署配置

```yaml
# docker-compose.test.yml (测试环境专用)
version: '3.8'

services:
  fastapi-app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5002:5002"
    environment:
      - DATABASE_URL=mysql+pymysql://erp_test:Test@123!@mysql:3306/erp_test
      - REDIS_URL=redis://redis:6379/0
      - FASTAPI_DEBUG=false
    depends_on:
      - mysql
      - redis
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: Root@123!
      MYSQL_DATABASE: erp_test
      MYSQL_USER: erp_test
      MYSQL_PASSWORD: Test@123!
    volumes:
      - mysql_data:/var/lib/mysql
      - ./init-sql:/docker-entrypoint-initdb.d
    command: --innodb-buffer-pool-size=4G --max-connections=500
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 16G

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

  nginx:
    image: nginx:1.24-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx-test.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - fastapi-app

volumes:
  mysql_data:
```

### 2.4 数据准备规范

#### 2.4.1 测试数据规模

| 数据表 | 初始数据量 | 数据生成规则 | 说明 |
|-------|----------|-------------|------|
| users | 10,000条 | 批量插入脚本 | 含不同角色用户 |
| products | 50,000条 | 分类别随机生成 | 含SKU、价格、库存 |
| orders | 100,000条 | 模拟历史订单 | 覆盖各状态流转 |
| stock_records | 500,000条 | 出入库记录 | 时间跨度1年 |
| customers | 20,000条 | 企业+个人客户 | 用于关联查询 |
| approvals | 30,000条 | 各类审批流程 | 含待审/已审状态 |

#### 2.4.2 数据生成脚本示例

```python
# scripts/generate_test_data.py
import asyncio
import random
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine

async def generate_users(count=10000):
    """批量生成测试用户"""
    engine = create_async_engine(settings.ASYNC_DATABASE_URL)
    sql = """
    INSERT INTO users (username, email, role_id, created_at)
    SELECT 
        CONCAT('test_user', n),
        CONCAT('user', n, '@test.com'),
        (FLOOR(RAND() * 4) + 1),
        DATE_SUB(NOW(), INTERVAL FLOOR(RAND()*365) DAY)
    FROM (
        SELECT @row := @row + 1 AS n FROM 
        (SELECT 1 UNION SELECT 2 UNION SELECT 3 ... LIMIT %s) t,
        (SELECT @row := 0) r
    ) numbers
    """
    async with engine.connect() as conn:
        await conn.execute(sql, count)
        await conn.commit()
    print(f"✓ 已生成 {count} 条用户数据")

if __name__ == "__main__":
    asyncio.run(generate_users())
```

#### 2.4.3 数据隔离策略

```bash
# 测试前备份生产数据结构
mysqldump -u root -p --no-data erp_production > schema_backup.sql

# 创建测试专用数据库
mysql -u root -p -e "CREATE DATABASE erp_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"

# 导入结构并填充测试数据
mysql -u root -p erp_test < schema_backup.sql
python scripts/generate_test_data.py
```

---

## 3. 测试工具选型与配置

### 3.1 工具对比与选择

| 对比维度 | Apache JMeter | Grafana K6 | Locust |
|---------|--------------|-----------|--------|
| **协议支持** | HTTP/JDBC/JMS等全协议 | HTTP/gRPC/WebSocket | HTTP为主 |
| **分布式压测** | ✅ 原生支持 | ✅ 云原生支持 | ✅ Master-Slave |
| **脚本复杂度** | GUI+XML，学习曲线陡 | JavaScript，较友好 | Python，开发友好 |
| **资源消耗** | 较高（Java堆内存） | 低（Go编写） | 中等 |
| **报表功能** | HTML Report丰富 | InfluxDB+Grafana | Web UI简单 |
| **社区生态** | 成熟稳定 | 新兴活跃 | Python生态 |
| **推荐场景** | ⭐ **本方案首选** | 云原生/K8s环境 | 开发团队Python栈 |

**最终选择**: **Apache JMeter 5.6+**
- 理由：全面支持HTTP/下载测试、成熟的分布式压测、丰富的监听器、团队熟悉度高

### 3.2 JMeter 安装与配置

#### 3.2.1 安装步骤

```bash
# 1. 下载并解压
cd /opt
wget https://downloads.apache.org/jmeter/binaries/apache-jmeter-5.6.3.tgz
tar -xzf apache-jmeter-5.6.3.tgz
ln -s apache-jmeter-5.6.3 jmeter

# 2. 配置JVM参数（编辑 jmeter.sh 或 jmeter.bat）
export JVM_ARGS="-Xms2g -Xmx4g -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/jmeter_heap.hprof"

# 3. 安装常用插件
cd jmeter/lib/ext
wget https://jmeter-plugins.org/downloads/packages/jpgc-plugins-0.90.zip
unzip jpgc-plugins-0.90.zip

# 4. 验证安装
./jmeter -v
# 应显示: Apache JMeter 5.6.3
```

#### 3.2.2 核心配置参数

```properties
# jmeter.properties 关键配置

# 语言设置
#language=zh_CN

# HTTP连接池配置
httpclient.max_connections=500
httpclient.max_connections_per_host=100
httpclient.time_to_live=60000

# 响应超时设置
httpclient.timeout=30000
http.socket.timeout=30000
http.connection.timeout=5000

# 结果保存配置
jmeter.save.saveservice.output_format=xml
jmeter.save.saveservice.response_data=true
jmeter.save.saveservice.samplerData=true
jmeter.save.saveservice.timestamp_format=ms

# 远程测试配置（分布式压测）
remote_hosts=192.168.1.101:1099,192.168.1.102:1099
server_port=1099
server.rmi.localport=1099
```

### 3.3 K6 备选方案配置

```javascript
// k6-config.js - 基础配置模板
import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

export const options = {
  stages: [
    { duration: '2m', target: 100 },   // 预热阶段
    { duration: '5m', target: 500 },   // 正常负载
    { duration: '3m', target: 1000 },  // 压力负载
    { duration: '2m', target: 100 },   // 冷却阶段
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'],  // 95%请求<2秒
    http_req_failed: ['rate<0.01'],     // 错误率<1%
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:5002';

export default function () {
  const res = http.get(`${BASE_URL}/api/health`);
  check(res, {
    'status is 200': (r) => r.status === 200,
  });
  sleep(1);
}
```

---

## 4. 测试场景设计

### 4.1 场景总览矩阵

| 场景编号 | 场景名称 | 并发用户数 | 持续时间 | 目标 | 优先级 |
|---------|---------|-----------|---------|------|-------|
| SMC-001 | 健康检查基线 | 10 | 5min | 验证环境就绪 | P0 |
| SMC-002 | 用户登录认证 | 100 | 10min | 验证JWT签发性能 | P0 |
| SMC-003 | 产品列表查询 | 200 | 15min | 分页查询性能 | P0 |
| SMC-004 | 订单创建流程 | 150 | 20min | 写入事务性能 | P0 |
| SMC-005 | 库存实时查询 | 300 | 15min | 高频读取性能 | P0 |
| SMC-006 | 报表统计聚合 | 50 | 30min | 复杂SQL性能 | P1 |
| SMC-007 | 混合业务场景 | 500 | 60min | 综合负载模拟 | P0 |
| SMC-008 | 峰值压力测试 | 1000 | 10min | 寻找性能拐点 | P0 |
| SMC-009 | 极限破坏测试 | 2000 | 5min | 验证降级熔断 | P1 |
| SMC-010 | 长时间稳定性 | 200 | 8h | 内存泄漏检测 | P1 |
| SMC-011 | 大文件下载测试 | 100 | 30min | 文件传输稳定性 | P0 |
| SMC-012 | 高并发下载测试 | 500 | 15min | 连接池与限流 | P0 |
| SMC-013 | 批量导出压力测试 | 50 | 20min | 服务端生成性能 | P1 |

### 4.2 详细场景定义

#### 4.2.1 SMC-007 混合业务场景（核心场景）

**场景描述**: 模拟真实业务流量分布，按比例分配各类操作

```
流量配比模型:
┌──────────────────────────────────────────────┐
│  读操作 (70%)                                │
│  ├─ 产品查询:    25%                         │
│  ├─ 订单查询:    20%                         │
│  ├─ 库存查询:    15%                         │
│  └─ 用户信息:    10%                         │
│                                              │
│  写操作 (25%)                                │
│  ├─ 创建订单:    12%                         │
│  ├─ 更新库存:     8%                         │
│  └─ 提交审批:     5%                         │
│                                              │
│  导出下载 (5%)                               │
│  └─ 报表/Excel导出: 5%                      │
└──────────────────────────────────────────────┘
```

**JMeter线程组配置**:

```xml
<!-- 通过Throughput Controller实现比例控制 -->
<hashTree>
  <!-- 70% 读操作 -->
  <ThroughputController style="0" maxThroughput="70" percentAll="true">
    <hashTree>
      <!-- 产品查询 25% -->
      <ThroughputController style="0" maxThroughput="25" percentAll="true">
        <hashTree>
          <HTTPSamplerProxy>
            <stringProp name="domain">${HOST}</stringProp>
            <stringProp name="port">${PORT}</stringProp>
            <stringProp name="path">/api/v1/products?page=1&size=20</stringProp>
            <stringProp name="method">GET</stringProp>
            <HeaderManager>
              <collectionProp name="headers">
                <elementProp name="Authorization">
                  <stringProp name="Header.name">Authorization</stringProp>
                  <stringProp name="Header.value">Bearer ${TOKEN}</stringProp>
                </elementProp>
              </collectionProp>
            </HeaderManager>
          </HTTPSamplerProxy>
        </hashTree>
      </ThroughputController>
      
      <!-- 其他读操作类似配置... -->
    </hashTree>
  </ThroughputController>
  
  <!-- 25% 写操作 -->
  <ThroughputController style="0" maxThroughput="25" percentAll="true">
    <hashTree>
      <!-- 写操作配置... -->
    </hashTree>
  </ThroughputController>
  
  <!-- 5% 下载操作 -->
  <ThroughputController style="0" maxThroughput="5" percentAll="true">
    <hashTree>
      <!-- 下载配置... -->
    </hashTree>
  </ThroughputController>
</hashTree>
```

#### 4.2.2 SMC-011 大文件下载专项测试

**测试目标**: 验证大文件传输的完整性、断点续传支持、带宽占用

| 参数项 | 配置值 | 说明 |
|-------|-------|------|
| 文件大小梯度 | 10MB / 50MB / 100MB / 500MB | 覆盖常见导出文件大小 |
| 下载方式 | HTTP GET / POST | 支持两种请求模式 |
| 并发度 | 10 / 50 / 100 | 逐步递增 |
| 网络条件 | 正常 / 弱网(模拟丢包5%) | 使用JMeter延迟插件 |
| 校验方式 | MD5 / SHA256 | 下载后自动校验 |

**完整性校验脚本**:

```groovy
// JMeter JSR223 PostProcessor - 文件完整性校验
import org.apache.commons.codec.digest.DigestUtils;
import java.io.FileInputStream;

def response = prev.getResponseData();
String fileName = vars.get("download_filename");
String expectedMD5 = vars.get("expected_md5");

if (response != null && response.length > 0) {
    String actualMD5 = DigestUtils.md5Hex(response);
    
    if (actualMD5.equals(expectedMD5)) {
        SampleResult.setResponseCode("200");
        SampleResult.setResponseMessage("OK - MD5校验通过");
        log.info("✓ 文件校验通过: " + fileName);
    } else {
        SampleResult.setSuccessful(false);
        SampleResult.setResponseMessage("FAIL - MD5不匹配");
        log.error("✗ 文件损坏: 期望=" + expectedMD5 + " 实际=" + actualMD5);
    }
}
```

#### 4.2.3 SMC-012 高并发下载测试

**测试目标**: 验证系统在高并发下载时的：
- 连接池耗尽处理
- 限流机制生效
- 带宽公平分配
- 服务端资源释放

**阶梯式加压策略**:

```
时间轴: ──────────────────────────────────────→
       [预热]  [正常]  [高压]  [极限]  [恢复]
并发:    50     200     500    1000    100
时长:   5min   10min   15min   10min   5min
       
监控指标:
- 活跃连接数 (netstat -an | grep ESTABLISHED | wc -l)
- 429 Too Many Requests 错误率
- 平均下载速率 (MB/s)
- 服务端内存使用率 (%)
```

**JMeter配置要点**:

```xml
<!-- 下载采样器配置 -->
<HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="大文件下载">
  <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
  <stringProp name="HTTPSampler.domain">${HOST}</stringProp>
  <stringProp name="HTTPSampler.port">${PORT}</stringProp>
  <stringProp name="HTTPSampler.path">/api/v1/reports/export?type=full_report</stringProp>
  <stringProp name="HTTPSampler.method">POST</stringProp>
  <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
  <stringProp name="HTTPSampler.embedded_url_re"></stringProp>
  <stringProp name="HTTPSampler.connect_timeout">30000</stringProp>
  <stringProp name="HTTPSampler.response_timeout">120000</stringProp>
  
  <!-- 保存响应到文件用于后续校验 -->
  <Listener guiclass="SaveResponsesToFile" testclass="SaveResponsesToFile" testname="保存下载文件">
    <stringProp name="filename">results/download_${__threadNum}_${__time(yyyyMMddHHmmss)}.xlsx</stringProp>
  </Listener>
</HTTPSamplerProxy>
```

---

## 5. 测试执行流程

### 5.1 分阶段执行路线图

```
┌──────────────────────────────────────────────────────────────┐
│                    测试执行主流程                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Phase 1: 准备阶段 (T-2天)                                   │
│  ├── 环境检查与部署                                           │
│  ├── 数据初始化                                               │
│  └── 工具配置验证                                             │
│                                                              │
│  Phase 2: 调试阶段 (T-1天)                                    │
│  ├── 单接口脚本调试                                           │
│  ├── 参数化与关联验证                                         │
│  └── 小规模预演(10并发, 5min)                                 │
│                                                              │
│  Phase 3: 基线测试 (Day 1 上午)                               │
│  ├── SMC-001~SMC-006 单场景基线                               │
│  └── 记录基准指标                                              │
│                                                              │
│  Phase 4: 压力测试 (Day 1 下午)                               │
│  ├── SMC-007~SMC-009 负载/峰值/极限                           │
│  ├── 实时监控与日志采集                                       │
│  └── 瓶颈初步定位                                              │
│                                                              │
│  Phase 5: 专项测试 (Day 2 上午)                               │
│  ├── SMC-011~SMC-013 下载接口专项                             │
│  ├── 文件完整性校验                                           │
│  └── 并发问题复现                                             │
│                                                              │
│  Phase 6: 稳定性测试 (Day 2 下午 ~ Day 3)                     │
│  ├── SMC-010 长时间运行                                        │
│  └── 资源泄漏检测                                             │
│                                                              │
│  Phase 7: 收尾阶段 (Day 3 下午)                               │
│  ├── 数据清理                                                 │
│  ├── 报告编制                                                 │
│  └── 问题汇总与建议                                            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 各阶段详细检查清单

#### Phase 1: 环境准备检查清单

```bash
#!/bin/bash
# env_check.sh - 环境健康检查脚本

echo "========================================"
echo "  滨发协同系统 - 压测环境检查"
echo "  检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
echo ""

# 1. 基础设施检查
echo "[1/7] 检查服务器资源..."
echo "CPU核数: $(nproc)"
echo "总内存: $(free -h | awk '/Mem:/ {print $2}')"
echo "磁盘空间: $(df -h / | awk 'NR==2 {print $4}') 可用"

# 2. Docker服务状态
echo ""
echo "[2/7] 检查Docker容器状态..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 3. 应用健康检查
echo ""
echo "[3/7] 检查应用健康状态..."
HEALTH=$(curl -s http://localhost:5002/api/health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
echo "FastAPI状态: $HEALTH"

# 4. 数据库连接
echo ""
echo "[4/7] 检查数据库连接..."
mysql -h localhost -u erp_test -pTest@123\! erp_test -e "SELECT COUNT(*) as user_count FROM users;" 2>/dev/null

# 5. Redis连接
echo ""
echo "[5/7] 检查Redis连接..."
redis-cli ping

# 6. JMeter配置
echo ""
echo "[6/7] 检查JMeter配置..."
java -version 2>&1 | head -1
ls -lh /opt/jmeter/bin/jmeter

# 7. 网络连通性
echo ""
echo "[7/7] 检查网络连通性..."
ping -c 3 localhost > /dev/null && echo "✓ 本地网络正常" || echo "✗ 网络异常"

echo ""
echo "========================================"
echo "  环境检查完成"
echo "========================================"
```

#### Phase 2: 脚本调试标准流程

```
调试步骤:
1. 单接口验证
   ↓
   curl -X GET "http://localhost:5002/api/v1/products?page=1&size=5" \
        -H "Authorization: Bearer test_token"
   ↓
   预期: 返回200 + JSON数据
   ↓
2. JMeter录制/手动编写脚本
   ↓
3. 添加断言 (Response Code=200, JSON Path验证)
   ↓
4. 参数化 (Token、动态ID、分页参数)
   ↓
5. 关联处理 (如需要从上一个接口提取数据)
   ↓
6. 小规模运行 (1线程, 1次循环)
   ↓
7. 查看结果树,确认无误
   ↓
8. 逐步增加并发 (5 → 10 → 50)
   ↓
9. 监控错误率和响应时间
   ↓
10. 进入正式测试
```

### 5.3 测试执行命令速查

```bash
# ========== JMeter 命令集 ==========

# GUI模式调试
/opt/jmeter/bin/jmeter -t test_plans/smoke_test.jmx -n -l results/smoke_test.jtl

# 非GUI模式执行 (推荐生产使用)
/opt/jmeter/bin/jmx \
  -n \
  -t test_plans/stress_test_full.jmx \
  -l results/full_test_$(date +%Y%m%d_%H%M%S).jtl \
  -e -o report/html_report_$(date +%Y%m%d_%H%M%S) \
  -Jthreads=500 \
  -Jrampup=60 \
  -Jduration=300 \
  -Jhost=localhost \
  -Jport=5002

# 分布式压测 (多机协同)
/opt/jmeter/bin/jmx -n -R slave1,slave2,slave3 -t distributed_test.jmx

# 仅运行下载测试
/opt/jmeter/bin/jmx -n -t download_stress_test.jmx \
  -l results/download_$(date +%Y%m%d).jtl \
  -Jconcurrent_downloads=100 \
  -Jfile_sizes="10MB,50MB,100MB"

# ========== 监控命令集 ==========

# 实时查看系统资源
watch -n 1 'echo "=== 系统资源 ===" && free -h && echo "" && top -bn1 | head -5'

# MySQL连接数监控
mysqladmin -u root -p status | grep Connections

# FastAPI进程状态
ps aux | grep uvicorn | grep -v grep

# Nginx连接状态
curl -s http://localhost/nginx_status | awk '{print $3}'
```

---

## 6. 监控指标设定

### 6.1 核心KPI指标体系

#### 6.1.1 应用层指标

| 指标名称 | 英文标识 | 计算公式 | 基线值 | 警戒值 | 危险值 |
|---------|---------|---------|-------|-------|-------|
| **平均响应时间** | Avg_RT | Σ(响应时间)/请求数 | < 200ms | 500ms | > 2000ms |
| **P95响应时间** | P95_RT | 95%分位值 | < 500ms | 1000ms | > 3000ms |
| **P99响应时间** | P99_RT | 99%分位值 | < 1000ms | 2000ms | > 5000ms |
| **吞吐量(TPS)** | TPS | 成功请求数/秒 | > 500 | 300 | < 100 |
| **错误率** | Error_Rate | 失败请求数/总请求数×100% | < 0.1% | 1% | > 5% |
| **并发用户数** | Concurrent_Users | 活跃线程数 | - | - | - |

#### 6.1.2 下载专项指标

| 指标名称 | 英文标识 | 基线值 | 警戒值 | 危险值 | 说明 |
|---------|---------|-------|-------|-------|------|
| **下载成功率** | Download_Success_Rate | > 99.9% | 99% | < 95% | 包含完整性校验 |
| **平均下载速度** | Avg_Download_Speed | > 5 MB/s | 2 MB/s | < 1 MB/s | 取决于文件大小 |
| **下载超时率** | Timeout_Rate | < 0.01% | 0.1% | > 1% | 120s内未完成 |
| **文件损坏率** | Corruption_Rate | 0% | 0% | > 0% | MD5/SHA256校验失败 |
| **并发连接利用率** | Conn_Pool_Utilization | < 70% | 85% | > 95% | 连接池占用量 |

#### 6.1.3 资源层指标

| 资源类型 | 监控项 | 基线值 | 警戒值 | 危险值 | 采集频率 |
|---------|-------|-------|-------|-------|---------|
| **CPU** | 使用率 | < 40% | 70% | > 85% | 5s |
| **内存** | 使用率 | < 60% | 75% | > 90% | 5s |
| **磁盘I/O** | IOWAIT | < 5% | 15% | > 30% | 10s |
| **网络** | 带宽利用率 | < 30% | 60% | > 85% | 10s |
| **MySQL** | 活跃连接数 | < 50 | 200 | > 400 | 5s |
| **MySQL** | 慢查询数(/min) | < 5 | 20 | > 50 | 60s |
| **Redis** | 内存使用率 | < 50% | 70% | > 85% | 10s |
| **MySQL** | InnoDB Buffer命中率 | > 99% | 95% | < 90% | 30s |

### 6.2 监控架构图

```
                    ┌─────────────────┐
                    │  Grafana 仪表板  │
                    │  (可视化展示)    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ Prometheus │ │ InfluxDB   │ │ JMeter     │
     │ (系统指标) │ │ (性能数据) │ │ (原生结果) │
     └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
           │              │              │
    ┌──────┴──────┐ ┌─────┴──────┐ ┌─────┴──────┐
    │Node Exporter│ │Telegraf   │ │JMeter      │
    │(服务器指标) │ │(应用指标)  │ │Backend     │
    └──────┬──────┘ └─────┬──────┘ └────────────┘
           │              │
    ┌──────┴──────────────┴──────┐
    │         被测系统             │
    │  FastAPI + MySQL + Redis    │
    └─────────────────────────────┘
```

### 6.3 Prometheus + Grafana 监控配置

#### 6.3.1 prometheus.yml 配置

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: 'fastapi-app'
    static_configs:
      - targets: ['localhost:5002']
    metrics_path: '/metrics'
    
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
      
  - job_name: 'mysql-exporter'
    static_configs:
      - targets: ['localhost:9104']
      
  - job_name: 'redis-exporter'
    static_configs:
      - targets: ['localhost:9121']
```

#### 6.3.2 Grafana Dashboard 关键面板

| 面板ID | 面板名称 | 查询语句(PromQL) | 阈值线 |
|-------|---------|------------------|-------|
| 1 | QPS趋势 | `sum(rate(http_requests_total[1m]))` | - |
| 2 | P95响应时间 | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))` | 1s |
| 3 | 错误率 | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100` | 1% |
| 4 | CPU使用率 | `100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)` | 70%/85% |
| 5 | 内存使用率 | `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100` | 75%/90% |
| 6 | MySQL连接数 | `mysql_global_status_threads_connected` | 200/400 |
| 7 | Redis内存 | `redis_memory_used_bytes / redis_memory_max_bytes * 100` | 70%/85% |

### 6.4 JMeter内置监听器配置

```xml
<!-- Summary Report - 摘要报告 -->
<ResultCollector guiclass="SummaryReport" testclass="ResultCollector" testname="摘要报告">
  <boolProp name="error_logging">false</boolProp>
  <objProp>
    <value class="SampleSaveConfiguration">
      <time>true</time>
      <latency>true</latency>
      <timestamp>true</timestamp>
      <success>true</success>
      <label>true</label>
      <code>true</code>
      <message>true</message>
      <threadName>true</threadName>
      <dataType>true</dataType>
      <encoding>false</encoding>
      <assertions>true</assertions>
      <subresults>true</subresults>
      <responseData>false</responseData>
      <samplerData>false</samplerData>
      <xml>false</xml>
      <fieldNames>true</fieldNames>
      <responseHeaders>false</responseHeaders>
      <requestHeaders>false</requestHeaders>
      <responseDataOnError>false</responseDataOnError>
      <saveAssertionResultsFailureMessage>true</saveAssertionResultsFailureMessage>
      <assertionsResultsToSave>0</assertionsResultsToSave>
      <bytes>true</bytes>
      <sentBytes>true</sentBytes>
      <url>true</url>
      <threadCounts>true</threadCounts>
      <idleTime>true</idleTime>
      <connectTime>true</connectTime>
    </value>
  </objProp>
  <stringProp name="filename"></stringProp>
</ResultCollector>

<!-- Response Times Over Time - 响应时间趋势图 -->
<ResponseGraph guiclass="ResponseTimesGraphVisualizer" testclass="GraphAccumulator" testname="响应时间趋势">
  <collectionProp name="GraphAccumulator.graph_items">
    ...
  </collectionProp>
</ResponseGraph>
```

---

## 7. 风险评估与应急预案

### 7.1 风险识别矩阵

| 风险ID | 风险描述 | 可能性 | 影响程度 | 风险等级 | 触发条件 |
|-------|---------|-------|---------|---------|---------|
| RSK-001 | 测试环境宕机 | 中 | 高 | 🔴高 | CPU>95%持续5min |
| RSK-002 | 数据库连接池耗尽 | 高 | 高 | 🔴高 | 活跃连接>450 |
| RSK-003 | 测试数据污染生产 | 低 | 极高 | 🔴高 | 误连生产库 |
| RSK-004 | 磁盘空间不足 | 中 | 中 | 🟡中 | 使用率>90% |
| RSK-005 | 网络带宽打满 | 中 | 中 | 🟡中 | 带宽>800Mbps |
| RSK-006 | Redis内存溢出 | 低 | 高 | 🟡中 | 内存>95% |
| RSK-007 | 日志文件过大 | 高 | 低 | 🟢低 | 日志目录>10GB |
| RSK-008 | 下载文件堆积 | 中 | 中 | 🟡中 | 临时文件>5GB |

### 7.2 应急预案详解

#### 7.2.1 RSK-001: 环境宕机应急

**预警信号**:
- 系统无响应超过30秒
- SSH无法连接
- 应用进程崩溃退出

**应急操作流程**:

```bash
# 1. 立即停止压测 (第一优先级)
kill -9 $(pgrep -f "jmeter.*stress")
echo "$(date): [紧急] 已终止所有压测进程" >> test_emergency.log

# 2. 检查系统状态
echo "=== 系统紧急状态报告 ===" >> emergency_report_$(date +%Y%m%d).log
uptime >> emergency_report_$(date +%Y%m%d).log
free -h >> emergency_report_$(date +%Y%m%d).log
df -h >> emergency_report_$(date +%Y%m%d).log
ps aux --sort=-%mem | head -10 >> emergency_report_$(date +%Y%m%d).log

# 3. 重启关键服务
docker restart fastapi-app
sleep 10
docker ps | grep fastapi

# 4. 验证恢复
curl -f http://localhost:5002/api/health && echo "✓ 系统已恢复" || echo "✗ 恢复失败，需人工介入"

# 5. 通知相关人员
# 发送邮件/钉钉/企业微信告警
```

#### 7.2.2 RSK-002: 数据库连接池耗尽应急

**预防措施**:
```sql
-- 设置合理的连接数限制
SET GLOBAL max_connections = 500;
SHOW VARIABLES LIKE 'max_connections';
SHOW STATUS LIKE 'Threads_connected';
```

**应急SQL脚本**:

```sql
-- emergency_db.sql - 数据库急救脚本
-- 1. 查看当前连接详情
SELECT 
    id,
    user,
    host,
    db,
    command,
    time,
    state,
    info
FROM information_schema.processlist
WHERE command != 'Sleep'
ORDER BY time DESC
LIMIT 20;

-- 2. 终止长时间运行的空闲连接 (谨慎使用)
-- SELECT concat('KILL ',id,';') 
-- FROM information_schema.processlist 
-- WHERE command='Sleep' AND time > 300;

-- 3. 查看连接数趋势
SHOW STATUS LIKE 'Threads_connected';
SHOW STATUS LIKE 'Connections';
SHOW STATUS LIKE 'Max_used_connections';
```

#### 7.2.3 RSK-003: 数据污染防护措施

**强制隔离规则**:

```bash
# pre_test_check.sh - 测试前安全检查
#!/bin/bash

TARGET_DB="erp_test"
PRODUCTION_DB="erp_production"

# 检查当前连接的数据库
CURRENT_DB=$(mysql -N -s -e "SELECT DATABASE();")

if [[ "$CURRENT_DB" == "$PRODUCTION_DB" ]]; then
    echo "🚨🚨🚨 致命错误: 当前连接的是生产数据库!!! 🚨🚨🚨"
    echo "立即终止所有操作!"
    exit 1
fi

# 验证测试数据库特征
TABLE_COUNT=$(mysql -N -s $TARGET_DB -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$TARGET_DB';")

if [[ "$TABLE_COUNT" -lt 10 ]]; then
    echo "⚠️  警告: 测试数据库表数量异常少 ($TABLE_COUNT)，请确认是否为正确的测试环境"
    read -p "是否继续? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        exit 1
    fi
fi

echo "✓ 安全检查通过: 当前数据库=$TARGET_DB, 表数量=$TABLE_COUNT"
```

#### 7.2.4 RSK-008: 下载文件清理机制

```python
# utils/cleanup_downloads.py - 自动清理脚本
import os
import time
from datetime import datetime, timedelta

DOWNLOAD_DIR = "/tmp/jmeter_downloads"
MAX_SIZE_GB = 5
MAX_AGE_HOURS = 24

def cleanup_download_files():
    """清理测试下载文件"""
    total_freed = 0
    now = datetime.now()
    
    if not os.path.exists(DOWNLOAD_DIR):
        return
    
    for filename in os.listdir(DOWNLOAD_DIR):
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        
        if os.path.isfile(filepath):
            # 检查文件年龄
            file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            age_hours = (now - file_mtime).total_seconds() / 3600
            
            if age_hours > MAX_AGE_HOURS:
                file_size = os.path.getsize(filepath)
                os.remove(filepath)
                total_freed += file_size
                print(f"已删除: {filename} ({file_size/1024/1024:.2f}MB)")
    
    print(f"\n清理完成: 共释放 {total_freed/1024/1024/1024:.2f}GB 空间")

if __name__ == "__main__":
    cleanup_download_files()
```

### 7.3 应急联系人名单

| 角色 | 姓名 | 电话 | 邮箱 | 职责 |
|-----|------|------|------|------|
| **测试负责人** | [待填写] | [待填写] | [待填写] | 测试决策与协调 |
| **运维负责人** | [待填写] | [待填写] | [待填写] | 环境保障与恢复 |
| **DBA** | [待填写] | [待填写] | [待填写] | 数据库问题处理 |
| **开发负责人** | [待填写] | [待填写] | [待填写] | 性能问题分析 |

---

## 8. 测试报告模板及分析方法

### 8.1 报告文档结构模板

```markdown
# 滨发协同系统 - 性能测试报告

**报告编号**: PERF-2026-0411-001  
**测试版本**: v2.0.0  
**测试日期**: 2026-04-11 ~ 2026-04-13  
**测试人员**: [姓名]  
**审核人员**: [姓名]

---

## 1. 执行摘要

### 1.1 测试结论
- 总体评价: ✅ 通过 / ⚠️ 有条件通过 / ❌ 不通过
- 核心发现: [3-5个关键结论]

### 1.2 关键指标达成情况

| 指标 | 目标值 | 实际值 | 达成率 | 状态 |
|-----|-------|-------|-------|------|
| 平均RT | < 200ms | xxx ms | xx% | ✅/❌ |
| P95 RT | < 500ms | xxx ms | xx% | ✅/❌ |
| TPS | > 500 | xxx | xx% | ✅/❌ |
| 错误率 | < 0.1% | x.xx% | - | ✅/❌ |
| 下载成功率 | > 99.9% | xx.xx% | - | ✅/❌ |

## 2. 测试环境

### 2.1 环境配置
[硬件/软件/网络配置表格]

### 2.2 数据规模
[测试数据量说明]

## 3. 测试执行概况

### 3.1 场景执行记录

| 场景ID | 场景名称 | 执行时间 | 并发数 | 持续时间 | 结果 |
|-------|---------|---------|-------|---------|------|
| SMC-001 | ... | ... | ... | ... | ... |

## 4. 性能测试结果详析

### 4.1 API接口性能
[图表 + 数据表格]

### 4.2 下载接口专项
[大文件/并发/完整性测试结果]

### 4.3 资源使用分析
[CPU/内存/IO/网络趋势图]

## 5. 瓶颈分析与优化建议

### 5.1 发现的性能瓶颈
1. [瓶颈1描述]
2. [瓶颈2描述]
...

### 5.2 优化建议
| 编号 | 建议 | 优先级 | 预期效果 | 负责人 |
|-----|------|-------|---------|-------|
| OPT-001 | ... | P0/P1/P2 | ... | ... |

## 6. 风险与遗留问题

### 6.1 未解决问题
[问题描述 + 影响 + 建议]

### 6.2 后续计划
[下一步行动项]

## 7. 附录

- 附录A: JMeter原始数据(.jtl)
- 附录B: Grafana截图
- 附录C: 服务器监控日志
- 附录D: 完整测试脚本
```

### 8.2 数据分析方法论

#### 8.2.1 瓶颈定位方法

```
第一步: 观察现象
    ↓
    响应时间突增? 错误率飙升? 吞吐量下降?
    ↓
第二步: 层层下钻
    ↓
    应用层 → 数据库层 → 系统资源层 → 网络层
    ↓
第三步: 对比分析
    ↓
    基线 vs 当前 | 不同并发对比 | 同类接口对比
    ↓
第四步: 根因确认
    ↓
    慢SQL? 锁竞争? GC频繁? 带宽瓶颈?
    ↓
第五步: 验证假设
    ↓
    调整参数后重新测试 → 确认改善效果
```

#### 8.2.2 常见瓶颈特征对照表

| 瓶颈类型 | 特征表现 | 验证方法 | 解决方向 |
|---------|---------|---------|---------|
| **CPU瓶颈** | CPU>85%, RT线性增长, 无队列积压 | top/htop | 算法优化/水平扩展 |
| **内存瓶颈** | Swap使用增加, GC频繁, OOM | free -h / jstat | 增加内存/代码优化 |
| **IO瓶颈** | iowait>15%, 磁盘利用率100% | iostat / vmstat | SSD升级/读写分离 |
| **数据库瓶颈** | 慢查询增多, 连接等待 | slow_log / SHOW PROCESSLIST | SQL优化/索引调整 |
| **网络瓶颈** | 带宽饱和, 重传率高 | iftop / netstat | 带宽扩容/CDN加速 |
| **锁竞争** | 事务等待时间长, 死锁 | SHOW ENGINE INNODB STATUS | 减小事务粒度/乐观锁 |
| **连接池耗尽** | 大量获取连接超时错误 | 连接池监控 | 调整池大小/优化持有时间 |

#### 8.2.3 图表解读指南

**响应时间-并发数曲线 (R-T Curve)**:
```
RT(ms)
  ^
  │                    ← 突变点(拐点)
  │                  ╱
  │                ╱
  │              ╱
  │            ╱
  │          ╱
  │        ╱
  │______╱____________________→ 并发数
        ↑
      最优并发区间
```

**解读要点**:
- **平缓区**: 系统有富余容量
- **缓升区**: 开始出现资源竞争
- **陡升区**: 已达瓶颈，接近崩溃
- **拐点**: 系统最大承载能力的标志

### 8.3 自动化报告生成脚本

```python
# utils/generate_report.py - 自动生成测试报告
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from jinja2 import Template

def parse_jmeter_results(jtl_file):
    """解析JMeter结果文件"""
    tree = ET.parse(jtl_file)
    root = tree.getroot()
    
    results = []
    for sample in root.findall('httpSample'):
        result = {
            'label': sample.get('label'),
            'timestamp': sample.get('ts'),
            'elapsed': int(sample.get('t')),
            'success': sample.get('s') == 'true',
            'bytes': int(sample.get('by')),
            'response_code': sample.get('rc'),
        }
        results.append(result)
    
    return calculate_metrics(results)

def calculate_metrics(results):
    """计算关键指标"""
    total = len(results)
    success_count = sum(1 for r in results if r['success'])
    
    elapsed_times = [r['elapsed'] for r in results]
    elapsed_times.sort()
    
    p50_idx = int(total * 0.50)
    p95_idx = int(total * 0.95)
    p99_idx = int(total * 0.99)
    
    metrics = {
        'total_requests': total,
        'success_count': success_count,
        'error_count': total - success_count,
        'error_rate': f"{(total - success_count) / total * 100:.2f}%",
        'avg_rt': f"{sum(elapsed_times) / total:.0f}ms",
        'p50_rt': f"{elapsed_times[p50_idx]}ms",
        'p95_rt': f"{elapsed_times[p95_idx]}ms",
        'p99_rt': f"{elapsed_times[p99_idx]}ms",
        'throughput': f"{total / (max(r['timestamp'] for r in results) - min(r['timestamp'] for r in results)) * 1000:.1f}/s",
    }
    
    return metrics

def generate_html_report(metrics, output_file):
    """生成HTML格式报告"""
    template = Template("""
<!DOCTYPE html>
<html>
<head>
    <title>性能测试报告</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .metric-card { display: inline-block; margin: 10px; padding: 20px; border-radius: 8px; background: #f5f5f5; }
        .pass { color: green; } .fail { color: red; } .warn { color: orange; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #4CAF50; color: white; }
    </style>
</head>
<body>
    <h1>滨发协同系统 - 性能测试报告</h1>
    <p>生成时间: {{ timestamp }}</p>
    
    <h2>核心指标概览</h2>
    <div class="metric-card">
        <h3>总请求数</h3><p>{{ metrics.total_requests }}</p>
    </div>
    <div class="metric-card">
        <h3>错误率</h3><p class="{{ 'fail' if metrics.error_rate|float > 1 else 'pass' }}">{{ metrics.error_rate }}</p>
    </div>
    <div class="metric-card">
        <h3>平均响应时间</h3><p>{{ metrics.avg_rt }}</p>
    </div>
    <div class="metric-card">
        <h3>P95响应时间</h3><p>{{ metrics.p95_rt }}</p>
    </div>
    <div class="metric-card">
        <h3>吞吐量</h3><p>{{ metrics.throughput }}</p>
    </div>
    
    <h2>详细数据</h2>
    <table>
        <tr><th>指标</th><th>数值</th><th>判定</th></tr>
        {% for key, value in metrics.items() %}
        <tr><td>{{ key }}</td><td>{{ value }}</td><td>-</td></tr>
        {% endfor %}
    </table>
</body>
</html>
    """)
    
    html_content = template.render(
        metrics=metrics,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ 报告已生成: {output_file}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <jtl文件>")
        sys.exit(1)
    
    metrics = parse_jmeter_results(sys.argv[1])
    generate_html_report(metrics, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
```

---

## 9. 执行明细与通过标准

### 9.1 测试阶段任务分解

#### Phase 1: 环境准备 (预计耗时: 4小时)

| 任务ID | 任务内容 | 负责人 | 预计工时 | 前置依赖 | 交付物 | 验收标准 |
|-------|---------|-------|---------|---------|-------|---------|
| TSK-001 | 申请测试服务器资源 | 运维 | 0.5h | - | 服务器访问权限 | 可SSH登录 |
| TSK-002 | 部署Docker测试环境 | 运维 | 1h | TSK-001 | docker-compose up成功 | 所有容器Running |
| TSK-003 | 初始化测试数据库 | DBA | 1h | TSK-002 | 数据导入完成 | 表结构与生产一致 |
| TSK-004 | 生成测试数据 | 开发 | 1h | TSK-003 | 数据生成脚本执行完毕 | 数据量达标(见2.4.1) |
| TSK-005 | 安装配置JMeter | 测试 | 0.5h | TSK-001 | JMeter可用 | jmeter -v正常 |
| TSK-006 | 部署监控系统 | 运维 | 1h | TSK-002 | Prometheus+Grafana运行 | 仪表板可访问 |

#### Phase 2: 脚本开发与调试 (预计耗时: 8小时)

| 任务ID | 任务内容 | 负责人 | 预计工时 | 前置依赖 | 交付物 | 验收标准 |
|-------|---------|-------|---------|---------|-------|---------|
| TSK-007 | 录制/编写API基础脚本 | 测试 | 2h | TSK-005 | .jmx脚本文件 | 脚本可独立运行 |
| TSK-008 | 实现参数化和关联 | 测试 | 2h | TSK-007 | 参数化后的脚本 | 动态数据正确替换 |
| TSK-009 | 开发下载测试脚本 | 测试 | 2h | TSK-007 | 下载专项脚本 | 文件可下载且完整 |
| TSK-010 | 配置断言和校验规则 | 测试 | 1h | TSK-008 | 断言配置 | 异常能被捕获 |
| TSK-011 | 小规模预演(冒烟测试) | 测试 | 1h | TSK-010 | 冒烟测试结果 | 错误率为0 |

#### Phase 3: 正式测试执行 (预计耗时: 48小时，含稳定性测试)

| 任务ID | 任务内容 | 负责人 | 预计工时 | 前置依赖 | 交付物 | 验收标准 |
|-------|---------|-------|---------|---------|-------|---------|
| TSK-012 | 执行基线测试(SMC-001~006) | 测试 | 4h | TSK-011 | 基线数据报告 | 所有基线指标记录 |
| TSK-013 | 执行负载/压力测试(SMC-007~009) | 测试 | 6h | TSK-012 | 压力测试原始数据 | 数据完整无丢失 |
| TSK-014 | 执行下载专项测试(SMC-011~013) | 测试 | 4h | TSK-012 | 下载测试报告 | 包含完整性校验结果 |
| TSK-015 | 执行稳定性测试(SMC-010) | 测试 | 24h+ | TSK-013 | 稳定性监控数据 | 无内存泄漏/OOM |
| TSK-016 | 实时监控与问题记录 | 测试+运维 | 全程 | TSK-012 | 监控日志 | 异常事件全部记录 |

#### Phase 4: 分析与报告 (预计耗时: 8小时)

| 任务ID | 任务内容 | 负责人 | 预计工时 | 前置依赖 | 交付物 | 验收标准 |
|-------|---------|-------|---------|---------|-------|---------|
| TSK-017 | 数据整理与清洗 | 测试 | 2h | TSK-015 | 清洗后的数据集 | 数据准确完整 |
| TSK-018 | 瓶颈分析与根因定位 | 测试+开发 | 3h | TSK-017 | 瓶颈分析报告 | 至少识别3个瓶颈点 |
| TSK-019 | 编写测试报告 | 测试 | 2h | TSK-018 | 最终测试报告 | 符合8.1模板要求 |
| TSK-020 | 组织评审会议 | 测试经理 | 1h | TSK-019 | 评审纪要 | 结论明确可追溯 |

### 9.2 通过/不通过判定标准

#### 9.2.1 总体判定规则

```
判定逻辑:
IF (所有P0场景通过) AND (P1场景通过率 >= 80%) AND (无阻塞性问题)
    THEN 结论 = "✅ 通过" → 可上线
ELSE IF (P0场景存在轻微偏差) AND (有优化方案)
    THEN 结论 = "⚠️ 有条件通过" → 修复后回归
ELSE
    THEN 结论 = "❌ 不通过" → 禁止上线
```

#### 9.2.2 各场景具体通过标准

| 场景ID | 核心指标 | 通过标准 | 有条件通过 | 不通过 |
|-------|---------|---------|-----------|-------|
| **SMC-001~006** (基线) | Avg RT | < 200ms | 200-500ms | > 500ms |
| | Error Rate | < 0.1% | 0.1%-1% | > 1% |
| **SMC-007** (混合负载) | P95 RT | < 1000ms | 1000-2000ms | > 2000ms |
| | TPS | > 300/s | 200-300/s | < 200/s |
| | Error Rate | < 0.5% | 0.5%-2% | > 2% |
| **SMC-008** (峰值压力) | P99 RT | < 3000ms | 3000-5000ms | > 5000ms |
| | 系统可用性 | 100% | > 99% | < 99% |
| **SMC-010** (稳定性) | 内存增长 | < 5%/8h | 5-10%/8h | > 10%/8h |
| | 无OOM/重启 | 是 | - | 发生OOM或重启 |
| **SMC-011** (大文件下载) | 成功率 | 100% | > 99% | < 99% |
| | 完整性校验 | 100%通过 | > 99%通过 | 存在校验失败 |
| | Avg Speed | > 3 MB/s | 1-3 MB/s | < 1 MB/s |
| **SMC-012** (并发下载) | 429错误率 | < 1% | 1-5% | > 5% |
| | 连接池未耗尽 | 是 | 偶发耗尽 | 频繁耗尽 |
| | 服务端正常响应 | 是 | 偶发超时 | 大面积超时 |

#### 9.2.3 阻塞性问题定义

以下任一情况发生即视为**阻塞性问题**，必须修复后方可上线：

1. ❌ 任何P0场景的错误率超过5%
2. ❌ 发生数据库死锁导致业务中断
3. ❌ 出现OOM（OutOfMemory）导致服务崩溃
4. ❌ 下载文件损坏率>0%
5. ❌ 数据不一致（如库存扣减错误）
6. ❌ 安全漏洞暴露（如未授权访问）

### 9.3 团队分工与职责

| 角色 | 主要职责 | 参与阶段 | 产出物 |
|-----|---------|---------|-------|
| **测试负责人** | 方案制定、脚本开发、执行测试、报告编写 | 全程 | 测试方案、脚本、报告 |
| **性能测试工程师** | 场景设计、数据分析、瓶颈定位 | Phase 2-4 | 测试数据、分析结论 |
| **开发工程师** | 环境配合、问题修复、优化实施 | Phase 1,3,4 | 修复补丁、优化方案 |
| **DBA** | 数据库调优、慢SQL分析、索引优化 | Phase 3-4 | SQL优化建议 |
| **运维工程师** | 环境部署、监控配置、应急处理 | Phase 1,3 | 部署文档、监控仪表板 |
| **项目经理** | 资源协调、进度把控、风险决策 | 全程 | 项目计划、评审纪要 |

### 9.4 时间规划甘特图

```
Week 1:
Mon   Tue   Wed   Thu   Fri   Sat   Sun
│环境准备│脚本开发│脚本开发│基线测试│压力测试│压力测试│专项测试│
│TSK001 │TSK007 │TSK009 │TSK012 │TSK013 │TSK013 │TSK014 │
│TSK002 │TSK008 │TSK010 │       │       │       │       │
│TSK003 │       │TSK011 │       │       │       │       │
│TSK004 │       │       │       │       │       │       │
│TSK005 │       │       │       │       │       │       │
│TSK006 │       │       │       │       │       │       │

Week 2:
Mon   Tue   Wed   Thu   Fri   Sat   Sun
│稳定性测试│稳定性测试│稳定性测试│稳定性测试│分析与报告│分析与报告│评审│
│TSK015  │TSK015  │TSK015  │TSK015  │TSK017  │TSK019  │TSK020│
│TSK016  │TSK016  │TSK016  │TSK016  │TSK018  │       │      │
```

---

## 10. 附录: JMeter脚本示例

### 10.1 项目结构

```
stress_test_project/
├── README.md                          # 本文档
├── test_plans/
│   ├── smoke_test.jmx                 # 冒烟测试脚本
│   ├── api_baseline.jmx               # API基线测试
│   ├── mixed_load.jmx                 # 混合负载测试
│   ├── stress_peak.jmx                # 峰值压力测试
│   ├── endurance.jmx                  # 稳定性测试
│   ├── download_large_file.jmx        # 大文件下载测试
│   ├── download_concurrent.jmx        # 并发下载测试
│   └── full_suite.jmx                 # 完整测试套件
├── data/
│   ├── test_users.csv                 # 测试用户数据
│   ├── product_ids.csv                # 产品ID列表
│   ├── order_payloads.json            # 订单JSON模板
│   └── expected_checksums.txt         # 期望的文件校验值
├── config/
│   ├── jmeter.properties              # JMeter自定义配置
│   └── user.properties                # 用户自定义变量
├── results/
│   ├── *.jtl                          # 原始测试结果
│   └── html_reports/                  # HTML报告输出
├── scripts/
│   ├── generate_test_data.py          # 测试数据生成
│   ├── cleanup_downloads.py           # 下载文件清理
│   ├── generate_report.py             # 报告生成
│   └── env_check.sh                   # 环境检查
├── docker/
│   ├── docker-compose.test.yml        # 测试环境编排
│   └── nginx-test.conf                # Nginx配置
└── monitoring/
    ├── prometheus.yml                 # Prometheus配置
    └── grafana_dashboards/            # Grafana仪表板JSON
```

### 10.2 完整测试脚本骨架 (download_concurrent.jmx)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="高并发下载压力测试">
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments">
        <collectionProp name="Arguments.arguments">
          <elementProp name="HOST" elementType="Argument">
            <stringProp name="Argument.name">HOST</stringProp>
            <stringProp name="Argument.value">localhost</stringProp>
          </elementProp>
          <elementProp name="PORT" elementType="Argument">
            <stringProp name="Argument.name">PORT</stringProp>
            <stringProp name="Argument.value">5002</stringProp>
          </elementProp>
          <elementProp name="CONCURRENT_USERS" elementType="Argument">
            <stringProp name="Argument.name">CONCURRENT_USERS</stringProp>
            <stringProp name="Argument.value">500</stringProp>
          </elementProp>
          <elementProp name="RAMP_UP" elementType="Argument">
            <stringProp name="Argument.name">RAMP_UP</stringProp>
            <stringProp name="Argument.value">60</stringProp>
          </elementProp>
          <elementProp name="DURATION" elementType="Argument">
            <stringProp name="Argument.name">DURATION</stringProp>
            <stringProp name="Argument.value">900</stringProp>
          </elementProp>
        </collectionProp>
      </elementProp>
    </TestPlan>
    <hashTree>
      
      <!-- 线程组: 阶梯式加压 -->
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="并发下载用户组">
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
        <stringProp name="ThreadGroup.num_threads">${CONCURRENT_USERS}</stringProp>
        <stringProp name="ThreadGroup.ramp_time">${RAMP_UP}</stringProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">${DURATION}</stringProp>
        <stringProp name="ThreadGroup.delay">0</stringProp>
      </ThreadGroup>
      <hashTree>
        
        <!-- 登录获取Token -->
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="用户登录">
          <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
          <stringProp name="HTTPSampler.domain">${HOST}</stringProp>
          <stringProp name="HTTPSampler.port">${PORT}</stringProp>
          <stringProp name="HTTPSampler.path">/api/v1/users/login</stringProp>
          <stringProp name="HTTPSampler.method">POST</stringProp>
          <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
          <HTTPSamplerProxy>
            <elementProp name="HTTPsampler.Arguments" elementType="Arguments">
              <collectionProp name="Arguments.arguments">
                <elementProp name="username" elementType="HTTPArgument">
                  <stringProp name="Argument.name">username</stringProp>
                  <stringProp name="Argument.value">perf_test_user</stringProp>
                </elementProp>
                <elementProp name="password" elementType="HTTPArgument">
                  <stringProp name="Argument.name">password</stringProp>
                  <stringProp name="Argument.value">Test@123!</stringProp>
                </elementProp>
              </collectionProp>
            </elementProp>
          </HTTPSamplerProxy>
          
          <!-- 提取Token到变量 -->
          <PostProcessor guiclass="JSONPostProcessor" testclass="JSONPostProcessor" testname="JSON提取器">
            <stringProp name="JSONPostProcessor.referenceNames">TOKEN</stringProp>
            <stringProp name="JSONPostProcessor.jsonPathExprs">$..access_token</stringProp>
            <stringProp name="JSONPostProcessor.match_numbers">1</stringProp>
          </PostProcessor>
        </HTTPSamplerProxy>
        <hashTree/>
        
        <!-- 思考时间: 模拟用户阅读操作间隔 -->
        <ConstantTimer guiclass="ConstantTimerGui" testclass="ConstantTimer" testname="思考时间(1-3秒)">
          <stringProp name="ConstantTimer.delay">${__Random(1000,3000)}</stringProp>
        </ConstantTimer>
        <hashTree/>
        
        <!-- 下载请求采样器 -->
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="下载采购单Excel">
          <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
          <stringProp name="HTTPSampler.domain">${HOST}</stringProp>
          <stringProp name="HTTPSampler.port">${PORT}</stringProp>
          <stringProp name="HTTPSampler.path">/api/v1/purchase-center/export?format=xlsx&date_range=2026-01-01~2026-04-11</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
          <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
          <stringProp name="HTTPSampler.connect_timeout">30000</stringProp>
          <stringProp name="HTTPSampler.response_timeout">180000</stringProp>
          
          <HeaderManager>
            <collectionProp name="headers">
              <elementProp name="Authorization" elementType="Header">
                <stringProp name="Header.name">Authorization</stringProp>
                <stringProp name="Header.value">Bearer ${TOKEN}</stringProp>
              </elementProp>
              <elementProp name="Accept" elementType="Header">
                <stringProp name="Header.name">Accept</stringProp>
                <stringProp name="Header.value">application/vnd.openxmlformats-officedocument.spreadsheetml.sheet</stringProp>
              </elementProp>
            </collectionProp>
          </HeaderManager>
        </HTTPSamplerProxy>
        <hashTree>
          
          <!-- 保存下载文件 -->
          <Listener guiclass="SaveResponsesToFile" testclass="SaveResponsesToFile" testname="保存下载文件">
            <stringProp name="filename">results/downloads/download_${__threadNum}_${__time(yyyyMMdd-HHmmss)}.xlsx</stringProp>
            <boolProp name="save_successful_responses">true</boolProp>
            <boolProp name="save_failed_responses">true</boolProp>
          </Listener>
          
          <!-- 文件完整性校验(MD5) -->
          <PostProcessor guiclass="JSR223PostProcessor" testclass="JSR223PostProcessor" testname="MD5完整性校验">
            <stringProp name="scriptLanguage">groovy</stringProp>
            <stringProp name="parameters"></stringProp>
            <stringProp name="script">
import org.apache.commons.codec.digest.DigestUtils;
import java.io.ByteArrayInputStream;

byte[] responseData = prev.getResponseData();

if (responseData != null &amp;&amp; responseData.length > 0) {
    String md5Hex = DigestUtils.md5Hex(new ByteArrayInputStream(responseData));
    vars.put("file_md5", md5Hex);
    
    log.info("线程#" + ctx.getThreadNum() + " 下载完成, 文件大小: " + responseData.length + " bytes, MD5: " + md5Hex);
    
    if (responseData.length &lt; 1024) {
        SampleResult.setSuccessful(false);
        SampleResult.setResponseMessage("文件过小，可能下载失败");
    }
} else {
    SampleResult.setSuccessful(false);
    SampleResult.setResponseMessage("响应数据为空");
}
            </stringProp>
          </PostProcessor>
          
          <!-- 响应断言 -->
          <Assertion guiclass="ResponseAssertionGui" testclass="ResponseAssertion" testname="响应码断言">
            <collectionProp name="Asserion.test_strings">
              <stringProp name="49586">200</stringProp>
              <stringProp name="49586">429</stringProp>
            </collectionProp>
            <stringProp name="Assertion.custom_message">期望状态码200或429(限流)</stringProp>
          </Assertion>
          
          <!-- 响应头断言(Content-Type) -->
          <Assertion guiclass="ResponseAssertionGui" testclass="ResponseAssertion" testname="Content-Type断言">
            <collectionProp name="Asserion.test_strings">
              <stringProp name="49586">application/vnd.openxmlformats-officedocument.spreadsheetml.sheet</stringProp>
              <stringProp name="49586">application/octet-stream</stringProp>
            </collectionProp>
          </Assertion>
        </hashTree>
        
        <!-- 循环控制器: 模拟多次下载行为 -->
        <LoopController guiclass="LoopControlPanel" testclass="LoopController" testname="循环下载5次">
          <intProp name="LoopController.loops">5</intProp>
        </LoopController>
        <hashTree>
          <!-- 复用上面的下载采样器... -->
        </hashTree>
        
      </hashTree>
      
      <!-- 监听器配置 -->
      <ResultCollector guiclass="SummaryReport" testclass="ResultCollector" testname="汇总报告"/>
      <ResultCollector guiclass="StatVisualizer" testclass="ResultCollector" testname="聚合报告"/>
      <ResultCollector guiclass="GraphResultsVisualizer" testclass="GraphListener" testname="图形结果"/>
      <ResultCollector guiclass="ViewResultsFullVisualizer" testclass="ViewResultsFullVisualizer" testname="查看结果树"/>
      
    </hashTree>
  </hashTree>
</jmeterTestPlan>
```

### 10.3 CSV数据文件格式示例

**test_users.csv**:
```csv
username,password,role_id,user_id
perf_user_001,Test@123!,2,10001
perf_user_002,Test@123!,2,10002
...
perf_user_500,Test@123!,2,10500
```

**expected_checksums.txt**:
```csv
file_name,expected_md5,expected_sha256,size_bytes
purchase_template.xlsx,d41d8cd98f00b204e9800998ecf8427e,e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855,12345
report_full.xlsx,5d41402abc4b2a76b9719d911017c592,09a8fcf...d4e8,567890
```

---

## 文档修订历史

| 版本 | 日期 | 修订人 | 修订内容 |
|-----|------|-------|---------|
| v1.0 | 2026-04-11 | [作者名] | 初版发布 |

---

**文档结束**

> **注意事项**:
> 1. 本方案中涉及的具体数值（如并发数、阈值等）需根据实际压测结果进行调整
> 2. 所有密码和敏感信息在实际使用时应从安全存储中获取，禁止硬编码
> 3. 测试完成后务必执行数据清理脚本，删除所有测试生成的临时文件
> 4. 本文档应作为活文档维护，每次测试后更新基线数据和经验教训
