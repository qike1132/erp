/**
 * 「添加角色」入口与 pattern-room 对齐的回归测试。
 *
 * 对齐契约（参照 frontend-vite/src/views/pattern-room/components/RoleTabs.vue
 * 的「新增角色」形态，见 .role-tab-add / .role-tab-input 与其 onAddClick/onAddConfirm）：
 * 1. 入口 = 常驻的虚线图标方按钮（仅 + 图标，title/aria-label「新增角色」），不再内联文字；
 * 2. 点击后在按钮**右侧**追加内联输入框（按钮不消失、不被替换）；
 * 3. 输入框 placeholder「角色名称」、maxlength=100
 *    （后端 ProductRole.role_name = String(100)，见 fastapi_app/shared_models/product_material.py:85）；
 * 4. Enter / blur 确认：trim 后非空才新增角色；Esc 取消；两种收尾都清空输入；
 * 5. 提交契约不变：新增角色仍走 buildRolePayload 的 { role_key, role_name } 路径
 *    （见 src/views/product/composables/bomTypes.ts:113）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'

vi.mock('@/api', () => ({
  productApi: {
    loadBom: vi.fn().mockResolvedValue({
      success: true,
      product: { roles: [], default_bom_label: null },
      materials: [],
    }),
    saveBom: vi.fn().mockResolvedValue({ success: true }),
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchForBomCopy: vi.fn(),
  },
  supplierApi: { options: vi.fn().mockResolvedValue({ suppliers: [] }) },
}))

import BomEditor from '@/views/product/components/BomEditor.vue'
import { productApi } from '@/api'
import { cssRule, readSfc } from './support/cssRule'

interface ExposedEditor {
  open: (p: { id: number; name: string }) => Promise<void>
}

let wrapper: VueWrapper | null = null

/** 打开 BOM 配置弹窗（弹窗内容在 Teleport 内，测试里 stub 成就地渲染） */
async function mountOpened() {
  wrapper = mount(BomEditor, {
    attachTo: document.body,
    global: {
      stubs: {
        teleport: true,
        UiAutocomplete: true,
        BomCopyDialog: true,
        BomSupplierSelect: true,
      },
    },
  })
  await (wrapper.vm as unknown as ExposedEditor).open({ id: 1, name: '测试产品' })
  await nextTick()
  return wrapper
}

/** 点开「添加角色」，返回内联输入框（显式断言存在，避免索引访问的类型空洞） */
async function openAddInput(w: VueWrapper): Promise<DOMWrapper<Element>> {
  await w.find('.bom-role-add-btn').trigger('click')
  await nextTick()
  const input = w.find('.bom-role-add-input')
  if (!input.exists()) throw new Error('点击「添加角色」后未渲染 .bom-role-add-input')
  return input
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.clearAllMocks()
})

describe('BomEditor「添加角色」入口形态（对齐 pattern-room RoleTabs）', () => {
  it('入口是常驻图标方按钮：仅 + 图标，带「新增角色」title 与 aria-label', async () => {
    const w = await mountOpened()
    const btn = w.find('.bom-role-add-btn')

    expect(btn.exists()).toBe(true)
    expect(btn.attributes('title')).toBe('新增角色')
    expect(btn.attributes('aria-label')).toBe('新增角色')
    // 按钮上不再内联文字：文案只保留在 title / 空态提示里
    expect(btn.text()).toBe('')
  })

  it('输入框与按钮同处一个 wrap，且排在按钮之后（按钮不被替换）', async () => {
    const w = await mountOpened()
    expect(w.find('.bom-role-add-input').exists()).toBe(false)

    const input = await openAddInput(w)

    expect(w.find('.bom-role-add-btn').exists()).toBe(true)
    const wrap = w.find('.bom-role-add-wrap')
    expect(wrap.exists()).toBe(true)
    expect(wrap.element.children[0]).toBe(w.find('.bom-role-add-btn').element)
    expect(wrap.element.children[1]).toBe(input.element)
  })

  it('输入框口径与参照页一致：placeholder「角色名称」、maxlength=100', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)

    expect(input.attributes('placeholder')).toBe('角色名称')
    expect(input.attributes('maxlength')).toBe('100')
  })

  it('点开即聚焦输入框（键盘可直接输入）', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)

    expect(document.activeElement).toBe(input.element)
  })

  it('空态提示指向「＋」入口，不再指向已移除的文字按钮', async () => {
    const w = await mountOpened()
    const empty = w.find('.bom-role-empty')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).not.toContain('＋ 添加角色')
    expect(empty.text()).toContain('＋')
  })
})

describe('BomEditor「添加角色」交互（对齐 pattern-room RoleTabs）', () => {
  it('回车提交：trim 后新增角色、自动选中、收起并清空输入', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)

    await input.setValue('  打版  ')
    await input.trigger('keydown.enter')
    await nextTick()

    const tabs = w.findAll('.bom-role-tab')
    expect(tabs).toHaveLength(1)
    expect(tabs[0]?.text()).toContain('打版')
    expect(w.find('.bom-role-add-input').exists()).toBe(false)
  })

  it('纯空白回车不新增角色，但仍收起输入', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)

    await input.setValue('   ')
    await input.trigger('keydown.enter')
    await nextTick()

    expect(w.findAll('.bom-role-tab')).toHaveLength(0)
    expect(w.find('.bom-role-add-input').exists()).toBe(false)
  })

  it('失焦提交：与回车同口径（trim 后非空即新增）', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)

    await input.setValue('车缝')
    await input.trigger('blur')
    await nextTick()

    expect(w.findAll('.bom-role-tab')).toHaveLength(1)
    expect(w.find('.bom-role-add-input').exists()).toBe(false)
  })

  it('Esc 取消：不新增角色、收起输入；再次点开时输入为空', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)

    await input.setValue('会被丢弃')
    await input.trigger('keydown.esc')
    await nextTick()

    expect(w.findAll('.bom-role-tab')).toHaveLength(0)
    expect(w.find('.bom-role-add-input').exists()).toBe(false)

    const again = await openAddInput(w)
    expect((again.element as HTMLInputElement).value).toBe('')
  })
})

describe('BomEditor「添加角色」提交契约（接口与字段含义不变）', () => {
  it('新增角色后保存：仍走 { role_key, role_name } 的 save_bom 角色负载', async () => {
    const w = await mountOpened()
    const input = await openAddInput(w)
    await input.setValue('  打版  ')
    await input.trigger('keydown.enter')
    await nextTick()

    await w.find('.bom-btn-save').trigger('click')
    await flushPromises()

    const saveBom = productApi.saveBom as unknown as ReturnType<typeof vi.fn>
    expect(saveBom).toHaveBeenCalledTimes(1)
    const [productId, payload] = saveBom.mock.calls[0] as [number, { roles: unknown[] }]
    expect(productId).toBe(1)
    expect(payload.roles).toEqual([{ role_key: 'rk-1', role_name: '打版' }])
  })
})

describe('BomEditor「添加角色」样式对齐契约（源码声明值）', () => {
  const bomSource = readSfc('src/views/product/components/BomEditor.vue')
  const refSource = readSfc('src/views/pattern-room/components/RoleTabs.vue')

  it('添加按钮与参照页 .role-tab-add 的声明逐条一致', () => {
    expect(cssRule(bomSource, '.bom-role-add-btn')).toEqual(cssRule(refSource, '.role-tab-add'))
    expect(cssRule(bomSource, '.bom-role-add-btn:hover')).toEqual(cssRule(refSource, '.role-tab-add:hover'))
  })

  it('内联输入框与参照页 .role-tab-input 的声明逐条一致', () => {
    expect(cssRule(bomSource, '.bom-role-add-input')).toEqual(cssRule(refSource, '.role-tab-input'))
  })
})
