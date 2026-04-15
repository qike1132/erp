# Tasks - Claude CLI源码深度技术分析

## 任务列表

- [x] Task 1: 解析Source Map文件结构并提取完整源文件清单
  - [x] 1.1 使用Node.js解析cli.js.map JSON结构
  - [x] 1.2 提取sources数组（共4756个源文件）
  - [x] 1.3 过滤第三方库（lodash/node_modules），保留1906个应用源码
  - [x] 1.4 按功能域分类：API层、Bridge系统、权限模块、工具框架、UI组件、传输层、技能系统、MCP集成、配置管理
  - [x] 1.5 输出模块依赖关系概览

- [x] Task 2: 深度分析API通信层实现（claude.ts / api.ts）
  - [x] 2.1 分析Anthropic SDK集成方式与初始化流程（5种Provider工厂模式）
  - [x] 2.2 研究Token计算逻辑与配额状态提取机制（三层Token计量体系）
  - [x] 2.3 分析流式SSE响应处理架构（AsyncIterator Stream类+背压控制）
  - [x] 2.4 研究错误分类（categorizeRetryableAPIError）与重试策略（19种SSL错误码）
  - [x] 2.5 分析缓存控制（Cache-Control Ephemeral/Global Scope）实现
  - [x] 2.6 提取消息规范化函数（normalizeMessagesForAPI等）

- [x] Task 3: 深度分析权限系统架构
  - [x] 3.1 分析useCanUseTool Hook的完整决策流程（7步流水线）
  - [x] 3.2 研究Transcript Classifier自动批准机制（ML驱动+置信度评分）
  - [x] 3.3 分析PermissionContext创建与队列管理（工厂函数+FIFO队列）
  - [x] 3.4 研究PermissionPrompt组件的交互设计（Ink React键盘导航）
  - [x] 3.5 分析各类权限处理器（coordinator/interactive/swarmWorker三级防御）
  - [x] 3.6 提取AutoMode拒绝追踪与YOLO审批流程（6种权限模式）

- [x] Task 4: 深度分析Bridge远程连接系统
  - [x] 4.1 分析bridgeMain.ts的核心架构与会话生命周期
  - [x] 4.2 研究JWT令牌刷新调度器（TokenRefreshScheduler定时策略）
  - [x] 4.3 分析SessionSpawner的多会话生成模式（默认32并发）
  - [x] 4.4 研究bridgeMessaging的消息类型守卫与过滤逻辑（discriminated union）
  - [x] 4.5 分析Backoff重试配置与优雅关闭机制（DEFAULT_BACKOFF常量详情）
  - [x] 4.6 提取WorkSecret编解码与会话ID兼容性处理

- [x] Task 5: 深度分析工具执行框架
  - [x] 5.1 分析Tool.ts的类型定义与工具Schema体系（Zod验证集成）
  - [x] 5.2 研究BashTool的危险命令检测逻辑（正则表达式匹配）
  - [x] 5.3 分析FileEditTool的差异计算与展示机制（SearchReplace模式）
  - [x] 5.4 研究工具进度报告类型体系（BashProgress/MCPProgress等8种类型）
  - [x] 5.5 分析工具权限上下文（ToolPermissionContext的数据结构字段）

- [x] Task 6: 深度分析QueryEngine与用户输入处理
  - [x] 6.1 分析QueryEngine的主循环架构（21个核心方法/状态机模型）
  - [x] 6.2 研究processUserInput的完整处理流水线（8步流程）
  - [x] 6.3 分析斜杠命令解析（parseSlashCommand）与分发机制（144种命令模式）
  - [x] 6.4 研究消息历史管理与使用量统计（accumulateUsage/updateUsage）
  - [x] 6.5 分析成本追踪（cost-tracker）实现（美元级成本展示）

- [x] Task 7: 深度分析传输层实现
  - [x] 7.1 分析SSETransport的帧增量解析算法（parseSSEFrames双换行分隔）
  - [x] 7.2 研究连接生命周期管理与存活性检测（LIVENESS_TIMEOUT_MS=45000）
  - [x] 7.3 分析指数退避重连策略（RECONNECT_BASE_DELAY_MS=1000 + jitter）
  - [x] 7.4 研究POST请求重试机制（10次重试/指数退避/8000ms封顶）
  - [x] 7.5 对比WebSocketTransport与HybridTransport的设计差异

- [x] Task 8: 深度分析技能系统与文件监控
  - [x] 8.1 分析skillChangeDetector的文件监控架构（chokidar集成）
  - [x] 8.2 研究防抖（debounce）与稳定性检测机制（300ms/1000ms阈值）
  - [x] 8.3 分析Bun环境下chokidar轮询workaround（USE_POLLING+FSWatcher死锁）
  - [x] 8.4 研究动态技能加载回调链（onDynamicSkillsLoaded事件链）
  - [x] 8.5 分析bundled skills的实现模式（声明式数据对象+模板化prompt）

- [x] Task 9: 提炼关键技术实现亮点
  - [x] 9.1 分析lodash-es四层缓存架构（Hash→ListCache→MapCache→Stack自动升级）
  - [x] 9.2 研究React Compiler _c()优化模式（$[]缓存数组/浅比较命中）
  - [x] 9.3 分析createSignal事件通知模式（发布订阅机制）
  - [x] 9.4 研究性能剖析检查点机制（双Profiler: startup+headless）
  - [x] 9.5 提取TypeScript高级类型模式（discriminated union/模板字面量/Pick-Omit）

- [x] Task 10: 编写Trae AI提升方案与技术学习报告
  - [x] 10.1 整合所有模块分析结果
  - [x] 10.2 针对Trae AI提出具体优化建议（5大方案/20+改进点）
  - [x] 10.3 量化预期收益（性能↓50%延迟/功能↑40%吞吐/体验↓67%操作步数）
  - [x] 10.4 输出完整的Markdown格式技术学习报告（已保存至specs目录）

# Task Dependencies
- [Task 2-9] 可并行执行（各模块独立分析） ✅ 已并行完成
- [Task 10] 依赖于 [Task 1-9] 全部完成 ✅ 已整合输出
- [Task 1] 必须首先完成（提供源码结构基础）✅ 首先完成
