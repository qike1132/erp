import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const updateMock = vi.fn()
vi.mock('@/api/production', () => ({
  dailyProductionApi: { updateRecord: (...a: unknown[]) => updateMock(...a) },
}))

import RecordEditDialog from '@/views/production/components/RecordEditDialog.vue'
import type { DailyProductionRecord } from '@/types'

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

// UiDialog 基于 reka-ui，内容经 portal 渲染到 body，`stubs: { teleport: true }` 不足以
// 让插槽内容可断言。本仓库既有做法是把它 stub 成普通容器（见 ocrPreviewModal.test.ts /
// OutsourceShipDialog.test.ts），保留默认插槽与 footer 插槽即可。
const stubs = {
  UiDialog: {
    props: ['open', 'title'],
    emits: ['update:open'],
    template: '<div class="ui-dialog"><slot /><slot name="footer" /></div>',
  },
}

describe('RecordEditDialog', () => {
  beforeEach(() => {
    updateMock.mockReset()
    updateMock.mockResolvedValue({ success: true, message: 'ok' })
  })

  it('只提交被改动过的字段', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs },
    })

    await wrapper.find('[data-test="edit-quantity"]').setValue('700')
    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(updateMock).toHaveBeenCalledWith(7, { quantity: 700 })
  })

  it('没有改动时不提交，只关闭', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs },
    })

    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(updateMock).not.toHaveBeenCalled()
    expect(wrapper.emitted('update:open')).toEqual([[false]])
  })

  it('数量改为 0 时拒绝提交并给出提示', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs },
    })

    await wrapper.find('[data-test="edit-quantity"]').setValue('0')
    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(updateMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('大于 0')
  })

  it('保存成功后 emit saved', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs },
    })

    await wrapper.find('[data-test="edit-remark"]').setValue('补录')
    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
