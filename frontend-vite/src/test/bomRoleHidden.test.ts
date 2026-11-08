/**
 * BOM 角色页签「隐藏款」指定回归测试。
 *
 * 需求：
 * 1. 右键任意角色可「指定为隐藏款」/「取消隐藏款」，结果随保存 BOM 落库；
 * 2. 每个 SKU 只允许一个隐藏款——重复指定时自动替换并提示；
 * 3. 页签徽标与保存负载（is_hidden）必须与右键操作后的状态一致。
 *
 * ⚠️ 弹窗内容经 Teleport 渲染到 body，查询走 document（同 bomEditorRoleTabs.test.ts）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'

const { saveBomMock, toastMock } = vi.hoisted(() => ({
  saveBomMock: vi.fn().mockResolvedValue({ success: true }),
  toastMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  productApi: {
    loadBom: vi.fn().mockResolvedValue({
      success: true,
      product: {
        roles: [
          { id: 7, name: '角色A', is_hidden: false },
          { id: 8, name: '角色B', is_hidden: true },
        ],
        default_bom_label: null,
      },
      materials: [
        {
          id: 1, category: 'fabric', material_name: '面料A', role_id: null,
          specification: 'S1', unit: '米', supplier_name: '供应商甲',
        },
      ],
    }),
    saveBom: saveBomMock,
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchForBomCopy: vi.fn(),
  },
  supplierApi: { options: vi.fn().mockResolvedValue({ suppliers: [] }) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: toastMock }))

import BomEditor from '@/views/product/components/BomEditor.vue'

interface ExposedEditor {
  open: (p: { id: number; name: string }) => Promise<void>
  /** 是否有未保存的 BOM 修改（关闭时据此弹「放弃修改」确认） */
  bomDirty: boolean
}

let wrapper: VueWrapper | null = null

async function mountOpened() {
  wrapper = mount(BomEditor, {
    attachTo: document.body,
    global: { stubs: { UiAutocomplete: true, BomCopyDialog: true, BomSupplierSelect: true } },
  })
  await (wrapper.vm as unknown as ExposedEditor).open({ id: 1, name: '陈列样盲盒' })
  await nextTick()
  return wrapper
}

function tabs(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('.bom-role-tab'))
}

function tabOf(name: string): HTMLElement {
  const found = tabs().find((el) => (el.textContent || '').includes(name))
  if (!found) throw new Error(`未找到角色页签：${name}`)
  return found
}

function menuItems(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('.bom-menu-item'))
    .map((el) => (el.textContent || '').trim())
}

function badgeOf(name: string): Element | null {
  return tabOf(name).querySelector('.bom-role-hidden-badge')
}

async function openMenu(name: string) {
  tabOf(name).dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 100, clientY: 100 }))
  await nextTick()
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  saveBomMock.mockClear()
  toastMock.mockClear()
})

describe('BOM 角色隐藏款指定', () => {
  it('加载后只为已指定角色显示「隐藏款」徽标', async () => {
    await mountOpened()

    expect(badgeOf('角色B')).not.toBeNull()
    expect(badgeOf('角色A')).toBeNull()
  })

  it('右键未指定角色显示「指定为隐藏款」，点击后徽标迁移并提示替换', async () => {
    await mountOpened()

    await openMenu('角色A')
    expect(menuItems()).toEqual(['重命名', '指定为隐藏款', '删除角色'])

    const item = Array.from(document.querySelectorAll<HTMLElement>('.bom-menu-item'))
      .find((el) => (el.textContent || '').trim() === '指定为隐藏款')!
    item.click()
    await nextTick()

    expect(badgeOf('角色A')).not.toBeNull()
    expect(badgeOf('角色B')).toBeNull()
    expect(toastMock).toHaveBeenCalledWith(
      '已将「角色A」设为隐藏款，原隐藏款「角色B」已自动取消', 'success',
    )
  })

  it('右键已指定角色显示「取消隐藏款」，点击后徽标消失', async () => {
    await mountOpened()

    await openMenu('角色B')
    expect(menuItems()).toEqual(['重命名', '取消隐藏款', '删除角色'])

    const item = Array.from(document.querySelectorAll<HTMLElement>('.bom-menu-item'))
      .find((el) => (el.textContent || '').trim() === '取消隐藏款')!
    item.click()
    await nextTick()

    expect(badgeOf('角色B')).toBeNull()
    expect(toastMock).toHaveBeenCalledWith('已取消「角色B」的隐藏款标记', 'success')
  })

  it('右键指定隐藏款后 bomDirty 变为 true（关闭弹窗会先确认，不会静默丢弃）', async () => {
    const w = await mountOpened()
    const vm = w.vm as unknown as ExposedEditor
    expect(vm.bomDirty).toBe(false)

    await openMenu('角色A')
    const item = Array.from(document.querySelectorAll<HTMLElement>('.bom-menu-item'))
      .find((el) => (el.textContent || '').trim() === '指定为隐藏款')!
    item.click()
    await nextTick()

    // 指定结果在保存前只是本地状态：必须计入「未保存修改」，
    // 否则关闭 BOM 弹窗不弹确认、用户以为已保存（OCR M2）
    expect(vm.bomDirty).toBe(true)
  })

  it('保存 BOM 时把 is_hidden 随角色负载一起提交（仅一个为 true）', async () => {
    await mountOpened()

    await openMenu('角色A')
    const item = Array.from(document.querySelectorAll<HTMLElement>('.bom-menu-item'))
      .find((el) => (el.textContent || '').trim() === '指定为隐藏款')!
    item.click()
    await nextTick()

    const saveBtn = Array.from(document.querySelectorAll<HTMLElement>('.bom-btn-save'))
      .find((el) => (el.textContent || '').includes('保存BOM'))!
    saveBtn.click()
    await flushPromises()

    expect(saveBomMock).toHaveBeenCalledTimes(1)
    const payload = saveBomMock.mock.calls[0]![1] as { roles: Array<Record<string, unknown>> }
    expect(payload.roles).toEqual([
      { id: 7, role_name: '角色A', is_hidden: true },
      { id: 8, role_name: '角色B', is_hidden: false },
    ])
  })
})
