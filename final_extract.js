const fs = require('fs');

// 读取Source Map文件
const sourceMapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMapData = JSON.parse(fs.readFileSync(sourceMapPath, 'utf8'));

// 核心源文件列表
const coreFiles = [
  '../src/services/api/client.ts',
  '../src/services/api/errorUtils.ts',
  '../src/services/api/withRetry.ts',
  '../src/hooks/useCanUseTool.tsx',
  '../src/components/permissions/PermissionPrompt.tsx',
  '../src/types/permissions.ts',
  '../src/utils/permissions/PermissionMode.ts',
  '../src/utils/stream.ts'
];

console.log('╔══════════════════════════════════════════════════╗');
console.log('║     Claude CLI API通信层与权限系统深度分析       ║');
console.log('╚══════════════════════════════════════════════════╝\n');

// 提取并分析每个核心文件
coreFiles.forEach((targetFile, index) => {
  const fileIndex = sourceMapData.sources.indexOf(targetFile);
  
  if (fileIndex === -1) {
    console.log(`❌ 未找到文件: ${targetFile}`);
    return;
  }
  
  const sourceCode = sourceMapData.sourcesContent[fileIndex];
  
  console.log(`\n${'='.repeat(70)}`);
  console.log(`【${index + 1}】${targetFile.split('/').pop()}`);
  console.log(`完整路径: ${targetFile}`);
  console.log(`代码量: ${(sourceCode.length / 1024).toFixed(2)} KB`);
  console.log(`${'='.repeat(70)}\n`);
  
  // 输出完整源码（截断过长的部分）
  const maxOutputLength = 8000;
  if (sourceCode.length > maxOutputLength) {
    console.log(sourceCode.substring(0, maxOutputLength));
    console.log('\n... [代码过长，已截断] ...');
    console.log(`\n(共 ${sourceCode.length} 字符，显示前 ${maxOutputLength} 字符)`);
  } else {
    console.log(sourceCode);
  }
  
  console.log('\n');
});

// 生成总结
console.log('\n' + '═'.repeat(70));
console.log('                    📊 分析总结');
console.log('═'.repeat(70) + '\n');

let totalSize = 0;
let foundCount = 0;

coreFiles.forEach(file => {
  const idx = sourceMapData.sources.indexOf(file);
  if (idx !== -1 && sourceMapData.sourcesContent[idx]) {
    foundCount++;
    totalSize += sourceMapData.sourcesContent[idx].length;
  }
});

console.log(`✅ 成功提取 ${foundCount}/${coreFiles.length} 个核心源文件`);
console.log(`📦 总代码量: ${(totalSize / 1024).toFixed(2)} KB`);
console.log(`📁 Source Map版本: ${sourceMapData.version}`);
console.log(`🔍 总源文件数: ${sourceMapData.sources.length}`);