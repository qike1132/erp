const fs = require('fs');
const path = require('path');

const srcPath = 'd:\\erp_system\\frontend-vite\\src';
const excludePatterns = ['UiToast', 'UiUpload', 'UiProgressBar', 'UiProgress', 'DefaultLayout'];

const iconLabelMap = {
  'fa-times': '\u5173\u95ed',       // 关闭
  'fa-xmark': '\u5173\u95ed',       // 关闭
  'fa-trash': '\u5220\u9664',       // 删除
  'fa-trash-alt': '\u5220\u9664',   // 删除
  'fa-edit': '\u7f16\u8f91',       // 编辑
  'fa-pen': '\u7f16\u8f91',        // 编辑
  'fa-search': '\u641c\u7d22',     // 搜索
  'fa-eye': '\u67e5\u770b',        // 查看
  'fa-eye-slash': '\u5207\u6362\u5bc6\u7801\u53ef\u89c1\u6027', // 切换密码可见性
  'fa-lock': '\u5207\u6362\u72b6\u6001',   // 切换状态
  'fa-lock-open': '\u5207\u6362\u72b6\u6001', // 切换状态
  'fa-plus': '\u6dfb\u52a0',       // 添加
  'fa-eraser': '\u6e05\u9664',     // 清除
  'fa-redo': '\u5237\u65b0',       // 刷新
  'fa-sync-alt': '\u5237\u65b0',   // 刷新
  'fa-upload': '\u4e0a\u4f20',     // 上传
  'fa-download': '\u4e0b\u8f7d',   // 下载
  'fa-chevron-left': '\u4e0a\u4e00\u9875',   // 上一页
  'fa-chevron-right': '\u4e0b\u4e00\u9875',  // 下一页
  'fa-angle-left': '\u4e0a\u4e00\u9875',     // 上一页
  'fa-angle-right': '\u4e0b\u4e00\u9875',    // 下一页
  'fa-angle-double-left': '\u9996\u9875',     // 首页
  'fa-angle-double-right': '\u672b\u9875',    // 末页
  'fa-undo-alt': '\u6062\u590d',   // 恢复
  'fa-cog': '\u8bbe\u7f6e',       // 设置
  'fa-cogs': '\u914d\u7f6e',      // 配置
  'fa-filter': '\u7b5b\u9009',    // 筛选
  'fa-magic': '\u5ba1\u6838',     // 审核
  'fa-shield-alt': '\u5de1\u68c0', // 巡检
  'fa-layer-group': '\u6279\u91cf', // 批量
  'fa-boxes-stacked': '\u6279\u91cf', // 批量
  'fa-clipboard-check': '\u5ba1\u6838', // 审核
  'fa-hand-point-left': '\u8fd4\u56de', // 返回
  'fa-chart-pie': '\u7edf\u8ba1', // 统计
  'fa-calculator': '\u8ba1\u7b97', // 计算
  'fa-file-export': '\u5bfc\u51fa', // 导出
  'fa-file-excel': '\u5bfc\u5165', // 导入
  'fa-file-import': '\u5bfc\u5165', // 导入
  'fa-file-download': '\u4e0b\u8f7d', // 下载
  'fa-server': '\u670d\u52a1\u5668', // 服务器
  'fa-history': '\u5386\u53f2\u8bb0\u5f55', // 历史记录
};

function getAriaLabel(iconTag) {
  for (const [icon, label] of Object.entries(iconLabelMap)) {
    if (iconTag.includes(icon)) return label;
  }
  return null;
}

function processFile(filePath) {
  let content = fs.readFileSync(filePath, 'utf8');
  let modified = false;

  // Pattern: <button ...> only <i> icon </button> (single line)
  // Match: <button ...>whitespace<i .../>whitespace</button>
  const singleLinePattern = /(<button\s[^>]*?)(>)(\s*<i\s[^>]*?\/?>\s*)(<\/button>)/g;
  content = content.replace(singleLinePattern, (match, btnOpen, btnClose1, iconTag, btnClose2) => {
    if (btnOpen.includes('aria-label')) return match;
    // Check if there's text content
    const textOnly = iconTag.replace(/<[^>]+>/g, '').trim();
    if (textOnly) return match;
    const label = getAriaLabel(iconTag);
    if (!label) return match;
    modified = true;
    return `${btnOpen} aria-label="${label}"${btnClose1}${iconTag}${btnClose2}`;
  });

  // Pattern: <button ...> only <i> icon </button> (with </i>)
  const withCloseTagPattern = /(<button\s[^>]*?)(>)(\s*<i\s[^>]*?>\s*<\/i>\s*)(<\/button>)/g;
  content = content.replace(withCloseTagPattern, (match, btnOpen, btnClose1, iconTag, btnClose2) => {
    if (btnOpen.includes('aria-label')) return match;
    const textOnly = iconTag.replace(/<[^>]+>/g, '').trim();
    if (textOnly) return match;
    const label = getAriaLabel(iconTag);
    if (!label) return match;
    modified = true;
    return `${btnOpen} aria-label="${label}"${btnClose1}${iconTag}${btnClose2}`;
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
