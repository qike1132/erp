/**
 * CSV 导出工具函数
 *
 * 提供 CSV 字符串行列表下载为文件的通用能力，
 * 消除各视图中重复的 Blob 构造 + 临时链接下载逻辑。
 */

/** 纯数字（含负数/小数）：-123 这类值不能被当成公式前缀处理，否则数值列变文本。 */
const PLAIN_NUMBER = /^-?\d+(\.\d+)?$/
/** 公式起始字符（含前导空白绕过：`  =cmd` 在 Excel 里仍会被求值）。 */
const FORMULA_START = /^\s*[=+\-@\t\r]/

/**
 * 按 RFC 4180 转义单个 CSV 字段，并中和电子表格公式。
 *
 * 字段包含逗号、双引号、换行符时，需用双引号包裹并将内部双引号转义为两个双引号。
 * 数字与简单字符串原样返回。
 *
 * H8（2026-10-26）：RFC 4180 转义**不等于**公式中和。以 `= + - @`（含前导空白）
 * 开头的单元格在 Excel/WPS 打开时会被当作公式求值——`=HYPERLINK(...)`、`=cmd|...`
 * 之类可外带数据或在旧版 DDE 下执行命令。导入失败明细里的客户名/产品名/条码
 * 都是用户可控内容，导出再被运营打开就是一条注入链。这里按 OWASP 口径加 `'`
 * 前缀强制按文本显示；纯数字（`-123`）保持原样，避免数值列被转成文本。
 *
 * @param value 任意字段值（数字/字符串/null）
 * @returns 转义后的 CSV 字段字符串
 */
export function escapeCsvField(value: unknown): string {
  if (value === null || value === undefined) return '';
  let str = String(value);
  if (!PLAIN_NUMBER.test(str) && FORMULA_START.test(str)) {
    str = `'${str}`;
  }
  if (/[",\r\n]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/**
 * 将字段值数组拼接为一行 CSV 字符串（自动按 RFC 4180 转义）。
 *
 * @param fields 字段值数组
 * @returns 转义并拼接后的 CSV 行字符串
 */
export function buildCsvRow(fields: unknown[]): string {
  return fields.map(escapeCsvField).join(',');
}

/**
 * 将 CSV 行列表下载为带 BOM 的 UTF-8 CSV 文件。
 *
 * 调用方负责构建表头与数据行（每行一个字符串，字段间已用逗号拼接）；
 * 本函数仅负责：BOM 前缀、Blob 构造、临时链接下载、URL 释放。
 *
 * 推荐使用 escapeCsvField / buildCsvRow 构建每行，避免包含逗号/引号/换行的字段破坏 CSV 格式。
 *
 * @param rows CSV 行列表（含表头），每行为已拼接好的字符串。
 * @param filename 下载文件名（含扩展名）。
 */
export function downloadCsv(rows: string[], filename: string): void {
  const blob = new Blob(['\uFEFF' + rows.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
