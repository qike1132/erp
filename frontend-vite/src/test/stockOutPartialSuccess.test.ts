/**
 * 出货批量提交「部分成功只移除已入库行」守卫
 * （2026-10-17 审计 F-FE-DESK-CORE-01）
 *
 * 原实现部分成功分支不清暂存区，重新提交会把已入库的行再提交一次 → 重复出库。
 * 修复后：results 与暂存行严格对位时只移除成功行；对不上时保守保留全部并提示人工核对。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const batchSubmitStockouts = vi.fn()
const availableShipment = vi.fn()

vi.mock('@/api', () => ({
  stockApi: {
    batchSubmitStockouts: (...a: unknown[]) => batchSubmitStockouts(...a),
    availableShipment: (...a: unknown[]) => availableShipment(...a),
  },
}))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import { useStockOutActions } from '@/views/stock/composables/useStockOutActions'

function stagedItem(over: Record<string, unknown> = {}) {
  return {
    id: 1, product_id: '11', product_name: 'P', customer: '客户A',
    date: '2026-10-16', quantity: 5, note: '', ...over,
  }
}

describe('出货批量提交部分成功处理', () => {
  beforeEach(() => {
    batchSubmitStockouts.mockReset()
    availableShipment.mockReset().mockResolvedValue({ data: { available_quantity: 9999 } })
  })

  it('部分成功：只移除成功行，失败行留在暂存区', async () => {
    const a = stagedItem({ product_id: '1' })
    const b = stagedItem({ product_id: '2' })
    const staged = ref([a, b])
    batchSubmitStockouts.mockResolvedValue({
      success: true,
      results: [{ success: true }, { success: false, error: '批次余量不足' }],
    })
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    expect(staged.value).toHaveLength(1)
    // ref 会把元素包成 reactive 代理，按字段比对而非引用
    expect(staged.value[0]?.product_id).toBe('2')
  })

  it('全部成功：清空暂存（原有行为不回归）', async () => {
    const staged = ref([stagedItem(), stagedItem()])
    batchSubmitStockouts.mockResolvedValue({
      success: true,
      results: [{ success: true }, { success: true }],
    })
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    expect(staged.value).toHaveLength(0)
  })

  it('结果数与暂存数不一致：保守保留全部并提示对齐失败', async () => {
    const staged = ref([stagedItem(), stagedItem()])
    batchSubmitStockouts.mockResolvedValue({
      success: true,
      results: [{ success: true }], // 少返回一条
    })
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    expect(staged.value).toHaveLength(2)
  })

  it('全部失败：暂存区原样保留', async () => {
    const staged = ref([stagedItem()])
    batchSubmitStockouts.mockResolvedValue({
      success: true,
      results: [{ success: false, error: '无可用订单' }],
    })
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    expect(staged.value).toHaveLength(1)
  })
})
