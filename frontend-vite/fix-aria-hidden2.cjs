const fs = require('fs');
const path = require('path');

const srcPath = 'd:\\erp_system\\frontend-vite\\src';
const excludePatterns = ['UiToast', 'UiUpload', 'UiProgressBar', 'UiProgress', 'DefaultLayout'];

function processFile(filePath) {
  let content = fs.readFileSync(filePath, 'utf8');
  let modified = false;

  // Fix: <i class="fas ..."></i> without aria-hidden
  content = content.replace(/<i\s+class="fas\s+[^"]*"(?![^>]*aria-hidden)[^>]*><\/i>/g, (match) => {
    modified = true;
    return match.replace('></i>', ' aria-hidden="true"></i>');
  });

  // Fix: <i :class="..."></i> without aria-hidden
  content = content.replace(/<i\s+:class="[^"]*"(?![^>]*aria-hidden)[^>]*><\/i>/g, (match) => {
    modified = true;
    return match.replace('></i>', ' aria-hidden="true"></i>');
  });

  // Fix: <i class="far ..."></i> without aria-hidden
  content = content.replace(/<i\s+class="far\s+[^"]*"(?![^>]*aria-hidden)[^>]*><\/i>/g, (match) => {
    modified = true;
    return match.replace('></i>', ' aria-hidden="true"></i>');
  });

  // Fix: <i class="fas ..." style="..."></i> without aria-hidden (multi-attribute)
  content = content.replace(/<i\s+class="fas\s+[^"]*"\s+[^>]*(?<!aria-hidden="true")><\/i>/g, (match) => {
    if (match.includes('aria-hidden')) return match;
    modified = true;
    return match.replace('></i>', ' aria-hidden="true"></i>');
  });

  // Fix: <i v-if="..." class="fas ..."></i> without aria-hidden
  content = content.replace(/<i\s+v-if="[^"]*"\s+class="fas\s+[^"]*"(?![^>]*aria-hidden)[^>]*><\/i>/g, (match) => {
    modified = true;
    return match.replace('></i>', ' aria-hidden="true"></i>');
  });

  // Fix: <i v-if="..." class="fas ..." style="..."></i> without aria-hidden
  content = content.replace(/<i\s+v-if="[^"]*"\s+class="fas\s+[^"]*"\s+[^>]*(?![^>]*aria-hidden)[^>]*><\/i>/g, (match) => {
    if (match.includes('aria-hidden')) return match;
    modified = true;
    return match.replace('></i>', ' aria-hidden="true"></i>');
  });

  if (modified) {
    fs.writeFileSync(filePath, content, 'utf8');
    console.log('MODIFIED: ' + path.relative(srcPath, filePath));
  }
}

function walkDir(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkDir(fullPath);
    } else if (entry.name.endsWith('.vue')) {
      const shouldExclude = excludePatterns.some(p => fullPath.includes(p));
      if (!shouldExclude) {
        processFile(fullPath);
      }
    }
  }
}

walkDir(srcPath);
console.log('\nDone.');
