# ERP系统开发规则 v5.1.0

## 版本
v5.1.0 | 2026-04-07

## 规则文件结构
核心:agent-orchestration-core.md(516字) | 模块:core/*.md | 参考:agent-orchestration-detailed.md

## 规则优先级
1.core/*.md 2.project-rules.md

## 指令处理流程
技能检查→置信评分→规则确认→Agent调度决策→执行前确认→执行→验证→反馈学习

## 强制检查清单
□任务类型识别 □Agent匹配 □调度决策 □代码审核 □Solo Coder验收

## 任务复杂度评估（触发则必须Agent）
□技术领域>1 | □文件数>3 | □数据库变更 | □多模块 | □多Agent协作

## 调度决策
任一触发→必须调度Agent | Solo Coder不得自我授权 | 禁止跳过

## 置信度阈值
≥95%精细拆解 | 85-94%正常执行 | <70%询问用户

## 强制规则
安全:禁止硬编码|参数化查询|验证输入|HTTPS
性能:禁止N+1|使用索引|分页|缓存
规范:文档注释|单元测试|命名规范|错误处理

## SQL规范
动态条件用WHERE 1=1模式，禁止字符串拼接

## 技能自动激活
性能问题→python-performance-optimization | 代码审查→code-review-excellence | 调试→systematic-debugging

## 禁止跳过
技能检查|安全验证|质量检查|Agent调度检查

## 三阶段强制流程(P0)
Agent调度 → Code Review → Solo Coder验收

**核心原则**: 所有任务必须经过三阶段流程，禁止以任何理由跳过Agent调度和Code Review。