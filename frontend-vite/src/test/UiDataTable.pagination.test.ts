/**
 * UiDataTable 分页：受控页码 / 单页隐藏 / 量词（2026-10-02 回归）。
 *
 * 背景：客户/供应商列表迁移到 UiDataTable 后，表格**内部**页码会在 totalRecords 变化时
 * 复位到 1，而父组件仍按旧页码回源 —— 表格显示第 N 页数据、指示器却显示「1 / N」。
 * 修法：父组件传 `currentPage` 进入受控模式，组件不再自行复位页码。
 *
 * 另两条同批修复：单页时隐藏分页条（旧实现恒渲染）、量词可覆盖（按单据分页、
 * 一行一 SKU 渲染时说「条」会与实际行数对不上）。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import UiDataTable from '@/components/ui/UiDataTable.vue'

const ROWS = Array.from({ length: 5 }, (_, i) => ({ id: i + 1, name: `P${i + 1}` }))
const COLS = [{ field: 'name', header: '名称' }]

function mountTable(props: Record<string, unknown> = {}) {
  return mount(UiDataTable, {
    props: { data: ROWS, columns: COLS, rowKey: 'id', paginator: true, rows: 5, ...props },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

describe('UiDataTable 分页', () => {
  it('受控模式：totalRecords 变化不会把页码复位到 1', async () => {
    const wrapper = mountTable({ currentPage: 3, totalRecords: 30 })
    expect(wrapper.find('.ui-page-info').text()).toBe('3 / 6')

    await wrapper.setProps({ totalRecords: 27 })
    await nextTick()

    // 数据回源由父组件按 currentPage 驱动，组件不得擅自复位
    expect(wrapper.find('.ui-page-info').text()).toBe('3 / 6')
  })

  it('受控模式：父组件传新页码时跟随', async () => {
    const wrapper = mountTable({ currentPage: 1, totalRecords: 30 })
    expect(wrapper.find('.ui-page-info').text()).toBe('1 / 6')

    await wrapper.setProps({ currentPage: 2 })
    await nextTick()

    expect(wrapper.find('.ui-page-info').text()).toBe('2 / 6')
  })

  it('非受控模式：totalRecords 变化仍复位到第 1 页（13 个共用视图的既有行为不变）', async () => {
    const wrapper = mountTable({ totalRecords: 30 })
    // 真的翻到第 2 页（点「下一页」而不是 $emit —— 后者不会改组件内部状态）
    await wrapper.findAll('.ui-page-btn')[1]!.trigger('click')
    expect(wrapper.find('.ui-page-info').text()).toBe('2 / 6')

    await wrapper.setProps({ totalRecords: 25 })
    await nextTick()

    expect(wrapper.find('.ui-page-info').text()).toBe('1 / 5')
  })

  it('hidePaginatorOnSinglePage：只有一页时不渲染分页条', () => {
    const single = mountTable({ rows: 20, totalRecords: 5, hidePaginatorOnSinglePage: true })
    expect(single.find('.ui-pagination').exists()).toBe(false)

    const multi = mountTable({ rows: 5, totalRecords: 30, hidePaginatorOnSinglePage: true })
    expect(multi.find('.ui-pagination').exists()).toBe(true)
  })

  it('默认不隐藏：单页也渲染分页条（保持既有 13 个视图不变）', () => {
    const wrapper = mountTable({ rows: 20, totalRecords: 5 })
    expect(wrapper.find('.ui-pagination').exists()).toBe(true)
  })

  it('itemUnit 覆盖「共 N ?」的量词', () => {
    const wrapper = mountTable({ totalRecords: 30, itemUnit: '单' })
    expect(wrapper.find('.ui-page-total').text()).toBe('共 30 单')

    const def = mountTable({ totalRecords: 30 })
    expect(def.find('.ui-page-total').text()).toBe('共 30 条')
  })
})
