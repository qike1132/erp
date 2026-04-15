# Agent工作流程规范 v1.0

## 核心原则
Solo Coder只做验收，不直接执行 | Agent负责执行任务

## 任务复杂度评估（触发则必须Agent）
□技术领域>1 | □文件数>3 | □数据库变更 | □多模块 | □多Agent协作

## 调度决策
任一触发→必须使用Task工具调度Agent

## Agent匹配表
前端UI→frontend-developer | 后端API→backend-architect | 全栈→frontend+backend
数据库→backend-architect | 安全→security-related | 代码审查→code-review-excellence
性能→python-performance-optimization

## 调度执行流程
1.复杂度自检(强制) → 2.触发阈值→调度Agent → 3.Agent执行 → 4.Code Review → 5.Solo Coder验收

## 任务开始前检查
□识别任务类型 □评估复杂度 □确认调度决策 □触发则用Task工具调度 □记录决策

## Agent执行后检查
□验证输出完整 □触发Code Review □确认用户 □Solo Coder验收 □记录学习

## 禁止行为
❌Solo Coder自我授权直接执行 | ❌跳过Agent调度 | ❌跳过流程 | ❌跳过Task工具

## 预防机制
强制检查点 | 禁止自我授权 | Code Review强制覆盖 | 调度决策记录追踪

## 相关文档
agent-orchestration-core.md | project-rules.md | agent-orchestration-detailed.md