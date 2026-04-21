---
name: tool-interface-spec
description: "统一工具接口规范：为 Comate 所有工具定义标准化的安全标记、并发判定和结果大小控制。基于 Claude Code 的 Tool 接口设计，提供 isReadOnly/isDestructive/isConcurrencySafe 标记和 buildTool Builder 模式。"
---

# 统一工具接口规范

## 核心设计原则

基于 Claude Code 的 Tool 接口分析，为 Comate 工具系统定义标准化接口。

### 设计哲学

1. **Builder 模式优于继承**: 用 `buildTool()` 提供默认值，开发者只覆盖差异
2. **安全标记内嵌**: 每个工具自声明 `isReadOnly`/`isDestructive`/`isConcurrencySafe`
3. **结果大小可控**: `maxResultSize` 防止单个工具结果消耗全部上下文
4. **Prompt 按需注入**: 核心工具全量注入，扩展工具仅注入 schema

## 工具安全分类

### 当前 Comate 工具分类

| 工具 | isReadOnly | isDestructive | isConcurrencySafe | 说明 |
|------|-----------|--------------|------------------|------|
| read_file | true | false | true | 只读，可并发 |
| grep_content | true | false | true | 只读，可并发 |
| glob_path | true | false | true | 只读，可并发 |
| codebase_search | true | false | true | 只读，可并发 |
| edit_file | false | false | false | 写操作，不可并发 |
| write_file | false | true | false | 创建/覆盖文件，破坏性 |
| delete_file | false | true | false | 删除文件，破坏性 |
| run_command | false | varies | varies | 依赖命令内容 |
| delegate_subtask | true | false | true | 委派只读子任务时可并发 |
| ask_user_question | true | false | false | 需等待用户响应 |

### run_command 的动态安全判定

run_command 的安全性取决于实际执行的命令：

| 命令模式 | isReadOnly | isDestructive | isConcurrencySafe |
|----------|-----------|--------------|------------------|
| `git status/diff/log` | true | false | true |
| `pytest/python -c` | true | false | true |
| `pip install` | false | false | false |
| `rm/del` | false | true | false |
| `docker restart` | false | true | false |
| `python run.py` | false | false | false |

## 并发安全调度算法

### StreamingToolExecutor 简化逻辑

```
并发调度规则:
1. running 队列为空 → 任何工具都可执行
2. running 中有只读工具 → 只读工具可加入并发
3. running 中有写操作 → 等待其完成后才调度新工具
4. running 中有破坏性操作 → 等待其完成后才调度新工具

用伪代码:
canExecute(tool):
    if running.isEmpty(): return true
    if tool.isReadOnly and running.all(isReadOnly): return true
    return false  // 写操作必须独占
```

### Comate 当前并发能力

Comate 的 `delegate_subtask` 已支持并行调用（单条消息中多个 tool_use），但缺少并发安全判定。

**优化建议**: 在并行调用 delegate_subtask 时：
- 多个 Explore 类型的子任务可以并行
- General 类型的子任务（可能执行写操作）应串行
- 如果一个 General 子任务修改了文件，后续子任务必须等它完成

## 结果大小控制

### 各工具的 maxResultSize 建议

| 工具 | maxResultSize | 单位 | 截断策略 |
|------|-------------|------|---------|
| read_file | 2000 | 行 | 显示头尾各 200 行 |
| grep_content | 100 | 条匹配 | 标注总数，建议缩窄 |
| glob_path | 200 | 个文件 | 标注总数，建议缩窄 |
| run_command | 30000 | 字符 | 截断输出，提示完整输出路径 |
| delegate_subtask | 5000 | 字符 | 子代理结果摘要 |

### 实施方法

Comate 已有的参数：
- `read_file`: `limit` + `offset` → 分段读取
- `grep_content`: `head_limit` → 限制匹配数
- `run_command`: 输出自动截断在 30000 字符

需新增：
- `glob_path`: 添加 `max_results` 参数
- `delegate_subtask`: 子代理结果超长时自动摘要

## 工具 Prompt 注入策略

### 两层注入

**核心工具** (6个，全量注入到 system prompt):
- read_file, grep_content, glob_path, edit_file, write_file, run_command

**扩展工具** (仅注入名称+描述，按需加载完整说明):
- delegate_subtask, codebase_search, ask_user_question
- todo_write, web_search, web_fetch

### Token 预算

| 类型 | 数量 | 每个工具 Token | 总计 |
|------|------|-------------|------|
| 核心工具全量 | 6 | ~200 | ~1200 |
| 扩展工具目录 | 6 | ~30 | ~180 |
| **合计** | 12 | - | **~1380** |

## 实施路线图

### Phase 1: 安全标记 (立即可做)
- 在每次工具调用前，agent 自行判断 isReadOnly/isDestructive
- 写操作前自动确认: "此操作将修改 [文件]，是否继续？"
- 破坏性操作 (delete, overwrite) 需双重确认

### Phase 2: 并发调度 (中期)
- 多个 delegate_subtask(Explore) 并行执行
- delegate_subtask(General) 串行执行
- 通过 todo_write 跟踪并发任务状态

### Phase 3: 结果大小控制 (中期)
- 工具结果超长时自动截断
- 提供摘要而非原始输出
- 截断时标注原始大小和截断位置
