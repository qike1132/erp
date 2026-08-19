# 生产审核证据归档目录

本目录存放 12 层生产代码审核 pipeline 产生的全部证据,
经 `EvidenceArchiver.sanitize` 脱敏后归档,确保上线决策可追溯。

## 子目录说明

| 子目录 | 用途 | 产出层 |
|--------|------|--------|
| `contract_snapshots/` | API 契约快照(OpenAPI diff) | L5 |
| `perf_reports/` | 性能测试报告(locust / lighthouse / resource) | L7 |
| `coverage_reports/` | 测试覆盖率报告(pytest / vitest) | L9 |
| `security_reports/` | 安全扫描报告(bandit / pip-audit / npm audit / Snyk / 镜像扫描 / 红队) | L6 |
| `manual_reviews/` | 人工审查记录 | L3~L11 |
| `gate_logs/` | 门禁检查日志(L1/~L12/) | 全部层 |

## 根目录文件

| 文件 | 说明 |
|------|------|
| `audit_state.json` | 审核运行状态(支持断点恢复,审核完成后自动清理) |
| `issue_tracker.json` | 按严重度分级的问题跟踪清单 |
| `release_signoff.json` | 上线就绪签字单(各层审核员签字 + 发布负责人决策) |
| `audit_report.json` | 全量审核总报告(12 层结果 + 评分 + 签字单 + 历史 diff) |
| `audit_summary.md` | markdown 摘要报告(供发布负责人快速查阅) |

## 脱敏规则

所有 `str` 类型证据写入前经 `EvidenceArchiver.sanitize` 脱敏,
`bytes` 类型(如 PNG 图片)原样写入。

脱敏覆盖模式:
- `password = "xxx"` / `password: "xxx"` / `password: 'xxx'`
- `secret` / `token` / `api_key` / `apikey`
- `DATABASE_URL` / `dsn` / `access_key` / `private_key`
- URL 内嵌凭证 `scheme://user:pass@host`
- JSON 键值对 `"password": "xxx"`

敏感值替换为 `[REDACTED]`。

## 访问鉴权

审核报告访问须鉴权(DFX 4.3.4)。生产环境部署时应:
1. 限制 `evidence/` 目录访问权限(仅审核员与发布负责人可读)
2. 通过反向代理或 IAM 策略控制访问
3. 定期清理历史证据(保留最近 N 轮)