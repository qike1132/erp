/**
 * XLS 导出工具函数
 *
 * 通过 HTML 表格 + application/vnd.ms-excel MIME 类型生成 .xls 文件，
 * Excel 可直接打开。带 UTF-8 BOM 避免中文乱码。
 */

const XLS_STYLE = `<style>
  body { font-family: SimSun, 宋体; padding: 20px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #333; padding: 8px; font-size: 13px; text-align: center; }
  th { background: #e6e6e6; }
</style>`

/**
 * 将 HTML 表格字符串下载为 .xls 文件。
 *
 * @param html 表格 HTML（由调用方构建，含 <table> 标签）
 * @param filename 下载文件名（含 .xls 扩展名）
 */
export function downloadXls(html: string, filename: string): void {
  const bom = '\uFEFF'
  const fullHtml = `<html><head><meta charset="utf-8">${XLS_STYLE}</head><body>${html}</body></html>`
  const blob = new Blob([bom + fullHtml], { type: 'application/vnd.ms-excel;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}