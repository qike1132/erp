# ERP系统依赖库升级测试计划

**版本**: v1.0.0  
**日期**: 2026-04-09  
**状态**: 待执行

---

## 1. 测试策略

### 1.1 测试金字塔

```
         /\
        /  \  E2E测试 (10%)
       /----\
      /      \ 集成测试 (30%)
     /--------\
    /          \ 单元测试 (60%)
   /------------\
```

### 1.2 测试范围

| 测试类型 | 覆盖范围 | 优先级 |
|----------|----------|--------|
| 单元测试 | 新增工具库函数 | P0 |
| 集成测试 | API接口、数据库操作 | P0 |
| 性能测试 | 搜索、导入、导出 | P1 |
| 安全测试 | XSS防护、输入验证 | P0 |
| 回归测试 | 全部核心功能 | P0 |

### 1.3 测试环境

| 环境 | 用途 | 配置 |
|------|------|------|
| 开发环境 | 开发调试 | 本地 |
| 测试环境 | 自动化测试 | CI/CD |
| 预发布环境 | 集成测试 | 服务器 |
| 生产环境 | 上线验证 | 生产服务器 |

---

## 2. 单元测试

### 2.1 测试文件结构

```
tests/
├── test_new_libraries.py      # 新库单元测试
├── test_validators.py         # 验证器测试
├── test_date_utils.py         # 日期工具测试
├── test_p1_features.py        # P1功能测试
├── test_p2_features.py        # P2功能测试
├── integration/
│   ├── test_api_integration.py
│   └── test_db_integration.py
└── performance/
    ├── test_search_performance.py
    └── test_import_performance.py
```

### 2.2 新库单元测试用例

#### 2.2.1 phonenumbers测试

| 测试ID | 测试用例 | 输入 | 预期输出 | 优先级 |
|--------|----------|------|----------|--------|
| UT-PH-001 | 中国大陆手机号验证 | 13812345678 | 有效 | P0 |
| UT-PH-002 | 无效手机号验证 | 12345 | 无效 | P0 |
| UT-PH-003 | 国际号码验证 | +12125551234 | 有效 | P1 |
| UT-PH-004 | E164格式化 | 13812345678 | +8613812345678 | P0 |
| UT-PH-005 | 空值处理 | None | 无效 | P0 |

#### 2.2.2 chardet测试

| 测试ID | 测试用例 | 输入 | 预期输出 | 优先级 |
|--------|----------|------|----------|--------|
| UT-CH-001 | UTF-8编码检测 | UTF-8字节 | utf-8 | P0 |
| UT-CH-002 | GBK编码检测 | GBK字节 | GBK | P0 |
| UT-CH-003 | 空数据处理 | b'' | 默认编码 | P0 |
| UT-CH-004 | 混合编码处理 | 混合字节 | 主要编码 | P1 |

#### 2.2.3 pypinyin测试

| 测试ID | 测试用例 | 输入 | 预期输出 | 优先级 |
|--------|----------|------|----------|--------|
| UT-PY-001 | 拼音转换 | 苹果手机 | ['ping','guo','shou','ji'] | P0 |
| UT-PY-002 | 首字母提取 | 苹果手机 | pgsj | P0 |
| UT-PY-003 | 多音字处理 | 重庆 | ['zhong','qing'] | P1 |
| UT-PY-004 | 空字符串处理 | '' | [] | P0 |

#### 2.2.4 arrow测试

| 测试ID | 测试用例 | 输入 | 预期输出 | 优先级 |
|--------|----------|------|----------|--------|
| UT-AR-001 | 日期解析 | 2024-01-15 | datetime对象 | P0 |
| UT-AR-002 | 相对日期 | 今天 | 当前日期 | P0 |
| UT-AR-003 | 日期范围-本月 | month | 月初到月末 | P0 |
| UT-AR-004 | 日期范围-本周 | week | 周一到周日 | P0 |
| UT-AR-005 | 无效日期处理 | abc | None | P0 |

#### 2.2.5 bleach测试

| 测试ID | 测试用例 | 输入 | 预期输出 | 优先级 |
|--------|----------|------|----------|--------|
| UT-BL-001 | XSS过滤 | <script>alert(1)</script> | 空字符串 | P0 |
| UT-BL-002 | 保留安全标签 | <b>文本</b> | <b>文本</b> | P0 |
| UT-BL-003 | 移除危险属性 | <a onclick="x"> | <a> | P0 |
| UT-BL-004 | 空值处理 | None | '' | P0 |

---

## 3. 集成测试

### 3.1 API接口测试

| 测试ID | 测试场景 | 测试步骤 | 预期结果 |
|--------|----------|----------|----------|
| IT-API-001 | 产品拼音搜索 | 1. 调用/api/product-search?q=pingguo | 返回包含"苹果"的产品 |
| IT-API-002 | 客户手机号验证 | 1. 创建客户 2. 输入手机号 | 自动格式化并验证 |
| IT-API-003 | 批量导入编码检测 | 1. 上传GBK编码Excel | 自动检测并正确导入 |
| IT-API-004 | 报表日期范围 | 1. 选择"本月" | 正确返回本月数据 |
| IT-API-005 | 模糊产品搜索 | 1. 搜索"苹果手机"(有错字) | 返回相似产品 |

### 3.2 数据库操作测试

| 测试ID | 测试场景 | 测试步骤 | 预期结果 |
|--------|----------|----------|----------|
| IT-DB-001 | 产品创建 | 1. 创建产品 2. 验证字段 | 数据正确存储 |
| IT-DB-002 | 订单创建 | 1. 创建订单 2. 验证关联 | 关联关系正确 |
| IT-DB-003 | 批量导入事务 | 1. 导入数据 2. 模拟失败 | 正确回滚 |
| IT-DB-004 | 缓存更新 | 1. 修改数据 2. 检查缓存 | 缓存正确更新 |

### 3.3 业务流程测试

| 测试ID | 测试场景 | 测试步骤 | 预期结果 |
|--------|----------|----------|----------|
| IT-BIZ-001 | 订单完整流程 | 创建→备货→出货→完成 | 状态正确流转 |
| IT-BIZ-002 | 库存扣减流程 | 订单→备货→库存扣减 | 数量正确 |
| IT-BIZ-003 | 批量导入流程 | 上传→解析→验证→导入 | 全部成功 |
| IT-BIZ-004 | 报表导出流程 | 查询→生成→下载 | 文件正确 |

---

## 4. 性能测试

### 4.1 性能基准

| 测试项 | 基准值 | 目标值 | 测试方法 |
|--------|--------|--------|----------|
| 产品搜索响应时间 | 200ms | 100ms | 100次并发请求 |
| 批量导入10000行 | 15s | 10s | 单次导入 |
| 报表导出1000行 | 5s | 3s | 单次导出 |
| API平均响应时间 | 100ms | 80ms | 1000次请求 |
| 内存占用 | 500MB | 400MB | 峰值监控 |

### 4.2 性能测试脚本

```python
# tests/performance/test_performance.py

import pytest
import time
from app import create_app

class TestSearchPerformance:
    """搜索性能测试"""
    
    @pytest.fixture
    def app(self):
        return create_app('testing')
    
    def test_product_search_latency(self, app):
        """产品搜索延迟测试"""
        with app.test_client() as client:
            latencies = []
            for _ in range(100):
                start = time.time()
                response = client.get('/api/product-search?q=苹果')
                latencies.append(time.time() - start)
            
            avg_latency = sum(latencies) / len(latencies)
            p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]
            
            assert avg_latency < 0.1, f"平均延迟{avg_latency}s超过100ms"
            assert p99_latency < 0.2, f"P99延迟{p99_latency}s超过200ms"
    
    def test_fuzzy_search_performance(self, app):
        """模糊搜索性能测试"""
        with app.test_client() as client:
            start = time.time()
            for _ in range(50):
                client.get('/api/product-search?q=苹果手机')
            elapsed = time.time() - start
            
            assert elapsed < 5, f"50次搜索耗时{elapsed}s超过5s"
```

### 4.3 负载测试

```python
# tests/performance/test_load.py

import pytest
import asyncio
import aiohttp

class TestLoad:
    """负载测试"""
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """并发请求测试"""
        async def make_request(session, url):
            async with session.get(url) as response:
                return response.status
        
        async with aiohttp.ClientSession() as session:
            tasks = [
                make_request(session, 'http://localhost:5003/api/health')
                for _ in range(100)
            ]
            results = await asyncio.gather(*tasks)
            
            success_rate = sum(1 for r in results if r == 200) / len(results)
            assert success_rate > 0.99, f"成功率{success_rate}低于99%"
```

---

## 5. 安全测试

### 5.1 安全测试用例

| 测试ID | 测试场景 | 测试输入 | 预期结果 |
|--------|----------|----------|----------|
| SEC-001 | XSS攻击防护 | <script>alert(1)</script> | 脚本被过滤 |
| SEC-002 | SQL注入防护 | ' OR '1'='1 | 参数化查询 |
| SEC-003 | CSRF防护 | 伪造请求 | 请求被拒绝 |
| SEC-004 | 文件上传安全 | 恶意文件 | 文件被拒绝 |
| SEC-005 | 敏感信息泄露 | 错误响应 | 无敏感信息 |

### 5.2 安全扫描

```bash
# 依赖漏洞扫描
pip-audit

# 代码安全扫描
bandit -r app/ utils/ -f json -o security_report.json

# 敏感信息扫描
detect-secrets scan app/ > secrets_report.json
```

---

## 6. 回归测试

### 6.1 核心功能回归清单

```
用户管理
□ 用户登录
□ 用户登出
□ 密码修改
□ 权限验证

产品管理
□ 产品列表
□ 产品创建
□ 产品编辑
□ 产品删除
□ 产品搜索

订单管理
□ 订单列表
□ 订单创建
□ 订单编辑
□ 订单状态流转
□ 订单删除

库存管理
□ 备货入库
□ 出货出库
□ 库存查询
□ 库存日志

批量操作
□ 批量导入
□ 批量导出
□ 模板下载

报表统计
□ 订单流水
□ 备货流水
□ 出货流水
□ 报表导出
```

### 6.2 自动化回归测试

```bash
# 运行全部测试
pytest tests/ -v --cov=app --cov=utils --cov-report=html

# 运行特定标记的测试
pytest -m regression tests/

# 并行执行
pytest -n 4 tests/
```

---

## 7. 测试报告

### 7.1 测试报告模板

```markdown
# ERP系统依赖库升级测试报告

## 测试概要
- 测试日期: YYYY-MM-DD
- 测试环境: 测试环境
- 测试人员: XXX

## 测试结果汇总
| 测试类型 | 用例数 | 通过数 | 失败数 | 通过率 |
|----------|--------|--------|--------|--------|
| 单元测试 | XX | XX | XX | XX% |
| 集成测试 | XX | XX | XX | XX% |
| 性能测试 | XX | XX | XX | XX% |
| 安全测试 | XX | XX | XX | XX% |

## 性能测试结果
| 指标 | 基准值 | 实际值 | 是否达标 |
|------|--------|--------|----------|
| 搜索响应时间 | 100ms | XXms | 是/否 |
| 导入速度 | 10s | XXs | 是/否 |

## 问题列表
| 问题ID | 描述 | 严重程度 | 状态 |
|--------|------|----------|------|
| BUG-001 | XXX | 高 | 待修复 |

## 结论
[通过/不通过]
```

### 7.2 测试通过标准

| 指标 | 标准 |
|------|------|
| 单元测试通过率 | ≥ 95% |
| 集成测试通过率 | 100% |
| 性能测试达标率 | ≥ 90% |
| 安全测试通过率 | 100% |
| 代码覆盖率 | ≥ 80% |
| 无P0级Bug | 0个 |
| P1级Bug | ≤ 3个 |

---

## 8. 测试执行计划

### 8.1 测试时间表

| 阶段 | 时间 | 测试内容 | 负责人 |
|------|------|----------|--------|
| 第1周 | Day 1-2 | P0单元测试 | 测试工程师 |
| 第1周 | Day 3-5 | P0集成测试 | 测试工程师 |
| 第2周 | Day 1-3 | P1功能测试 | 测试工程师 |
| 第2周 | Day 4-5 | 性能测试 | 测试工程师 |
| 第3周 | Day 1-2 | 安全测试 | 安全工程师 |
| 第3周 | Day 3-5 | 回归测试 | 测试工程师 |
| 第4周 | Day 1-2 | 预发布测试 | 全员 |
| 第4周 | Day 3-5 | 生产验证 | 运维 |

### 8.2 测试交付物

| 交付物 | 负责人 | 交付时间 |
|--------|--------|----------|
| 测试用例文档 | 测试工程师 | 第1周Day 1 |
| 单元测试报告 | 测试工程师 | 第1周Day 5 |
| 集成测试报告 | 测试工程师 | 第2周Day 3 |
| 性能测试报告 | 测试工程师 | 第2周Day 5 |
| 安全测试报告 | 安全工程师 | 第3周Day 2 |
| 回归测试报告 | 测试工程师 | 第3周Day 5 |
| 最终测试报告 | 测试负责人 | 第4周Day 2 |

---

**文档状态**: 待执行  
**最后更新**: 2026-04-09
