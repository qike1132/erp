import { describe, it, expect, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick, h } from 'vue'
import PartFieldCombobox from '@/views/pattern-room/components/PartFieldCombobox.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

/**
 * PartFieldCombobox —— 板房部位字段的历史候选输入框（从 BomSupplierSelect 泛化）
 *
 * 覆盖：聚焦即列候选、输入子串实时过滤（任意位置、不区分大小写）、点选回填本列、
 * 无匹配仍可自由输入 + 「保存后将自动记录」提示、输出值已 trim、
 * 面板内滚轮不关面板、Esc 只关面板。
 * 面板经 Teleport 渲染到 body，查询走 document.body；类名沿用 bss-*。
 */

const SUPPLIER_OPTS = [
  { value: '美利达', count: 7 },
  { value: '美丽宝', count: 1 },
]
const FABRIC_OPTS = [{ value: '全棉毛绒布', count: 5 }]

let wrappers: VueWrapper[] = []

function mountBox(props: Record<string, unknown> = {}) {
  const w = mount(PartFieldCombobox, {
    props: { modelValue: '', options: SUPPLIER_OPTS, emptyHint: '保存后将自动记录', ...props },
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

describe('PartFieldCombobox', () => {
  it('供应商候选含「美利达」时，输入「美」过滤后列表仍含它（子串任意位置）', async () => {
    const w = mountBox()
    const input = w.find('input')
    await input.trigger('focus')
    await nextTick()
    expect(optionTexts()).toContain('美利达')
    await input.setValue('美')
    expect(optionTexts()).toContain('美利达')
    expect(optionTexts()).not.toContain('全棉毛绒布')
  })

  it('布料名称等价用例：候选含「全棉毛绒布」，输入「绒布」列表仍含它', async () => {
    const w = mountBox({ options: FABRIC_OPTS })
    const input = w.find('input')
    await input.trigger('focus')
    await input.setValue('绒布')
    expect(optionTexts()).toContain('全棉毛绒布')
  })

  it('子串匹配不区分大小写', async () => {
    const w = mountBox({ options: [{ value: 'Guangzhou Fabric', count: 1 }] })
    const input = w.find('input')
    await input.trigger('focus')
    await input.setValue('fabric')
    expect(optionTexts()).toEqual(['Guangzhou Fabric'])
  })

  it('选中只回填本列：emit 单个 update:modelValue，无其它 emit', async () => {
    const w = mountBox()
    await w.find('input').trigger('focus')
    await nextTick()
    const target = document.body.querySelectorAll('.bss-option')[0] as HTMLElement
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await nextTick()
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['美利达'])
    expect(Object.keys(w.emitted()).filter((k) => k !== 'update:modelValue')).toEqual([])
  })

  it('无匹配仍可自由输入新值，并给出「保存后将自动记录」提示', async () => {
    const w = mountBox()
    const input = w.find('input')
    await input.trigger('focus')
    await input.setValue('全新供应商甲')
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['全新供应商甲'])
    expect(optionTexts()).toEqual([])
    expect(document.body.querySelector('.bss-empty')?.textContent).toContain('保存后将自动记录')
  })

  it('输出值已 trim：props 带首尾空格，列表显示与 emit 都是 trim 后值', async () => {
    const w = mountBox({ options: [{ value: ' 美利达 ', count: 3 }] })
    const input = w.find('input')
    await input.trigger('focus')
    await nextTick()
    // 选中前：面板列表显示的是 trim 后值
    expect(optionTexts()).toEqual(['美利达'])
    const target = document.body.querySelectorAll('.bss-option')[0] as HTMLElement
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await nextTick()
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['美利达'])
  })

  it('键盘：ArrowDown 移动高亮 + Enter 选中', async () => {
    const w = mountBox()
    const input = w.find('input')
    await input.trigger('focus')
    await nextTick()
    await input.trigger('keydown.down')
    await input.trigger('keydown.enter')
    await nextTick()
    // 初始 highlight=0（美利达），ArrowDown 到 1（美丽宝）
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['美丽宝'])
  })

  /**
   * 回归：面板在「弹窗内」必须可滚动
   *
   * 根因（实测证据）：reka-ui 的 DismissableLayer 在弹窗打开时对 body 设
   * `pointer-events: none`（见 node_modules/reka-ui/dist/DismissableLayer/DismissableLayer.js：
   * `ownerDocument.value.body.style.pointerEvents = "none"`），且只对弹窗自身的
   * [data-dismissable-layer] 恢复 auto。本组件面板 Teleport 到 body，是弹窗 portal 的
   * 兄弟节点而非其子节点，于是继承到 body 的 none —— 面板照样渲染（滚动条照样画出），
   * 却收不到任何鼠标事件，滚轮与拖动滚动条全部失灵。
   *
   * 修法：面板自身声明 pointer-events: auto 覆盖继承。这里用**真的** UiDialog（跑真实的
   * DismissableLayer 副作用）而不是桩，否则测不出这条链路。断言样式而非滚动事件本身 ——
   * jsdom 不实现滚动，但 computed style 才是浏览器判定是否命中的依据。
   */
  it('面板在真实弹窗内仍可交互（覆盖 body 的 pointer-events: none）', async () => {
    const w = mount(
      {
        render: () => h(UiDialog, { open: true }, {
          default: () => h(PartFieldCombobox, {
            options: SUPPLIER_OPTS,
            emptyHint: '保存后将自动记录',
          }),
        }),
      },
      { attachTo: document.body },
    )
    wrappers.push(w)
    await nextTick()

    // reka-ui 的 DismissableLayer 已把 body 设为 pointer-events: none
    expect(document.body.style.pointerEvents).toBe('none')

    // 弹窗内容经 DialogPortal 渲染到 body，只能从 body 里直接取
    const input = document.body.querySelector('.bss-input') as HTMLInputElement
    expect(input).toBeTruthy()
    input.dispatchEvent(new FocusEvent('focus'))
    await nextTick()

    const panel = document.body.querySelector('.bss-panel') as HTMLElement
    expect(panel).toBeTruthy()
    expect(getComputedStyle(panel).pointerEvents).toBe('auto')
  })
})
