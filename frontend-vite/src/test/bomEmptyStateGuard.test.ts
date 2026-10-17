/**
 * BOM 空态护栏（2026-10-17 审计 F-FE-WS-A-01）
 *
 * 原实现：loadBomData 失败只 toast，编辑基线已被清成空集，saveBom 仍可提交；
 * 后端「全量替换」语义下空 payload = 删光该 SKU 整张 BOM。
 * 修复后：
 *  1) 读失败（异常或 success=false）置 bomLoadFailed，saveBom 直接拒绝；
 *  2) 读成功但提交空集且库中已有物料 → 强制 danger 二次确认；
 *  3) 读成功正常保存不受影响。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const loadBom = vi.fn()
const saveBom = vi.fn()
const supplierOptions = vi.fn()

vi.mock('@/api', () => ({
  productApi: {
    loadBom: (...a: unknown[]) => loadBom(...a),
    saveBom: (...a: unknown[]) => saveBom(...a),
  },
  supplierApi: {
    options: (...a: unknown[]) => supplierOptions(...a),
  },
}))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import { useProductListActions } from '@/views/product/composables/useProductListActions'
import type { ConfirmDialogLike } from '@/views/product/composables/bomTypes'

function makeConfirm(ok: boolean) {
  return { confirm: vi.fn().mockResolvedValue(ok) } as unknown as ConfirmDialogLike & { confirm: ReturnType<typeof vi.fn> }
}

const loadedOk = {
  success: true,
  product: { roles: [], default_bom_label: null },
  materials: [{
    id: 1, category: 'fabric', name: '面料A', material_name: '面料A',
    specification: 'S', unit: '码', unit_usage: 2, quantity: 2,
    supplier_id: 1, supplier_name: '供应商甲', role_id: null, remark: '',
  }],
}

describe('BOM 空态护栏', () => {
  beforeEach(() => {
    loadBom.mockReset()
    saveBom.mockReset().mockResolvedValue({ success: true })
    supplierOptions.mockReset().mockResolvedValue({ data: [] })
  })

  it('读失败后 saveBom 被拒绝，不发起保存请求', async () => {
    loadBom.mockRejectedValue(new Error('network'))
    const confirm = makeConfirm(true)
    const actions = useProductListActions(confirm)
    await actions.openBomModal({ id: 7, name: 'P7' })
    await actions.saveBom()
    expect(saveBom).not.toHaveBeenCalled()
    expect(confirm.confirm).not.toHaveBeenCalled()
  })

  it('success=false 同样拒绝保存', async () => {
    loadBom.mockResolvedValue({ success: false, detail: 'boom' })
    const confirm = makeConfirm(true)
    const actions = useProductListActions(confirm)
    await actions.openBomModal({ id: 7, name: 'P7' })
    await actions.saveBom()
    expect(saveBom).not.toHaveBeenCalled()
  })

  it('删光已有物料的行再保存：弹 danger 确认，用户拒绝则不提交', async () => {
    loadBom.mockResolvedValue(loadedOk)
    let ok = true
    const confirm = { confirm: vi.fn(async () => ok) }
    const actions = useProductListActions(confirm as unknown as ConfirmDialogLike)
    await actions.openBomModal({ id: 7, name: 'P7' })
    await actions.deleteBomItem(0) // 删光唯一一行（行删除确认放行）
    ok = false                     // 保存前的「空覆盖非空」确认拒绝
    await actions.saveBom()
    expect(saveBom).not.toHaveBeenCalled()
    // deleteBomItem 一次 + saveBom 复查一次
    expect(confirm.confirm).toHaveBeenCalledTimes(2)
  })

  it('删光后保存且用户确认：允许提交', async () => {
    loadBom.mockResolvedValue(loadedOk)
    const confirm = { confirm: vi.fn(async () => true) }
    const actions = useProductListActions(confirm as unknown as ConfirmDialogLike)
    await actions.openBomModal({ id: 7, name: 'P7' })
    await actions.deleteBomItem(0)
    await actions.saveBom()
    expect(saveBom).toHaveBeenCalledTimes(1)
  })

  it('正常加载 + 正常保存：提交不受护栏影响', async () => {
    loadBom.mockResolvedValue(loadedOk)
    const confirm = makeConfirm(true)
    const actions = useProductListActions(confirm)
    await actions.openBomModal({ id: 7, name: 'P7' })
    await actions.saveBom()
    expect(saveBom).toHaveBeenCalledTimes(1)
  })
})
