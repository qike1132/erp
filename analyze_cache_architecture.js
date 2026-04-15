const fs = require('fs');

console.log('🔬 深度分析四层缓存架构实现\n');
console.log('='.repeat(80) + '\n');

const mapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(mapPath, 'utf8'));

// 提取所有lodash-es缓存相关源文件
const cacheFiles = {
    hash: null,
    listCache: null,
    mapCache: null,
    stack: null,
    nativeCreate: null,
    hashUndefined: null,
    assocIndexOf: null,
    isKeyable: null,
    largeArraySize: null
};

sourceMap.sources.forEach((src, i) => {
    const content = sourceMap.sourcesContent[i];
    if (!content) return;
    
    const srcLower = src.toLowerCase();
    
    if (srcLower.includes('hash.js') && !srcLower.includes('list') && !srcLower.includes('map')) {
        cacheFiles.hash = { name: src, content };
    }
    else if (srcLower.includes('_listcache.js')) {
        cacheFiles.listCache = { name: src, content };
    }
    else if (srcLower.includes('_mapcache.js')) {
        cacheFiles.mapCache = { name: src, content };
    }
    else if (srcLower.includes('_stack.js') && !srcLower.includes('clear') && !srcLower.includes('delete') && !srcLower.includes('get') && !srcLower.includes('has') && !srcLower.includes('set')) {
        cacheFiles.stack = { name: src, content };
    }
    else if (srcLower.includes('nativecreate') || (content.includes('nativeCreate') && srcLower.includes('freeglobal'))) {
        if (!cacheFiles.nativeCreate) {
            cacheFiles.nativeCreate = { name: src, content };
        }
    }
    else if (srcLower.includes('hash_undefined') || srcLower.includes('hashundefined')) {
        cacheFiles.hashUndefined = { name: src, content };
    }
    else if (srcLower.includes('associndexof')) {
        cacheFiles.assocIndexOf = { name: src, content };
    }
    else if (srcLower.includes('iskeyable')) {
        cacheFiles.isKeyable = { name: src, content };
    }
    else if (srcLower.includes('large_array_size') || srcLower.includes('largearraysize')) {
        cacheFiles.largeArraySize = { name: src, content };
    }
});

console.log('📦 找到的缓存架构文件:\n');
Object.entries(cacheFiles).forEach(([key, value]) => {
    if (value) {
        console.log(`  ✅ ${key}: ${value.name} (${value.content.length} 字符)`);
    } else {
        console.log(`  ❌ ${key}: 未找到`);
    }
});

// 输出每个层的实现细节
console.log('\n' + '='.repeat(80));
console.log('第1层: Hash 层 - nativeCreate(null) 实现');
console.log('='.repeat(80) + '\n');

if (cacheFiles.nativeCreate) {
    console.log('📄 源文件:', cacheFiles.nativeCreate.name);
    console.log('\n源码实现:');
    console.log('-'.repeat(60));
    console.log(cacheFiles.nativeCreate.content);
    console.log('-'.repeat(60));
}

if (cacheFiles.hashUndefined) {
    console.log('\n📌 HASH_UNDEFINED 哨兵值定义:');
    console.log(cacheFiles.hashUndefined.content);
}

if (cacheFiles.hash) {
    console.log('\n📦 Hash 类完整实现:');
    console.log(cacheFiles.hash.content);
}

console.log('\n' + '='.repeat(80));
console.log('第2层: ListCache 层 - 数组存储+线性查找');
console.log('='.repeat(80) + '\n');

if (cacheFiles.assocIndexOf) {
    console.log('📄 assocIndexOf 核心查找算法:');
    console.log(cacheFiles.assocIndexOf.content);
}

if (cacheFiles.listCache) {
    console.log('\n📋 ListCache 类完整实现:');
    console.log(cacheFiles.listCache.content);
}

// 提取ListCache的各个方法
const listCacheMethods = ['_listCacheClear', '_listCacheDelete', '_listCacheGet', '_listCacheHas', '_listCacheSet'];
console.log('\n🔧 ListCache 各方法实现:');
listCacheMethods.forEach(method => {
    const idx = sourceMap.sources.findIndex(s => s.toLowerCase().includes(method.toLowerCase()));
    if (idx !== -1 && sourceMap.sourcesContent[idx]) {
        console.log(`\n  ${method}:`);
        console.log(`  ${sourceMap.sourcesContent[idx]}`);
    }
});

console.log('\n' + '='.repeat(80));
console.log('第3层: MapCache 层 - hash/map/string 三分发');
console.log('='.repeat(80) + '\n');

if (cacheFiles.isKeyable) {
    console.log('🎯 isKeyable 类型判断函数:');
    console.log(cacheFiles.isKeyable.content);
}

if (cacheFiles.mapCache) {
    console.log('\n🗺️  MapCache 类完整实现:');
    console.log(cacheFiles.mapCache.content);
}

console.log('\n' + '='.repeat(80));
console.log('第4层: Stack 层 - ListCache→MapCache 自动升级');
console.log('='.repeat(80) + '\n');

if (cacheFiles.largeArraySize) {
    console.log('📏 LARGE_ARRAY_SIZE 阈值常量:');
    console.log(cacheFiles.largeArraySize.content);
}

if (cacheFiles.stack) {
    console.log('\n📚 Stack 类完整实现（自动升级机制）:');
    console.log(cacheFiles.stack.content);
}

// 提取Stack的各个方法
const stackMethods = ['_stackClear', '_stackDelete', '_stackGet', '_stackHas', '_stackSet'];
console.log('\n🔄 Stack 升级相关方法:');
stackMethods.forEach(method => {
    const idx = sourceMap.sources.findIndex(s => s.toLowerCase().includes(method.toLowerCase()));
    if (idx !== -1 && sourceMap.sourcesContent[idx]) {
        console.log(`\n  ${method}:`);
        console.log(`  ${sourceMap.sourcesContent[idx]}`);
    }
});

console.log('\n\n' + '='.repeat(80));
console.log('✅ 四层缓存架构分析完成');
console.log('='.repeat(80));