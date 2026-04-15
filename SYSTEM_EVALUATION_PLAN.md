# ERP系统全面评测方案

## 文档信息
- **项目名称**: ERP管理系统
- **评测版本**: v1.0
- **评测日期**: 2026-03-26
- **评测负责人**: QA团队
- **文档状态**: 待执行

---

## 1. 评测概述

### 1.1 评测目标
对即将上线的ERP系统进行全面、系统性的评测，确保其在正式环境中能够稳定、安全、高效地运行。本次评测需遵循行业最佳实践，采用科学的测试方法和工具，确保覆盖所有关键质量属性。

### 1.2 系统概况
- **技术栈**: Flask 2.3.3 + SQLAlchemy + Bootstrap 5 + Redis
- **数据库**: SQLite(开发) / MySQL 8.0(生产)
- **架构模式**: 单体模块化架构(Modular Monolith)
- **代码规模**: 39,855行 (核心业务9,478行)
- **功能模块**: 13个数据模型，10个业务蓝图

### 1.3 评测范围
| 评测维度 | 覆盖范围 | 优先级 |
|---------|---------|--------|
| 功能完整性 | 所有业务功能模块 | P0 |
| 性能测试 | 关键业务流程 | P0 |
| 安全性测试 | 认证授权、数据保护 | P0 |
| 兼容性测试 | 浏览器、操作系统 | P1 |
| 易用性测试 | UI/UX、操作流程 | P1 |
| 数据管理 | 备份恢复、数据迁移 | P1 |
| 错误处理 | 异常场景、日志记录 | P2 |

---

## 2. 功能完整性测试方案

### 2.1 测试策略
- **测试方法**: 黑盒测试 + 白盒测试
- **测试层级**: 单元测试 → 集成测试 → 系统测试
- **覆盖率目标**: 总体85% (Models 90%, Routes 85%, Utils 90%)

### 2.2 功能模块测试矩阵

#### 2.2.1 核心业务模块 (P0)
| 模块名称 | 测试用例数 | 测试场景 | 当前覆盖率 | 目标覆盖率 |
|---------|-----------|---------|-----------|-----------|
| **订单管理** | 45 | 创建、编辑、删除、审批、状态流转 | 14% | 90% |
| **库存管理** | 38 | 入库、出库、盘点、预警、调拨 | 17% | 90% |
| **产品管理** | 32 | 产品CRUD、分类、规格、条码 | 30% | 85% |
| **审批流程** | 50 | 创建、提交、审批、驳回、撤销、权限 | 80% | 95% |
| **用户权限** | 28 | 用户管理、角色分配、权限验证 | 21% | 85% |

#### 2.2.2 辅助功能模块 (P1)
| 模块名称 | 测试用例数 | 测试场景 | 当前覆盖率 | 目标覆盖率 |
|---------|-----------|---------|-----------|-----------|
| **报表统计** | 25 | 销售报表、库存报表、财务报表 | 16% | 80% |
| **批量操作** | 35 | 批量导入、导出、上传、处理 | 0% | 85% |
| **案例管理** | 30 | 案例CRUD、库存日志、出入库 | 19% | 85% |
| **API接口** | 20 | RESTful API、数据验证、错误处理 | 20% | 80% |

### 2.3 测试用例设计原则

#### 正向测试
- 验证正常业务流程的完整执行
- 验证边界值处理（最小值、最大值、边界值）
- 验证数据完整性约束

#### 逆向测试
- 验证非法输入的处理
- 验证权限不足的拒绝
- 验证业务规则违反的提示

#### 场景测试
- 验证典型用户操作路径
- 验证跨模块业务流程
- 验证并发操作场景

### 2.4 测试执行计划

```python
# 测试执行命令
# 1. 运行所有测试
pytest tests/ -v --cov=app --cov-report=html --cov-report=xml

# 2. 运行指定模块测试
pytest tests/test_order.py -v --cov=app.routes.order

# 3. 运行标记的测试
pytest -m "p0" -v  # 运行P0优先级测试
pytest -m "slow" -v  # 运行慢速测试

# 4. 并行执行
pytest tests/ -n 4 --dist=loadscope
```

---

## 3. 性能测试方案

### 3.1 性能指标基准

| 指标类型 | 指标名称 | 目标值 | 测试方法 |
|---------|---------|--------|---------|
| **响应时间** | 平均响应时间 | < 500ms | K6负载测试 |
| | 95%响应时间 | < 1000ms | K6负载测试 |
| | 99%响应时间 | < 2000ms | K6负载测试 |
| **吞吐量** | 并发用户数 | 100用户 | 逐步加压测试 |
| | TPS(每秒事务数) | > 50 TPS | 持续负载测试 |
| **资源占用** | CPU使用率 | < 70% | 监控工具 |
| | 内存占用 | < 2GB | 监控工具 |
| | 数据库连接数 | < 50 | 数据库监控 |

### 3.2 关键业务性能测试场景

#### 场景1: 订单创建流程
```javascript
// K6测试脚本示例
import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
  stages: [
    { duration: '2m', target: 50 },  // 逐步加压到50用户
    { duration: '5m', target: 50 },  // 持续5分钟
    { duration: '2m', target: 100 }, // 加压到100用户
    { duration: '5m', target: 100 }, // 持续5分钟
    { duration: '2m', target: 0 },   // 逐步减压
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'], // 95%请求<1秒
    http_req_failed: ['rate<0.05'],    // 错误率<5%
  },
};

export default function () {
  // 登录获取token
  let loginRes = http.post('http://localhost:5000/api/login', {
    username: 'testuser',
    password: 'testpass'
  });
  
  // 创建订单
  let orderRes = http.post('http://localhost:5000/api/orders', JSON.stringify({
    product_id: 1,
    quantity: 10,
    customer: '测试客户'
  }), {
    headers: { 'Content-Type': 'application/json' },
  });
  
  check(orderRes, {
    '订单创建成功': (r) => r.status === 200,
    '响应时间<500ms': (r) => r.timings.duration < 500,
  });
  
  sleep(1);
}
```

#### 场景2: 库存查询并发测试
- **测试目标**: 验证库存查询接口的并发处理能力
- **并发用户**: 50-200用户
- **持续时间**: 10分钟
- **监控指标**: 响应时间、错误率、数据库连接数

#### 场景3: 批量导入性能测试
- **测试数据**: 1000条产品数据
- **测试目标**: 验证批量导入的处理效率
- **性能基准**: < 30秒完成导入

### 3.3 性能监控方案

```python
# 使用memory_profiler监控内存
from memory_profiler import profile

@profile
def batch_import_products(file_path):
    # 批量导入逻辑
    pass

# 使用py-spy进行性能分析
# py-spy record -o profile.svg --pid <pid>
```

### 3.4 性能测试执行步骤

1. **环境准备**
   - 部署测试环境，配置与生产环境一致
   - 准备测试数据（至少10000条订单、5000个产品）
   - 配置监控工具（Prometheus + Grafana）

2. **基准测试**
   - 单用户执行关键业务流程，建立性能基线
   - 记录各接口的平均响应时间

3. **负载测试**
   - 执行K6脚本，逐步增加并发用户
   - 监控系统资源占用情况
   - 记录性能拐点和瓶颈

4. **压力测试**
   - 持续增加负载直到系统崩溃
   - 记录系统最大承载能力
   - 分析崩溃原因和恢复时间

5. **稳定性测试**
   - 以80%最大负载持续运行24小时
   - 监控内存泄漏、连接泄漏等问题

---

## 4. 安全性测试方案

### 4.1 安全测试范围

| 测试类型 | 测试内容 | 测试工具 | 优先级 |
|---------|---------|---------|--------|
| **漏洞扫描** | 自动化漏洞检测 | OWASP ZAP, Bandit | P0 |
| **渗透测试** | SQL注入、XSS、CSRF | 手动测试 + Burp Suite | P0 |
| **权限测试** | RBAC权限验证 | 功能测试 | P0 |
| **加密测试** | 数据传输、存储加密 | 代码审计 | P1 |
| **配置审计** | 服务器安全配置 | Lynis, 手动检查 | P1 |

### 4.2 安全测试用例

#### 4.2.1 SQL注入测试
```python
# 测试用例示例
test_cases = [
    ("产品查询", "product_name", "' OR '1'='1"),
    ("用户登录", "username", "admin'--"),
    ("订单查询", "order_no", "1; DROP TABLE orders;--"),
    ("库存查询", "product_id", "1 UNION SELECT * FROM users"),
]

for name, field, payload in test_cases:
    response = client.post(f'/api/{endpoint}', {field: payload})
    assert response.status_code != 500  # 不应导致服务器错误
    assert 'error' in response.json()   # 应返回错误信息
```

#### 4.2.2 XSS攻击测试
```python
xss_payloads = [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert('XSS')>",
    "javascript:alert('XSS')",
    "<svg onload=alert('XSS')>",
]

for payload in xss_payloads:
    response = client.post('/api/products', {
        'name': payload,
        'description': payload
    })
    # 验证payload被转义或过滤
    assert payload not in response.data.decode()
```

#### 4.2.3 CSRF防护测试
```python
def test_csrf_protection():
    # 不带CSRF token的请求应被拒绝
    response = client.post('/api/orders', data={...})
    assert response.status_code == 400
    
    # 带正确CSRF token的请求应成功
    csrf_token = get_csrf_token(client)
    response = client.post('/api/orders', 
                          data={...},
                          headers={'X-CSRFToken': csrf_token})
    assert response.status_code == 200
```

#### 4.2.4 权限控制测试
```python
# RBAC权限测试矩阵
permission_matrix = {
    'admin': ['create', 'read', 'update', 'delete', 'approve'],
    'manager': ['create', 'read', 'update', 'approve'],
    'staff': ['create', 'read', 'update'],
    'viewer': ['read'],
}

def test_rbac(user_role, action, resource):
    user = create_user_with_role(user_role)
    client = login_as(user)
    
    if action in permission_matrix[user_role]:
        # 应有权限
        response = perform_action(client, action, resource)
        assert response.status_code in [200, 201]
    else:
        # 应无权限
        response = perform_action(client, action, resource)
        assert response.status_code == 403
```

### 4.3 安全配置检查清单

- [ ] SECRET_KEY使用环境变量，无硬编码
- [ ] 数据库密码不使用默认值
- [ ] DEBUG模式在生产环境关闭
- [ ] HTTPS强制启用
- [ ] Session配置安全（HttpOnly, Secure, SameSite）
- [ ] 密码使用强哈希算法（bcrypt/pbkdf2）
- [ ] 敏感数据传输使用TLS 1.2+
- [ ] 文件上传限制类型和大小
- [ ] API速率限制已配置
- [ ] 错误信息不泄露敏感信息

### 4.4 安全测试工具

```bash
# 1. 使用Bandit进行代码安全扫描
bandit -r app/ -f html -o security_report.html

# 2. 使用OWASP ZAP进行动态扫描
zap-baseline.py -t http://localhost:5000

# 3. 使用pip-audit检查依赖漏洞
pip-audit --format json > dependency_vulnerabilities.json

# 4. 使用Safety检查已知漏洞
safety check -r requirements.txt
```

---

## 5. 兼容性测试方案

### 5.1 浏览器兼容性测试矩阵

| 浏览器 | 版本 | 测试内容 | 优先级 |
|--------|------|---------|--------|
| **Chrome** | 最新版 + 前2版本 | 全功能测试 | P0 |
| **Firefox** | 最新版 + 前2版本 | 全功能测试 | P0 |
| **Edge** | 最新版 + 前2版本 | 全功能测试 | P0 |
| **Safari** | 最新版 + 前2版本 | 核心功能测试 | P1 |
| **IE11** | - | 基础功能测试 | P2 |

### 5.2 操作系统兼容性测试

| 操作系统 | 版本 | 测试环境 | 测试内容 |
|---------|------|---------|---------|
| **Windows** | 10, 11 | 本地/虚拟机 | 全功能测试 |
| **macOS** | 最新版 | 本地/虚拟机 | 全功能测试 |
| **Linux** | Ubuntu 20.04+ | Docker容器 | 服务端测试 |

### 5.3 设备兼容性测试

| 设备类型 | 分辨率 | 测试内容 | 工具 |
|---------|--------|---------|------|
| **桌面** | 1920x1080 | 全功能测试 | Chrome DevTools |
| **笔记本** | 1366x768 | 响应式测试 | Chrome DevTools |
| **平板** | 768x1024 | 核心功能测试 | BrowserStack |
| **手机** | 375x667 | 基础功能测试 | BrowserStack |

### 5.4 兼容性测试检查点

- [ ] UI渲染一致性（布局、字体、颜色）
- [ ] JavaScript功能正常执行
- [ ] CSS样式正确应用
- [ ] 表单提交和验证正常
- [ ] 文件上传下载功能正常
- [ ] 打印功能正常
- [ ] 响应式布局适配正确

---

## 6. 易用性测试方案

### 6.1 UI/UX评估标准

| 评估维度 | 评估标准 | 权重 |
|---------|---------|------|
| **一致性** | 设计风格、交互方式、术语使用一致 | 25% |
| **直观性** | 操作流程清晰，功能易于发现 | 25% |
| **效率** | 完成任务的步骤最少化 | 20% |
| **容错性** | 错误提示清晰，易于恢复 | 15% |
| **美观度** | 视觉设计专业、现代 | 15% |

### 6.2 核心业务流程易用性测试

#### 流程1: 订单创建流程
- **步骤数**: 目标 ≤ 5步
- **完成时间**: 目标 ≤ 2分钟
- **错误率**: 目标 < 5%
- **用户满意度**: 目标 ≥ 4.0/5.0

#### 流程2: 库存查询流程
- **步骤数**: 目标 ≤ 3步
- **完成时间**: 目标 ≤ 30秒
- **信息清晰度**: 关键信息突出显示

#### 流程3: 报表生成流程
- **步骤数**: 目标 ≤ 4步
- **完成时间**: 目标 ≤ 1分钟
- **结果可读性**: 图表清晰，数据准确

### 6.3 可访问性测试

遵循WCAG 2.1 AA标准：
- [ ] 所有图片有alt文本
- [ ] 表单字段有label关联
- [ ] 键盘导航完整可用
- [ ] 颜色对比度符合标准（4.5:1）
- [ ] 屏幕阅读器兼容
- [ ] 焦点顺序合理

### 6.4 用户体验测试方法

1. **启发式评估**: 由UX专家依据Nielsen十大原则评估
2. **用户测试**: 邀请5-8名目标用户完成典型任务
3. **问卷调查**: 使用SUS(System Usability Scale)评分
4. **A/B测试**: 对关键页面进行方案对比

---

## 7. 数据管理测试方案

### 7.1 数据备份测试

#### 测试场景
| 场景 | 测试内容 | 频率 | RPO/RTO |
|------|---------|------|---------|
| **全量备份** | 完整数据库备份 | 每日 | RPO: 24h, RTO: 2h |
| **增量备份** | 增量数据备份 | 每小时 | RPO: 1h, RTO: 30min |
| **实时备份** | 关键数据实时同步 | 实时 | RPO: 0, RTO: 5min |

#### 测试步骤
```bash
# 1. 执行备份
python scripts/backup.py --type full

# 2. 验证备份完整性
python scripts/verify_backup.py --file backup_20260326.sql

# 3. 模拟数据丢失
DROP DATABASE erp_production;

# 4. 执行恢复
python scripts/restore.py --file backup_20260326.sql

# 5. 验证数据一致性
python scripts/check_data_integrity.py
```

### 7.2 数据恢复测试

- **测试频率**: 每月一次
- **测试环境**: 独立的恢复测试环境
- **验证内容**:
  - 数据完整性（记录数、字段值）
  - 关系完整性（外键约束）
  - 业务逻辑一致性（计算字段）

### 7.3 数据迁移测试

```python
# 数据迁移验证脚本
def verify_migration():
    # 1. 记录数对比
    old_count = get_old_db_count()
    new_count = get_new_db_count()
    assert old_count == new_count, "记录数不一致"
    
    # 2. 关键字段对比
    sample_records = get_sample_records(1000)
    for record in sample_records:
        old_data = get_old_db_record(record.id)
        new_data = get_new_db_record(record.id)
        assert compare_records(old_data, new_data)
    
    # 3. 业务逻辑验证
    verify_business_logic()
```

---

## 8. 错误处理与日志测试方案

### 8.1 异常场景测试

| 异常类型 | 测试场景 | 预期结果 |
|---------|---------|---------|
| **网络异常** | 断网、超时 | 友好提示，自动重试 |
| **数据库异常** | 连接失败、死锁 | 降级处理，记录日志 |
| **文件异常** | 文件不存在、权限不足 | 明确错误提示 |
| **输入异常** | 非法格式、超长输入 | 验证提示，防止注入 |
| **业务异常** | 库存不足、权限不足 | 业务错误提示 |

### 8.2 错误提示测试

- **准确性**: 错误信息准确描述问题
- **友好性**: 使用用户易懂的语言
- **指导性**: 提供解决问题的建议
- **一致性**: 同类错误使用统一提示

### 8.3 日志功能测试

#### 日志记录要求
```python
# 日志格式标准
{
    "timestamp": "2026-03-26T10:30:45.123Z",
    "level": "ERROR",
    "module": "order",
    "function": "create_order",
    "user_id": 123,
    "request_id": "req-abc-123",
    "message": "库存不足",
    "context": {
        "product_id": 456,
        "requested_qty": 100,
        "available_qty": 50
    }
}
```

#### 日志测试检查点
- [ ] 所有关键操作有日志记录
- [ ] 错误日志包含完整上下文
- [ ] 敏感信息已脱敏
- [ ] 日志级别使用正确
- [ ] 日志文件轮转配置正确
- [ ] 日志可追溯（包含request_id）

### 8.4 日志分析测试

```bash
# 1. 日志完整性检查
grep -c "ERROR" logs/app.log  # 错误日志数量
grep -c "WARNING" logs/app.log  # 警告日志数量

# 2. 日志可读性检查
python scripts/analyze_logs.py --format json

# 3. 问题诊断测试
# 模拟错误场景，验证日志可用于定位问题
```

---

## 9. 测试管理要求

### 9.1 测试计划

| 阶段 | 时间 | 任务 | 负责人 | 交付物 |
|------|------|------|--------|--------|
| **准备阶段** | 第1周 | 环境搭建、数据准备 | 运维 | 测试环境 |
| **功能测试** | 第2-3周 | 功能测试执行 | 测试工程师 | 功能测试报告 |
| **性能测试** | 第4周 | 性能测试执行 | 性能工程师 | 性能测试报告 |
| **安全测试** | 第5周 | 安全测试执行 | 安全工程师 | 安全测试报告 |
| **综合测试** | 第6周 | 兼容性、易用性测试 | 测试团队 | 综合测试报告 |
| **报告阶段** | 第7周 | 报告汇总、评审 | QA负责人 | 最终评测报告 |

### 9.2 缺陷管理

#### 缺陷分级标准
| 等级 | 定义 | 响应时间 | 修复时限 |
|------|------|---------|---------|
| **P0** | 系统崩溃、数据丢失、安全漏洞 | 立即 | 24小时 |
| **P1** | 核心功能不可用、严重性能问题 | 4小时 | 3天 |
| **P2** | 次要功能缺陷、UI问题 | 1天 | 1周 |
| **P3** | 优化建议、文档问题 | 3天 | 2周 |

#### 缺陷处理流程
```
发现缺陷 → 记录(JIRA) → 分级 → 分配 → 修复 → 验证 → 关闭
```

### 9.3 测试报告模板

```markdown
# ERP系统评测报告

## 1. 执行摘要
- 测试时间：YYYY-MM-DD ~ YYYY-MM-DD
- 测试范围：[列出测试模块]
- 测试结果：通过/有条件通过/不通过

## 2. 测试统计
- 总用例数：XXX
- 通过数：XXX (XX%)
- 失败数：XXX (XX%)
- 阻塞数：XXX (XX%)

## 3. 覆盖率统计
- 代码覆盖率：XX%
- 功能覆盖率：XX%
- 需求覆盖率：XX%

## 4. 性能测试结果
- 平均响应时间：XXX ms
- 95%响应时间：XXX ms
- 最大并发用户：XXX
- TPS：XXX

## 5. 安全测试结果
- 高危漏洞：X个
- 中危漏洞：X个
- 低危漏洞：X个

## 6. 缺陷统计
- P0缺陷：X个（已修复X个）
- P1缺陷：X个（已修复X个）
- P2缺陷：X个（已修复X个）
- P3缺陷：X个（已修复X个）

## 7. 风险评估
[列出主要风险和建议]

## 8. 上线建议
[通过/有条件通过/不通过，及理由]
```

---

## 10. 评测工具清单

### 10.1 功能测试工具
- **pytest**: 单元测试和集成测试框架
- **pytest-cov**: 代码覆盖率统计
- **pytest-html**: HTML测试报告
- **selenium**: UI自动化测试

### 10.2 性能测试工具
- **K6**: 负载测试和性能测试
- **locust**: Python性能测试框架
- **memory_profiler**: 内存分析
- **py-spy**: 性能采样分析

### 10.3 安全测试工具
- **bandit**: Python代码安全扫描
- **OWASP ZAP**: Web应用安全扫描
- **pip-audit**: 依赖漏洞检查
- **safety**: 已知漏洞检查

### 10.4 兼容性测试工具
- **BrowserStack**: 跨浏览器测试
- **Sauce Labs**: 云端测试平台
- **Chrome DevTools**: 响应式测试

### 10.5 监控工具
- **Prometheus**: 指标收集
- **Grafana**: 可视化监控
- **ELK Stack**: 日志分析

---

## 11. 附录

### 11.1 测试数据准备脚本

```python
# scripts/prepare_test_data.py
def prepare_test_data():
    """准备测试数据"""
    # 创建测试用户
    create_test_users(100)
    
    # 创建测试产品
    create_test_products(1000)
    
    # 创建测试订单
    create_test_orders(10000)
    
    # 创建测试库存记录
    create_test_stock_records(5000)
```

### 11.2 测试环境配置

```yaml
# docker-compose.test.yml
version: '3.8'
services:
  app:
    build: .
    environment:
      - FLASK_ENV=testing
      - DATABASE_URL=mysql://test:test@db:3306/erp_test
      - REDIS_URL=redis://redis:6379/1
    depends_on:
      - db
      - redis
  
  db:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=test
      - MYSQL_DATABASE=erp_test
  
  redis:
    image: redis:7-alpine
```

### 11.3 持续集成配置

```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: 3.9
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run tests
        run: pytest tests/ --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## 12. 执行检查清单

### 12.1 测试前检查
- [ ] 测试环境已部署并配置正确
- [ ] 测试数据已准备完毕
- [ ] 测试工具已安装并配置
- [ ] 测试用例已评审通过
- [ ] 测试人员已分配任务

### 12.2 测试中检查
- [ ] 每日测试进度跟踪
- [ ] 缺陷及时记录和跟踪
- [ ] 测试环境稳定性监控
- [ ] 测试数据一致性维护

### 12.3 测试后检查
- [ ] 所有测试用例已执行
- [ ] 所有P0/P1缺陷已修复并验证
- [ ] 测试报告已编写
- [ ] 评测报告已评审
- [ ] 上线决策已确定

---

**文档版本**: v1.0  
**最后更新**: 2026-03-26  
**下次评审**: 测试完成后
