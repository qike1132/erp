const fs = require('fs');
let html = fs.readFileSync('ui_prototype_v2.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
try { new Function(m[1]); console.log('JS SYNTAX OK'); }
catch (e) { console.log('JS ERR: ' + e.message); process.exit(1); }
html = html.replace(/<script>[\s\S]*?<\/script>/g, '');
const stack = [];
const re = /<\/?([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^'">])*)>/g;
let mm;
const selfClose = new Set(['input','img','br','hr','meta','line','circle','rect','path','polyline','marker','text','stop','ellipse']);
while ((mm = re.exec(html)) !== null) {
  const tag = mm[1], isClose = mm[0][1] === '/';
  if (isClose) {
    if (!stack.length) continue;
    const top = stack.pop();
    if (top !== tag) { console.log('MISMATCH </' + tag + '> expected </' + top + '> at ' + mm.index); process.exit(1); }
  } else if (!selfClose.has(tag) && !/\/>$/.test(mm[0])) stack.push(tag);
}
console.log('HTML TAGS OK, remaining=' + JSON.stringify(stack));
