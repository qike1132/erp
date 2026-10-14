/**
 * BOM 配置弹窗「角色页签」与 pattern-room 对齐的回归测试。
 *
 * 用户反馈：① 添加角色后的页签颜色要与参照页一致；② 删除角色要改成
 * 「右键点角色 → 弹出删除角色」。
 *
 * 对齐契约（参照 frontend-vite/src/views/pattern-room/components/RoleTabs.vue）：
 * 1. 页签外观 = .role-tab / .role-tab--active（白底描边 → 蓝色渐变选中），
 *    默认BOM 页签不再有独立的虚线/灰色规则；
 * 2. 删除入口 = 右键菜单（.role-tab-menu / .role-tab-menu-item.danger「删除角色」），
 *    页签上不再有「⋯」按钮；键盘 Shift+F10 同样可打开；
 * 3. 菜单随视口变化/Esc 关闭，视口过小时坐标兜底 8px，键盘路径归还焦点；
 * 4. 既有功能不丢：菜单保留「重命名」；默认BOM 页签不可删除；删除仍走原确认弹窗。
 *
 * ⚠️ 弹窗内容经 Teleport 渲染到 body，所以查询走 document，**不能**用
 * `stubs: { teleport: true }`：该 stub 每次父组件重渲染都会重建插槽内容，
 * 节点身份与焦点断言会假红（实测 .bom-role-label 也会被判为「新节点」）。
 * 参照 src/test/patternRoomPrint.test.ts:81 的既有约定。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { DOMWrapper, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'

vi.mock('@/api', () => ({
  productApi: {
    loadBom: vi.fn().mockResolvedValue({
      success: true,
      product: { roles: [{ id: 7, name: '客户A' }], default_bom_label: null },
      materials: [
        { id: 1, category: 'fabric', material_name: '面料A', role_id: null },
        { id: 2, category: 'fabric', material_name: '面料B', role_id: 7 },
      ],
    }),
    saveBom: vi.fn().mockResolvedValue({ success: true }),
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchForBomCopy: vi.fn(),
  },
  supplierApi: { options: vi.fn().mockResolvedValue({ suppliers: [] }) },
}))

import BomEditor from '@/views/product/components/BomEditor.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { cssRule, readSfc } from './support/cssRule'

interface ExposedEditor {
  open: (p: { id: number; name: string }) => Promise<void>
}

let wrapper: VueWrapper | null = null

/** 打开 BOM 配置弹窗：默认BOM（有物料）+ 1 个角色「客户A」→ 2 个页签 */
async function mountOpened() {
  wrapper = mount(BomEditor, {
    attachTo: document.body,
    global: { stubs: { UiAutocomplete: true, BomCopyDialog: true, BomSupplierSelect: true } },
  })
  await (wrapper.vm as unknown as ExposedEditor).open({ id: 1, name: '测试产品' })
  await nextTick()
  return wrapper
}

/** 弹窗内容在 Teleport 里 → 查询走 document */
function q(selector: string): DOMWrapper<Element> {
  const el = document.querySelector(selector)
  if (!el) throw new Error(`未找到 ${selector}`)
  return new DOMWrapper(el)
}

function qa(selector: string): DOMWrapper<Element>[] {
  return [...document.querySelectorAll(selector)].map((el) => new DOMWrapper(el))
}

function exists(selector: string): boolean {
  return document.querySelector(selector) !== null
}

/** 取第 index 个角色页签（显式断言存在，避免索引访问的类型空洞） */
function tabAt(index: number): DOMWrapper<Element> {
  const tabs = qa('.bom-role-tab')
  const tab = tabs[index]
  if (!tab) throw new Error(`角色页签缺失: index=${index}`)
  return tab
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('BomEditor 角色页签：删除入口改为右键菜单（对齐 RoleTabs）', () => {
  it('页签上不再渲染「⋯」按钮，管理入口只在右键菜单里', async () => {
    await mountOpened()
    expect(qa('.bom-role-tab')).toHaveLength(2)
    expect(qa('.bom-role-more')).toHaveLength(0)
    expect(exists('.bom-role-menu')).toBe(false)
  })

  it('右键角色页签弹出菜单，含 danger 项「删除角色」与「重命名」', async () => {
    await mountOpened()
    await tabAt(1).trigger('contextmenu')

    const menu = q('.bom-role-menu')
    expect(menu.attributes('role')).toBe('menu')
    expect(qa('.bom-menu-item').map((i) => i.text().trim())).toEqual(['重命名', '删除角色'])
    expect(q('.bom-menu-item.danger').text()).toContain('删除角色')
  })

  it('默认BOM 页签的菜单只有「重命名」，不提供删除（产品级不可删）', async () => {
    await mountOpened()
    await tabAt(0).trigger('contextmenu')

    expect(qa('.bom-menu-item').map((i) => i.text().trim())).toEqual(['重命名'])
    expect(exists('.bom-menu-item.danger')).toBe(false)
  })

  it('点「删除角色」走原确认弹窗，确认后页签与其物料作用域一并移除', async () => {
    const w = await mountOpened()
    await tabAt(1).trigger('contextmenu')
    await q('.bom-menu-item.danger').trigger('click')

    const confirm = w.findComponent(UiConfirmDialog)
    expect(confirm.props('open')).toBe(true)
    expect(String(confirm.props('text'))).toContain('客户A')

    confirm.vm.$emit('confirm')
    await flushPromises()
    await nextTick()

    expect(qa('.bom-role-tab')).toHaveLength(1)
    expect(tabAt(0).text()).toContain('默认BOM')
  })

  it('左键点击页签只切换作用域，不弹菜单', async () => {
    await mountOpened()
    await tabAt(1).trigger('click')
    await nextTick()

    expect(exists('.bom-role-menu')).toBe(false)
    expect(tabAt(1).classes()).toContain('active')
  })
})

describe('BomEditor 角色页签：菜单健壮性与键盘可达（对齐 RoleTabs）', () => {
  it('Shift+F10 打开菜单、焦点落首个菜单项、Esc 关闭并归还焦点', async () => {
    await mountOpened()
    const tab = tabAt(1)

    await tab.trigger('keydown', { key: 'F10', shiftKey: true })
    await nextTick()

    const item = q('.bom-menu-item')
    expect(document.activeElement).toBe(item.element)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()

    expect(exists('.bom-role-menu')).toBe(false)
    expect(document.activeElement).toBe(tab.element)
  })

  it('resize 与 scroll 都会关闭菜单（避免菜单与页签错位）', async () => {
    await mountOpened()
    await tabAt(1).trigger('contextmenu')
    expect(exists('.bom-role-menu')).toBe(true)
    window.dispatchEvent(new Event('resize'))
    await nextTick()
    expect(exists('.bom-role-menu')).toBe(false)

    await tabAt(1).trigger('contextmenu')
    expect(exists('.bom-role-menu')).toBe(true)
    window.dispatchEvent(new Event('scroll'))
    await nextTick()
    expect(exists('.bom-role-menu')).toBe(false)
  })

  it('视口小于菜单尺寸时坐标兜底 8px，不出现负坐标', async () => {
    const innerWidth = vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(100)
    const innerHeight = vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(40)
    try {
      await mountOpened()
      await tabAt(1).trigger('contextmenu', { clientX: 500, clientY: 500 })

      const style = q('.bom-role-menu').attributes('style') ?? ''
      expect(style).toContain('left: 8px')
      expect(style).toContain('top: 8px')
    } finally {
      innerWidth.mockRestore()
      innerHeight.mockRestore()
    }
  })

  it('取消删除后角色仍在，菜单已收起（不对不存在的角色动手）', async () => {
    const w = await mountOpened()
    await tabAt(1).trigger('contextmenu')
    await q('.bom-menu-item.danger').trigger('click')

    w.findComponent(UiConfirmDialog).vm.$emit('cancel')
    await flushPromises()
    await nextTick()

    expect(exists('.bom-role-menu')).toBe(false)
    expect(qa('.bom-role-tab')).toHaveLength(2)
  })

  it('页签可键盘聚焦，Enter/Space 能切换作用域（div 页签需显式补键盘行为）', async () => {
    await mountOpened()
    expect(tabAt(1).attributes('tabindex')).toBe('0')

    await tabAt(1).trigger('keydown', { key: 'Enter' })
    await nextTick()
    expect(tabAt(1).classes()).toContain('active')

    await tabAt(0).trigger('keydown', { key: ' ' })
    await nextTick()
    expect(tabAt(0).classes()).toContain('active')
    expect(tabAt(1).classes()).not.toContain('active')
  })

  it('重命名输入框：空格不被页签快捷键吞掉，maxlength 与参照页/后端口径一致', async () => {
    await mountOpened()
    await tabAt(1).trigger('contextmenu')
    await nextTick()
    await qa('.bom-menu-item')[0]!.trigger('click')
    await flushPromises()
    await nextTick()

    const input = q('.bom-role-edit-input')

    // 页签的 keydown 监听挂在 div 上，input 的按键会冒泡上去。参照页 RoleTabs 的页签是
    // button、内部永远没有 input，所以那边不需要放行；这里若不放行，空格会被
    // preventDefault 吞掉，「裁床 1 组」这类含空格的角色名根本输不进去。
    const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })
    input.element.dispatchEvent(space)
    expect(space.defaultPrevented).toBe(false)

    await input.setValue('裁床 1 组')
    expect((input.element as HTMLInputElement).value).toBe('裁床 1 组')

    // 后端 ProductRole.role_name 是 String(100)，参照页 RoleTabs.vue 也是 100：
    // 改名输入框若停在 50，长角色名会在前端被悄悄截断。
    expect(input.attributes('maxlength')).toBe('100')
  })
})

describe('BomEditor 角色页签：颜色与参照页一致（源码声明值）', () => {
  const bom = readSfc('src/views/product/components/BomEditor.vue')
  const ref = readSfc('src/views/pattern-room/components/RoleTabs.vue')

  it('页签本体/悬停/选中/聚焦态与 .role-tab 系列逐条一致', () => {
    const pairs: [string, string][] = [
      ['.bom-role-tab', '.role-tab'],
      ['.bom-role-tab:hover', '.role-tab:hover'],
      ['.bom-role-tab.active', '.role-tab--active'],
      ['.bom-role-tab.active:hover', '.role-tab--active:hover'],
      ['.bom-role-tab:focus-visible', '.role-tab:focus-visible'],
    ]
    for (const [mine, theirs] of pairs) {
      expect(cssRule(bom, mine), `${mine} 应与 ${theirs} 逐条一致`).toEqual(cssRule(ref, theirs))
    }
  })

  it('右键菜单容器/遮罩/菜单项与 .role-tab-menu 系列逐条一致', () => {
    const pairs: [string, string][] = [
      ['.bom-role-menu', '.role-tab-menu'],
      ['.bom-role-menu-mask', '.role-tab-menu-mask'],
      ['.bom-menu-item', '.role-tab-menu-item'],
      ['.bom-menu-item.danger', '.role-tab-menu-item.danger'],
      ['.bom-menu-item.danger:hover', '.role-tab-menu-item.danger:hover'],
      ['.bom-menu-item:focus-visible', '.role-tab-menu-item:focus-visible'],
    ]
    for (const [mine, theirs] of pairs) {
      expect(cssRule(bom, mine), `${mine} 应与 ${theirs} 逐条一致`).toEqual(cssRule(ref, theirs))
    }
  })

  it('默认BOM 页签不再有独立颜色类（颜色与角色页签统一）', async () => {
    await mountOpened()
    const defaultTab = tabAt(0)
    expect(defaultTab.classes()).not.toContain('default-tab')
    // 去掉 active 后，默认页签与角色页签的类名集合一致 → 走同一套颜色规则
    const strip = (c: string[]) => c.filter((x) => x !== 'active').sort()
    expect(strip(defaultTab.classes())).toEqual(strip(tabAt(1).classes()))
  })
})
