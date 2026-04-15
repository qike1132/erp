# CI/CD自动化流程运行指南

## 1. CI/CD流程概述

本项目的CI/CD流程基于GitHub Actions实现，包含以下阶段：

```
代码提交 → 自动测试 → 代码检查 → 安全扫描 → 构建 → 部署
```

## 2. 触发条件

CI/CD流程会在以下情况自动触发：

### 2.1 自动触发
- **推送到main分支**: 触发完整流程，包括生产环境部署
- **推送到develop分支**: 触发完整流程，包括staging环境部署
- **Pull Request到main/develop分支**: 触发测试和检查，不部署

### 2.2 手动触发
在GitHub仓库页面：
1. 点击"Actions"标签
2. 选择"ERP System CI/CD Pipeline"
3. 点击"Run workflow"
4. 选择分支
5. 点击"Run workflow"按钮

## 3. CI/CD流程详解

### 3.1 测试阶段 (test job)

**运行环境**: Ubuntu Latest, Python 3.9/3.10/3.11

**执行步骤**:
1. **检出代码**
   ```bash
   git checkout <branch>
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-cov pytest-html pytest-xdist
   pip install bandit pip-audit
   ```

3. **运行测试**
   ```bash
   pytest tests/ -v --cov=app --cov-report=xml --cov-report=html --html=test-report.html -n auto
   ```
   
   - `-v`: 详细输出
   - `--cov=app`: 代码覆盖率统计
   - `--cov-report=xml/html`: 生成XML和HTML覆盖率报告
   - `--html=test-report.html`: 生成HTML测试报告
   - `-n auto`: 并行测试

4. **上传覆盖率报告**
   - 自动上传到Codecov（如果配置了Codecov token）

5. **安全扫描**
   ```bash
   bandit -r app/ -f json -o security-report.json
   pip-audit --format json > dependency-audit.json
   ```

6. **检查覆盖率阈值**
   - 如果覆盖率低于80%，输出警告

### 3.2 代码检查阶段 (lint job)

**运行环境**: Ubuntu Latest, Python 3.9

**执行步骤**:
1. **Black代码格式检查**
   ```bash
   black --check app/ tests/
   ```

2. **Flake8代码规范检查**
   ```bash
   flake8 app/ tests/ --max-line-length=100 --exclude=__pycache__,migrations
   ```

3. **Pylint代码质量检查**
   ```bash
   pylint app/ --disable=all --enable=E,F
   ```

### 3.3 构建阶段 (build job)

**前置条件**: test和lint阶段都通过

**执行步骤**:
1. **构建Python包**
   ```bash
   python -m build
   ```

2. **上传构建产物**
   - 生成的dist/目录中的包文件

### 3.4 部署阶段

#### Staging部署 (deploy-staging job)
- **触发条件**: develop分支的push事件
- **执行**: 部署到staging环境

#### Production部署 (deploy-production job)
- **触发条件**: main分支的push事件
- **执行**: 部署到production环境

## 4. 本地运行CI/CD流程

### 4.1 运行测试

```bash
# 运行所有测试
pytest tests/ -v --cov=app --cov-report=html

# 并行测试
pytest tests/ -n auto

# 生成HTML报告
pytest tests/ --html=test-report.html
```

### 4.2 运行代码检查

```bash
# Black格式检查
black --check app/ tests/

# 自动格式化
black app/ tests/

# Flake8检查
flake8 app/ tests/ --max-line-length=100

# Pylint检查
pylint app/
```

### 4.3 运行安全扫描

```bash
# Bandit安全扫描
bandit -r app/ -f json -o security-report.json

# 依赖漏洞检查
pip-audit --format json > dependency-audit.json
```

## 5. 查看CI/CD运行结果

### 5.1 在GitHub上查看

1. 进入GitHub仓库
2. 点击"Actions"标签
3. 选择具体的workflow运行记录
4. 查看各个job的执行详情

### 5.2 下载报告

在workflow运行完成后，可以下载以下报告：
- **test-report**: 测试报告和覆盖率报告
- **security-reports**: 安全扫描报告
- **dist**: 构建产物

### 5.3 查看覆盖率

如果配置了Codecov：
1. 访问 https://codecov.io
2. 查看项目的覆盖率趋势
3. 查看覆盖率详情

## 6. 配置CI/CD

### 6.1 配置Codecov（可选）

1. 在 https://codecov.io 注册账号
2. 添加GitHub仓库
3. 获取Codecov token
4. 在GitHub仓库设置中添加Secret: `CODECOV_TOKEN`

### 6.2 配置部署（需要补充）

编辑 `.github/workflows/ci-cd.yml`，在部署步骤中添加实际部署命令：

```yaml
- name: Deploy to staging
  run: |
    echo "Deploying to staging environment..."
    # 添加实际部署命令，例如：
    # ssh user@staging-server 'cd /app && git pull && systemctl restart app'
    # 或使用Docker:
    # docker build -t erp:staging .
    # docker push registry/erp:staging
```

## 7. CI/CD流程图

```
┌─────────────┐
│  代码提交    │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│        GitHub Actions           │
├─────────────────────────────────┤
│                                 │
│  ┌──────────┐  ┌──────────┐   │
│  │  Test    │  │  Lint    │   │
│  │  Job     │  │  Job     │   │
│  └────┬─────┘  └────┬─────┘   │
│       │              │         │
│       └──────┬───────┘         │
│              │                 │
│              ▼                 │
│       ┌──────────┐            │
│       │  Build   │            │
│       │  Job     │            │
│       └────┬─────┘            │
│            │                   │
│            ▼                   │
│    ┌───────────────┐          │
│    │  Deploy       │          │
│    │  (Staging/    │          │
│    │   Production) │          │
│    └───────────────┘          │
└─────────────────────────────────┘
```

## 8. 常见问题

### 8.1 测试失败
- 查看测试报告，定位失败的测试用例
- 本地运行失败的测试用例进行调试
- 修复后重新提交代码

### 8.2 代码检查失败
- **Black**: 运行 `black app/ tests/` 自动格式化
- **Flake8**: 根据提示修复代码规范问题
- **Pylint**: 根据提示修复代码质量问题

### 8.3 安全扫描发现问题
- 查看security-report.json
- 根据Bandit建议修复安全问题
- 更新有漏洞的依赖包

### 8.4 覆盖率不足
- 查看覆盖率报告，找到未覆盖的代码
- 补充测试用例
- 目标：覆盖率 ≥ 80%

## 9. 最佳实践

### 9.1 提交代码前
```bash
# 1. 运行测试
pytest tests/ -v

# 2. 检查代码格式
black --check app/ tests/
flake8 app/ tests/

# 3. 检查覆盖率
pytest tests/ --cov=app --cov-report=term
```

### 9.2 创建Pull Request
1. 确保所有本地测试通过
2. 创建feature分支
3. 提交代码并创建PR
4. 等待CI/CD流程完成
5. 确认所有检查通过后合并

### 9.3 部署到生产环境
1. 合并PR到main分支
2. CI/CD自动触发
3. 等待所有检查通过
4. 自动部署到生产环境

## 10. 监控和告警

### 10.1 设置通知
在GitHub仓库设置中：
1. Settings → Notifications
2. 配置邮件或Slack通知
3. CI/CD失败时自动通知

### 10.2 查看趋势
- 测试通过率趋势
- 覆盖率趋势
- 构建时间趋势

---

**文档版本**: v1.0  
**最后更新**: 2026-03-26
