const fs = require('fs');

console.log('⚛️  分析 React Compiler 优化模式 & createSignal & Profiler\n');
console.log('='.repeat(80) + '\n');

const mapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(mapPath, 'utf8'));

// ============================================
// 第1部分: React Compiler 优化模式
// ============================================
console.log('📦 第1部分: React Compiler 优化模式 (_c函数)');
console.log('='.repeat(80) + '\n');

const reactCompilerFiles = [];
sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (!content) return;
    
    if (src.includes('_c') || (content.includes('function _c(') || content.includes('_c = '))) {
        reactCompilerFiles.push({ name: src, content, index: i });
    }
});

console.log(`找到 ${reactCompilerFiles.length} 个 React Compiler 相关文件:\n`);

reactCompilerFiles.slice(0, 10).forEach(file => {
    console.log(`📄 ${file.name}`);
    console.log(`   大小: ${file.content.length} 字符`);
    
    // 提取 _c 函数定义
    if (file.content.includes('function _c(') || file.content.includes('_c =')) {
        const match = file.content.match(/(?:function\s+_c|_c\s*=)\s*\([^)]*\)\s*[\s\S]{0,1500}/);
        if (match) {
            console.log('\n   核心代码片段:');
            console.log('   ' + '-'.repeat(60));
            // 显示前800字符
            console.log('   ' + match[0].substring(0, 800));
            console.log('   ' + '-'.repeat(60));
        }
    }
    console.log('');
});

// 搜索 $[ 缓存数组模式
console.log('\n💾 搜索缓存数组模式 ($[0], $[1]...):');
const cachePatternFiles = [];
sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (content && content.includes('$[')) {
        cachePatternFiles.push({ name: src, content, index: i });
    }
});

console.log(`   找到 ${cachePatternFiles.length} 个包含缓存数组模式的文件`);
if (cachePatternFiles.length > 0) {
    console.log('\n   示例文件:');
    cachePatternFiles.slice(0, 3).forEach(file => {
        console.log(`\n   📄 ${file.name}`);
        // 提取包含 $[ 的上下文
        const idx = file.content.indexOf('$[');
        const start = Math.max(0, idx - 100);
        const end = Math.min(file.content.length, idx + 300);
        console.log('   ' + file.content.substring(start, end));
    });
}

// ============================================
// 第2部分: createSignal 事件通知模式
// ============================================
console.log('\n\n' + '='.repeat(80));
console.log('📡 第2部分: createSignal 事件通知模式');
console.log('='.repeat(80) + '\n');

const signalFiles = [];
sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (!content) return;
    
    if (src.toLowerCase().includes('signal') || content.includes('createSignal')) {
        signalFiles.push({ name: src, content, index: i });
    }
});

console.log(`找到 ${signalFiles.length} 个 Signal 相关文件:\n`);

signalFiles.forEach(file => {
    console.log(`📄 ${file.name} (${file.content.length} 字符)`);
    
    // 提取 createSignal 或 signal 相关的核心实现
    if (file.content.includes('createSignal')) {
        const match = file.content.match(/createSignal[\s\S]{0,2000}/);
        if (match) {
            console.log('\n   实现代码:');
            console.log('   ' + '-'.repeat(60));
            console.log('   ' + match[0].substring(0, 1200));
            console.log('   ' + '-'.repeat(60));
        }
    } else if (file.content.includes('function Signal') || file.content.includes('class Signal')) {
        const match = file.content.match(/(?:function|class)\s+Signal[\s\S]{0,1500}/);
        if (match) {
            console.log('\n   类/函数定义:');
            console.log('   ' + match[0].substring(0, 1000));
        }
    }
    console.log('');
});

// 搜索发布订阅相关模式
console.log('\n🔔 搜索发布订阅机制 (subscribe/publish/emit/on/off):');
const pubSubPatterns = ['subscribe', 'publish', 'emit', '.on(', '.off(', 'addEventListener', 'listeners'];
const pubSubFiles = [];

pubSubPatterns.forEach(pattern => {
    sourceMap.sources.forEach((src, i) => {
        const content = sourceMap.sourcesContent[i];
        if (content && content.includes(pattern) && !pubSubFiles.find(f => f.index === i)) {
            // 只取与signal相关的
            if (src.toLowerCase().includes('signal') || src.toLowerCase().includes('event')) {
                pubSubFiles.push({ name: src, pattern, index: i });
            }
        }
    });
});

console.log(`   找到 ${pubSubFiles.length} 个发布订阅相关实现`);
pubSubFiles.slice(0, 5).forEach(file => {
    console.log(`   - ${file.name} (匹配: ${file.pattern})`);
});

// ============================================
// 第3部分: TypeScript 高级类型模式
// ============================================
console.log('\n\n' + '='.repeat(80));
console.log('📘 第3部分: TypeScript 高级类型模式');
console.log('='.repeat(80) + '\n');

const tsPatterns = [
    { pattern: 'discriminated union', keywords: ['type ', ' | ', ': '] },
    { pattern: 'Pick<Omit<', keywords: ['Pick<', 'Omit<'] },
    { pattern: 'Exclude<', keywords: ['Exclude<'] },
    { pattern: 'template literal', keywords: ['`', '${'] },
    { pattern: 'infer', keywords: ['infer '] },
    { pattern: 'extends condition', keywords: ['extends ', '?', ':'] }
];

const tsTypeFiles = new Map();
sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (!content || !src.endsWith('.ts') && !src.endsWith('.tsx')) return;
    
    tsPatterns.forEach(tp => {
        if (tp.keywords.every(kw => content.includes(kw))) {
            if (!tsTypeFiles.has(i)) {
                tsTypeFiles.set(i, { 
                    name: src, 
                    content, 
                    patterns: [],
                    index: i 
                });
            }
            tsTypeFiles.get(i).patterns.push(tp.pattern);
        }
    });
});

console.log(`找到 ${tsTypeFiles.size} 个包含高级类型的 TypeScript 文件:\n`);

Array.from(tsTypeFiles.values()).slice(0, 8).forEach(file => {
    console.log(`📄 ${file.name}`);
    console.log(`   检测到的类型模式: ${file.patterns.join(', ')}`);
    
    // 提取类型定义示例
    const typeMatches = file.content.match(/(?:type|interface|enum)\s+\w+[\s\S]{0,500}/g);
    if (typeMatches && typeMatches.length > 0) {
        console.log('\n   类型定义示例:');
        typeMatches.slice(0, 2).forEach(match => {
            console.log('   ' + match.substring(0, 300));
            console.log('');
        });
    }
    console.log('');
});

// ============================================
// 第4部分: 性能剖析集成
// ============================================
console.log('\n\n' + '='.repeat(80));
console.log('📈 第4部分: 性能剖析集成 (Profiler)');
console.log('='.repeat(80) + '\n');

const profilerFiles = [];
sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (!content) return;
    
    if (src.toLowerCase().includes('profiler') || 
        content.includes('startupProfiler') ||
        content.includes('headlessProfiler') ||
        content.includes('profileCheckpoint') ||
        content.includes('profileReport')) {
        profilerFiles.push({ name: src, content, index: i });
    }
});

console.log(`找到 ${profilerFiles.length} 个 Profiler 相关文件:\n`);

profilerFiles.forEach(file => {
    console.log(`📄 ${file.name} (${file.content.length} 字符)`);
    
    // 提取 profiler 关键实现
    const profilerKeywords = ['startupProfiler', 'headlessProfiler', 'profileCheckpoint', 'profileReport'];
    profilerKeywords.forEach(keyword => {
        if (file.content.includes(keyword)) {
            const idx = file.content.indexOf(keyword);
            const start = Math.max(0, idx - 50);
            const end = Math.min(file.content.length, idx + 400);
            console.log(`\n   🔍 ${keyword} 实现:`);
            console.log('   ' + file.content.substring(start, end));
        }
    });
    console.log('');
});

// 检查是否有检查点(checkpoint)机制
console.log('\n⏱️  检查点(Checkpoint)机制分析:');
const checkpointFiles = [];
sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (content && (content.includes('checkpoint') || content.includes('markStart') || content.includes('markEnd'))) {
        checkpointFiles.push({ name: src, index: i });
    }
});
console.log(`   找到 ${checkpointFiles.length} 个包含检查点机制的文件`);
checkpointFiles.slice(0, 5).forEach(f => {
    console.log(`   - ${f.name}`);
});

console.log('\n\n' + '='.repeat(80));
console.log('✅ 所有技术亮点分析完成');
console.log('='.repeat(80));