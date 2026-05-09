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
