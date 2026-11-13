/**
 * 屏幕表头「列名」抽取（测试辅助，2026-11-13）。
 *
 * 背景：用户要求把「统一损耗率（千分之几）」输入框并入「损耗率」表头单元格，
 * 该 th 内因此多了「统一」「‰」两个量纲说明与一个 input —— `th.text()` 不再等于列名
 * （会拼成「损耗率统一‰」）。
 *
 * 列序类断言的契约是**列名顺序**（屏幕 ↔ 打印/导出逐列一致），不是「表头格里所有文字」，
 * 故统一从这里取列名：只有内嵌控件的那一格取 `.sm-rate-head__label`，其余列照旧 `th.text()`。
 * 这样「把某列塞进别的格」或「挪列」仍然会红（列名列表变了），而只是加控件不会误伤。
 */
import type { DOMWrapper } from '@vue/test-utils'

/** 单个表头格的列名 */
export function headerLabelText(th: DOMWrapper<Element>): string {
  const label = th.find('.sm-rate-head__label')
  return (label.exists() ? label.text() : th.text()).trim()
}

/** 表头列名数组（顺序 = 列序） */
export function headerLabels(ths: DOMWrapper<Element>[]): string[] {
  return ths.map(headerLabelText)
}
