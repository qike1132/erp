/**
 * 打印预览工具 — 使用隐藏 iframe 方式在当前页面内触发浏览器打印对话框，
 * 避免 window.open 弹窗被拦截，且无需离开当前页面。
 */

export function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

const PRINT_STYLE = `
  body { font-family: SimSun, 宋体; padding: 20px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #333; padding: 8px; font-size: 13px; }
  th { background: #e6e6e6; }
`

/**
 * 在当前页面内触发打印预览
 * @param title 打印标题（纯文本，自动转义）
 * @param bodyHtml 主体内容 HTML（由调用方负责安全，确保已转义用户输入）
 * @param style 自定义 CSS（默认使用项目打印样式）
 */
export function printHtml(title: string, bodyHtml: string, style: string = PRINT_STYLE) {
  if (import.meta.env.VITE_CAPACITOR) return
  const iframe = document.createElement('iframe')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  document.body.appendChild(iframe)

  const doc = iframe.contentDocument || iframe.contentWindow?.document
  if (!doc) {
    document.body.removeChild(iframe)
    return
  }

  const safeTitle = escapeHtml(title)
  doc.open()
  doc.write(
    `<!DOCTYPE html><html><head><title>${safeTitle}</title><style>${style}</style></head>` +
    `<body><div style="text-align:center;margin-bottom:20px;"><h2>${safeTitle}</h2></div>${bodyHtml}</body></html>`,
  )
  doc.close()

  setTimeout(() => {
    iframe.contentWindow?.print()
    setTimeout(() => document.body.removeChild(iframe), 1000)
  }, 300)
}

/**
 * 便捷方法：打印一个表格
 * @param title 标题
 * @param headers 表头数组
 * @param rows 行数据数组（每行是单元格值数组）
 * @param style 自定义 CSS
 */
export function printTable(title: string, headers: string[], rows: string[][], style?: string) {
  const thead = `<tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>`
  const tbody = rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')
  printHtml(title, `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`, style)
}
