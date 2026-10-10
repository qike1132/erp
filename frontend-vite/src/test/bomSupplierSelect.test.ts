import { describe, it, expect, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import BomSupplierSelect from '@/views/product/components/BomSupplierSelect.vue'

/**
 * BomSupplierSelect — BOM 供应商选择框
 *
 * 覆盖：聚焦即弹出全部供应商、输入实时过滤（大小写不敏感）、
 * 点击选项回填并关闭、输入不存在名称时给出「将自动创建」提示。
 * 面板经 Teleport 渲染到 body，故查询走 document.body。
 */

const OPTIONS = [
  { id: 1, name: '广州面料有限公司' },
  { id: 2, name: '东莞辅料厂' },
  { id: 3, name: 'Guangzhou Fabric' },
]

let wrappers: VueWrapper[] = []

function mountSelect(props: Record<string, unknown> = {}) {
  const w = mount(BomSupplierSelect, {
    props: { modelValue: '', options: OPTIONS, ...props },
    attachTo: document.body,
  })
  wrappers.push(w)
  return w
}

function panelEl() {
  return document.body.querySelector('.bss-panel')
}

function optionTexts(): string[] {
  return Array.from(document.body.querySelectorAll('.bss-option')).map(
    (n) => n.textContent?.trim() ?? '',
  )
}

afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers = []
  document.body.innerHTML = ''
})

describe('BomSupplierSelect', () => {
  it('聚焦即弹出全部供应商', async () => {
    const w = mountSelect()
    await w.find('input').trigger('focus')
    await nextTick()
    expect(panelEl()).toBeTruthy()
    expect(optionTexts()).toEqual(['广州面料有限公司', '东莞辅料厂', 'Guangzhou Fabric'])
  })

  it('输入实时过滤（大小写不敏感）', async () => {
    const w = mountSelect()
    const input = w.find('input')
    await input.trigger('focus')
    await input.setValue('fabric')
    expect(optionTexts()).toEqual(['Guangzhou Fabric'])
    await input.setValue('东莞')
    expect(optionTexts()).toEqual(['东莞辅料厂'])
  })

  it('点击选项回填名称并关闭面板', async () => {
    const w = mountSelect()
    await w.find('input').trigger('focus')
    await nextTick()
    const target = document.body.querySelectorAll('.bss-option')[1] as HTMLElement
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await nextTick()
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['东莞辅料厂'])
    expect(panelEl()).toBeFalsy()
  })

  it('输入不存在的名称时提示「保存后自动创建」', async () => {
    const w = mountSelect()
    const input = w.find('input')
    await input.trigger('focus')
    await input.setValue('新供应商甲')
    expect(optionTexts()).toEqual([])
    expect(document.body.querySelector('.bss-empty')?.textContent).toContain('自动创建')
  })
})
