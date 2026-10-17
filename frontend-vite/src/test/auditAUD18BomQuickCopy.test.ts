/**
 * AUD-18 回归：BOM 快速复制在默认作用域覆盖前必须二次确认（2026-10-17 审计）。
 *
 * 缺陷：快速复制把 overwrite 硬编码为 true 且全程零确认，点一下就把目标产品
 * 角色/面料/辅料/填充物四表全量删除替换，误操作不可从界面恢复。
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

function mountQuickCopy(confirmOverwrite: () => Promise<boolean>) {
  const deps = {
    currentProductId: ref<number | null>(1),
    currentProductName: ref('目标产品'),
    reloadBom: vi.fn(async () => {}),
    selectedRole: ref(null),
    selectRoleById: vi.fn(),
    confirmOverwrite,
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
