/**
 * AUD-18 回归：BOM 快速复制在默认作用域覆盖前必须二次确认（2026-10-17 审计）。
 *
 * 缺陷：快速复制把 overwrite 硬编码为 true 且全程零确认，点一下就把目标产品
 * 角色/面料/辅料/填充物四表全量删除替换，误操作不可从界面恢复。
 *
 * 2026-10-18 OCR 复评补充两条：
 * - 角色作用域（roleId / roleName）同样 overwrite=true，后端只删该角色名下的物料，
 *   需要单独确认且文案区分「该角色」vs「整个产品」；
 * - 保存进行中（bomSaving）必须拒绝发起复制（两者都是全量替换语义）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'

const mocks = vi.hoisted(() => ({
  loadBom: vi.fn(),
  copyBom: vi.fn(),
  searchProductsForBom: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/api', () => ({
  productApi: {
    loadBom: mocks.loadBom,
    copyBom: mocks.copyBom,
    searchProductsForBom: mocks.searchProductsForBom,
  },
}))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))

import { useBomQuickCopy } from '@/views/product/composables/useBomQuickCopy'
import type { Role } from '@/views/product/composables/bomTypes'

function mountQuickCopy(
  confirmOverwrite: () => Promise<boolean>,
  confirmRoleOverwrite: () => Promise<boolean> = vi.fn(async () => true),
  selectedRole: Role | null = null,
  isBusy: () => boolean = () => false,
) {
  const deps = {
    currentProductId: ref<number | null>(1),
    currentProductName: ref('目标产品'),
    reloadBom: vi.fn(async () => {}),
    selectedRole: ref(selectedRole),
    selectRoleById: vi.fn(),
    isBusy,
    confirmOverwrite,
    confirmRoleOverwrite,
  }
  const Comp = defineComponent({
    setup() {
      return { api: useBomQuickCopy(deps) }
    },
    template: '<div />',
  })
  const wrapper = mount(Comp)
  const api = wrapper.vm.api as ReturnType<typeof useBomQuickCopy>
  api.selectAutocompleteItem({ id: 2, name: '源产品' } as never)
  return { api, wrapper }
}

describe('AUD-18 BOM 快速复制覆盖确认', () => {
  beforeEach(() => {
    mocks.loadBom.mockReset()
    mocks.copyBom.mockReset()
    mocks.showToast.mockReset()
    mocks.loadBom.mockResolvedValue({ success: true, materials: [{ id: 9 }] })
    mocks.copyBom.mockResolvedValue({ success: true })
  })

  it('目标已有 BOM 且用户取消 → 不得调用复制接口', async () => {
    const confirm = vi.fn(async () => false)
    const { api } = mountQuickCopy(confirm)

    await api.quickCopyBom()

    expect(mocks.loadBom).toHaveBeenCalledWith(1)
    expect(confirm).toHaveBeenCalledWith('目标产品')
    expect(mocks.copyBom).not.toHaveBeenCalled()
  })

  it('用户确认后才执行覆盖复制', async () => {
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm)

    await api.quickCopyBom()

    expect(confirm).toHaveBeenCalled()
    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true, null, null)
  })

  it('目标没有 BOM 时不打扰用户', async () => {
    mocks.loadBom.mockResolvedValue({ success: true, materials: [] })
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm)

    await api.quickCopyBom()

    expect(confirm).not.toHaveBeenCalled()
    expect(mocks.copyBom).toHaveBeenCalled()
  })
})

describe('AUD-18 BOM 快速复制：角色作用域覆盖确认（OCR 2026-10-18）', () => {
  beforeEach(() => {
    mocks.loadBom.mockReset()
    mocks.copyBom.mockReset()
    mocks.showToast.mockReset()
    mocks.loadBom.mockResolvedValue({
      success: true,
      materials: [{ id: 9, category: 'fabric', name: '面料A', role_id: 5 }],
      product: { roles: [{ id: 5, name: '大货' }] },
    })
    mocks.copyBom.mockResolvedValue({ success: true, target_role: { id: 5, name: '大货' } })
  })

  it('角色作用域已有物料 → 走角色确认（文案带角色名），不走产品级确认', async () => {
    const confirmProduct = vi.fn(async () => true)
    const confirmRole = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirmProduct, confirmRole, { id: 5, name: '大货' })

    await api.quickCopyBom()

    expect(confirmProduct).not.toHaveBeenCalled()
    expect(confirmRole).toHaveBeenCalledWith('大货')
    // 确认后仍按原参数复制到该角色
    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true, 5, null)
  })

  it('角色确认被拒绝 → 不调用复制接口', async () => {
    const confirmRole = vi.fn(async () => false)
    const { api } = mountQuickCopy(vi.fn(async () => true), confirmRole, { id: 5, name: '大货' })

    await api.quickCopyBom()

    expect(mocks.copyBom).not.toHaveBeenCalled()
  })

  it('该角色下没有物料 → 不打扰用户（其他角色的物料不算）', async () => {
    mocks.loadBom.mockResolvedValue({
      success: true,
      materials: [{ id: 8, category: 'fabric', name: '面料B', role_id: 6 }],
      product: { roles: [{ id: 6, name: '其他' }] },
    })
    const confirmRole = vi.fn(async () => true)
    const { api } = mountQuickCopy(vi.fn(async () => true), confirmRole, { id: 5, name: '大货' })

    await api.quickCopyBom()

    expect(confirmRole).not.toHaveBeenCalled()
    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true, 5, null)
  })

  it('新建未保存角色（roleName）：后端按名命中已有角色定义时也要确认', async () => {
    const confirmRole = vi.fn(async () => true)
    const { api } = mountQuickCopy(vi.fn(async () => true), confirmRole, { role_key: 'rk-1', name: '大货' })

    await api.quickCopyBom()

    expect(confirmRole).toHaveBeenCalledWith('大货')
    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true, null, '大货')
  })
})

describe('AUD-18 BOM 快速复制：保存进行中拒绝复制（OCR 2026-10-18）', () => {
  beforeEach(() => {
    mocks.loadBom.mockReset()
    mocks.copyBom.mockReset()
    mocks.showToast.mockReset()
    mocks.loadBom.mockResolvedValue({ success: true, materials: [] })
    mocks.copyBom.mockResolvedValue({ success: true })
  })

  it('bomSaving 在途 → 不发复制请求、不弹确认', async () => {
    const confirmProduct = vi.fn(async () => true)
    const confirmRole = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirmProduct, confirmRole, null, () => true)

    await api.quickCopyBom()

    expect(mocks.copyBom).not.toHaveBeenCalled()
    expect(confirmProduct).not.toHaveBeenCalled()
    expect(confirmRole).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('保存进行中，请稍候再复制', 'warning')
  })

  it('未在途 → 正常放行（证明上面的拦截不是恒真）', async () => {
    const confirmProduct = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirmProduct, vi.fn(async () => true), null, () => false)

    await api.quickCopyBom()

    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true, null, null)
  })
})
