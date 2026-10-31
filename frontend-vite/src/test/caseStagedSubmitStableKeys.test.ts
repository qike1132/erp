/**
 * 案例库存暂存单的批量提交：稳定行 id 与提交期锁行（2026-10-30 审计 A-M38）
 *
 * 现场：`submitBatch` 用服务端回传的 `failed.index` 直接索引 `staged.value`，
 * 再按下标过滤。只要请求在途时清单发生任何变动（删行/清空/改序），下标就对不上：
 * 成功行被留在清单里、失败行被悄悄丢掉——用户看到「部分失败」却不知道是哪几条还在。
 *
 * 修复后：提交前固定快照（key + payload），失败按 key 对回；提交期间所有改行入口
 * （删除/改数量/方向/日期/备注/清空）一律拒绝，UI 上也禁用。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  batchMovementsMock: vi.fn(),
  showToastMock: vi.fn(),
  invalidateMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  caseApi: { batchMovements: mocks.batchMovementsMock },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToastMock,
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: vi.fn(async () => true) }),
}))

vi.mock('@/types/errors', () => ({
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

vi.mock('@/utils/format', () => ({
  toISODate: () => '2026-10-30',
}))

vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateMock }),
}))

import { mount } from '@vue/test-utils'
import { useCaseStockWorkbench } from '@/views/case/composables/useCaseStockWorkbench'
import StagedCart from '@/views/case/components/StagedCart.vue'

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function seedThree(hook: ReturnType<typeof useCaseStockWorkbench>) {
  hook.addStagedBatch([
    { caseId: '1', caseName: '皮套A', isPart: false, quantity: 2 },
    { caseId: '2', caseName: '皮套B', isPart: false, quantity: 3 },
    { caseId: '3', caseName: '配件C', isPart: true, quantity: 1 },
  ])
  return hook.staged.value.map((s) => s.key)
}

describe('submitBatch 失败行按稳定 id 对回', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('服务端返回的 index 顺序无关，失败行仍精确保留', async () => {
    const hook = useCaseStockWorkbench()
    const keys = seedThree(hook)
    mocks.batchMovementsMock.mockResolvedValue({
      failed: [
        { index: 2, error: '配件库存不足' },
        { index: 0, error: '皮套A 库存不足' },
      ],
    })

    await hook.submitBatch()

    // 失败的是第 0、2 条 → 只剩它们，且顺序与清单一致
    expect(hook.staged.value.map((s) => s.key)).toEqual([keys[0], keys[2]])
    expect(hook.lastFailures.value.map((f) => f.key)).toEqual([keys[2], keys[0]])
    expect(hook.lastFailures.value.find((f) => f.key === keys[0])?.productName).toBe('皮套A')
  })

  it('提交在途时删行被拒绝，避免下标对回错位', async () => {
    const hook = useCaseStockWorkbench()
    const keys = seedThree(hook)
    const d = deferred<{ failed: { index: number; error: string }[] }>()
    mocks.batchMovementsMock.mockReturnValue(d.promise)

    const pending = hook.submitBatch()
    await hook.removeStaged(keys[0]!)
    expect(hook.staged.value).toHaveLength(3)

    d.resolve({ failed: [{ index: 1, error: '库存不足' }] })
    await pending

    // 若在途删除真生效，index=1 会对到「配件C」——这里必须是皮套B
    expect(hook.staged.value.map((s) => s.key)).toEqual([keys[1]])
    expect(hook.lastFailures.value[0]?.productName).toBe('皮套B')
  })

  it('提交在途时改数量/方向/日期/备注/清空一律无效', async () => {
    const hook = useCaseStockWorkbench()
    const keys = seedThree(hook)
    const d = deferred<{ failed: { index: number; error: string }[] }>()
    mocks.batchMovementsMock.mockReturnValue(d.promise)

    const pending = hook.submitBatch()
    hook.updateStagedQuantity(keys[0]!, 99)
    hook.updateStagedDirection(keys[0]!, 'out')
    hook.updateStagedDate(keys[0]!, '2026-01-01')
    hook.updateStagedNote(keys[0]!, 'lazy')
    hook.clearStaged()

    const first = hook.staged.value[0]!
    expect(first.quantity).toBe(2)
    expect(first.direction).toBe('in')
    expect(first.date).toBe('2026-10-30')
    expect(first.note).toBe('')
    expect(hook.staged.value).toHaveLength(3)

    d.resolve({ failed: [] })
    await pending
  })

  it('全部成功时清空清单并提示成功', async () => {
    const hook = useCaseStockWorkbench()
    seedThree(hook)
    mocks.batchMovementsMock.mockResolvedValue({ failed: [] })

    await hook.submitBatch()

    expect(hook.staged.value).toEqual([])
    expect(hook.lastFailures.value).toEqual([])
    expect(mocks.showToastMock).toHaveBeenCalledWith('提交成功，共 3 条', 'success')
  })

  it('提交完成后解除锁行，行编辑恢复可用', async () => {
    const hook = useCaseStockWorkbench()
    const keys = seedThree(hook)
    mocks.batchMovementsMock.mockResolvedValue({ failed: [{ index: 0, error: '库存不足' }] })

    await hook.submitBatch()
    expect(hook.submitting.value).toBe(false)

    hook.updateStagedQuantity(keys[0]!, 7)
    expect(hook.staged.value[0]!.quantity).toBe(7)
  })

  it('请求体取自提交快照（在途改值不会混进本次请求）', async () => {
    const hook = useCaseStockWorkbench()
    const keys = seedThree(hook)
    const d = deferred<{ failed: { index: number; error: string }[] }>()
    mocks.batchMovementsMock.mockReturnValue(d.promise)

    const pending = hook.submitBatch()
    hook.updateStagedQuantity(keys[1]!, 50)
    d.resolve({ failed: [] })
    await pending

    const payload = mocks.batchMovementsMock.mock.calls[0]![0] as { quantity: number }[]
    expect(payload.map((p) => p.quantity)).toEqual([2, 3, 1])
  })
})

describe('StagedCart 提交期锁行（渲染）', () => {
  const row = {
    key: 7,
    caseId: '1',
    caseName: '皮套A',
    isPart: false,
    direction: 'in' as const,
    date: '2026-10-30',
    quantity: 2,
    note: '',
  }

  function mountCart(submitting: boolean) {
    return mount(StagedCart, {
      props: {
        staged: [row],
        stagedTotal: 2,
        submitting,
        lastFailures: [{ index: 0, key: 7, productName: '皮套A', error: '库存不足' }],
      },
    })
  }

  it('提交中：方向/日期/备注/数量/移除全部禁用', () => {
    const wrapper = mountCart(true)

    expect(wrapper.find('.sc-dir').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.sc-remove-btn').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.sc-qty-input').attributes('disabled')).toBeDefined()
    // date + note
    expect(wrapper.findAll('.sc-item input:disabled')).toHaveLength(3)
    // 减/加两个按钮
    expect(wrapper.findAll('.sc-qty-btn:disabled')).toHaveLength(2)
  })

  it('非提交中：控件可用，提交按钮可点', () => {
    const wrapper = mountCart(false)

    expect(wrapper.find('.sc-remove-btn').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.sc-qty-input').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.sc-btn-submit').attributes('disabled')).toBeUndefined()
  })

  it('失败明细按稳定 key 渲染（同一行重复提交不会互相覆盖）', () => {
    const wrapper = mount(StagedCart, {
      props: {
        staged: [row],
        stagedTotal: 2,
        submitting: false,
        lastFailures: [
          { index: 0, key: 7, productName: '皮套A', error: '库存不足' },
          { index: 1, key: 8, productName: '皮套B', error: '日期非法' },
        ],
      },
    })

    const items = wrapper.findAll('.sc-failures li')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('皮套A')
    expect(items[1]!.text()).toContain('皮套B')
  })
})
