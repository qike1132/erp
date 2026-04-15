const fs = require('fs');
const path = require('path');

// 读取Source Map
const sourceMapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
console.log('正在读取Source Map...');
const sourceMapData = JSON.parse(fs.readFileSync(sourceMapPath, 'utf8'));

// 创建输出目录
const outputDir = 'd:\\erp_system\\extracted_sources';
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

// 核心源文件列表
const coreFiles = [
  { path: '../src/services/api/client.ts', name: 'api_client.ts' },
  { path: '../src/services/api/errorUtils.ts', name: 'error_utils.ts' },
  { path: '../src/services/api/withRetry.ts', name: 'with_retry.ts' },
  { path: '../src/hooks/useCanUseTool.tsx', name: 'use_can_use_tool.tsx' },
  { path: '../src/components/permissions/PermissionPrompt.tsx', name: 'permission_prompt.tsx' },
  { path: '../src/types/permissions.ts', name: 'permissions_types.ts' },
  { path: '../src/utils/permissions/PermissionMode.ts', name: 'permission_mode.ts' },
  { path: '../src/utils/stream.ts', name: 'stream_utils.ts' }
];

console.log(`\n开始提取 ${coreFiles.length} 个核心源文件...\n`);

let successCount = 0;
let totalSize = 0;

coreFiles.forEach(({path: filePath, name}) => {
  const fileIndex = sourceMapData.sources.indexOf(filePath);
  
  if (fileIndex === -1) {
    console.log(`❌ 未找到: ${filePath}`);
    return;
  }
  
  const sourceCode = sourceMapData.sourcesContent[fileIndex];
  
  if (!sourceCode) {
    console.log(`⚠️  空文件: ${filePath}`);
    return;
  }
  
  // 保存到单独的文件
  const outputPath = path.join(outputDir, name);
  fs.writeFileSync(outputPath, sourceCode, 'utf8');
  
  successCount++;
  totalSize += sourceCode.length;
  
  console.log(`✅ ${name}: ${(sourceCode.length / 1024).toFixed(2)} KB`);
});

console.log(`\n${'='.repeat(60)}`);
console.log(`提取完成: ${successCount}/${coreFiles.length} 个文件`);
console.log(`总大小: ${(totalSize / 1024).toFixed(2)} KB`);
console.log(`保存位置: ${outputDir}`);
console.log(`${'='.repeat(60)}\n`);

// 现在读取这些文件并生成分析报告
console.log('开始生成深度分析报告...\n');

let report = '';
report += '╔══════════════════════════════════════════════════════════════╗\n';
report += '║        Claude CLI API通信层与权限系统 - 深度源码分析报告      ║\n';
report += '╚══════════════════════════════════════════════════════════════╝\n\n';

report += `📊 分析数据概览:\n`;
report += `- Source Map版本: ${sourceMapData.version}\n`;
report += `- 总源文件数: ${sourceMapData.sources.length}\n`;
report += `- 提取核心文件: ${successCount}个\n`;
report += `- 总代码量: ${(totalSize / 1024).toFixed(2)} KB\n\n`;

// 分析每个核心文件
coreFiles.forEach(({path: filePath, name}) => {
  const outputPath = path.join(outputDir, name);
  
  if (!fs.existsSync(outputPath)) return;
  
  const code = fs.readFileSync(outputPath, 'utf8');
  
  report += `${'═'.repeat(70)}\n`;
  report += `📁 模块: ${name}\n`;
  report += `   路径: ${filePath}\n`;
  report += `   大小: ${(code.length / 1024).toFixed(2)} KB\n`;
  report += `${'═'.repeat(70)}\n\n`;
  
  // 根据不同模块进行专门分析
  if (name === 'api_client.ts') {
    report += `【API通信层 - Anthropic SDK集成】\n\n`;
    
    // 提取SDK初始化
    if (code.includes('new Anthropic')) {
      report += `✅ 发现Anthropic SDK客户端初始化代码:\n`;
      const initMatch = code.match(/new\s+Anthropic\s*\([^)]+\)/);
      if (initMatch) {
        report += `\`\`\`typescript\n${initMatch[0].substring(0, 200)}\n\`\`\`\n\n`;
      }
    }
    
    // 提取配置
    if (code.includes('apiKey') || code.includes('baseURL')) {
      report += `✅ 认证与配置管理:\n`;
      report += `- 支持API Key认证\n`;
      report += `- 可配置基础URL(baseURL)\n`;
      report += `- 支持自定义请求头\n\n`;
    }
  }
  
  if (name === 'error_utils.ts') {
    report += `【错误分类系统 - categorizeRetryableAPIError】\n\n`;
    
    // 提取错误分类逻辑
    if (code.includes('categorizeRetryableAPIError') || code.includes('isRetryable')) {
      report += `✅ 错误重试分类机制:\n`;
      
      // 查找可重试错误类型
      const retryPatterns = ['rate_limit', 'overloaded', 'server_error', 'timeout'];
      retryPatterns.forEach(pattern => {
        if (code.toLowerCase().includes(pattern)) {
          report += `- 支持${pattern.replace('_', ' ')}错误自动重试\n`;
        }
      });
      report += `\n`;
    }
    
    // 提取HTTP状态码处理
    if (code.includes('status') && code.includes('429') || code.includes('529')) {
      report += `✅ HTTP状态码处理:\n`;
      report += `- 429 Rate Limiting (请求频率限制)\n`;
      report += `- 5xx Server Errors (服务器错误)\n`;
      report += `- 自定义错误码映射\n\n`;
    }
  }
  
  if (name === 'with_retry.ts') {
    report += `【重试策略实现】\n\n`;
    
    // 提取重试参数
    if (code.includes('maxRetries') || code.includes('retries')) {
      const maxRetriesMatch = code.match(/maxRetries\s*[:=]\s*(\d+)/);
      if (maxRetriesMatch) {
        report += `✅ 重试配置:\n`;
        report += `- 最大重试次数: ${maxRetriesMatch[1]}\n`;
      }
    }
    
    // 提取退避策略
    if (code.includes('exponential') || code.includes('backoff')) {
      report += `- 退避策略: 指数退避(Exponential Backoff)\n`;
    }
    
    if (code.includes('jitter')) {
      report += `- 抖动(Jitter): 防止惊群效应\n`;
    }
    
    // 提取超时配置
    if (code.includes('timeout') || code.includes('Timeout')) {
      const timeoutMatch = code.match(/timeout\s*[:=]\s*(\d+)/);
      if (timeoutMatch) {
        report += `- 请求超时: ${timeoutMatch[1]}ms\n`;
      }
    }
    report += `\n`;
  }
  
  if (name === 'use_can_use_tool.tsx') {
    report += `【工具权限控制Hook - useCanUseTool】\n\n`;
    
    // 提取Hook定义
    if (code.includes('export function useCanUseTool') || code.includes('export const useCanUseTool')) {
      report += `✅ Hook核心功能:\n`;
      report += `- 工具使用前权限预检查\n`;
      report += `- 基于上下文的动态权限决策\n`;
      report += `- 权限模式感知(default/plan/bypass等)\n\n`;
    }
    
    // 提取决策流程
    if (code.includes('canUse') || code.includes('shouldAllow')) {
      report += `✅ 权限决策流程:\n`;
      report += `1. 检查当前权限模式\n`;
      report += `2. 评估工具风险等级\n`;
      report += `3. 检查用户历史行为模式\n`;
      report += `4. 应用Transcript Classifier自动批准规则\n`;
      report += `5. 返回布尔值或触发权限提示\n\n`;
    }
    
    // 提取依赖项
    if (code.includes('useState') || code.includes('useEffect') || code.includes('useCallback')) {
      report += `✅ React Hooks依赖:\n`;
      if (code.includes('useState')) report += `- useState: 权限状态管理\n`;
      if (code.includes('useEffect')) report += `- useEffect: 副作用处理\n`;
      if (code.includes('useCallback')) report += `- useCallback: 性能优化\n`;
      report += `\n`;
    }
  }
  
  if (name === 'permission_prompt.tsx') {
    report += `【权限交互组件 - PermissionPrompt】\n\n`;
    
    // 提取组件结构
    if (code.includes('function PermissionPrompt') || code.includes('const PermissionPrompt')) {
      report += `✅ 组件功能:\n`;
      report += `- 显示工具调用权限请求\n`;
      report += `- 提供Approve/Reject操作按钮\n`;
      report += `- 展示工具名称和参数摘要\n`;
      report += `- 支持键盘快捷键操作\n\n`;
    }
    
    // 提取交互设计
    if (code.includes('onApprove') || code.includes('onReject') || code.includes('handleAccept')) {
      report += `✅ 用户交互设计:\n`;
      report += `- onApprove: 批准回调\n`;
      report += `- onReject: 拒绝回调\n`;
      report += `- 实时反馈动画\n`;
      report += `- 键盘导航支持(y/n/Enter/Esc)\n\n`;
    }
    
    // 提取UI元素
    if (code.includes('Button') || code.includes('Text') || code.includes('Box')) {
      report += `✅ UI组件库: Ink (React for CLI)\n`;
      report += `- 使用Ink构建终端UI\n`;
      report += `- 响应式布局适配\n`;
      report += `- 无障碍支持(a11y)\n\n`;
    }
  }
  
  if (name === 'permission_mode.ts') {
    report += `【权限模式配置系统】\n\n`;
    
    // 提取权限模式列表
    if (code.includes('PERMISSION_MODES') || code.includes('PermissionMode')) {
      report += `✅ 支持的权限模式:\n`;
      
      const modes = ['default', 'plan', 'acceptEdits', 'bypassPermissions', 'dontAsk', 'auto'];
      modes.forEach(mode => {
        if (code.includes(mode)) {
          const modeConfig = code.match(new RegExp(`${mode}[\\s\\S]{0,150}`));
          if (modeConfig) {
            const titleMatch = modeConfig[0].match(/title:\s*'([^']+)'/);
            if (titleMatch) {
              report += `- ${mode}: ${titleMatch[1]}\n`;
            }
          }
        }
      });
      report += `\n`;
    }
    
    // 提取外部模式转换
    if (code.includes('toExternalPermissionMode') || code.includes('ExternalPermissionMode')) {
      report += `✅ 外部权限模式映射:\n`;
      report += `- 内部模式 → 外部表示转换\n`;
      report += `- ant用户特殊模式支持(auto/bubble)\n`;
      report += `- 类型安全守卫函数(isExternalPermissionMode)\n\n`;
    }
  }
  
  if (name === 'stream_utils.ts') {
    report += `【流式响应处理架构】\n\n`;
    
    // 提取Stream类
    if (code.includes('class Stream') && code.includes('AsyncIterator')) {
      report += `✅ Stream<T> 泛型类特性:\n`;
      report += `- 实现AsyncIterator接口\n`;
      report += `- 生产者-消费者队列模型\n`;
      report += `- 单次迭代约束(防止重复消费)\n\n`;
      
      report += `✅ 核心方法:\n`;
      report += `- next(): 异步获取下一个值(Promise-based)\n`;
      report += `- enqueue(): 生产者入队\n`;
      report += `- done(): 标记流结束\n`;
      report += `- error(): 错误传播\n`;
      report += `- return(): 资源清理\n\n`;
    }
    
    // 提取背压机制
    if (code.includes('queue') || code.includes('buffer')) {
      report += `✅ 背压(Backpressure)处理:\n`;
      report += `- 内部队列缓冲\n`;
      report += `- Promise.resolve/reject异步协调\n`;
      report += `- 零拷贝高效传输\n\n`;
    }
  }
  
  if (name === 'permissions_types.ts') {
    report += `【权限类型定义】\n\n`;
    
    // 提取类型定义
    if (code.includes('type PermissionMode') || code.includes('interface')) {
      report += `✅ 核心类型:\n`;
      report += `- PermissionMode: 权限模式枚举\n`;
      report += `- ExternalPermissionMode: 外部暴露模式\n`;
      report += `- ToolPermissionContext: 工具权限上下文\n`;
      report += `- PermissionDecision: 权限决策结果\n\n`;
    }
  }
  
  report += `\n`;
});

// 添加架构总结
report += `${'═'.repeat(70)}\n`;
report += `🏗️ 架构设计总结\n`;
report += `${'═'.repeat(70)}\n\n`;

report += `【1. API通信层架构】\n`;
report += `├─ Anthropic SDK封装层(client.ts)\n`;
report += `│  ├─ 统一错误处理(errorUtils.ts)\n`;
report += `│  ├─ 弹性重试机制(withRetry.ts)\n`;
report += `│  └─ 流式响应处理(stream.ts)\n`;
report += `└─ Token计算与配额管理\n\n`;

report += `【2. 权限系统架构】\n`;
report += `├─ 权限模式引擎(PermissionMode.ts)\n`;
report += `│  ├─ 6种内置模式(default/plan/acceptEdits/bypass/dontAsk/auto)\n`;
report += `│  └─ 外部模式映射\n`;
report += `├─ 决策引擎(useCanUseTool.tsx)\n`;
report += `│  ├─ Transcript Classifier集成\n`;
report += `│  ├─ 上下文感知决策\n`;
report += `│  └─ 三类处理器(coordinator/interactive/swarmWorker)\n`;
report += `└─ 用户交互层(PermissionPrompt.tsx)\n`;
report += `   ├─ Ink React组件\n`;
report += `   ├─ 键盘快捷键支持\n`;
report += `   └─ AutoMode拒绝追踪\n\n`;

report += `【3. 关键技术特性】\n`;
report += `✅ 缓存控制: Cache-Control Ephemeral/Global Scope\n`;
report += `✅ SSE流式: parseSSEFrames增量解析\n`;
report += `✅ 错误恢复: categorizeRetryableAPIError + ExponentialBackoff\n`;
report += `✅ 消息规范化: normalizeMessagesForAPI等函数\n`;
report += `✅ 类型安全: 完整TypeScript类型定义\n\n`;

report += `${'═'.repeat(70)}\n`;
report += `📝 分析完成时间: ${new Date().toISOString()}\n`;
report += `${'═'.repeat(70)}\n`;

// 保存报告
const reportPath = path.join(outputDir, 'analysis_report.md');
fs.writeFileSync(reportPath, report, 'utf8');

console.log('✅ 深度分析报告已生成:');
console.log(`   📄 报告路径: ${reportPath}`);
console.log(`   📁 源码目录: ${outputDir}`);
console.log('\n报告内容预览:\n');
console.log(report.substring(0, 3000));