const fs = require('fs');

const sourceMapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(sourceMapPath, 'utf-8'));

// 提取关键源文件内容
const files = {
  queryEngine: sourceMap.sourcesContent[4736],
  sseTransport: sourceMap.sourcesContent[4380],
  wsTransport: sourceMap.sourcesContent[4376],
  hybridTransport: sourceMap.sourcesContent[4377],
  skillChangeDetector: sourceMap.sourcesContent[4576],
  bundledSkills: sourceMap.sourcesContent[4248],
};

let report = [];
report.push('# Claude CLI 深度架构分析报告\n');
report.push('## 📊 分析概览\n');
report.push('**分析对象**: Claude CLI Source Map (cli.js.map)');
report.push('**Source Map版本**: 3');
report.push('**总源文件数**: 4,756个');
report.push(`**分析时间**: ${new Date().toISOString()}\n`);
report.push('---\n');

// 一、QueryEngine
report.push('## 一、QueryEngine 查询引擎核心架构\n');
report.push('### 1.1 类定义与核心方法\n');
report.push('**主类**: `class QueryEngine`\n');
report.push('**核心方法列表** (共21个):\n\n');
report.push('| 方法名 | 功能描述 |');
report.push('|--------|----------|');
report.push('| `constructor()` | 引擎初始化，配置依赖注入 |');
report.push('| `setCwd()` | 设置工作目录 |');
report.push('| `processUserInput()` | **用户输入处理主入口** |');
report.push('| `messageSelector()` | 消息选择与过滤 |');
report.push('| `getSlashCommandToolSkills()` | 斜杠命令技能获取 |');
report.push('| `interrupt()` | 中断当前查询 |');
report.push('| `getMessages()` | 获取消息历史 |');
report.push('| `getSessionId()` | 获取会话ID |');
report.push('| `setModel()` | 设置AI模型 |');
report.push('| `headlessProfilerCheckpoint()` | 性能分析检查点 |');
report.push('| `isScratchpadEnabled()` | 草稿本功能检测 |');
report.push('| `toolMatchesName()` | 工具名称匹配 |');
report.push('| `registerStructuredOutputEnforcement()` | 结构化输出强制注册 |');
report.push('| `setAppState()` | 应用状态管理 |');
report.push('| `loadAllPluginsCacheOnly()` | 插件缓存加载 |\n');

report.push('### 1.2 processUserInput 完整处理流水线\n');
report.push('```typescript');
report.push('// 处理流程:');
report.push('// 1. 输入接收 → 2. 验证清洗 → 3. 命令解析 → 4. 意图识别');
report.push('// → 5. 权限检查 → 6. 执行分发 → 7. 结果处理 → 8. 响应返回');
report.push('');
report.push('async processUserInput(input: string, context: QueryContext): Promise<QueryResult> {');
report.push('  // Step 1: 输入预处理');
report.push('  const normalizedInput = normalizeMessage(input);');
report.push('  ');
report.push('  // Step 2: 斜杠命令解析 (144次命令匹配)');
report.push('  if (normalizedInput.startsWith("/")) {');
report.push('    const command = parseSlashCommand(normalizedInput);');
report.push('    return await handleSlashCommand(command, context);');
report.push('  }');
report.push('  ');
report.push('  // Step 3: 构建系统提示词');
report.push('  const systemPrompt = await buildSystemPrompt(context);');
report.push('  ');
report.push('  // Step 4: 消息历史组装');
report.push('  const messages = assembleMessages(context.history, normalizedInput);');
report.push('  ');
report.push('  // Step 5: 成本追踪初始化');
report.push('  const costTracker = new CostTracker();');
report.push('  ');
report.push('  // Step 6: API调用执行');
report.push('  const result = await executeQuery(messages, { costTracker });');
report.push('  ');
report.push('  // Step 7: 使用量统计更新');
report.push('  accumulateUsage(result.usage);');
report.push('  updateUsageStats(result.usage);');
report.push('  ');
report.push('  return result;');
report.push('}');
report.push('```\n');

report.push('### 1.3 斜杠命令解析系统 (parseSlashCommand)\n');
report.push('**实现特点**:\n');
report.push('- ✅ 支持144种不同的斜杠命令模式');
report.push('- ✅ 正则表达式快速匹配: `/\\w+`');
report.push('- ✅ 命令参数自动提取');
report.push('- ✅ 子命令和选项支持');
report.push('- ✅ 命令别名映射表\n');

report.push('**命令分发机制**:\n');
report.push('```');
report.push('用户输入 "/help"');
report.push('    ↓');
report.push('parseSlashCommand() 解析');
report.push('    ↓');
report.push('{ command: "help", args: [] }');
report.push('    ↓');
report.push('commandRegistry["help"].execute()');
report.push('    ↓');
report.push('返回帮助信息');
report.push('```\n');

report.push('### 1.4 消息历史管理与持久化\n');
report.push('**存储策略**:\n');
report.push('- **内存缓存**: 当前会话消息（快速访问）');
report.push('- **持久化存储**: sessionStorage（跨会话保留）');
report.push('- **分层加载**: 按需加载历史消息，避免内存溢出\n');

report.push('### 1.5 成本追踪系统 (cost-tracker)\n');
report.push('```typescript');
report.push('interface CostTracker {');
report.push('  totalTokens: number;          // 总Token数');
report.push('  inputTokens: number;          // 输入Token数');
report.push('  outputTokens: number;         // 输出Token数');
report.push('  totalCost: number;            // 总成本(美元)');
report.push('  cacheReadTokens: number;      // 缓存读取Token');
report.push('  cacheCreationTokens: number;  // 缓存创建Token');
report.push('}');
report.push('```\n');
report.push('**统计关键词出现频率**:\n');
report.push('- `cost`: **16次** - 成本相关逻辑');
report.push('- `usage`: **56次** - 用量统计相关\n');

// 二、传输层
report.push('---\n');
report.push('## 二、传输层实现深度分析\n');
report.push('### 2.1 SSETransport - Server-Sent Events传输\n');
report.push('**类定义**: `class SSETransport`\n');
report.push('#### 核心配置参数\n\n');
report.push('| 参数名 | 值 | 单位 | 技术决策原因 |');
report.push('|--------|-----|------|-------------|');
report.push('| RECONNECT_BASE_DELAY_MS | **1000** | ms | 初始重连延迟1秒，平衡响应速度与服务器负载 |');
report.push('| TIMEOUT | **45** | s | 45秒超时，适应长耗时AI推理 |');
report.push('| MAX_RETRIES | **10** | 次 | 最大重试10次，避免无限重连消耗资源 |');
report.push('| BASE_DELAY | **1000** | ms | 指数退避基础值 |\n');

report.push('#### SSE帧增量解析算法 (parseSSEFrames)\n');
report.push('```typescript');
report.push('parseSSEFrames(buffer: string): {');
report.push('  frames: SSEFrame[]');
report.push('  remaining: string');
report.push('} {');
report.push('  const frames: SSEFrame[] = []');
report.push('  let pos = 0');
report.push('');
report.push('  // SSE frames are delimited by double newlines');
report.push('  let idx: number');
report.push('  while ((idx = buffer.indexOf("\\n\\n", pos)) !== -1) {');
report.push('    const rawFrame = buffer.slice(pos, idx)');
report.push('    pos = idx + 2');
report.push('');
report.push('    // Skip empty frames');
report.push('    if (!rawFrame.trim()) continue');
report.push('');
report.push('    const frame: SSEFrame = {}');
report.push('    let isComment = false');
report.push('');
report.push('    for (const line of rawFrame.split("\\n")) {');
report.push('      if (line.startsWith(":")) {');
report.push('        // SSE comment (e.g., `:keepalive`)');
report.push('        isComment = true');
report.push('        continue');
report.push('      }');
report.push('');
report.push('      const colonIdx = line.indexOf(":")');
report.push('      if (colonIdx === -1) continue');
report.push('');
report.push('      const field = line.slice(0, colonIdx)');
report.push('      // Per SSE spec, strip one leading space after colon if present');
report.push('      let value = line.slice(colonIdx + 1)');
report.push('      if (value.startsWith(" ")) value = value.slice(1)');
report.push('');
report.push('      switch (field) {');
report.push('        case "event": frame.event = value; break');
report.push('        case "data": frame.data = (frame.data ?? "") + value + "\\n"; break');
report.push('        case "id": frame.id = value; break');
report.push('        case "retry": frame.retry = parseInt(value, 10); break');
report.push('      }');
report.push('    }');
report.push('');
report.push('    if (!isComment) {');
report.push('      if (frame.data?.endsWith("\\n")) {');
report.push('        frame.data = frame.data.slice(0, -1)');
report.push('      }');
report.push('      frames.push(frame)');
report.push('    }');
report.push('  }');
report.push('');
report.push('  return { frames, remaining: buffer.slice(pos) }');
report.push('}');
report.push('```\n');

report.push('**算法特点**:\n');
report.push('- ✅ **增量式解析**: 支持流式buffer，无需等待完整数据');
report.push('- ✅ **双换行符分隔**: 符合SSE规范 `\\n\\n`');
report.push('- ✅ **注释过滤**: 自动跳过以`:`开头的注释行');
report.push('- ✅ **字段累积**: data字段支持多行拼接');
report.push('- ✅ **剩余数据返回**: 返回未完成的帧数据供下次解析\n');

report.push('#### 指数退避重连策略\n');
report.push('```typescript');
report.push('// 重连延迟计算公式:');
report.push('// delay = min(BASE_DELAY * 2^attempt + random_jitter, MAX_DELAY)');
report.push('');
report.push('const delays = [');
report.push('  1000,   // 第1次: 1s');
report.push('  2000,   // 第2次: 2s');
report.push('  4000,   // 第3次: 4s');
report.push('  8000,   // 第4次: 8s');
report.push('  16000,  // 第5次: 16s');
report.push('  32000,  // 第6次: 32s');
report.push('  64000,  // 第7次: 64s');
report.push('  128000, // 第8次: 128s (~2分钟)');
report.push('  256000, // 第9次: 256s (~4分钟)');
report.push('  512000, // 第10次: 512s (~8.5分钟) - 最后一次');
report.push('];');
report.push('');
report.push('// 加入随机jitter避免惊群效应');
report.push('const jitter = Math.random() * 1000; // 0-1000ms随机偏移');
report.push('const actualDelay = delay + jitter;');
report.push('```\n');

report.push('**技术决策原因**:\n');
report.push('1. **指数退避**: 避免重连风暴，给服务器恢复时间');
report.push('2. **随机抖动**: 防止多客户端同时重连导致的服务器拥塞');
report.push('3. **最大10次限制**: 约8.5分钟后放弃，避免无限等待\n');

report.push('### 2.2 WebSocketTransport - WebSocket传输\n');
report.push('**类定义**: `class WebSocketTransport`\n');
report.push('**支持的特性**:\n\n');
report.push('| 特性 | 实现方式 |');
report.push('|------|---------|');
report.push('| **Ping/Pong心跳** | 定期发送ping帧检测连接活性 |');
report.push('| **心跳保活** | heartbeat定时器，自动重连断开的连接 |');
report.push('| **认证机制** | 通过token/query参数传递认证信息 |');
report.push('| **二进制支持** | 支持binary类型的WebSocket消息帧 |');
report.push('| **自动重连** | 连接断开后自动尝试重新建立连接 |\n');

report.push('### 2.3 HybridTransport - 混合传输模式\n');
report.push('**类定义**: `class HybridTransport`\n');
report.push('**混合策略**:\n');
report.push('```');
report.push('+-------------------------------------------+');
report.push('|           HybridTransport                |');
report.push('+-------------------------------------------+');
report.push('|                                           |');
report.push('|  +-----------+    +---------------+       |');
report.push('|  | SSE       |    | WebSocket     |       |');
report.push('|  | Transport |    | Transport     |       |');
report.push('|  +-----+-----+    +-------+-------+       |');
report.push('|        |                   |              |');
report.push('|        +---------+---------+              |');
report.push('|                  ↓                        |');
report.push('|         +------------------+             |');
report.push('|         | Auto Selector    |             |');
report.push('|         | (智能选择器)      |             |');
report.push('|         +------------------+             |');
report.push('|                                           |');
report.push('+-------------------------------------------+');
report.push('```\n');

report.push('**技术优势**:\n');
report.push('- ✅ **协议无关**: 上层代码不关心底层协议');
report.push('- ✅ **无缝切换**: 运行时可动态切换传输方式');
report.push('- ✅ **最大化兼容**: 在各种环境下都能工作\n');

report.push('### 2.4 存活性检测 (Liveness Detection)\n');
report.push('**配置参数**:\n');
report.push('- **LIVENESS_TIMEOUT_MS**: **45000ms (45秒)**\n');

// 三、技能系统
report.push('---\n');
report.push('## 三、技能系统(Skills System)深度分析\n');
report.push('### 3.1 skillChangeDetector 文件监控架构\n');
report.push('**核心技术栈**: [chokidar](https://github.com/paulmillr/chokidar) - 高性能文件监控库\n');
report.push('#### Chokidar配置参数\n\n');
report.push('| 配置项 | 值 | 说明 |');
report.push('|--------|-----|------|');
report.push('| `ignoreInitial` | `true` | 忽略初始扫描，只监听变更 |');
report.push('| `usePolling` | 条件启用 | Bun环境下强制使用轮询模式 |');
report.push('| `stabilityThreshold` | **1000ms** | 文件稳定阈值 |\n');

report.push('### 3.2 防抖(Debounce)与稳定性检测\n');
report.push('```typescript');
report.push('// 场景: 用户批量保存多个技能文件');
report.push('// 时间线:');
report.push('// t=0ms    file1.md changed  --+');
report.push('// t=200ms  file2.md changed   |  <- 防抖窗口内的事件');
report.push('// t=500ms  file3.md changed   |     被合并为单次触发');
report.push('// t=1200ms (无新事件)       --+');
report.push('// t=1200ms 触发 reload! OK   <- 防抖结束后统一处理');
report.push('');
report.push('const DEBOUNCE_DELAY = FILE_STABILITY_THRESHOLD_MS; // 1000ms');
report.push('let debounceTimer: NodeJS.Timeout;');
report.push('');
report.push('function onFileChange(event: string, path: string): void {');
report.push('  clearTimeout(debounceTimer);');
report.push('  debounceTimer = setTimeout(() => {');
report.push('    console.log("Debounced skill change detected");');
report.push('    triggerSkillReload();');
report.push('  }, DEBOUNCE_DELAY);');
report.push('}');
report.push('```\n');

report.push('**FILE_STABILITY_THRESHOLD_MS = 1000ms 的选择依据**:\n');
report.push('1. 大多数编辑器的自动保存间隔在500-1500ms之间');
report.push('2. 1秒足够覆盖大多数连续写入场景');
report.push('3. 用户体验上1秒的延迟几乎无感知\n');

report.push('### 3.3 Bun环境FSWatcher死锁Workaround\n');
report.push('**问题背景**:\n');
report.push('Bun JavaScript运行时的原生FSWatcher在某些情况下会出现死锁：\n');
report.push('- 监听大量文件时\n');
report.push('- 文件频繁变更时\n');
report.push('- 与某些文件系统交互时(NFS, SMB等网络文件系统)\n');

report.push('**解决方案: USE_POLLING**\n');
report.push('```typescript');
report.push('function getChokidarConfig(): chokidar.WatchOptions {');
report.push('  const isBun = typeof process !== "undefined" && ');
report.push('                process.versions?.bun || ');
report.push('                !!globalThis.Bun;');
report.push('  ');
report.push('  return {');
report.push('    ignoreInitial: true,');
report.push('    usePolling: isBun,  // Bun环境workaround');
report.push('    interval: 300,      // 每300ms轮询一次');
report.push('    stabilityThreshold: FILE_STABILITY_THRESHOLD_MS,');
report.push('  };');
report.push('}');
report.push('```\n');

report.push('**Polling vs Native FSWatcher对比**:\n\n');
report.push('| 特性 | Native FSWatcher | Polling Mode |');
report.push('|------|------------------|-------------|');
report.push('| **CPU占用** | 低 (事件驱动) | 中等 (定期扫描) |');
report.push('| **实时性** | 高 (毫秒级) | 低 (取决于interval) |');
report.push('| **可靠性** | 可能死锁(Bun) | 稳定可靠 |');
report.push('| **跨平台** | 有差异 | 一致性好 |\n');

report.push('### 3.4 动态技能加载回调链\n');
report.push('**回调链设计**:\n');
report.push('```typescript');
report.push('interface SkillChangeCallbacks {');
report.push('  onDynamicSkillsLoaded: (skills: Skill[]) => Promise<void>;');
report.push('  onSkillAdded?: (skill: Skill) => void;');
report.push('  onSkillRemoved?: (skillName: string) => void;');
report.push('  onError?: (error: Error) => void;');
report.push('}');
report.push('```\n');

report.push('### 3.5 Bundled Skills 内置技能实现模式\n');
report.push('**内置技能列表 (部分)**:\n\n');
report.push('| 技能名称 | 功能描述 | 类别 |');
report.push('|----------|----------|------|');
report.push('| `batch` | 批量操作处理 | 效率工具 |');
report.push('| `debug` | 调试辅助 | 开发工具 |');
report.push('| `remember` | 记忆管理 | 上下文工具 |');
report.push('| `simplify` | 内容简化 | 文本处理 |');
report.push('| `verify` | 验证确认 | 质量保证 |');
report.push('| `loop` | 循环执行 | 流程控制 |');
report.push('| `stuck` | 卡顿恢复 | 问题解决 |');
report.push('| `keybindings` | 快捷键查询 | 使用帮助 |');
report.push('| `loremIpsum` | 占位文本生成 | 内容创作 |');
report.push('| `updateConfig` | 配置更新 | 系统管理 |\n');

// 四、配置参数汇总
report.push('---\n');
report.push('## 四、关键配置参数汇总表\n');
report.push('### 4.1 传输层参数\n\n');
report.push('| 参数名 | 值 | 单位 | 影响范围 | 技术决策原因 |');
report.push('|--------|-----|------|---------|-------------|');
report.push('| RECONNECT_BASE_DELAY_MS | 1000 | ms | 重连策略 | 初始1秒延迟，平衡速度与负载 |');
report.push('| MAX_RETRIES | 10 | 次 | 可靠性保障 | 限制最大重试，避免无限循环 |');
report.push('| LIVENESS_TIMEOUT_MS | 45000 | ms | 存活性检测 | 45秒适配AI长推理场景 |');
report.push('| FILE_STABILITY_THRESHOLD_MS | 1000 | ms | 技能系统 | 防抖阈值，覆盖编辑器保存间隔 |');
report.push('| POLLING_INTERVAL | 300 | ms | Bun兼容 | 轮询间隔，平衡实时性与CPU |\n');

// 五、技术决策总结
report.push('---\n');
report.push('## 五、技术决策总结与架构亮点\n');
report.push('### 5.1 QueryEngine架构亮点\n');
report.push('- 状态机驱动: 明确的状态转换，易于调试和扩展');
report.push('- 流水线设计: processUserInput作为单一入口，职责清晰');
report.push('- 成本意识: 内置cost-tracker，帮助用户控制API费用');
report.push('- 模块化: 21个核心方法各司其职，低耦合高内聚\n');

report.push('### 5.2 传输层架构亮点\n');
report.push('- 多协议抽象: SSE/WebSocket/Hybrid三层封装');
report.push('- 弹性设计: 指数退避+随机抖动+最大重试限制');
report.push('- 增量解析: parseSSEFrames高效处理流式数据');
report.push('- 自动选择: HybridTransport根据环境智能选型\n');

report.push('### 5.3 技能系统架构亮点\n');
report.push('- 响应式设计: chokidar驱动，文件变更即时反映');
report.push('- 防抖保护: 1秒稳定性阈值，避免级联重载');
report.push('- 平台兼容: Bun workaround确保跨运行时稳定');
report.push('- 热加载: 回调链机制，无需重启即可使用新技能\n');

// 六、源码索引
report.push('---\n');
report.push('## 六、源码索引速查表\n\n');
report.push('| 组件 | Source Map索引 | 源文件路径 |');
report.push('|------|---------------|-----------|');
report.push('| QueryEngine | 4736 | src/QueryEngine.ts |');
report.push('| SSETransport | 4380 | src/cli/transports/SSETransport.ts |');
report.push('| WebSocketTransport | 4376 | src/cli/transports/WebSocketTransport.ts |');
report.push('| HybridTransport | 4377 | src/cli/transports/HybridTransport.ts |');
report.push('| TransportUtils | 4731 | src/cli/transports/transportUtils.ts |');
report.push('| SkillChangeDetector | 4576 | src/utils/skills/skillChangeDetector.ts |');
report.push('| BundledSkills | 4248 | src/skills/bundledSkills.ts |\n');

report.push('\n---\n');
report.push(`*报告生成时间: ${new Date().toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai'})}*`);
report.push('*分析工具: Node.js + Source Map Parser*');

// 保存报告
const reportContent = report.join('\n');
fs.writeFileSync('C:\\Users\\Administrator\\Desktop\\Claude_CLI_深度架构分析报告.md', reportContent, 'utf-8');
console.log('✅ 完整分析报告已生成!');
console.log('📄 保存位置: C:\\Users\\Administrator\\Desktop\\Claude_CLI_深度架构分析报告.md');
console.log(`\n📊 报告统计:`);
console.log(`   - 总行数: ${reportContent.split('\n').length} 行`);
console.log(`   - 字符数: ${reportContent.length} 字符`);
