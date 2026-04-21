---
name: context-compression
description: "三层上下文压缩策略：工具结果截断 + 对话级摘要 + 响应式紧急压缩。在长对话中自动管理上下文窗口，防止信息丢失和 token 溢出。当对话轮次超过15轮、token 使用超过70%、或 API 返回 context_window_exceeded 错误时触发。"
---

# 三层上下文压缩策略

> Context is a scarce resource. Every token matters.

## 核心原则

1. **先保存后响应 (WAL)**: 修改文件前先更新 SESSION-STATE.md，避免中断导致上下文丢失
2. **压缩边界可见**: 每次压缩在 Compaction Boundary Log 中记录，用户可追溯信息丢失
3. **关键信息优先保留**: 当前任务状态、活跃文件、关键决策不压缩

## Layer 1: 工具结果截断 (Tool Result Truncation)

### 规则

| 工具 | 最大结果大小 | 截断策略 |
|------|-------------|---------|
| read_file | 2000 行 | 超长文件只读头尾各 200 行 + `[... truncated N lines ...]` |
| grep_content | 100 条匹配 | 超出部分标注总数，建议缩窄搜索范围 |
| run_command | 30000 字符 | 超长输出写入临时文件，返回前 50 行 + 文件路径 |
| glob_path | 200 个文件 | 超出部分省略，提示缩小 glob 范围 |

### 实施方法

使用工具参数控制输出大小：
- `read_file`: 使用 `limit` 和 `offset` 参数分段读取
- `grep_content`: 使用 `head_limit` 参数限制匹配数
- `run_command`: 长输出用 `> temp_file` 重定向，再读取关键部分

## Layer 2: 对话级摘要压缩 (Conversation Compact)

### 触发条件

- 对话轮次超过 15 轮
- 估算 token 使用超过上下文窗口 70%
- 用户主动请求 `/compact`

### 压缩算法

当触发压缩时，生成结构化摘要替换历史消息：

```markdown
## Context Compaction Summary

### User Intent
[用户的核心意图，1-2 句话]

### Completed Actions
- [已完成的操作列表，每项一行]

### Current State
- 当前正在修改的文件: [文件列表]
- 当前任务进度: [进度描述]
- 遇到的问题: [问题描述]

### Key Decisions
- [本次对话中做出的关键决策]

### Pending Issues
- [待解决的问题]
```

### 压缩执行步骤

1. 更新 `memory/SESSION-STATE.md` 中的 Compaction Boundary Log
2. 在消息流中插入压缩边界标记：`[COMPACT: 压缩了 N 条消息为摘要]`
3. 保留最近 3 轮对话的完整上下文
4. 将更早的对话替换为结构化摘要

### 禁止压缩的内容

- 当前正在编辑的文件的完整内容
- 用户最近一次明确指令
- 未解决的错误信息
- 安全相关的权限决策

## Layer 3: 响应式紧急压缩 (Reactive Compact)

### 触发条件

- API 返回 `context_window_exceeded` 或类似 token 溢出错误
- `hasAttemptedReactiveCompact` 标志为 false（防止无限循环）

### 执行步骤

1. 设置 `hasAttemptedReactiveCompact = true`
2. 立即将所有历史消息压缩为极简摘要（仅保留：意图 + 当前进度 + 待处理项）
3. 仅保留最近 1 轮对话的完整上下文
4. 自动重试请求
5. 如果重试仍然失败，向用户报告并请求手动干预

### 紧急压缩摘要格式

```markdown
## Emergency Compact

**Intent**: [用户意图]
**Progress**: [当前进度百分比或描述]
**Active Files**: [正在修改的文件路径]
**Blocker**: [当前阻塞问题]
**Next Step**: [下一步需要做什么]
```

## SESSION-STATE.md 维护协议

每次重要操作后更新 `memory/SESSION-STATE.md`：

| 事件 | 更新内容 |
|------|---------|
| 开始新任务 | Current Task, Started, Key Files |
| 修改文件 | Active Files Being Modified |
| 做出决策 | Key Decisions Made This Session |
| 触发压缩 | Compaction Boundary Log |
| 完成任务 | Status → completed, 清空 Active Files |

## Token 预算分配建议

| 区域 | 预算占比 | 说明 |
|------|---------|------|
| System Prompt | 15-20% | 身份 + 工具说明 + CLAUDE.md |
| 对话历史 | 40-50% | 近期对话 + 压缩摘要 |
| 工具结果 | 20-30% | 当前轮次的工具输出 |
| 输出预留 | 15-20% | 模型生成的响应空间 |

当对话历史接近 50% 预算时，主动触发 Layer 2 压缩。
