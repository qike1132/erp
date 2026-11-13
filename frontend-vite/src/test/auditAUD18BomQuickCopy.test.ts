/**
 * BOM 快速复制：整份复制语义（2026-11-13 owner 定）。
 *
 * 背景缺陷：源 SKU 的物料全部挂在角色下时（生产实例：源 21397 有 6 个角色、
 * 27 条物料，默认 BOM 为空），此前快速复制会把当前选中的目标角色透传给后端，
 * 后端「复制到角色」只搬默认作用域物料 → 复制 0 条却返回成功，前端显示
 * 「复制成功」后表格仍是「暂无物料」。
 *
 * 现在的契约：
 * - 快速复制一律整份复制（默认 BOM + 源产品全部角色及其物料），不传 role 参数；
 * - 目标已有物料或角色定义时，先做破坏性覆盖确认；
 * - 后端 400 的 detail 必须透出给用户，而不是笼统的「复制失败」。
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

function mountQuickCopy(
  confirmOverwrite: () => Promise<boolean>,
  isBusy: () => boolean = () => false,
) {
  const deps = {
    currentProductId: ref<number | null>(1),
    currentProductName: ref('目标产品'),
    reloadBom: vi.fn(async () => {}),
    isBusy,
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

describe('BOM 快速复制：整份复制与覆盖确认', () => {
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

  it('确认后执行整份复制：不传 role_id / role_name', async () => {
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm)

    await api.quickCopyBom()

    expect(confirm).toHaveBeenCalled()
    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true)
  })

  it('目标只有角色定义（无物料）→ 仍需确认（整份复制会删除目标角色）', async () => {
    mocks.loadBom.mockResolvedValue({
      success: true,
      materials: [],
      product: { roles: [{ id: 5, name: '默认' }] },
    })
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm)

    await api.quickCopyBom()

    expect(confirm).toHaveBeenCalledWith('目标产品')
    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true)
  })

  it('目标没有 BOM 时不打扰用户', async () => {
    mocks.loadBom.mockResolvedValue({ success: true, materials: [], product: { roles: [] } })
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm)

    await api.quickCopyBom()

    expect(confirm).not.toHaveBeenCalled()
    expect(mocks.copyBom).toHaveBeenCalled()
  })

  it('后端 400 detail 透出给用户（不再只剩宽泛的「复制失败」）', async () => {
    mocks.loadBom.mockResolvedValue({ success: true, materials: [], product: { roles: [] } })
    mocks.copyBom.mockRejectedValue({
      response: { status: 400, data: { detail: '源产品没有配置BOM表' } },
    })
    const { api } = mountQuickCopy(vi.fn(async () => true))

    await api.quickCopyBom()

    expect(mocks.showToast).toHaveBeenCalledWith('源产品没有配置BOM表', 'error')
  })
})

describe('BOM 快速复制：保存进行中拒绝复制（OCR 2026-10-18）', () => {
  beforeEach(() => {
    mocks.loadBom.mockReset()
    mocks.copyBom.mockReset()
    mocks.showToast.mockReset()
    mocks.loadBom.mockResolvedValue({ success: true, materials: [] })
    mocks.copyBom.mockResolvedValue({ success: true })
  })

  it('bomSaving 在途 → 不发复制请求、不弹确认', async () => {
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm, () => true)

    await api.quickCopyBom()

    expect(mocks.copyBom).not.toHaveBeenCalled()
    expect(confirm).not.toHaveBeenCalled()
    expect(mocks.showToast).toHaveBeenCalledWith('保存进行中，请稍候再复制', 'warning')
  })

  it('未在途 → 正常放行（证明上面的拦截不是恒真）', async () => {
    const confirm = vi.fn(async () => true)
    const { api } = mountQuickCopy(confirm, () => false)

    await api.quickCopyBom()

    expect(mocks.copyBom).toHaveBeenCalledWith(1, 2, true)
  })
})
