# Middleware 规则

## 概述

Trae AI 采用 14 层有序 Middleware 链，灵感来自 DeerFlow 架构。Middleware 执行顺序**严格固定**，顺序错误会导致 bug。

## 执行模型

```
洋葱模型:
  进入: 外层 → 内层
  退出: 内层 → 外层
  
  Request → [M1 → M2 → ... → M14] → Handler → [M14 → ... → M2 → M1] → Response
```

## 14 层 Middleware 顺序

| # | Middleware | 优先级 | 职责 | 依赖 |
|---|------------|--------|------|------|
| 1 | SafetyMiddleware | P0 | 安全检查、权限验证 | 无 |
| 2 | ContextMiddleware | P0 | 上下文管理、状态注入 | 无 |
| 3 | ThreadDataMiddleware | P0 | 线程隔离、目录创建 | 无 |
| 4 | UploadsMiddleware | P1 | 文件上传处理 | thread_id |
| 5 | SandboxMiddleware | P1 | 沙盒环境获取 | thread_id |
| 6 | SummarizationMiddleware | P1 | 上下文压缩 | 无 |
| 7 | TodoMiddleware | P1 | 任务跟踪 | 无 |
| 8 | TokenUsageMiddleware | P1 | Token 计量 | 无 |
| 9 | TitleMiddleware | P2 | 自动标题生成 | 无 |
| 10 | MemoryMiddleware | P2 | 异步记忆提取 | 无 |
| 11 | ViewImageMiddleware | P2 | 视觉模型图片注入 | 无 |
| 12 | ToolFilterMiddleware | P2 | 工具延迟暴露 | 无 |
| 13 | SubagentLimitMiddleware | P1 | 子Agent并发限制 | 无 |
| 14 | ClarificationMiddleware | P2 | 澄清请求拦截 | **必须在最后** |

## 关键依赖关系

```
ThreadDataMiddleware (注入 thread_id)
        ↓
    ┌───┴───┐
    ↓       ↓
UploadsMiddleware  SandboxMiddleware
(使用 thread_id)   (使用 thread_id)
```

## 强制规则

### R1: 顺序不可更改
- ❌ 禁止调整 Middleware 顺序
- ❌ 禁止跳过任何 Middleware
- ✅ 只能在末尾添加新 Middleware

### R2: 错误处理
- Middleware 失败时调用 `onError` 钩子
- 错误向上传播，终止执行链
- 记录详细错误日志

### R3: 性能监控
- 每个 Middleware 记录执行时间
- 超过 100ms 触发警告
- 超过 500ms 触发告警

## 检查清单

```
□ SafetyMiddleware 已执行安全检查
□ ContextMiddleware 已注入上下文
□ ThreadDataMiddleware 已创建线程目录
□ SandboxMiddleware 已获取沙盒环境
□ 所有 Middleware 按顺序执行
□ 无 Middleware 跳过或顺序错误
```

## 示例用法

```typescript
const orchestrator = new EnhancedAgentOrchestrator(registry);

const result = await orchestrator.executeWithMiddleware({
  threadId: 'thread-123',
  userId: 'user-456',
  description: 'Create a new API endpoint'
});

console.log(result.middlewareStats);
// {
//   totalMiddlewares: 14,
//   middlewaresExecuted: 14,
//   executionTime: 150
// }
```

## 版本

**版本**: v1.0.0  
**更新日期**: 2026-04-08  
**主文件**: agent-orchestration-core.md
