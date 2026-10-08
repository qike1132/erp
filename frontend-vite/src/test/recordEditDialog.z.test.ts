/**
 * 「改」编辑弹窗是从「生产明细」面板里点「改」打开的。面板是 PrimeVue Drawer，其遮罩 z
 * 由 PrimeVue 定为 2100（main.ts 的 zIndex.modal）。所以本弹窗必须用超过该层的嵌套层级
 * （--z-overlay/modal-nested），否则会被遮罩压住、点不到 —— 曾实测被遮挡。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import RecordEditDialog from '@/views/production/components/RecordEditDialog.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { DailyProductionRecord } from '@/types'

const record: DailyProductionRecord = {
  id: 1,
  department: 'filling',
  product_name: '白兔公仔',
  barcode: '6901234',
  unit_price: 7,
  quantity: 620,
  production_value: 4340,
  production_date: '2026-10-08',
  remark: '',
  created_by: '张三',
}

describe('RecordEditDialog 层级', () => {
  it('用嵌套层级，保证盖在抽屉遮罩之上', () => {
    const wrapper = mount(RecordEditDialog, { props: { open: true, record } })

    const dialog = wrapper.findComponent(UiDialog)
    expect(dialog.props('overlayZClass')).toBe('z-[var(--z-overlay-nested)]')
    expect(dialog.props('contentZClass')).toBe('z-[var(--z-modal-nested)]')
  })
})
