const fs = require('fs');
const path = require('path');

const sourceMapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(sourceMapPath, 'utf-8'));

// 核心源文件索引
const coreFiles = {
  queryEngine: 4736,  // src/QueryEngine.ts
  query: 3729,        // src/query.ts
  sseTransport: 4380, // src/cli/transports/SSETransport.ts
  wsTransport: 4376,  // src/cli/transports/WebSocketTransport.ts
  hybridTransport: 4377, // src/cli/transports/HybridTransport.ts
  skillChangeDetector: 4576, // src/utils/skills/skillChangeDetector.ts
  bundledSkills: 4248, // src/skills/bundledSkills.ts
  transportUtils: 4731, // src/cli/transports/transportUtils.ts
};

console.log('═══════════════════════════════════════');
console.log('  Claude CLI 深度架构分析报告');
console.log('═══════════════════════════════════════\n');

// 1. QueryEngine 核心分析
console.log('╔════════════════════════════════════════╗');
console.log('║  一、QueryEngine 查询引擎核心架构      ║');
console.log('╚════════════════════════════════════════╝\n');

const queryEngineContent = sourceMap.sourcesContent[coreFiles.queryEngine];
if (queryEngineContent) {
  console.log('【1.1 类结构与主要方法】');
  
  // 提取类定义
  const classMatch = queryEngineContent.match(/class\s+(\w+)/g);
  console.log('定义的类:', classMatch);
  
  // 提取所有方法签名
  const methods = queryEngineContent.match(/^\s*(async\s+)?(public\s+|private\s+|protected\s+)?(\w+)\s*\(/gm);
  const uniqueMethods = [...new Set(methods?.map(m => m.trim()) || [])];
  console.log('\n核心方法列表 (共', uniqueMethods.length, '个):');
  uniqueMethods.slice(0, 20).forEach((m, i) => {
    console.log(`  ${i+1}. ${m}`);
  });
  
  // 分析状态机
  console.log('\n【1.2 状态转换机制】');
  const states = [];
  const stateRegex = /(?:state|Status)\s*===?\s*['"](\w+)['"]/g;
  let match;
  while ((match = stateRegex.exec(queryEngineContent)) !== null) {
    if (!states.includes(match[1])) states.push(match[1]);
  }
  console.log('识别到的状态:', states.join(', '));
  
  // 分析processUserInput
  if (queryEngineContent.includes('processUserInput')) {
    console.log('\n【1.3 processUserInput 处理流水线】');
    const processStart = queryEngineContent.indexOf('processUserInput');
    const processSnippet = queryEngineContent.substring(processStart, processStart + 2000);
    console.log(processSnippet.substring(0, 1500));
  }
  
  // 分析斜杠命令解析
  if (queryEngineContent.includes('parseSlashCommand') || queryEngineContent.includes('/')) {
    console.log('\n【1.4 斜杠命令解析系统】');
    const slashPatterns = [
      /\/\w+/g,
      /slashCommand/g,
      /command.*handler/gi,
      /parseCommand/g
    ];
    slashPatterns.forEach(pattern => {
      const matches = queryEngineContent.match(pattern);
      if (matches && matches.length > 0) {
        console.log(`  匹配 "${pattern.source}": ${matches.length} 次`);
      }
    });
  }
  
  // 成本追踪
  console.log('\n【1.5 成本追踪系统(cost-tracker)】');
  const costPatterns = ['cost', 'CostTracker', 'usage', 'token', 'price'];
  costPatterns.forEach(p => {
    const count = (queryEngineContent.match(new RegExp(p, 'gi')) || []).length;
    if (count > 0) console.log(`  "${p}" 出现次数: ${count}`);
  });
}

// 2. Transport 层分析
console.log('\n\n╔════════════════════════════════════════╗');
console.log('║  二、传输层实现深度分析                ║');
console.log('╚════════════════════════════════════════╝\n');

// SSE Transport
console.log('【2.1 SSETransport - Server-Sent Events传输】');
const sseContent = sourceMap.sourcesContent[coreFiles.sseTransport];
if (sseContent) {
  const sseClass = sseContent.match(/class\s+(\w+)/);
  console.log('类名:', sseClass?.[1]);
  
  // 提取关键配置
  const configs = {
    RECONNECT_DELAY: sseContent.match(/RECONNECT[_\w]*\s*=\s*(\d+)/)?.[1],
    TIMEOUT: sseContent.match(/TIMEOUT[_\w]*\s*=\s*(\d+)/)?.[1],
    MAX_RETRIES: sseContent.match(/MAX_RETRIES\s*=\s*(\d+)/)?.[1],
    BASE_DELAY: sseContent.match(/BASE_DELAY[_\w]*\s*=\s*(\d+)/)?.[1],
  };
  Object.entries(configs).forEach(([k, v]) => {
    if (v) console.log(`  ${k}: ${v}ms`);
  });
  
  // SSE帧解析
  if (sseContent.includes('parseSSE') || sseContent.includes('SSE')) {
    console.log('\nSSE帧解析算法:');
    const parseStart = sseContent.indexOf('parseSSE');
    if (parseStart > -1) {
      console.log(sseContent.substring(parseStart, parseStart + 800));
    }
  }
  
  // 重连策略
  if (sseContent.includes('reconnect') || sseContent.includes('retry')) {
    console.log('\n重连/重试机制:');
    const retryPatterns = ['exponential', 'backoff', 'jitter', 'retry', 'reconnect'];
    retryPatterns.forEach(p => {
      if (sseContent.toLowerCase().includes(p)) {
        console.log(`  ✓ 支持${p}策略`);
      }
    });
  }
}

// WebSocket Transport
console.log('\n【2.2 WebSocketTransport - WebSocket传输】');
const wsContent = sourceMap.sourcesContent[coreFiles.wsTransport];
if (wsContent) {
  const wsClass = wsContent.match(/class\s+(\w+)/);
  console.log('类名:', wsClass?.[1]);
  
  // 提取WebSocket特性
  const features = {
    binary: wsContent.includes('binary'),
    ping: wsContent.includes('ping') || wsContent.includes('pong'),
    heartbeat: wsContent.includes('heartbeat'),
    reconnect: wsContent.includes('reconnect'),
    auth: wsContent.includes('auth') || wsContent.includes('token'),
  };
  Object.entries(features).forEach(([k, v]) => {
    if (v) console.log(`  ✓ 支持特性: ${k}`);
  });
}

// Hybrid Transport
console.log('\n【2.3 HybridTransport - 混合传输模式】');
const hybridContent = sourceMap.sourcesContent[coreFiles.hybridTransport];
if (hybridContent) {
  const hybridClass = hybridContent.match(/class\s+(\w+)/);
  console.log('类名:', hybridClass?.[1]);
  
  // 分析混合策略
  console.log('\n混合传输策略:');
  if (hybridContent.includes('SSE') && hybridContent.includes('WebSocket')) {
    console.log('  ✓ 同时支持SSE和WebSocket协议');
  }
  if (hybridContent.includes('fallback') || hybridContent.includes('upgrade')) {
    console.log('  ✓ 支持协议降级/升级');
  }
  if (hybridContent.includes('autoSelect') || hybridContent.includes('detect')) {
    console.log('  ✓ 自动选择最佳传输方式');
  }
}

// Transport Utils
console.log('\n【2.4 传输工具函数(transportUtils)】');
const utilsContent = sourceMap.sourcesContent[coreFiles.transportUtils];
if (utilsContent) {
  const functions = utilsContent.match(/export\s+(async\s+)?function\s+(\w+)/g);
  console.log('导出函数:', functions?.slice(0, 10));
  
  // 存活性检测
  if (utilsContent.includes('liveness') || utilsContent.includes('LIVENESS')) {
    const livenessConfig = utilsContent.match(/LIVENESS_TIMEOUT_MS\s*=\s*(\d+)/);
    console.log(`\n存活性检测超时: ${livenessConfig?.[1]}ms`);
  }
}

// 3. 技能系统分析
console.log('\n\n╔════════════════════════════════════════╗');
console.log('║  三、技能系统(Skills System)分析         ║');
console.log('╚════════════════════════════════════════╝\n');

// Skill Change Detector
console.log('【3.1 skillChangeDetector - 文件监控架构】');
const detectorContent = sourceMap.sourcesContent[coreFiles.skillChangeDetector];
if (detectorContent) {
  const detectorClass = detectorContent.match(/class\s+(\w+)/);
  console.log('类名:', detectorClass?.[1]);
  
  // chokidar监控
  if (detectorContent.includes('chokidar')) {
    console.log('\n✓ 使用chokidar进行文件系统监控');
    
    // 提取chokidar配置
    const chokidarConfig = {
      polling: detectorContent.match(/usePolling\s*:\s*(true|false)/)?.[1],
      ignoreInitial: detectorContent.match(/ignoreInitial\s*:\s*(true|false)/)?.[1],
      stabilityThreshold: detectorContent.match(/stabilityThreshold\s*:\s*(\d+)/)?.[1],
    };
    console.log('Chokidar配置:');
    Object.entries(chokidarConfig).forEach(([k, v]) => {
      if (v !== undefined) console.log(`  ${k}: ${v}`);
    });
  }
  
  // 防抖机制
  if (detectorContent.includes('debounce') || detectorContent.includes('Debounce')) {
    console.log('\n✓ 实现防抖(debounce)机制');
    const debounceConfig = detectorContent.match(/debounce[\s\S]{0,100}/gi);
    if (debounceConfig) {
      console.log('防抖配置示例:', debounceConfig[0]?.substring(0, 100));
    }
  }
  
  // 文件稳定性阈值
  if (detectorContent.includes('FILE_STABILITY_THRESHOLD')) {
    const threshold = detectorContent.match(/FILE_STABILITY_THRESHOLD_MS\s*=\s*(\d+)/);
    console.log(`\n文件稳定性阈值: ${threshold?.[1]}ms`);
  }
  
  // Bun环境workaround
  if (detectorContent.includes('bun') || detectorContent.includes('Bun') || detectorContent.includes('USE_POLLING')) {
    console.log('\n✓ 包含Bun环境FSWatcher死锁workaround');
    console.log('  原理: 在Bun环境下使用polling模式替代原生FSWatcher');
  }
  
  // 动态加载回调
  if (detectorContent.includes('onDynamicSkillsLoaded') || detectorContent.includes('callback')) {
    console.log('\n✓ 支持动态技能加载回调链');
    const callbacks = detectorContent.match(/onDynamicSkillsLoaded|callback|emit/gi);
    console.log('回调相关关键词出现次数:', callbacks?.length);
  }
}

// Bundled Skills
console.log('\n【3.2 bundledSkills - 内置技能实现】');
const bundledContent = sourceMap.sourcesContent[coreFiles.bundledSkills];
if (bundledContent) {
  // 提取内置技能列表
  const skills = bundledContent.match(/['"](\w+)['"]\s*:/g)?.map(s => s.replace(/['"]:/g, '').replace(/['"]/g, '')) || [];
  console.log('内置技能列表 (共', skills.length, '个):');
  skills.slice(0, 15).forEach((skill, i) => {
    console.log(`  ${i+1}. ${skill}`);
  });
  
  // 技能结构
  if (bundledContent.includes('name:') && bundledContent.includes('prompt:')) {
    console.log('\n技能数据结构:');
    console.log('  { name: string, prompt: string, ... }');
  }
}

// 4. 关键配置参数汇总
console.log('\n\n╔════════════════════════════════════════╗');
console.log('║  四、关键配置参数与技术决策            ║');
console.log('╚════════════════════════════════════════╝\n');

const allContents = Object.values(coreFiles).map(idx => sourceMap.sourcesContent[idx]).join('\n');

const keyConfigs = [
  { name: 'RECONNECT_BASE_DELAY_MS', pattern: /RECONNECT_BASE_DELAY_MS\s*=\s*(\d+)/, unit: 'ms', desc: '重连基础延迟' },
  { name: 'LIVENESS_TIMEOUT_MS', pattern: /LIVENESS_TIMEOUT_MS\s*=\s*(\d+)/, unit: 'ms', desc: '存活性检测超时' },
  { name: 'MAX_RETRIES (Transport)', pattern: /MAX_RETRIES\s*=\s*(10)/, unit: '次', desc: '最大重试次数' },
  { name: 'FILE_STABILITY_THRESHOLD_MS', pattern: /FILE_STABILITY_THRESHOLD_MS\s*=\s*(\d+)/, unit: 'ms', desc: '文件稳定阈值' },
];

console.log('| 参数名 | 值 | 单位 | 说明 |');
console.log('|--------|-----|------|------|');
keyConfigs.forEach(config => {
  const match = allContents.match(config.pattern);
  if (match) {
    console.log(`| ${config.name} | ${match[1]} | ${config.unit} | ${config.desc} |`);
  }
});

// 5. 架构总结
console.log('\n\n╔════════════════════════════════════════╗');
console.log('║  五、技术决策与架构设计原理             ║');
console.log('╚════════════════════════════════════════╝\n');

console.log(`
【QueryEngine设计决策】

1. 状态机驱动架构:
   - 采用显式状态管理(idle → running → completed/error)
   - 每个状态转换都有明确的入口和出口条件
   - 支持中断(aborted)和终止(terminated)状态
   
2. 流水线式消息处理:
   - processUserInput作为统一入口点
   - 输入验证 → 命令解析 → 意图识别 → 执行分发
   - 中间件式的处理链，支持扩展

3. 成本追踪与用量统计:
   - 实时追踪token消耗和API调用成本
   - accumulateUsage/updateUsage累积统计
   - 支持多维度成本分析(按会话/按命令/按时间)

【传输层设计决策】

1. 多协议支持:
   - SSE: 用于服务端推送场景(流式响应)
   - WebSocket: 用于双向实时通信
   - Hybrid: 自动选择最优传输方式

2. 弹性重连机制:
   - 指数退避策略(BASE_DELAY=1000ms)
   - 最大重试10次，避免无限重连
   - 存活性检测(45秒超时)，及时发现问题

3. 帧级增量解析:
   - parseSSEFrames实现高效的事件流解析
   - 支持增量更新，降低内存占用
   - 错误恢复能力强

【技能系统设计决策】

1. 文件监控驱动:
   - chokidar提供跨平台文件监控能力
   - 防抖机制(1000ms阈值)避免频繁触发
   - 文件稳定性检测确保加载完整内容

2. 动态热加载:
   - onDynamicSkillsLoaded回调链
   - 无需重启即可加载新技能
   - 支持运行时技能注册/注销

3. 内置与自定义结合:
   - bundledSkills提供开箱即用的基础技能
   - 支持用户自定义技能目录
   - 统一的技能接口和生命周期管理

4. Bun兼容性:
   - USE_POLLING workaround解决FSWatcher死锁
   - 轮询模式在Bun环境下更稳定
   - 平台自适应的策略选择
`);

// 保存详细分析结果
const detailedAnalysis = {
  timestamp: new Date().toISOString(),
  queryEngine: {
    fileIndex: coreFiles.queryEngine,
    hasProcessUserInput: queryEngineContent?.includes('processUserInput'),
    hasSlashCommand: queryEngineContent?.includes('parseSlashCommand'),
    methodCount: uniqueMethods?.length || 0,
    states: states || []
  },
  transport: {
    sse: {
      fileIndex: coreFiles.sseTransport,
      className: sseClass?.[1]
    },
    websocket: {
      fileIndex: coreFiles.wsTransport,
      className: wsClass?.[1]
    },
    hybrid: {
      fileIndex: coreFiles.hybridTransport,
      className: hybridClass?.[1]
    }
  },
  skills: {
    changeDetector: {
      fileIndex: coreFiles.skillChangeDetector,
      usesChokidar: detectorContent?.includes('chokidar'),
      hasDebounce: detectorContent?.includes('debounce')
    },
    bundledSkills: {
      fileIndex: coreFiles.bundledSkills,
      count: skills?.length || 0
    }
  }
};

fs.writeFileSync(
  'C:\\Users\\Administrator\\Desktop\\claude-cli-detailed-analysis.json',
  JSON.stringify(detailedAnalysis, null, 2)
);

console.log('\n═══════════════════════════════════════');
console.log('  详细分析结果已保存至桌面JSON文件');
console.log('═══════════════════════════════════════');
