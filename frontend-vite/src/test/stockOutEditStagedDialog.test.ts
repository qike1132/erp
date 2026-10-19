/**
 * StockOutEditStagedDialog — saving 态呈现与关闭拦截（2026-10-19 OCR-4 Low×2）。
 *
 * 既有 stockOutTabEditBatchGate / stockOutTabOcrWiring 测试都把本组件 stub 掉，
 * saving 的 UI 层防线没有任何用例兜底，这里直接 mount 组件锁两层：
 *  1) 呈现层：saving=true 时页脚取消/保存按钮均 disabled，主按钮文案「保存中…」
 *  2) 关闭拦截：saving=true 时 UiDialog 发起的 update:open=false（✕ 与 Esc 同链路）
 *     必须被拦下不上报父级——否则在途保存被关掉后结果静默落暂存行，用户无从感知；
 *     且「取消」被禁用而 ✕ 能关，两条退出路径语义分裂。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, reactive } from 'vue'

import StockOutEditStagedDialog from '@/views/stock/components/StockOutEditStagedDialog.vue'

/** UiDialog 替身：点击触发与 ✕（DialogClose）/ Esc 完全相同的 update:open=false 链路 */
const UiDialogStub = defineComponent({
  name: 'UiDialog',
  props: { open: { type: Boolean, default: false } },
  emits: ['update:open'],
  template:
    '<div><button class="stub-close" @click="$emit(\'update:open\', false)">close</button><slot /><slot name="footer" /></div>',
})

/** UiButton 替身：透传 disabled（断言目标） */
const UiButtonStub = defineComponent({
  name: 'UiButton',
  props: { disabled: { type: Boolean, default: false }, variant: { type: String, default: '' } },
  template: '<button :disabled="disabled"><slot /></button>',
})

function mountDialog(saving: boolean) {
  const form = reactive({ customer: '客户甲', date: '2026-10-19', productName: '产品A', quantity: 2, note: '' })
  return mount(StockOutEditStagedDialog, {
    props: { open: true, form, customerOptions: [], saving },
    global: {
      stubs: { UiDialog: UiDialogStub, UiButton: UiButtonStub, UiDatePicker: true, UiSelect: true, UiInput: true },
    },
  })
}

describe('StockOutEditStagedDialog — saving 态（OCR-4 Low×2）', () => {
  it('呈现层：saving=true 时取消/保存按钮均禁用，主按钮文案「保存中…」', () => {
    const wrapper = mountDialog(true)
    const buttons = wrapper.findAll('button')
    expect(buttons).toHaveLength(3) // stub-close + 取消 + 保存
    const cancelBtn = buttons[1]!
    const saveBtn = buttons[2]!
    expect(cancelBtn.attributes('disabled')).toBeDefined()
    expect(saveBtn.attributes('disabled')).toBeDefined()
    expect(saveBtn.text()).toBe('保存中…')
  })

  it('呈现层对照：非 saving 时按钮可用，主按钮文案「保存」', () => {
    const wrapper = mountDialog(false)
    const buttons = wrapper.findAll('button')
    const cancelBtn = buttons[1]!
    const saveBtn = buttons[2]!
    expect(cancelBtn.attributes('disabled')).toBeUndefined()
    expect(saveBtn.attributes('disabled')).toBeUndefined()
    expect(saveBtn.text()).toBe('保存')
  })

  it('关闭拦截：saving=true 时 ✕/Esc 路径的 update:open=false 被拦，不上报父级', async () => {
    const wrapper = mountDialog(true)
    await wrapper.find('.stub-close').trigger('click')
    expect(wrapper.emitted('update:open')).toBeUndefined()
  })

  it('关闭放行：非 saving 时关闭路径正常上报 update:open=false', async () => {
    const wrapper = mountDialog(false)
    await wrapper.find('.stub-close').trigger('click')
    expect(wrapper.emitted('update:open')).toEqual([[false]])
  })
})