/**
 * 明细抽屉（RecordDrawer）渲染与交互。
 *
 * 抽屉是纯展示组件：records / total / stats / loading / departments 全部由父级传入，
 * 用户意图以事件抛出（edit / confirm-delete / update:filters / search），
 * 因此本测试**不需要 mock 网络**。
 *
 * 挂载按生产配置（unstyled + PT）—— 默认模式的 p-* 类名生产里不存在，
 * 且 UiDataTable 内部的 PrimeVue DataTable 需要插件才能渲染出 <tr>。
 *
 * 删除确认复用共享的 UiConfirmDialog，其内容经 reka-ui DialogPortal **传送**到
 * document.body，wrapper.find() 搜不到，故对确认框的断言一律走 document。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'

import RecordDrawer from '@/views/production/components/RecordDrawer.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { defaultRecordFilters, type RecordFilters } from '@/views/production/composables/recordFilters'
import { plushCutePT } from '@/styles/primevue-pt'
import type { DailyProductionRecord, ProductionRecordStats } from '@/types'

const record: DailyProductionRecord = {
  id: 7,
  department: 'filling',
  product_name: '白兔公仔 40cm',
  barcode: '6901234',
  unit_price: 7,
  quantity: 620,
  production_value: 4340,
  production_date: '2026-09-29',
  remark: '',
  created_by: '张三',
}

interface DrawerProps {
  open: boolean
  filters: RecordFilters
  records: DailyProductionRecord[]
  total: number
  stats: ProductionRecordStats | null
  loading: boolean
  departments: string[]
  createdByOptions: Array<{ label: string; value: string }>
}

function mountDrawer(overrides: Partial<DrawerProps> = {}) {
  const props: DrawerProps = {
    open: true,
    filters: defaultRecordFilters(),
    records: [record],
    total: 128,
    stats: null,
    loading: false,
    departments: ['filling', 'handcraft', 'packaging'],
    createdByOptions: [],
    ...overrides,
  }

  return mount(RecordDrawer, {
    props,
    // 确认框传送进 document.body，挂到 body 上便于清理与查询
    attachTo: document.body,
    global: {
      plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]],
      stubs: { UiDrawer: { template: '<div><slot /><slot name="footer" /></div>' } },
    },
  })
}

/** UiConfirmDialog 的确认/取消按钮：靠 aria-label 前缀定位（取消，<问句> / 确认，<问句>） */
function confirmBtn(): HTMLButtonElement | null {
  return document.querySelector<HTMLButtonElement>('button[aria-label^="确认，"]')
}
function cancelBtn(): HTMLButtonElement | null {
  return document.querySelector<HTMLButtonElement>('button[aria-label^="取消，"]')
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('RecordDrawer', () => {
  it('渲染表格行与产品名', () => {
    const wrapper = mountDrawer()

    expect(wrapper.text()).toContain('白兔公仔 40cm')
    expect(wrapper.findAll('[data-test="record-row"]').length).toBeGreaterThan(0)
  })

  it('stats 为 null 时合计显示 0，不显示 NaN 或空白', () => {
    // Review Focus #1
    const wrapper = mountDrawer({ stats: null, records: [] })

    const summary = wrapper.find('[data-test="drawer-summary"]')
    expect(summary.text()).toContain('0')
    expect(summary.text()).not.toContain('NaN')
    expect(summary.text()).not.toContain('undefined')
  })

  it('stats 有值时合计显示条数与产量', () => {
    const wrapper = mountDrawer({
      stats: { total_quantity: 4250, total_value: 27170, total_sku: 18 },
    })

    const summary = wrapper.find('[data-test="drawer-summary"]')
    expect(summary.text()).toContain('4,250')
    expect(summary.text()).toContain('18')
  })

  it('点击删除会请求确认，确认文本含产品名与数量', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')
    await nextTick()

    const confirm = confirmBtn()
    expect(confirm).not.toBeNull()
    // 必须限定在确认框内断言：挂载时 attachTo body，抽屉表格里本来就有产品名与 620，
    // 若查整个 body，这两条断言无论确认框内容如何都会通过（等于没测）。
    const dialog = confirm!.closest('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog!.textContent).toContain('白兔公仔 40cm')
    expect(dialog!.textContent).toContain('620')
  })

  it('取消删除时不 emit confirm-delete', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')
    await nextTick()
    cancelBtn()!.click()
    await nextTick()

    expect(wrapper.emitted('confirm-delete')).toBeUndefined()
  })

  it('确认删除时 emit confirm-delete 并带上记录 id', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')
    await nextTick()
    confirmBtn()!.click()
    await nextTick()

    expect(wrapper.emitted('confirm-delete')).toEqual([[7]])
  })

  it('点改 emit edit 并带上整条记录', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-edit"]').trigger('click')

    expect(wrapper.emitted('edit')?.[0]?.[0]).toMatchObject({ id: 7 })
  })

  it('无记录时渲染空态而不是空表', () => {
    const wrapper = mountDrawer({ records: [], total: 0 })

    expect(wrapper.find('[data-test="records-empty"]').exists()).toBe(true)
  })

  it('翻页把 UiDataTable 的 0 基页码转成 1 基写入 filters.page', async () => {
    // UiDataTable 的 @page 是 0 基，而 filters.page / 后端 /records 是 1 基。
    // total 128 / perPage 50 ⇒ 3 页，点「下一页」触发 UiDataTable 的 @page。
    const wrapper = mountDrawer()

    await wrapper.find('button[aria-label="下一页"]').trigger('click')

    const emitted = wrapper.emitted('update:filters')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as RecordFilters
    expect(payload.page).toBe(2)
    expect(payload.perPage).toBe(50)
  })

  it('抽屉关闭时清空待删除状态，重开不会残留确认框', async () => {
    // 抽屉可被 Esc / 遮罩关闭且不卸载；不可恢复的物理删除绝不能残留确认。
    // 断言 UiConfirmDialog 的 open（reka-ui 的 Presence 会在退场动画期间保留 DOM，
    // 故不看 DOM 存在性，看「是否被告知打开」这个稳定信号）。
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')
    await nextTick()
    const dialog = wrapper.findComponent(UiConfirmDialog)
    expect(dialog.props('open')).toBe(true)
    expect(dialog.props('sub')).toContain('白兔公仔 40cm')

    await wrapper.setProps({ open: false })
    await nextTick()
    expect(wrapper.findComponent(UiConfirmDialog).props('open')).toBe(false)

    await wrapper.setProps({ open: true })
    await nextTick()
    expect(wrapper.findComponent(UiConfirmDialog).props('open')).toBe(false)
  })
})
