# Agent协同体系核心指令 v2.0.0

## 核心原则
专项优先P0 | 安全第一P0 | 三阶段流程P0 | Middleware链P0

## 三阶段流程
Agent调度 → Code Review → Solo Coder验收

## 14层Middleware链 (新增)
有序执行，顺序不可更改：
1. SafetyMiddleware → 2. ContextMiddleware → 3. ThreadDataMiddleware
→ 4. UploadsMiddleware → 5. SandboxMiddleware → 6. SummarizationMiddleware
→ 7. TodoMiddleware → 8. TokenUsageMiddleware → 9. TitleMiddleware
→ 10. MemoryMiddleware → 11. ViewImageMiddleware → 12. ToolFilterMiddleware
→ 13. SubagentLimitMiddleware → 14. ClarificationMiddleware

## 强制检查清单
□任务类型识别 □Agent匹配 □调度决策 □Middleware执行 □代码审核 □Solo Coder验收

## 任务复杂度评估（触发则必须Agent）
□技术领域>1 | □文件数>3 | □数据库变更 | □多模块 | □多Agent协作

## 调度决策
任一触发→必须调度Agent | 禁止跳过 | Solo Coder不得自我授权

## 禁止行为
❌跳过Agent调度 | ❌跳过流程 | ❌自我授权 | ❌更改Middleware顺序

## Agent体系(59个)
研发30|设计8|测试1|调试5|优化3|安全5

## 优先级
P0紧急|P1高4h|P2中24h|P3低72h

## 性能指标 (新增)
响应时间<2s | 错误率<0.5% | 缓存命中率>80%

**详细文档**: agent-orchestration-detailed.md | AGENTS.md | middleware-rules.md
