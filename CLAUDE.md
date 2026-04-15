# Project Guidelines

## 折叠动画模板约定

当用户提到「参考折叠动画」时，应使用以下文件作为标准模板：

| 文件 | 用途 |
|------|------|
| `static/collapse-animated.css` | 动画样式模板 |
| `static/collapse-animated.js` | 动画逻辑模板 |
| `templates/product.html` (L1150-1170) | 修复 contain 属性导致点击事件路由异常的集成代码示例 |

**关键经验**：CSS `contain: layout` 属性会影响点击事件的 `e.target`，需要使用 document 级别点击拦截 + 坐标判断来解决。

## Self-Improvement Skill

This project uses the self-improvement skill for continuous learning and improvement.

### When to Log Learnings

Log to `.learnings/` directory when:

1. **Errors** → `.learnings/ERRORS.md`
   - Command fails unexpectedly
   - Exception or error occurs
   - Operation doesn't work as expected

2. **Corrections** → `.learnings/LEARNINGS.md`
   - User corrects your response
   - Knowledge was outdated or incorrect
   - Better approach discovered

3. **Feature Requests** → `.learnings/FEATURE_REQUESTS.md`
   - User requests missing capability
   - Suggested improvements

### Learning Format

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: ISO-8601 timestamp
**Priority**: low | medium | high | critical
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
Brief description

### Details
Full context

### Suggested Action
Specific fix or improvement

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file
- Tags: tag1, tag2

---
```

### Promote Learnings

When a learning is broadly applicable, promote it to:
- `CLAUDE.md` - Project conventions and gotchas
- `AGENTS.md` - Agent workflows and automation
- `.github/copilot-instructions.md` - GitHub Copilot context

### Quick Commands

```bash
# View pending learnings
grep -h "Status\*\*: pending" .learnings/*.md

# Search for related issues
grep -r "keyword" .learnings/
```

## Agent调度规则（Critical - 必须遵守）

**核心原则**：涉及多个技术领域的任务，**必须**使用Task工具调度专用Agent执行

### 触发Agent调度的条件

| 评估维度 | 调度阈值 | 说明 |
|----------|----------|------|
| 技术领域数 | >1个领域 | 前端/后端/数据库/运维/安全 |
| 文件数量 | >3个文件 | 需要修改的文件总数 |
| 数据库变更 | 需要DDL | 新增/删除/修改表结构 |
| 跨模块修改 | 涉及多个模块 | product + order 同时修改 |
| 多Agent协作 | 需要frontend+backend | 前后端同时修改 |

### 禁止行为（违反将记录到ERRORS.md）

- ❌ 以"任务简单"跳过Agent调度
- ❌ 以"置信度高"跳过流程
- ❌ Solo Coder自我授权直接执行
- ❌ 跳过Task工具直接修改代码

### Agent调度执行流程

```
1. 完成任务复杂度评估
2. 如果触发调度阈值 → 立即使用Task工具调度Agent
3. 等待Agent执行完成
4. 触发Code Review (code-review-excellence)
5. Solo Coder验收
```

### 相关文档

- `.trae/rules/AGENTS.md` - Agent工作流程与自动化规范
- `.trae/rules/agent-orchestration-core.md` - 核心指令
- `.trae/rules/project-rules.md` - 项目规则
