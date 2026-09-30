/**
 * UiDataTable 的行分组透传（多 SKU 分行的跨行合并靠它）。
 *
 * 需求来源：多 SKU 订单每个 SKU 占一行后，「时间/编号/客户」这三列在同一订单内取值相同，
 * 应该合并成一个跨行大格，而不是每行重复。
 *
 * 两个必须同时成立的性质：
 * ① 传了 `row-group-mode="rowspan"` + `group-rows-by` 时，被分组的列渲染出 `rowspan`；
 * ② **不传时行为完全不变** —— 这个组件被 13 个视图共用，透传必须是纯可选的。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import UiDataTable from '@/components/ui/UiDataTable.vue'

/** 同组的行必须相邻（PrimeVue 的行分组不做重排） */
const ROWS = [
  { id: 1, g: 'order-1', name: '甲', qty: 1 },
  { id: 2, g: 'order-1', name: '乙', qty: 2 },
  { id: 3, g: 'order-1', name: '丙', qty: 3 },
  { id: 4, g: 'order-2', name: '丁', qty: 4 },
]
const COLS = [
  { field: 'g', header: '组' },
  { field: 'name', header: '名称' },
  { field: 'qty', header: '数量' },
]

function mountTable(extraProps: Record<string, unknown> = {}) {
  return mount(UiDataTable, {
    props: { data: ROWS, columns: COLS, rowKey: 'id', ...extraProps },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

describe('UiDataTable 行分组透传', () => {
  it('不传分组属性时，任何单元格都不带 rowspan（13 个共用视图的行为不变）', () => {
    const tds = mountTable().findAll('tbody td')

    expect(tds.length).toBeGreaterThan(0)
    expect(tds.every((td) => td.attributes('rowspan') === undefined)).toBe(true)
  })

  it('rowspan 模式下，被分组的列合并成跨行格，未分组的列各行独立', () => {
    const wrapper = mountTable({ rowGroupMode: 'rowspan', groupRowsBy: 'g' })
    const bodyRows = wrapper.findAll('tbody tr')
    expect(bodyRows.length, '先锁行数，避免空表让下面的断言真空通过').toBe(4)

    // 第 1 行：分组列 g 合并 3 行；name/qty 不合并
    const firstRowCells = bodyRows[0]!.findAll('td')
    expect(firstRowCells[0]!.attributes('rowspan')).toBe('3')
    expect(firstRowCells[1]!.attributes('rowspan')).toBeUndefined()
    expect(firstRowCells[2]!.attributes('rowspan')).toBeUndefined()

    // 组内第 2、3 行的分组列不再渲染（已被上面的跨行格占据），故只剩 name/qty 两格
    expect(bodyRows[1]!.findAll('td').length).toBe(2)
    expect(bodyRows[2]!.findAll('td').length).toBe(2)

    // 第 4 行另属一组：它的分组格必须自己渲染出来、且文本是本组的值 ——
    // 防的是「按值合并把相邻不同组并成一个大格」这个真实风险。
    const lastRowCells = bodyRows[3]!.findAll('td')
    expect(lastRowCells.length, '单行分组的分组格应自己渲染，不能被并进上一组').toBe(3)
    expect(lastRowCells[0]!.text()).toBe('order-2')
    // 实测：PrimeVue 对跨度为 1 的分组不输出 rowspan 属性（语义等同 rowspan=1，不跨到上一组）
    expect(['1', undefined]).toContain(lastRowCells[0]!.attributes('rowspan'))
  })
})
