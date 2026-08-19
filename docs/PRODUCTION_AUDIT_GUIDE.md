# 生产代码审核流程指南

ERP 系统生产代码审核 pipeline(12 层)使用指南。

## 快速开始

```bash
# 运行完整 12 层审核
python scripts/run_prod_audit.py

# 等价于
python -m scripts.prod_audit.orchestrator --config scripts/prod_audit/audit_config.yaml
```

## CLI 用法

```bash
python scripts/run_prod_audit.py [选项]
```

### 选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--config <path>` | `scripts/prod_audit/audit_config.yaml` | 审核配置文件路径 |
| `--rules <path>` | `scripts/prod_audit/rules_registry.yaml` | 规则注册表文件路径 |
| `--evidence-dir <dir>` | `scripts/prod_audit/evidence` | 证据归档目录 |
| `--resume-from <layer_id>` | `None` | 断点恢复层 ID(如 `L4`) |

### 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 审核正常完成 |
| 1 | 层门禁阻断(存在 critical/high 问题) |
| 2 | 配置错误(文件不存在 / 格式非法 / Σweight ≠ 1) |
| 130 | 用户中断(Ctrl+C) |

## 断点恢复

审核中断后可从指定层恢复,已完成层结果复用:

```bash
# 从 L4 开始执行(L1~L3 结果从 evidence/audit_state.json 恢复)
python scripts/run_prod_audit.py --resume-from L4

# 也可在 audit_config.yaml 中设置
# resume_from: "L4"
```

状态文件 `evidence/audit_state.json` 在每层完成后更新,审核成功完成后自动清理。

## 12 层审核 pipeline

| 层 | ID | 权重 | 执行器 | 职责 |
|----|-----|------|--------|------|
| L1 | 静态分析门禁审核 | 0.10 | `L1StaticAnalysis` | ruff/bandit/mypy/函数行数/宽泛 except + vue-tsc/eslint/组件行数/产物扫描 |
| L2 | 架构与分层审核 | 0.08 | `L2Architecture` | 分层违规 / 循环依赖 / 服务行数 / 端点职责 |
| L3 | 业务逻辑与正确性审核 | 0.12 | `L3BusinessLogic` | 循环内查询 / 事务边界 / 状态机 / 并发安全 |
| L4 | 数据访问层审核 | 0.10 | `L4DataAccess` | N+1 查询 / 大事务 / 索引缺失 / 连接池 |
| L5 | API 契约与版本兼容审核 | 0.08 | `L5ApiContract` | OpenAPI 契约 / 版本兼容 / 字段命名 |
| L6 | 安全审核(蓝队 + 红队) | 0.15 | `L6Security` | pip-audit / npm audit / Snyk / 镜像扫描 / 红队渗透 |
| L7 | 性能与可扩展性审核 | 0.10 | `L7Performance` | locust 压测 / lighthouse / 资源监控 |
| L8 | 可观测性审核 | 0.07 | `L8Observability` | 日志字段 / 指标 / 链路追踪 / 告警 |
| L9 | 测试质量审核 | 0.08 | `L9TestQuality` | pytest 覆盖率 / vitest 覆盖率 / 测试有效性 |
| L10 | 前端与移动端审核 | 0.05 | `L10Frontend` | 产物体积 / Capacitor 兼容 / 移动端适配 |
| L11 | 部署就绪与配置审核 | 0.04 | `L11Deployment` | 健康检查 / 回滚方案 / 锁文件 / 环境配置 |
| L12 | 报告与上线决策 | 0.03 | `L12Report` | 聚合评分 / 签字单 / 历史对比 / 问题跟踪 |

权重之和 = 1.0,安全层 L6 权重最高(0.15)。

## 评分计算

### 层得分

每层起始 100 分,按问题严重度扣分:

| 严重度 | 扣分 |
|--------|------|
| critical | 25 |
| high | 15 |
| medium | 8 |
| low | 3 |
| info | 1 |

```
layer_score = max(0, 100 - Σpenalty)
```

### 总分

```
total_score = Σ(layer_score × weight)
```

### 生产就绪判定

```
is_ready = (total_score ≥ 85) AND (无 critical/high 问题)
```

- 评分阈值: `readiness_threshold = 85`(可在 `audit_config.yaml` 配置)
- 阻断阈值: `severity_threshold = high`(含 critical 与 high)

## 上线决策

### 放行条件(全部满足)

1. 12 层全部门禁通过(无 critical/high 问题)
2. 生产就绪评分 ≥ 85
3. 证据归档完整且脱敏
4. 各层审核员签字
5. 发布负责人确认放行

### 签字流程

1. 各层审核员在 `evidence/release_signoff.json` 的 `layer_signoffs` 填入 `reviewer` / `signed_at` / `result`
2. 发布负责人依据签字单决定:
   - 全部条件满足 → `release_decision = approved`
   - 任一未满足 → `release_decision = rejected` 并标注未达标项
3. 驳回则转研发修复后重新触发审核

## 证据目录结构

```
evidence/
├── audit_state.json          # 审核运行状态(断点恢复)
├── issue_tracker.json        # 问题跟踪清单
├── release_signoff.json      # 上线就绪签字单
├── audit_report.json         # 全量审核总报告
├── audit_summary.md          # markdown 摘要报告
├── contract_snapshots/       # API 契约快照
├── perf_reports/             # 性能测试报告(locust/lighthouse/resource)
├── coverage_reports/         # 测试覆盖率报告(pytest/vitest)
├── security_reports/         # 安全扫描报告(bandit/pip-audit/npm audit/Snyk/镜像扫描/红队)
├── manual_reviews/           # 人工审查记录
└── gate_logs/                # 门禁检查日志(L1/~L12/)
```

所有证据经 `EvidenceArchiver.sanitize` 脱敏(无密钥/连接串/token 明文)。

### 脱敏覆盖模式

- `password = "xxx"` / `password: "xxx"` / `password: 'xxx'`
- `secret` / `token` / `api_key` / `apikey`
- `DATABASE_URL` / `dsn` / `access_key` / `private_key`
- URL 内嵌凭证 `scheme://user:pass@host`
- JSON 键值对 `"password": "xxx"`

## 配置说明

### `audit_config.yaml`

| 配置项 | 说明 |
|--------|------|
| `weights` | 12 层权重(Σweight = 1.0) |
| `severity_threshold` | 阻断上线严重度阈值(含该级别及以上) |
| `readiness_threshold` | 生产就绪评分阈值(≥ 此值视为就绪) |
| `issue_penalty` | 各严重度问题扣分值 |
| `perf_thresholds` | 压测阈值(P95/RPS/错误率/冷启动/内存/LCP/FID/CLS/产物体积) |
| `coverage_thresholds` | 覆盖率分级阈值(核心/备份/来料/仪表盘) |
| `resume_from` | 断点恢复层 ID |
| `layers.<Lx>.enabled` | 层开关(false 时跳过该层) |
| `layers.<Lx>.reviewer` | 负责审核员 |
| `layers.<Lx>.whitelist` | 白名单文件路径列表 |
| `layers.<Lx>.thresholds` | 层阈值配置 |
| `layers.<Lx>.disable_reason` | 禁用原因(enabled=false 时必填) |

### `rules_registry.yaml`

每条规则含 `rule_id` / `version` / `source` / `severity` / `description`,
加载时校验 `rule_id` 唯一性。

## 运行测试

```bash
# 运行审核工程自身测试
python -m pytest scripts/prod_audit/tests/ -q

# 运行单个测试文件
python -m pytest scripts/prod_audit/tests/test_orchestrator.py -q
```

## 约束

- 审核流程总耗时 ≤ 4 小时
- 单层自动化门禁 ≤ 15 分钟
- 审核必须可重复执行(同源码同配置产出同结果)
- 审核证据归档不得包含敏感数据
- 审核报告访问须鉴权