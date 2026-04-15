# 学习记录

## [LRN-20260407-004] architecture

**Logged**: 2026-04-07T15:00:00Z
**Priority**: critical
**Status**: pending
**Area**: config

### Summary
Skill与Agent职责边界：Agent是任务执行主体，Skill是辅助工具

### Details
用户明确多智能体系统的架构设计原则：

**核心原则**：
1. **Agent负责执行**：每个任务应由专门的Agent负责执行
2. **Skill负责支持**：技能模块应作为辅助工具，与Agent协同工作
3. **职责边界明确**：当出现技能重合时，Agent为主，Skill为辅

**错误理解（需避免）**：
- ❌ 错误认为"激活Skill"等于"使用了Agent"
- ❌ 错误认为"Skill可以替代Agent执行任务"
- ❌ 在有专项Agent时不调用，直接用Skill自己执行

**正确理解**：
| 组件 | 职责 | 作用 |
|------|------|------|
| **Agent** | 任务执行主体 | 整体规划、决策、执行流程把控 |
| **Skill** | 辅助工具 | 提供功能性支持、最佳实践指导 |

**正确的执行架构**：
```
用户任务
    ↓
[Agent调度层] - Task工具调用专项Agent
    ↓
[专项Agent执行] - Frontend Developer Agent 负责前端开发
    ↓
[Skill辅助] - frontend-design Skill 提供设计规范支持
    ↓
[结果输出] - Agent产出最终成果
```

### Suggested Action
1. 更新 project-rules.md 明确 Skill/Agent 职责边界
2. 任务执行时必须先评估是否有专项Agent
3. 有专项Agent时必须调度，不得用Skill替代

### Metadata
- Source: user_feedback
- Related Files: .trae/rules/agent-orchestration-supreme-directive.md, .trae/frontend-developer/SKILL.md
- Tags: agent-skill-boundary, agent-as主体, skill-as辅助, architecture-design

---
