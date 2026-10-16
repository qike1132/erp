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

  /**
   * 回归（OCR finding 2026-10-16）：options 异步缩短后 highlight 可能越界，
   * 旧实现 `filtered.value[highlight.value]!` 用非空断言把真实的 undefined 藏起来，
   * Enter 时 choose(undefined) → displayOf 抛 TypeError。修法：用 min 夹住索引。
   */
  it('回归：options 缩短致 highlight 越界时，Enter 夹到有效项、不抛错', async () => {
    const w = mountBox({
      options: [
        { value: 'A', count: 1 },
        { value: 'B', count: 1 },
        { value: 'C', count: 1 },
      ],
    })
    const input = w.find('input')
    await input.trigger('focus')
    await nextTick()
    await input.trigger('keydown.down')
    await input.trigger('keydown.down') // highlight = 2
    await w.setProps({ options: [{ value: 'A', count: 1 }] }) // filtered 缩到 1，highlight 仍为 2
    await nextTick()
    await input.trigger('keydown.enter') // 越界：应夹到 index 0
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['A'])
  })

  /**
   * 回归（OCR finding 2026-10-16）：面板此前只由 Esc / 外部 mousedown / 滚动 / resize 关闭，
   * 无 @blur —— 键盘 Tab 移走焦点（不触发 mousedown）时面板不关，多行会各自叠开。
   */
  it('回归：焦点离开输入框（blur）即关面板', async () => {
    const w = mountBox()
    const input = w.find('input')
    await input.trigger('focus')
    await nextTick()
    expect(panelEl()).toBeTruthy()
    await input.trigger('blur')
    await nextTick()
    expect(panelEl()).toBeFalsy()
  })

  /**
   * 回归（队友转交的 OCR Medium #1）：Esc 此前用 `@keydown.esc.stop` 无条件 stopPropagation，
   * 不只面板打开时。面板已关后再按 Esc 被本组件吞掉 → 宿主 reka-ui UiDialog 的
   * DismissableLayer 收不到 Esc，弹窗再也没法用键盘关。
   */
  it('Esc 只在本组件面板打开时拦截，否则放行给宿主', async () => {
    const w = mountBox()
    const input = w.find('input')

    // 用一个祖先监听器模拟宿主 reka-ui DismissableLayer 的 Esc 处理
    const hostSaw: string[] = []
    const onHostEsc = (e: Event) => hostSaw.push((e as KeyboardEvent).key)
    document.body.addEventListener('keydown', onHostEsc)

    // 面板已关：Esc 必须放行，宿主收得到
    input.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await nextTick()
    expect(hostSaw).toEqual(['Escape'])

    // 面板开着：Esc 必须被本组件消费，不冒泡到宿主（否则会连带关掉整个弹窗）
    await input.trigger('focus')
    await nextTick()
    expect(panelEl()).toBeTruthy()
    input.element.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await nextTick()
    expect(panelEl()).toBeFalsy()
    expect(hostSaw).toEqual(['Escape'])  // 仍然只有面板关着那一次

    document.body.removeEventListener('keydown', onHostEsc)
  })

  /**
   * 回归（队友转交的 OCR Medium #2）：面板恒定位到 input.bottom+4，无视口边界。
   * input 靠近视口底部时 fixed 面板整体落在视口外，而滚动又会关面板 →
   * 选项既看不见也滚不到。此处用 getBoundingClientRect 桩让 input 贴在视口底部。
   */
  it('input 靠近视口底部时面板翻到上方，且不超出视口', async () => {
    const w = mountBox()
    const input = w.find('input')
    // 让 input 落在视口最底部（jsdom 视口默认 768 高）
    input.element.getBoundingClientRect = () =>
      ({ top: 700, bottom: 740, left: 10, right: 210, width: 200, height: 40 }) as DOMRect
    await input.trigger('focus')
    await nextTick()

    const panel = panelEl() as HTMLElement
    expect(panel).toBeTruthy()
    const top = Number.parseFloat(panel.style.top)
    // 面板 top 必须为负或不小于 input.bottom —— 即翻到 input 上方，而不是 744 视口外
    expect(top).toBeLessThan(740)
    expect(top).toBeGreaterThanOrEqual(0)
    // max-height 被夹住：面板底边不越过视口底部
    expect(Number.parseFloat(panel.style.maxHeight)).toBeLessThanOrEqual(768)
  })

  /**
   * 回归（队友转交的 OCR Medium #3）：choose() 是程序化赋值，原生 maxlength 只挡手输。
   * 后端 BatchPartItem.supplier_name 上限 100，而 PartUpdateRequest.supplier_name 上限 200
   * （前端 formMaxlength=100 / inlineMaxlength=200 忠实反映了这个不一致）。
   * 行内编辑存下的 101–200 字供应商名会成为候选，在批量弹窗里选中就写入一个
   * 手输永远达不到的值 → 提交 422（string_too_long），用户无法解释。
   */
  it('选中候选时夹到 maxlength，避免程序化写入超出上限的值', async () => {
    const LONG = '甲'.repeat(150)
    const w = mountBox({ options: [{ value: LONG, count: 2 }], maxlength: 100 })
    await w.find('input').trigger('focus')
    await nextTick()
    const target = document.body.querySelectorAll('.bss-option')[0] as HTMLElement
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await nextTick()
    const emitted = w.emitted('update:modelValue')?.at(-1)?.[0] as string
    expect(emitted).toHaveLength(100)
    expect(emitted).toBe('甲'.repeat(100))
  })
})
