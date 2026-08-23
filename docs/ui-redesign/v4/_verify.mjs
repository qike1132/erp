import { readFileSync, writeFileSync } from 'fs';

const file = 'D:/erp_system/docs/ui-redesign/v4/prototype.html';
const html = readFileSync(file, 'utf8');

const results = [];
const ok = (name, detail = '') => results.push(`  [PASS] ${name}${detail ? ' · ' + detail : ''}`);
const warn = (name, detail = '') => results.push(`  [WARN] ${name}${detail ? ' · ' + detail : ''}`);
const fail = (name, detail = '') => results.push(`  [FAIL] ${name}${detail ? ' · ' + detail : ''}`);

console.log('===== 1. 外链 / 外部资源扫描 =====');
// 常见外部引用模式(排除注释与 SVG 内部 url(#id) / 日志展示文本)
const patterns = [
  [/https?:\/\//g, 'http(s)://'],
  [/(?<!\/)\/\/[a-z0-9.-]+\./gi, '//host 协议相对'],
  [/@import/g, '@import'],
  [/<link\b/gi, '<link 标签'],
  [/<img\b/gi, '<img 标签'],
  [/<iframe\b/gi, '<iframe 标签'],
  [/\bsrc\s*=/gi, 'src= 属性'],
  [/\bhref\s*=/gi, 'href= 属性'],
  [/fetch\s*\(/g, 'fetch('],
  [/XMLHttpRequest/g, 'XMLHttpRequest'],
  [/new\s+WebSocket/g, 'WebSocket'],
  [/addEventListener\(\s*['"]message/gi, 'postMessage 监听'],
  [/url\(\s*['"]?https?:/gi, 'CSS url(http)'],
  [/\.woff2?|\.ttf|\.otf|\.eot/gi, '外部字体文件'],
];
for (const [re, label] of patterns) {
  const m = html.match(re);
  if (m) warn(`${label} 命中 ${m.length} 处`, m.slice(0, 8).join(' '));
  else ok(`无 ${label}`);
}

// CSS 内 url() 引用检查:应仅 #g1 #g2 等内部引用
const cssBlock = html.match(/<style>([\s\S]*?)<\/style>/)?.[1] || '';
const cssUrls = [...cssBlock.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g)].map(x => x[2]);
const badUrls = cssUrls.filter(u => !u.startsWith('#'));
if (badUrls.length) fail('CSS url() 引用', badUrls.join(' '));
else ok('CSS url() 引用均为内部渐变', cssUrls.join(' '));

console.log('===== 2. 内联 style/script 闭合 =====');
const styleTags = html.match(/<style>[\s\S]*?<\/style>/g) || [];
const scriptTags = html.match(/<script>[\s\S]*?<\/script>/g) || [];
ok(`<style> 块 ${styleTags.length} 个,均闭合`, styleTags.length ? `总 ${cssBlock.length} 字符` : '');
ok(`<script> 块 ${scriptTags.length} 个`, scriptTags.length ? `总 ${(html.match(/<script>[\s\S]*?<\/script>/g) || []).join('').length} 字符` : '');
const openStyle = (html.match(/<style>/g) || []).length;
const closeStyle = (html.match(/<\/style>/g) || []).length;
const openScript = (html.match(/<script>/g) || []).length;
const closeScript = (html.match(/<\/script>/g) || []).length;
openStyle === closeStyle ? ok(`<style> 开/闭配平 ${openStyle}/${closeStyle}`) : fail(`<style> 开闭不配平 ${openStyle}/${closeStyle}`);
openScript === closeScript ? ok(`<script> 开/闭配平 ${openScript}/${closeScript}`) : fail(`<script> 开闭不配平 ${openScript}/${closeScript}`);

console.log('===== 3. CSS 花括号配平 =====');
let depth = 0, minDepth = 0, at = -1;
for (let i = 0; i < cssBlock.length; i++) {
  const c = cssBlock[i];
  if (c === '{') depth++;
  else if (c === '}') {
    depth--;
    if (depth < minDepth) { minDepth = depth; at = i; }
  }
}
depth === 0 ? ok(`CSS 花括号配平(闭合深度 0)`) : fail(`CSS 花括号未配平,最终深度 ${depth},最低 ${minDepth} @${at}`);
// 统计规则数
const rules = (cssBlock.match(/\{[^}]*\}/g) || []).length;
ok(`CSS 规则块约 ${rules} 个`);

console.log('===== 4. JS 语法校验(node --check) =====');
const jsBlock = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] || '';
const tmp = 'D:/erp_system/docs/ui-redesign/v4/_inline_check.js';
writeFileSync(tmp, jsBlock, 'utf8');
ok(`已提取内联 JS ${jsBlock.length} 字符 → ${tmp}`);

console.log('===== 5. HTML 结构完整性 =====');
const checks = [
  ['<!doctype html>', /<!doctype html>/i],
  ['<meta charset>', /<meta charset=/i],
  ['<meta viewport>', /<meta name="viewport"/i],
  ['<title>', /<title>/],
  ['<html> 开标签', /<html/],
  ['</html> 闭标签', /<\/html>/],
  ['<head> 开标签', /<head>/],
  ['</head> 闭标签', /<\/head>/],
  ['<body> 开标签', /<body>/],
  ['</body> 闭标签', /<\/body>/],
  ['id="v-overview"', /id="v-overview"/],
  ['id="v-services"', /id="v-services"/],
  ['id="toast-wrap"', /id="toast-wrap"/],
];
for (const [name, re] of checks) {
  re.test(html) ? ok(name) : fail(name);
}
// 计数主要标签配平
for (const tag of ['div', 'section', 'header', 'footer', 'aside', 'main', 'table', 'svg', 'button']) {
  const o = (html.match(new RegExp(`<${tag}[\\s>]`, 'g')) || []).length;
  const c = (html.match(new RegExp(`</${tag}>`, 'g')) || []).length;
  o === c ? ok(`<${tag}> 配平 ${o}/${c}`) : warn(`<${tag}> 配平异常 ${o}/${c}`);
}

console.log('===== 结果 =====');
console.log(results.join('\n'));
const fails = results.filter(r => r.includes('[FAIL]')).length;
const warns = results.filter(r => r.includes('[WARN]')).length;
console.log(`\nFAIL=${fails} WARN=${warns}`);
