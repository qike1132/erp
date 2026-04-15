const fs = require('fs');

console.log('🔍 提取 getMapData 和其他关键辅助函数\n');
console.log('='.repeat(80) + '\n');

const mapPath = 'C:\\Users\\Administrator\\Desktop\\cli.js.map';
const sourceMap = JSON.parse(fs.readFileSync(mapPath, 'utf8'));

// 提取 getMapData
const getMapDataIdx = sourceMap.sources.findIndex(s => s.includes('_getMapData'));
if (getMapDataIdx !== -1 && sourceMap.sourcesContent[getMapDataIdx]) {
    console.log('🎯 _getMapData.js (MapCache 三分发的核心):');
    console.log('-'.repeat(80));
    console.log(sourceMap.sourcesContent[getMapDataIdx]);
    console.log('-'.repeat(80));
}

// 提取 _Map.js (原生Map的polyfill)
const mapIdx = sourceMap.sources.findIndex(s => s.endsWith('_Map.js') && !s.includes('Cache') && !s.includes('mapCache'));
if (mapIdx !== -1 && sourceMap.sourcesContent[mapIdx]) {
    console.log('\n\n🗺️  _Map.js (原生Map封装):');
    console.log('-'.repeat(80));
    console.log(sourceMap.sourcesContent[mapIdx]);
    console.log('-'.repeat(80));
}

// 提取 eq.js (深度比较函数)
const eqIdx = sourceMap.sources.findIndex(s => s.endsWith('eq.js') && s.includes('lodash-es'));
if (eqIdx !== -1 && sourceMap.sourcesContent[eqIdx]) {
    console.log('\n\n⚖️  eq.js (SameValueZero比较算法):');
    console.log('-'.repeat(80));
    console.log(sourceMap.sourcesContent[eqIdx]);
    console.log('-'.repeat(80));
}

// 提取 _freeGlobal 和 _root
const freeGlobalIdx = sourceMap.sources.findIndex(s => s.includes('_freeGlobal'));
if (freeGlobalIdx !== -1 && sourceMap.sourcesContent[freeGlobalIdx]) {
    console.log('\n\n🌍 _freeGlobal.js:');
    console.log(sourceMap.sourcesContent[freeGlobalIdx]);
}

const rootIdx = sourceMap.sources.findIndex(s => s.endsWith('_root.js') && s.includes('lodash-es'));
if (rootIdx !== -1 && sourceMap.sourcesContent[rootIdx]) {
    console.log('\n\n🌳 _root.js (全局对象检测):');
    console.log(sourceMap.sourcesContent[rootIdx]);
}

// 提取 _getNative
const getNativeIdx = sourceMap.sources.findIndex(s => s.includes('_getNative'));
if (getNativeIdx !== -1 && sourceMap.sourcesContent[getNativeIdx]) {
    console.log('\n\n🔧 _getNative.js (原生方法安全获取):');
    console.log(sourceMap.sourcesContent[getNativeIdx]);
}

console.log('\n\n✅ 所有辅助函数提取完成');