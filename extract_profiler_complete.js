const fs = require('fs');

console.log('📊 提取 Profiler 完整实现代码\n');
console.log('='.repeat(80) + '\n');

const mapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(mapPath, 'utf8'));

// 提取 startupProfiler 完整实现
const startupProfilerIdx = sourceMap.sources.findIndex(s => s.includes('startupProfiler'));
if (startupProfilerIdx !== -1 && sourceMap.sourcesContent[startupProfilerIdx]) {
    console.log('🚀 startupProfiler.ts 完整实现:');
    console.log('-'.repeat(80));
    console.log(sourceMap.sourcesContent[startupProfilerIdx]);
    console.log('-'.repeat(80));
}

// 提取 headlessProfiler 完整实现
const headlessProfilerIdx = sourceMap.sources.findIndex(s => s.includes('headlessProfiler') && !s.includes('startup'));
if (headlessProfilerIdx !== -1 && sourceMap.sourcesContent[headlessProfilerIdx]) {
    console.log('\n\n🎯 headlessProfiler.ts 完整实现:');
    console.log('-'.repeat(80));
    console.log(sourceMap.sourcesContent[headlessProfilerIdx]);
    console.log('-'.repeat(80));
}

// 提取 Hash 层的完整方法实现 (hashClear, hashDelete, hashGet, hashHas, hashSet)
console.log('\n\n' + '='.repeat(80));
console.log('🔧 Hash 层完整方法实现:');
console.log('='.repeat(80) + '\n');

const hashMethods = ['_hashClear', '_hashDelete', '_hashGet', '_hashHas', '_hashSet'];
hashMethods.forEach(method => {
    const idx = sourceMap.sources.findIndex(s => s.toLowerCase().includes(method.toLowerCase()));
    if (idx !== -1 && sourceMap.sourcesContent[idx]) {
        console.log(`\n${method}:`);
        console.log(sourceMap.sourcesContent[idx]);
        console.log('');
    }
});

// 提取 MapCache 的完整方法实现
console.log('\n' + '='.repeat(80));
console.log('🗺️  MapCache 层完整方法实现:');
console.log('='.repeat(80) + '\n');

const mapCacheMethods = ['_mapCacheClear', '_mapCacheDelete', '_mapCacheGet', '_mapCacheHas', '_mapCacheSet'];
mapCacheMethods.forEach(method => {
    const idx = sourceMap.sources.findIndex(s => s.toLowerCase().includes(method.toLowerCase()));
    if (idx !== -1 && sourceMap.sourcesContent[idx]) {
        console.log(`\n${method}:`);
        console.log(sourceMap.sourcesContent[idx]);
        console.log('');
    }
});

// 提取 _Hash.js 中的 HASH_UNDEFINED 定义
const hashUndefinedIdx = sourceMap.sources.findIndex(s => s.endsWith('_Hash.js') || (s.includes('Hash') && s.includes('HASH_UNDEFINED')));
if (hashUndefinedIdx !== -1) {
    const content = sourceMap.sourcesContent[hashUndefinedIdx];
    if (content && content.includes('HASH_UNDEFINED')) {
        console.log('\n' + '='.repeat(80));
        console.log('🔑 HASH_UNDEFINED 哨兵值定义:');
        console.log('='.repeat(80) + '\n');
        
        // 查找 HASH_UNDEFINED 的上下文
        const idx = content.indexOf('HASH_UNDEFINED');
        const start = Math.max(0, idx - 200);
        const end = Math.min(content.length, idx + 500);
        console.log(content.substring(start, end));
    }
}

console.log('\n\n✅ 所有核心实现代码提取完成');