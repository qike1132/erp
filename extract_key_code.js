const fs = require('fs');

// 读取分析结果
const analysisData = JSON.parse(fs.readFileSync('d:\\erp_system\\claude_cli_analysis.json', 'utf8'));

console.log('=== Claude CLI 深度源码分析报告 ===\n');

// 1. API通信层分析
console.log('【1. API通信层分析】\n');
const apiFiles = analysisData.extractedCode['API通信层'] || [];
apiFiles.slice(0, 10).forEach((file, idx) => {
  console.log(`--- 文件 ${idx + 1}: ${file.file} (${(file.length/1024).toFixed(2)} KB) ---`);
  
  // 提取关键代码片段
  const code = file.code;
  
  // 查找Anthropic SDK初始化相关代码
  if (code.includes('Anthropic') || code.includes('createClient')) {
    console.log('✓ 发现Anthropic SDK集成代码');
    
    // 提取初始化代码片段
    const initMatch = code.match(/new\s+Anthropic\s*\([^)]{0,200}\)/);
    if (initMatch) {
      console.log('SDK初始化示例:', initMatch[0].substring(0, 150));
    }
  }
  
  // 查找流式处理代码
  if (code.includes('stream') && code.includes('SSE')) {
    console.log('✓ 发现SSE流式处理代码');
  }
  
  // 查找Token计算代码
  if (code.includes('token') || code.includes('countTokens')) {
    console.log('✓ 发现Token计算逻辑');
  }
  
  console.log('');
});

// 2. 权限系统分析
console.log('\n【2. 权限系统分析】\n');
const permFiles = analysisData.extractedCode['权限系统'] || [];
permFiles.slice(0, 15).forEach((file, idx) => {
  if (file.file.includes('useCanUseTool') || file.file.includes('PermissionPrompt')) {
    console.log(`=== 核心文件: ${file.file} ===`);
    console.log(`文件大小: ${(file.length/1024).toFixed(2)} KB`);
    console.log('\n--- 关键代码片段 ---');
    
    const code = file.code;
    
    // 提取useCanUseTool Hook的核心逻辑
    if (code.includes('useCanUseTool')) {
      console.log('📌 useCanUseTool Hook 核心逻辑:');
      
      // 提取函数定义
      const funcMatch = code.match(/export\s+(?:function|const|async\s+function)\s+useCanUseTool[^{]*\{[\s\S]{0,500}/);
      if (funcMatch) {
        console.log(funcMatch[0].substring(0, 400));
      }
      
      // 提取权限检查逻辑
      if (code.includes('canUse') || code.includes('permission')) {
        console.log('\n📋 权限决策逻辑:');
        const permMatch = code.match(/(?:if|switch|case)[^;]{0,300}(?:canUse|permission|allow)/);
        if (permMatch) {
          console.log(permMatch[0].substring(0, 250));
        }
      }
    }
    
    // 提取PermissionPrompt组件
    if (code.includes('PermissionPrompt')) {
      console.log('\n🎨 PermissionPrompt 组件结构:');
      
      // 提取组件定义
      const compMatch = code.match(/export\s+(?:default\s+)?function\s+PermissionPrompt[^{]*\{[\s\S]{0,400}/);
      if (compMatch) {
        console.log(compMatch[0].substring(0, 350));
      }
      
      // 提取交互逻辑
      if (code.includes('onApprove') || code.includes('onReject') || code.includes('handle')) {
        console.log('\n🖱️ 用户交互处理:');
        const interactMatch = code.match(/(?:onApprove|onReject|handle)\w*\s*=\s*[^;]{0,200}/);
        if (interactMatch) {
          console.log(interactMatch[0].substring(0, 180));
        }
      }
    }
    
    console.log('\n' + '='.repeat(60) + '\n');
  }
});

// 3. 流式处理分析
console.log('【3. 流式SSE响应处理】\n');
const streamFiles = analysisData.extractedCode['流式处理'] || [];
streamFiles.slice(0, 5).forEach((file, idx) => {
  console.log(`--- 流式处理文件: ${file.file} ---`);
  const code = file.code;
  
  if (code.includes('EventSource') || code.includes('fetch') && code.includes('ReadableStream')) {
    console.log('✓ 发现SSE/流式HTTP实现');
    
    // 提取流式处理核心代码
    const streamMatch = code.match(/(?:async\s+)?function\s+\w*stream\w*\s*\([^)]*\)\s*\{[\s\S]{0,400}/i);
    if (streamMatch) {
      console.log('流式处理函数:', streamMatch[0].substring(0, 300));
    }
  }
  
  if (code.includes('categorizeRetryableAPIError') || code.includes('retry')) {
    console.log('✓ 发现错误重试机制');
    
    // 提取错误分类代码
    const retryMatch = code.match(/categorizeRetryableAPIError[^;]{0,300}/);
    if (retryMatch) {
      console.log('错误分类函数:', retryMatch[0].substring(0, 250));
    }
  }
  
  console.log('');
});

// 4. 缓存控制分析
console.log('【4. 缓存控制机制】\n');
const cacheFiles = analysisData.extractedCode['缓存控制'] || [];
cacheFiles.slice(0, 5).forEach((file, idx) => {
  if (!file.file.includes('lodash')) { // 排除lodash库
    console.log(`--- 缓存文件: ${file.file} ---`);
    const code = file.code;
    
    if (code.includes('Cache-Control') || code.includes('ephemeral') || code.includes('global')) {
      console.log('✓ 发现缓存控制头处理');
      
      // 提取缓存控制代码
      const cacheMatch = code.match(/Cache-Control[^;]{0,200}/);
      if (cacheMatch) {
        console.log('缓存控制配置:', cacheMatch[0].substring(0, 180));
      }
    }
    
    console.log('');
  }
});

// 5. 错误处理分析
console.log('【5. 错误分类与重试策略】\n');
const errorFiles = analysisData.extractedCode['错误处理'] || [];
errorFiles.slice(0, 5).forEach((file, idx) => {
  if (!file.file.includes('node_modules')) {
    console.log(`--- 错误处理文件: ${file.file} ---`);
    const code = file.code;
    
    if (code.includes('categorizeError') || code.includes('classifyError') || code.includes('isRetryable')) {
      console.log('✓ 发现错误分类逻辑');
      
      // 提取错误分类代码
      const errorMatch = code.match(/(?:function|const)\s*(?:categorize|classify|isRetryable)\w*\s*\([^)]*\)\s*\{[\s\S]{0,300}/);
      if (errorMatch) {
        console.log('错误分类实现:', errorMatch[0].substring(0, 280));
      }
    }
    
    console.log('');
  }
});

console.log('\n=== 分析完成 ===');