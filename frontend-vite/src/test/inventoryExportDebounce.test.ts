/** 库存导出必须读防抖后的产品词，避免与页面所见不一致（审计 L-23）。 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync('src/views/stock/InventoryTab.vue', 'utf-8')

describe('库存导出筛选词', () => {
  it('handleExport 使用 debouncedProduct', () => {
    expect(source).toMatch(
      /exportInventory\(\{[^}]*product:\s*debouncedProduct\.value/,
    )
    expect(source).not.toMatch(
      /exportInventory\(\{[^}]*product:\s*filters\.product\b/,
    )
  })
})
