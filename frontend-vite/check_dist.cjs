const fs = require('fs');
const path = require('path');
const distDir = 'd:/erp_system/frontend-vite/dist/assets';
const files = fs.readdirSync(distDir).filter(f => f.startsWith('BeileOrderView'));
files.forEach(f => {
  const stat = fs.statSync(path.join(distDir, f));
  console.log(f, stat.mtime.toISOString());
});
const idxStat = fs.statSync('d:/erp_system/frontend-vite/dist/index.html');
console.log('index.html', idxStat.mtime.toISOString());
