// 原型 HTML 语法校验工具（原 docs/ui-redesign/_v2check.js）
// 用法: cd docs/ui-redesign && node tools/prototype_check.js
// 安全说明: 旧版用 new Function 执行内联脚本来验语法（动态执行，Mimosa 高危）。
// 新版为纯静态检查——括号/引号配对 + HTML 标签配对，无动态执行、无子进程调用，
// 可通过所有安全扫描。完整语法校验请交给编辑器/ESLint。开发期工具，不参与生产构建。
const fs = require('fs');
let html = fs.readFileSync('ui_prototype_v2.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m || !m[1].trim()) {
  console.log('JS: no inline <script> found — SKIPPED');
} else {
  const script = m[1];
  // 静态括号/引号配对检查（剥离字符串与注释后统计开闭）
  const cleaned = script
    .replace(/\/\/[^\n]*/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/'(?:\\.|[^'\\\n])*'/g, "''")
    .replace(/"(?:\\.|[^"\\\n])*"/g, '""')
    .replace(/`(?:\\.|[^`\\])*`/g, '``');
  const pairs = { ')': '(', ']': '[', '}': '{' };
  const st = [];
  let bad = null;
  for (let i = 0; i < cleaned.length; i++) {
    const ch = cleaned[i];
    if (ch === '(' || ch === '[' || ch === '{') st.push(ch);
    else if (ch in pairs) {
      if (st.pop() !== pairs[ch]) { bad = `unbalanced '${ch}' at index ${i}`; break; }
    }
  }
  if (bad || st.length) { console.log('JS BRACKETS ERR: ' + (bad || `unclosed ${JSON.stringify(st)}`)); process.exit(1); }
  console.log('JS BRACKETS OK (static check, never executed)');
}

// HTML 标签配对检查（纯静态，无执行）
html = html.replace(/<script>[\s\S]*?<\/script>/g, '');
const stack = [];
const re = /<\/?([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^'">])*)>/g;
const selfClose = new Set(['input','img','br','hr','meta','line','circle','rect','path','polyline','marker','text','stop','ellipse']);
for (const mm of html.matchAll(re)) {
  const tag = mm[1], isClose = mm[0][1] === '/';
  if (isClose) {
    if (!stack.length) continue;
    const top = stack.pop();
    if (top !== tag) { console.log('MISMATCH </' + tag + '> expected </' + top + '> at ' + mm.index); process.exit(1); }
  } else if (!selfClose.has(tag) && !/\/>$/.test(mm[0])) stack.push(tag);
}
console.log('HTML TAGS OK, remaining=' + JSON.stringify(stack));
