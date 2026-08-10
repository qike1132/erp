# MEMORY — 长期记忆

## Karpathy Guidelines 强制加载规则

所有对话、所有任务必须无条件强制执行 Andrej Karpathy 四条编码原则：

1. **Think Before Coding** — 先分析代码结构再动手，不确定时主动提问，存在歧义时呈现多种方案让用户选择
2. **Simplicity First** — 最少代码解决问题，不引入未要求的抽象/灵活性/错误处理
3. **Surgical Changes** — 只改必要的部分，匹配现有代码风格，清理自己引入的死代码，不顺手重构
4. **Goal-Driven Execution** — 每次改动后验证（lint + 读文件确认完整性），多步骤任务先列计划

每次会话开始时应主动使用 `use_skill("karpathy-guidelines")` 加载此规则，确保始终处于激活状态。
