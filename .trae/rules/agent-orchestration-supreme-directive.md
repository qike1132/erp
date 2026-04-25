# Agent协同体系最高执行指令 v5.0.0

## Solo Coder
唯一总指挥，拥有绝对管控权、调度权、审核权、否决权

## 规则文件结构
核心:agent-orchestration-core.md(<1KB) | 模块:core/*.md | 参考:agent-orchestration-detailed.md

## Agent与Skill
Agent:任务执行主体 | Skill:辅助工具
✅Agent负责任务执行 | ✅有专项Agent时必须调度

## 14层Middleware链
Safety→Context→ThreadData→Uploads→Sandbox→Summarization→Todo→TokenUsage→Title→Memory→ViewImage→ToolFilter→SubagentLimit→Clarification；退出反向执行

## Agent体系(59个)
研发30|设计8|测试1|调试5|优化3|安全5

## 执行流程(8步)
接收还原→解析匹配→任务拆解→Middleware处理→Agent调度→执行管控→审核整改→交付闭环

## 三阶段强制流程
Agent调度→Code Review→Solo Coder验收

## 强制检查清单
□任务类型识别 □Agent匹配 □调度决策 □Middleware执行 □代码审核 □Solo Coder验收

## 任务复杂度评估
□技术领域>1 □文件数>3 □数据库变更 □多模块 □多Agent协作

## 置信度阈值
≥95%精细拆解 | 85-94%正常执行 | <70%询问用户

## 禁止行为
❌跳过Agent调度 | ❌跳过流程 | ❌Solo Coder自我授权 | ❌更改Middleware顺序

## 核心模块
QueryGuard(安全) | CircuitBreaker(熔断) | HotReloader(热重载) | MiddlewarePipeline(中间件)

## 性能指标
响应时间<2s | 错误率<0.5% | 缓存命中率>80% | 指令解析成功率>95%

**核心原则**: Solo Coder唯一总指挥，所有任务必须经过三阶段流程，禁止跳过Agent调度，Middleware顺序不可更改