/**
 * BomEditor 的「删除」确认框是从 BOM 配置弹窗里弹出的。
 *
 * 弹窗遮罩 .pd-overlay 的 z-index 是**硬编码 1050**（见 BomEditor.vue 样式），
 * 远高于 UiConfirmDialog 的 token 默认（--z-overlay=30 / --z-modal=40），
 * 于是确认框被弹窗压住 —— 用户实测：点删除弹出的 UI 被 BOM 配置 UI 遮挡、看不见也点不到。
 *
 * 修法与既有嵌套弹窗（RecordEditDialog / ReceiveDialog / 生产明细抽屉）一致：
 * 显式传 --z-overlay-nested/-modal-nested（2200/2210，均 > 1050，且 > PrimeVue 2100）。
 */
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  productApi: {
    loadBom: vi.fn(),
    saveBom: vi.fn(),
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchForBomCopy: vi.fn(),
  },
  supplierApi: { options: vi.fn().mockResolvedValue({ suppliers: [] }) },
}))

vi.mock('@/api/role', () => ({
  roleApi: { rename: vi.fn(), list: vi.fn().mockResolvedValue({ roles: [] }) },
  RoleApiError: class RoleApiError extends Error {},
}))

import BomEditor from '@/views/product/components/BomEditor.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'

function mountEditor() {
  return mount(BomEditor, {
    global: {
      stubs: {
        UiAutocomplete: true,
        BomCopyDialog: true,
        BomRolePicker: true,
        BomSupplierSelect: true,
        FontAwesomeIcon: true,
      },
    },
  })
}

describe('BomEditor 删除确认框层级', () => {
  it('用嵌套层级，保证盖在 BOM 配置弹窗（z-index 1050）之上', () => {
    const wrapper = mountEditor()
    const confirm = wrapper.findComponent(UiConfirmDialog)

    expect(confirm.exists()).toBe(true)
    expect(confirm.props('overlayZClass')).toBe('z-[var(--z-overlay-nested)]')
    expect(confirm.props('contentZClass')).toBe('z-[var(--z-modal-nested)]')
  })
})
