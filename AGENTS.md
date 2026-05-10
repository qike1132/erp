# ERP System - Agent Skills Reference

## Backend Architect
- **触发场景**: 后端架构设计、微服务、API开发、数据库架构
- **核心规则**: 安全优先(防御纵深、最小权限、加密)、性能优先(水平扩展、索引优化、缓存策略)
- **关键模式**: Helmet+rateLimit安全中间件、UUID主键、软删除(deleted_at)、GIN全文搜索索引、结构化错误响应
- **成功指标**: API p95<200ms、可用性>99.9%、查询<100ms、零高危漏洞

## Frontend Developer
- **触发场景**: Web应用UI、React/Vue/Angular组件、性能优化、无障碍
- **核心规则**: Core Web Vitals优先(代码分割/懒加载/缓存)、WCAG 2.1 AA(ARIA标签/语义HTML/键盘导航)
- **关键模式**: React.memo+useCallback优化、虚拟滚动(@tanstack/react-virtual)、role/tabIndex/aria-label
- **成功指标**: LCP<2.5s/FID<100ms/CLS<0.1、Lighthouse>90、组件复用>80%

## Database Optimizer
- **触发场景**: 数据库Schema设计、查询优化、索引策略、N+1修复、安全迁移
- **核心规则**: EXPLAIN ANALYZE必跑、外键必索引、禁SELECT *、连接池必用、迁移可逆、生产禁锁表(CONCURRENTLY)、N+1用JOIN解决
- **关键模式**: 部分索引WHERE过滤、复合索引(过滤+排序)、CONCURRENTLY创建索引、json_agg解决N+1
- **成功指标**: 索引查询<20ms、无大表Seq Scan、所有FK已索引

## Software Architect
- **触发场景**: 架构决策(ADR)、限界上下文、微服务vs单体选型、权衡分析
- **核心规则**: 拒绝架构空想(每个抽象需证明复杂度合理)、命名权衡(说清放弃什么)、领域优先技术、可逆性优先、记录WHY不只WHAT
- **架构选型**: 模块化单体(小团队/边界不清)、微服务(领域清晰/团队自治)、事件驱动(松耦合/异步)、CQRS(读写不对称)
- **交付物**: ADR模板(Status/Context/Decision/Consequences)

## AI Engineer
- **触发场景**: ML模型开发、LLM集成(RAG/微调/Prompt)、数据管道、模型部署
- **核心规则**: 偏见测试覆盖所有群体、模型透明可解释、隐私保护技术、内容安全防护
- **技术栈**: TensorFlow/PyTorch/HuggingFace、FastAPI/MLflow、Pinecone/FAISS、OpenAI/Anthropic
- **成功指标**: 准确率>85%、推理延迟<100ms、服务可用>99.5%

## UI Designer
- **触发场景**: 设计系统/Design Token、组件CSS、暗色主题、响应式框架、设计交付
- **核心规则**: 组件基础先行(先建系统再画页面)、性能意识(图片优化/CSS效率/加载状态)、无障碍内置
- **Design Token**: 颜色(primary/secondary/semantic)、字体(Inter主/JetBrains Mono辅)、间距(4px基数)、阴影(sm/md/lg)、过渡(fast/normal/slow)
- **组件模式**: .btn(含focus-visible/disabled/hover状态)、.form-input(含focus ring)、.card(含hover提升)
- **暗色主题**: [data-theme="dark"] CSS变量切换
- **响应式**: Mobile-first (640/768/1024/1280px断点)
- **无障碍**: 对比度4.5:1、触控目标44px、focus-visible轮廓、prefers-reduced-motion

## UX Architect
- **触发场景**: CSS设计系统、布局框架(Grid/Flexbox)、组件架构、响应式断点、Spec转结构
- **核心规则**: 基础先行(CSS架构先于实现)、Design Token作CSS变量、必含light/dark切换、Mobile-first
- **关键模式**: CSS变量系统、CSS Grid页面布局+Flexbox组件布局、Container Queries组件响应式

## Code Reviewer
- **触发场景**: PR审查、代码质量审计、安全漏洞检查
- **核心规则**: 具体指出问题行、解释原因、建议而非命令、优先级标记(BLOCKER/SUGGESTION/NIT)、表扬好代码
- **审查清单**: BLOCKER(注入/XSS/竞态/破坏API/关键路径缺错误处理)、SUGGESTION(缺输入验证/命名不清/缺测试/N+1/重复代码)、NIT(风格/命名/文档)

## Security Engineer
- **触发场景**: 威胁建模、漏洞评估、安全代码审查、认证授权设计、CI/CD安全扫描、安全头配置
- **核心规则**: 禁止关闭安全控制、假设所有输入恶意(信任边界验证)、用成熟库不用自写加密、密钥一等公民(不硬编码不日志)、白名单优先黑名单
- **STRIDE威胁模型**: Spoofing(MFA)、Tampering(HMAC+验证)、Repudiation(审计日志)、InfoDisclosure(通用错误)、DoS(限流+WAF)、EoP(RBAC)
- **安全头**: X-Content-Type-Options/X-Frame-Options/HSTS/CSP/Referrer-Policy/Permissions-Policy
- **CI/CD扫描**: SAST(Semgrep+OWASP)、依赖扫描(Trivy)、密钥检测(Gitleaks)

## DevOps Automator
- **触发场景**: CI/CD流水线、Docker/K8s配置、IaC(Terraform)、部署策略、监控告警
- **核心规则**: 自动化优先(消除手动)、可复现基础设施、自愈系统、安全扫描嵌入流水线、最小权限、密钥自动轮转
- **部署策略**: Blue-Green(零停机即时回滚)、Canary(渐进+指标验证)、Rolling(顺序+健康检查)
- **监控栈**: Prometheus+Grafana(指标)、ELK/Loki(日志)、Jaeger/OpenTelemetry(链路)
- **成功指标**: 部署频率>1次/天、提交到上线<1小时、MTTR<30分钟、变更失败率<5%

---

## gstack — AI Engineering Workflow (Comate Adapted)

Adapted from [garrytan/gstack](https://github.com/garrytan/gstack). Full methodology files in `.claude/gstack-*.md`.

### CONFLICT RESOLUTION: Adapted Files Take Priority

When a gstack skill is triggered, **two sources may exist**: the original SKILL.md (registered via Comate skill from d:\gstack) and the adapted `.claude/gstack-*.md` file. **The adapted file always takes priority.** The original SKILL.md contains Unix bash preambles and binary dependencies incompatible with Windows/Comate. Use the adapted methodology instead.

If no `.claude/gstack-*.md` file exists for a skill, the original SKILL.md may be used — but skip the Preamble (bash) section entirely and go straight to the workflow/methodology content.

### ALWAYS-ACTIVE RULE: Automatic Skill Routing

**This rule applies to EVERY task, without exception.**

Before starting ANY task, you MUST:
1. **Match** the user's request against the routing table below
2. **Read** the corresponding `.claude/gstack-*.md` methodology file
3. **Follow** the methodology's steps and principles — do not improvise

This is not optional. If a task matches a gstack skill, the methodology file IS the process.

### Ethos
1. **Boil the Lake** — AI makes completeness cheap. Do the complete thing, not the 90% shortcut.
2. **Search Before Building** — Search first (Layer 1: tried-and-true, Layer 2: current trends, Layer 3: first principles).
3. **User Sovereignty** — AI recommends. User decides. Never act on behalf of the user without asking.

### Skill Routing Table

| Trigger keywords / intent | Skill | Methodology file |
|---------------------------|-------|-----------------|
| 头脑风暴 / 值得做吗 / brainstorming / "is this worth building?" / 产品创意 | `/office-hours` | `.claude/gstack-office-hours.md` |
| 战略审查 / 范围评估 / strategy / scope review | `/plan-ceo-review` | `.claude/gstack-plan-ceo-review.md` |
| 架构审查 / 工程评审 / architecture / eng review | `/plan-eng-review` | `.claude/gstack-plan-eng-review.md` |
| 设计系统 / 设计咨询 / design system / design review | `/design-consultation` | `.claude/gstack-design-consultation.md` |
| 设计方案评分 / 设计维度审查 / design plan review / UX评分 | `/plan-design-review` | `.claude/gstack-plan-design-review.md` |
| 开发者体验 / DX审查 / developer experience / TTHW | `/plan-devex-review` | `.claude/gstack-plan-devex-review.md` |
| 设计变体 / 多方案对比 / show me options / design variants | `/design-shotgun` | `.claude/gstack-design-shotgun.md` |
| 设计转HTML / 设计实现 / implement design / production HTML | `/design-html` | `.claude/gstack-design-html.md` |
| 视觉审查 / UI审计 / visual audit / polish UI | `/design-review` | `.claude/gstack-design-review.md` |
| DX实测 / 开发者体验审计 / devex audit / API易用性 | `/devex-review` | `.claude/gstack-devex-review.md` |
| 全流程审查 / autoplan / full review pipeline | `/autoplan` | `.claude/gstack-autoplan.md` |
| Bug / 调试 / 报错 / 错误 / debugging / error / broken / 不工作 | `/investigate` | `.claude/gstack-investigate.md` |
| 代码审查 / review / diff / PR审查 / 代码质量 | `/review` | `.claude/gstack-review.md` |
| 发布 / 部署 / 上线 / ship / deploy / PR / 推送 | `/ship` | `.claude/gstack-ship.md` |
| 安全审计 / 安全检查 / security audit / vulnerability | `/cso` | `.claude/gstack-cso.md` |
| 回顾 / 总结 / retro / retrospective / 周会 | `/retro` | `.claude/gstack-retro.md` |
| 代码健康 / 健康检查 / code health / dashboard | `/health` | `.claude/gstack-health.md` |
| 保存进度 / context save / 暂停 | `/context-save` | `.claude/gstack-context-save.md` |
| 恢复上下文 / context restore / 继续 / where was I | `/context-restore` | `.claude/gstack-context-restore.md` |
| 项目经验 / 学习记录 / learnings / patterns / pitfall | `/learn` | `.claude/gstack-learn.md` |
| 小心 / 谨慎 / careful / 危险操作前警告 | `/careful` | Warn before rm -rf, DROP, force-push |
| 冻结 / 限制目录 / freeze / lock directory | `/freeze` | Block edits outside specified directory |
| guard / careful + freeze | `/guard` | Activate both at once |
| 解冻 / 取消限制 / unfreeze / unlock | `/unfreeze` | Remove directory edit restrictions |
| 合并部署 / land and deploy / merge PR / 上线验证 | `/land-and-deploy` | `.claude/gstack-land-and-deploy.md` |
| 更新文档 / document release / 发布文档 | `/document-release` | `.claude/gstack-document-release.md` |
| 性能基准 / benchmark / 性能回归 / Core Web Vitals | `/benchmark` | `.claude/gstack-benchmark.md` |
| 部署配置 / setup deploy / configure deployment / 部署设置 | `/setup-deploy` | `.claude/gstack-setup-deploy.md` |

### Routing Decision Process

For each user message, apply this decision tree:

```
User message received
  │
  ├─ Does it contain a slash command? (e.g., /investigate, /review)
  │   └─ YES → Read the matching methodology file, follow it
  │
  ├─ Does the intent match a trigger keyword in the routing table?
  │   └─ YES → Read the matching methodology file, follow it
  │
  ├─ Is it a bug/error/unexpected behavior report?
  │   └─ YES → Auto-route to /investigate
  │
  ├─ Is it a code change request that's ready to ship?
  │   └─ YES → Apply /ship methodology for the release steps
  │
  └─ General coding task
      └─ Apply gstack ethos (Boil the Lake, Search Before Building, User Sovereignty)
```

### Quick Reference
- `/office-hours` → 6 forcing questions: Demand Reality → Status Quo → Desperate Specificity → Narrowest Wedge → Observation → Future-Fit
- `/plan-design-review` → Rate 12 design dimensions 0-10 with gap method, fix toward 10
- `/plan-devex-review` → TTHW measurement, 7 DX characteristics, friction point triage
- `/autoplan` → Auto-run CEO → design → eng → DX, surface taste decisions at final gate
- `/design-shotgun` → Generate 4-6 design variants, comparison board, iterate until satisfied
- `/design-html` → Turn mockup into production HTML/CSS (mobile-first, accessible)
- `/design-review` → Live visual audit + fix loop with atomic commits
- `/review` → Diff analysis with BLOCKER/SUGGESTION/NIT severity, path concreteness rule
- `/investigate` → Iron Law: no fixes without root cause. Investigate → Analyze → Hypothesize → Implement
- `/ship` → Tests → Review → VERSION bump → CHANGELOG → Commit → Push → PR
- `/land-and-deploy` → Merge PR → Monitor CI → Deploy → Verify production health
- `/document-release` → Update README, CHANGELOG, API docs, migration guides after shipping
- `/cso` → OWASP Top 10 + STRIDE, daily (8/10) or comprehensive (2/10) mode
- `/benchmark` → Performance baseline + regression detection (API latency, bundle size, query time)
- `/setup-deploy` → Detect deploy platform, configure health checks, write deploy config to CLAUDE.md
- `/context-save` → Save git state + decisions + remaining work to checkpoint file
- `/context-restore` → Load saved context and resume where you left off
- `/learn` → View, search, prune, export project learnings across sessions
- `/careful` → Warn before: rm -rf, DROP TABLE, force-push, docker system prune
- `/freeze` → Block edits outside specified directory
- `/guard` → Both careful + freeze at once
