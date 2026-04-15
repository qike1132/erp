const fs = require('fs');
const path = require('path');

// 读取Source Map文件
const sourceMapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
console.log('正在读取Source Map文件...');
const sourceMapData = JSON.parse(fs.readFileSync(sourceMapPath, 'utf8'));

console.log(`\n=== Source Map 文件统计 ===`);
console.log(`版本: ${sourceMapData.version}`);
console.log(`总源文件数: ${sourceMapData.sources.length}`);
console.log(`源代码内容数: ${sourceMapData.sourcesContent.length}`);

// 搜索关键模块
const searchPatterns = [
  { pattern: 'claude', name: 'Claude核心模块' },
  { pattern: 'api', name: 'API通信层' },
  { pattern: 'permission', name: '权限系统' },
  { pattern: 'useCanUseTool', name: '工具权限Hook' },
  { pattern: 'PermissionPrompt', name: '权限提示组件' },
  { pattern: 'transcript', name: '转录分类器' },
  { pattern: 'token', name: 'Token管理' },
  { pattern: 'stream', name: '流式处理' },
  { pattern: 'cache', name: '缓存控制' },
  { pattern: 'error', name: '错误处理' },
  { pattern: 'retry', name: '重试机制' },
  { pattern: 'anthropic', name: 'Anthropic SDK' },
  { pattern: 'normalize', name: '消息规范化' },
  { pattern: 'categorize', name: '错误分类' }
];

console.log('\n=== 关键模块搜索结果 ===');
const foundModules = {};

searchPatterns.forEach(({pattern, name}) => {
  const matches = sourceMapData.sources.filter(source =>
    source.toLowerCase().includes(pattern.toLowerCase())
  );
  
  if (matches.length > 0) {
    foundModules[name] = matches;
    console.log(`\n【${name}】(${pattern}): 找到 ${matches.length} 个文件`);
    matches.slice(0, 5).forEach((file, idx) => {
      console.log(`  ${idx + 1}. ${file}`);
    });
    if (matches.length > 5) {
      console.log(`  ... 还有 ${matches.length - 5} 个文件`);
    }
  }
});

// 提取关键源码内容
console.log('\n=== 提取关键源码内容 ===');
const extractedCode = {};

Object.entries(foundModules).forEach(([moduleName, files]) => {
  files.forEach(file => {
    const fileIndex = sourceMapData.sources.indexOf(file);
    if (fileIndex !== -1 && sourceMapData.sourcesContent[fileIndex]) {
      const code = sourceMapData.sourcesContent[fileIndex];
      if (!extractedCode[moduleName]) {
        extractedCode[moduleName] = [];
      }
      
      // 只保存重要的源码（排除node_modules中的库文件）
      if (!file.includes('node_modules') && code.length > 100) {
        extractedCode[moduleName].push({
          file: file,
          code: code,
          length: code.length
        });
      }
    }
  });
});

// 保存详细分析结果
const analysisResult = {
  metadata: {
    version: sourceMapData.version,
    totalSources: sourceMapData.sources.length,
    analyzedAt: new Date().toISOString()
  },
  modules: foundModules,
  extractedCode: extractedCode
};

fs.writeFileSync('d:\\erp_system\\claude_cli_analysis.json', JSON.stringify(analysisResult, null, 2));
console.log('\n✅ 详细分析结果已保存到 claude_cli_analysis.json');

// 输出统计摘要
console.log('\n=== 分析摘要 ===');
let totalExtractedFiles = 0;
let totalCodeLength = 0;

Object.entries(extractedCode).forEach(([moduleName, files]) => {
  console.log(`${moduleName}: ${files.length} 个核心文件`);
  files.forEach(f => {
    totalExtractedFiles++;
    totalCodeLength += f.length;
  });
});

console.log(`\n总计提取 ${totalExtractedFiles} 个核心源文件`);
console.log(`总代码量: ${(totalCodeLength / 1024).toFixed(2)} KB`);