/**
 * BomEditor「未保存修改」确认（2026-10-17 审计 F5-5）。
 *
 * 缺陷：BOM 配置是长表单，但两个关闭入口（右上角 ✕、底部「取消」）都直接
 * `bomDialogVisible = false`，**全程没有 dirty 检查**——改完物料/角色后误触，
 * 整份修改无声消失，唯一的挽回手段是重新录一遍。
 *
 * 本测试锁定三条契约：
 * 1. 无改动 → 关闭入口直接关，不弹确认（不给日常操作添噪音）；
 * 2. 有改动 → 关闭入口先弹「放弃修改」确认；用户选「取消」时**弹窗保持打开**
 *    （确认框只是拦截器，不能顺手把 BOM 也关了）；
 * 3. dirty 判定只认「会被保存的内容」——切页签/切角色是纯视图态，不算改动；
 *    角色新增/改名是本地状态、保存才落库，必须算改动。
 *
 * ⚠️ 弹窗内容经 Teleport 渲染到 body，所以查询走 document，**不能**用
 * `stubs: { teleport: true }`：该 stub 每次父组件重渲染都会重建插槽内容，
 * 节点身份与焦点断言会假红。参照 src/test/bomEditorRoleTabs.test.ts 的既有约定。
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
        { id: 1, category: 'fabric', material_name: '面料A', specification: 'S1', unit: '码', supplier_name: '供应商甲', role_id: null },
        { id: 2, category: 'fabric', material_name: '面料B', specification: 'S2', unit: '码', supplier_name: '供应商乙', role_id: 7 },
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

interface ExposedEditor {
  open: (p: { id: number; name: string }) => Promise<void>
  bomDirty: boolean
}

let wrapper: VueWrapper | null = null

/** 打开 BOM 配置弹窗（默认 BOM 有 1 条物料 + 1 个角色「客户A」） */
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

/** BOM 弹窗本体是否还在（确认框拦截时必须保持打开） */
function bomOpen(): boolean {
  return exists('.bom-modal-dialog')
}

/** 改第一个物料的备注（模拟长表单里的一次编辑） */
async function editFirstRemark(text: string) {
  const input = qa('input[name="remark"]')[0]
  if (!input) throw new Error('未找到物料备注输入框')
  await input.setValue(text)
  await nextTick()
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('BomEditor 未保存确认：无改动时关闭不打扰', () => {
  it('打开后未做任何修改，点「取消」直接关闭且不弹确认框', async () => {
    const w = await mountOpened()
    expect(bomOpen()).toBe(true)

    await q('.bom-btn-cancel').trigger('click')
    await flushPromises()
    await nextTick()

    expect(w.findComponent(UiConfirmDialog).props('open')).toBe(false)
    expect(bomOpen()).toBe(false)
  })

  it('未做任何修改时右上角关闭按钮也直接关闭', async () => {
    const w = await mountOpened()

    await q('.bom-modal-close').trigger('click')
    await flushPromises()
    await nextTick()

    expect(w.findComponent(UiConfirmDialog).props('open')).toBe(false)
    expect(bomOpen()).toBe(false)
  })

  it('切换作用域/页签是纯视图态，不算未保存修改 → 关闭不弹确认', async () => {
    const w = await mountOpened()

    const roleTabs = qa('.bom-role-tab')
    await roleTabs[1]!.trigger('click') // 切到角色「客户A」
    await nextTick()
    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(false)

    await q('.bom-btn-cancel').trigger('click')
    await flushPromises()
    await nextTick()

    expect(w.findComponent(UiConfirmDialog).props('open')).toBe(false)
    expect(bomOpen()).toBe(false)
  })
})

describe('BomEditor 未保存确认：有改动时先确认再放弃', () => {
  it('改了物料备注后点「取消」弹出未保存确认', async () => {
    const w = await mountOpened()
    await editFirstRemark('改过的备注')
    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(true)

    await q('.bom-btn-cancel').trigger('click')
    await flushPromises()
    await nextTick()

    const confirm = w.findComponent(UiConfirmDialog)
    expect(confirm.props('open')).toBe(true)
    expect(String(confirm.props('text'))).toContain('未保存')
    // 确认框只是拦截器：此时 BOM 弹窗仍开着
    expect(bomOpen()).toBe(true)
  })

  it('确认框里选「取消」→ BOM 弹窗保持打开，修改不丢', async () => {
    const w = await mountOpened()
    await editFirstRemark('改过的备注')

    await q('.bom-btn-cancel').trigger('click')
    await flushPromises()
    await nextTick()

    w.findComponent(UiConfirmDialog).vm.$emit('cancel')
    await flushPromises()
    await nextTick()

    expect(bomOpen()).toBe(true)
    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(true)
    expect((qa('input[name="remark"]')[0]!.element as HTMLInputElement).value).toBe('改过的备注')
  })

  it('确认框里选「确认」→ BOM 弹窗关闭', async () => {
    const w = await mountOpened()
    await editFirstRemark('改过的备注')

    await q('.bom-btn-cancel').trigger('click')
    await flushPromises()
    await nextTick()

    w.findComponent(UiConfirmDialog).vm.$emit('confirm')
    await flushPromises()
    await nextTick()

    expect(bomOpen()).toBe(false)
  })

  it('右上角关闭按钮同样走未保存确认（不是绕过口）', async () => {
    const w = await mountOpened()
    await editFirstRemark('改过的备注')

    await q('.bom-modal-close').trigger('click')
    await flushPromises()
    await nextTick()

    expect(w.findComponent(UiConfirmDialog).props('open')).toBe(true)
    expect(bomOpen()).toBe(true)
  })

  it('新增角色（本地未落库）算未保存修改', async () => {
    const w = await mountOpened()
    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(false)

    await q('.bom-role-add-btn').trigger('click')
    await nextTick()
    const input = q('.bom-role-add-input')
    await input.setValue('打版')
    await input.trigger('keydown.enter')
    await nextTick()

    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(true)
  })
})

describe('BomEditor 未保存确认：保存后基线刷新', () => {
  it('保存成功后未保存标记归零（编辑基线同步到新状态）', async () => {
    const w = await mountOpened()
    await editFirstRemark('改过的备注')
    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(true)

    await q('.bom-btn-save').trigger('click')
    await flushPromises()
    await nextTick()

    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(false)
  })

  it('保存失败时未保存标记保持为真（修改确实没落库）', async () => {
    const { productApi } = await import('@/api')
    ;(productApi.saveBom as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ success: false, error: 'boom' })

    const w = await mountOpened()
    await editFirstRemark('改过的备注')

    await q('.bom-btn-save').trigger('click')
    await flushPromises()
    await nextTick()

    expect(bomOpen()).toBe(true)
    expect((w.vm as unknown as ExposedEditor).bomDirty).toBe(true)
  })
})
