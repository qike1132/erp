const fs = require('fs');
const path = require('path');

console.log('🔍 开始解析 Source Map 文件...\n');

const mapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(mapPath, 'utf8'));

console.log('📊 Source Map 基本信息:');
console.log(`   - 版本: ${sourceMap.version}`);
console.log(`   - 源文件数量: ${sourceMap.sources.length}`);
console.log(`   - Names 数量: ${sourceMap.names ? sourceMap.names.length : 0}`);
console.log(`   - Mappings 长度: ${(sourceMap.mappings || '').length} 字符`);
console.log('');

console.log('📁 源文件列表 (前20个):');
sourceMap.sources.slice(0, 20).forEach((src, i) => {
    console.log(`   [${i}] ${src}`);
});
if (sourceMap.sources.length > 20) {
    console.log(`   ... 还有 ${sourceMap.sources.length - 20} 个源文件`);
}
console.log('');

// 查找 lodash-es 相关的源文件
const lodashSources = sourceMap.sources.filter(s => s.includes('lodash-es'));
console.log(`\n🎯 找到 ${lodashSources.length} 个 lodash-es 相关源文件:`);
lodashSources.slice(0, 15).forEach((src, i) => {
    console.log(`   [${i}] ${src}`);
});

// 查找 React Compiler 和 createSignal 相关
const reactCompilerSources = sourceMap.sources.filter(s =>
    s.includes('_c') || s.includes('compiler') || s.includes('$[')
);
console.log(`\n⚛️  找到 ${reactCompilerSources.length} 个 React Compiler 相关源文件`);

const signalSources = sourceMap.sources.filter(s =>
    s.includes('createSignal') || s.includes('signal')
);
console.log(`\n📡 找到 ${signalSources.length} 个 Signal 相关源文件`);

const profilerSources = sourceMap.sources.filter(s =>
    s.includes('profiler') || s.includes('profileCheckpoint')
);
console.log(`\n📈 找到 ${profilerSources.length} 个 Profiler 相关源文件`);

// 提取缓存相关的源码
console.log('\n' + '='.repeat(80));
console.log('🔧 开始深度分析四层缓存架构...');
console.log('='.repeat(80) + '\n');

const cacheKeywords = ['Hash', 'ListCache', 'MapCache', 'Stack', 'nativeCreate', 'HASH_UNDEFINED'];
let cacheSourceIndex = -1;
let cacheSourceContent = '';

for (let i = 0; i < sourceMap.sources.length; i++) {
    const src = sourceMap.sources[i];
    if (cacheKeywords.some(kw => src.toLowerCase().includes(kw.toLowerCase()))) {
        console.log(`✅ 发现缓存相关源文件: ${src}`);
        cacheSourceIndex = i;
        if (sourceMap.sourcesContent && sourceMap.sourcesContent[i]) {
            cacheSourceContent = sourceMap.sourcesContent[i];
            console.log(`   源码长度: ${cacheSourceContent.length} 字符`);
            
            // 提取关键代码段
            const hashMatch = cacheSourceContent.match(/class Hash[\s\S]{0,2000}(?:clear|delete|get|has|set)/);
            if (hashMatch) {
                console.log('\n📦 Hash 类实现片段:');
                console.log(hashMatch[0].substring(0, 1500));
            }
        }
        break;
    }
}

if (cacheSourceIndex === -1) {
    console.log('❌ 未在 sources 中找到直接匹配的缓存文件');
    console.log('\n尝试在所有源码内容中搜索...');
    
    for (let i = 0; i < Math.min(sourceMap.sourcesContent?.length || 0, 100); i++) {
        const content = sourceMap.sourcesContent[i];
        if (content && content.includes('nativeCreate')) {
            console.log(`\n✅ 在索引 [${i}] ${sourceMap.sources[i]} 中找到 nativeCreate`);
            console.log(`   文件大小: ${content.length} 字符`);
            
            // 提取完整的缓存实现
            const startIdx = content.indexOf('nativeCreate');
            const extractStart = Math.max(0, startIdx - 500);
            const extractEnd = Math.min(content.length, startIdx + 8000);
            console.log('\n📋 缓存架构核心实现:');
            console.log(content.substring(extractStart, extractEnd));
            break;
        }
    }
}

// 输出分析结果摘要
console.log('\n' + '='.repeat(80));
console.log('📋 分析完成 - 准备输出详细报告');
console.log('='.repeat(80));

// 将关键信息保存到临时文件供后续使用
const analysisData = {
    totalSources: sourceMap.sources.length,
    lodashSourcesCount: lodashSources.length,
    lodashSources: lodashSources,
    hasCacheImplementation: cacheSourceIndex !== -1
};

fs.writeFileSync(
    path.join(__dirname, 'sourcemap_analysis.json'),
    JSON.stringify(analysisData, null, 2)
);
console.log('\n💾 分析数据已保存到 sourcemap_analysis.json');