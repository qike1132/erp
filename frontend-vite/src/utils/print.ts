/**
 * 打印预览工具 — 使用隐藏 iframe 方式在当前页面内触发浏览器打印对话框，
 * 避免 window.open 弹窗被拦截，且无需离开当前页面。
 */

/**
 * HTML 转义。**形参收 unknown**：后端字段为空时（null/undefined）不得让拼打印 HTML 的
 * 调用方抛 `TypeError` —— 那样屏幕一切正常、点「打印/导出」却毫无反应（异常被事件
 * 处理器吞掉，页面上没有任何线索）。空值一律转成空串，与屏幕 `{{ x || '' }}` 同口径。
 */
export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/**
 * HTML-.xls 的「按文本」单元格属性。
 *
 * 这种导出本质是 HTML 表格：给单元格加 `mso-number-format:'\@'`，Excel 打开时
 * 会把 `= + - @` 开头的文本当普通文本（前缀单引号只在 Excel 内手工输入时才是
 * 文本标记，写在 HTML 里反而会显示成多余字符）。与
 * `views/outsource/composables/useOutsourceUnshipped.ts` 的既有写法一致。
 */
export const EXCEL_TEXT_ATTR = ` style="mso-number-format:'\\@'"`

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
  // L-26 / N-33（2026-11-21 审计）：print() 或 doc.write 抛异常时原先 removeChild
  // 不会执行，隐藏 iframe 泄漏在 body 里（每次打印失败积累一个）。
  // 结构：write/close 的同步异常走外层 catch 立即回收；
  // 延迟打印的 print() 异常走内层 finally 兜底回收。
  try {
    doc.write(
      `<!DOCTYPE html><html><head><title>${safeTitle}</title><style>${style}</style></head>` +
      `<body><div style="text-align:center;margin-bottom:20px;"><h2>${safeTitle}</h2></div>${bodyHtml}</body></html>`,
    )
    doc.close()
  } catch (e) {
    if (iframe.parentNode) document.body.removeChild(iframe)
    throw e
  }

  setTimeout(() => {
    try {
      iframe.contentWindow?.print()
    } finally {
      setTimeout(() => {
        if (iframe.parentNode) document.body.removeChild(iframe)
      }, 1000)
    }
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
