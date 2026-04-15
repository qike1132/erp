const fs = require('fs');
const path = require('path');

const sourceMapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(sourceMapPath, 'utf-8'));

console.log('=== Source Map 基本信息 ===');
console.log('版本:', sourceMap.version);
console.log('源文件数量:', sourceMap.sources.length);
console.log('SourcesContent数量:', sourceMap.sourcesContent.length);

// 查找关键源文件
const targetFiles = {
  queryEngine: [],
  transport: [],
  skill: []
};

sourceMap.sources.forEach((source, idx) => {
  const lowerSource = source.toLowerCase();
  if (lowerSource.includes('query') || lowerSource.includes('engine')) {
    targetFiles.queryEngine.push({index: idx, path: source});
  }
  if (lowerSource.includes('transport') || lowerSource.includes('sse') || lowerSource.includes('websocket') || lowerSource.includes('hybrid')) {
    targetFiles.transport.push({index: idx, path: source});
  }
  if (lowerSource.includes('skill') || lowerSource.includes('chokidar') || lowerSource.includes('watcher')) {
    targetFiles.skill.push({index: idx, path: source});
  }
});

console.log('\n=== 关键文件定位 ===');
console.log('\nQueryEngine相关文件:');
targetFiles.queryEngine.forEach(f => console.log(`  [${f.index}] ${f.path}`));

console.log('\nTransport层相关文件:');
targetFiles.transport.forEach(f => console.log(`  [${f.index}] ${f.path}`));

console.log('\n技能系统相关文件:');
targetFiles.skill.forEach(f => console.log(`  [${f.index}] ${f.path}`));

// 分析关键常量和配置
console.log('\n\n=== 关键配置参数提取 ===');

const allContent = sourceMap.sourcesContent.join('\n');

// 提取关键配置
const configs = {
  // Transport层配置
  RECONNECT_BASE_DELAY_MS: allContent.match(/RECONNECT_BASE_DELAY_MS\s*=\s*(\d+)/)?.[1],
  LIVENESS_TIMEOUT_MS: allContent.match(/LIVENESS_TIMEOUT_MS\s*=\s*(\d+)/)?.[1],
  MAX_RETRIES: allContent.match(/MAX_RETRIES\s*=\s*(\d+)|maxRetries\s*=\s*(\d+)/gi),
  
  // 技能系统配置
  FILE_STABILITY_THRESHOLD_MS: allContent.match(/FILE_STABILITY_THRESHOLD_MS\s*=\s*(\d+)/)?.[1],
  USE_POLLING: allContent.match(/USE_POLLING\s*=\s*(true|false)/)?.[1],
  
  // QueryEngine状态
  states: [...new Set(allContent.match(/state\s*===?\s*['"](\w+)['"]/g) || [])],
};

Object.entries(configs).forEach(([key, value]) => {
  console.log(`\n${key}:`, value);
});

// 输出QueryEngine核心文件内容
console.log('\n\n=== QueryEngine 核心分析 ===');
targetFiles.queryEngine.slice(0, 3).forEach(file => {
  console.log(`\n--- ${file.path} ---`);
  const content = sourceMap.sourcesContent[file.index];
  if (content) {
    // 提取类定义和主要方法
    const classMatch = content.match(/class \w+/g);
    const methods = content.match(/^\s*(async\s+)?(\w+)\s*\(/gm);
    console.log('类/函数:', classMatch?.slice(0, 5));
    console.log('方法:', methods?.slice(0, 10));
    
    // 查找关键模式
    if (content.includes('processUserInput')) {
      console.log('\n✓ 包含 processUserInput 方法');
      const processMatch = content.match(/processUserInput[\s\S]{0,500}/);
      if (processMatch) console.log(processMatch[0].substring(0, 300));
    }
    if (content.includes('parseSlashCommand')) {
      console.log('\n✓ 包含 parseSlashCommand 方法');
    }
    if (content.includes('cost-tracker') || content.includes('costTracker') || content.includes('CostTracker')) {
      console.log('\n✓ 包含成本追踪功能');
    }
    if (content.includes('accumulateUsage') || content.includes('updateUsage')) {
      console.log('\n✓ 包含使用量统计');
    }
  }
});

// 输出Transport层核心文件内容
console.log('\n\n=== Transport 层核心分析 ===');
targetFiles.transport.slice(0, 5).forEach(file => {
  console.log(`\n--- ${file.path} ---`);
  const content = sourceMap.sourcesContent[file.index];
  if (content) {
    const classMatch = content.match(/class \w+/g);
    const methods = content.match(/^\s*(async\s+)?(\w+)\s*\(/gm);
    console.log('类:', classMatch?.slice(0, 3));
    console.log('方法:', methods?.slice(0, 8));
    
    if (content.includes('parseSSEFrames') || content.includes('parseSSE')) {
      console.log('✓ SSE帧解析');
    }
    if (content.includes('reconnect') || content.includes('Reconnect')) {
      console.log('✓ 重连机制');
    }
    if (content.includes('WebSocket')) {
      console.log('✓ WebSocket支持');
    }
    if (content.includes('HybridTransport')) {
      console.log('✓ Hybrid传输');
    }
    if (content.includes('liveness') || content.includes('Liveness')) {
      console.log('✓ 存活性检测');
    }
  }
});

// 输出技能系统核心文件内容
console.log('\n\n=== 技能系统核心分析 ===');
targetFiles.skill.slice(0, 5).forEach(file => {
  console.log(`\n--- ${file.path} ---`);
  const content = sourceMap.sourcesContent[file.index];
  if (content) {
    const classMatch = content.match(/class \w+/g);
    const methods = content.match(/^\s*(async\s+)?(\w+)\s*\(/gm);
    console.log('类:', classMatch?.slice(0, 3));
    console.log('方法:', methods?.slice(0, 8));
    
    if (content.includes('chokidar') || content.includes('Chokidar')) {
      console.log('✓ 使用chokidar文件监控');
    }
    if (content.includes('debounce') || content.includes('Debounce')) {
      console.log('✓ 防抖机制');
    }
    if (content.includes('onDynamicSkillsLoaded') || content.includes('dynamicSkills')) {
      console.log('✓ 动态技能加载');
    }
    if (content.includes('bundled') || content.includes('BundledSkills')) {
      console.log('✓ 内置技能支持');
    }
    if (content.includes('polling') || content.includes('USE_POLLING')) {
      console.log('✓ 轮询模式');
    }
  }
});

// 保存完整分析结果到文件
const analysisResult = {
  metadata: {
    version: sourceMap.version,
    totalSources: sourceMap.sources.length,
    analyzedAt: new Date().toISOString()
  },
  targetFiles,
  summary: {
    queryEngineFiles: targetFiles.queryEngine.length,
    transportFiles: targetFiles.transport.length,
    skillFiles: targetFiles.skill.length
  }
};

fs.writeFileSync('C:\\Users\\Administrator\\Desktop\\claude-cli-analysis.json', JSON.stringify(analysisResult, null, 2));
console.log('\n\n分析结果已保存至: C:\\Users\\Administrator\\Desktop\\claude-cli-analysis.json');
