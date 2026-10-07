/**
 * 数量范围校验的回归守卫。
 *
 * 需求：数量不在 1 至 9,999,999 之间时，输入框标红并提示
 * 「数量必须介于 1 到 9,999,999 之间」；合法时取消标红与提示；
 * 既要输入过程实时校验，也要在提交前再挡一次。
 *
 * 本文件锁死三件事：
 *   1) 边界判定（含空值/非数字/0/负数的语义）
 *   2) 范围与文案只有一处定义（三处输入框共用）
 *   3) 两个保存入口在越界时真的会拦住（实时标红可被绕过）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, reactive } from 'vue'

const mocks = vi.hoisted(() => ({
  getMock: vi.fn(),
  updateMock: vi.fn(),
  updateDeductMock: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: mocks.getMock,
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
  download: vi.fn(),
}))
vi.mock('@/api', () => ({
  orderApi: { update: mocks.updateMock, updateDeduct: mocks.updateDeductMock },
  auxApi: { availableStockins: vi.fn(async () => []) },
  stockApi: { stockins: vi.fn() },
}))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: ref(undefined) }),
}))

import { showToast } from '@/composables/useToast'
import {
  QUANTITY_MAX,
  QUANTITY_MIN,
  QUANTITY_RANGE_MESSAGE,
  isQuantityOutOfRange,
  quantityAriaInvalid,
} from '@/views/customer-order/composables/quantityRange'
import { useStagedEdit } from '@/views/customer-order/composables/useStagedEdit'
import { useOrderDetailEdit } from '@/views/report/composables/useOrderDetailEdit'
import type { StagedItem } from '@/views/customer-order/composables/types'

function stagedItem(quantity: number): StagedItem {
  return {
    uid: 's1', origin: 'manual', type: 'order',
    customer: '审计客户', productId: 101, productName: '审计产品',
    quantity, date: '2026-09-18', note: '', deductStock: false,
    deductQuantity: 0, shipmentPlans: [],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('数量范围：唯一来源', () => {
  it('范围常量与提示文案符合需求', () => {
    expect(QUANTITY_MIN).toBe(1)
    expect(QUANTITY_MAX).toBe(9999999)
    expect(QUANTITY_RANGE_MESSAGE).toBe('数量必须介于 1 到 9,999,999 之间')
  })
})

describe('isQuantityOutOfRange 边界', () => {
  const cases: Array<[unknown, boolean, string]> = [
    [1, false, '下限'],
    [2, false, '区间内'],
    [9999999, false, '上限'],
    [10000000, true, '超上限一位'],
    [99999999, true, '远超上限'],
    [0, true, '0 越界'],
    [-1, true, '负数越界'],
    [-99999, true, '负大数越界'],
    [1.5, false, '小数在区间内视为合法'],
    [10000000.5, true, '小数超上限'],
    ['10000000', true, '字符串形态同样判定'],
    ['5', false, '字符串合法值'],
    ['', false, '空串不判越界（由必填规则负责）'],
    ['abc', false, '非数字不判越界'],
    [null, false, 'null 不判越界'],
    [undefined, false, 'undefined 不判越界'],
    [NaN, false, 'NaN 不判越界'],
  ]
  for (const [input, expected, label] of cases) {
    it(`${label}：${String(input)} → ${expected}`, () => {
      expect(isQuantityOutOfRange(input)).toBe(expected)
    })
  }

  it('quantityAriaInvalid 与判定一致', () => {
    expect(quantityAriaInvalid(0)).toBe('true')
    expect(quantityAriaInvalid(10000000)).toBe('true')
    expect(quantityAriaInvalid(5)).toBeUndefined()
    expect(quantityAriaInvalid('')).toBeUndefined()
  })
})

describe('提交前最终校验：越界必须被拦住', () => {
  it('saveEditStaged 越界时不写回暂存区，并给出区间提示', () => {
    const stagedItems = ref<StagedItem[]>([stagedItem(5)])
    const { editStagedIdx, editStagedData, saveEditStaged } = useStagedEdit(stagedItems)
    editStagedIdx.value = 0          // 必须置位：否则写回分支本来就不会进，断言会假绿
    editStagedData.value = stagedItem(10000000)

    saveEditStaged()

    expect(stagedItems.value[0]!.quantity, '越界值不得写回暂存区').toBe(5)
    expect(vi.mocked(showToast).mock.calls.some((c) => c[0] === QUANTITY_RANGE_MESSAGE)).toBe(true)
  })

  it('saveEditStaged 合法时正常写回', () => {
    const stagedItems = ref<StagedItem[]>([stagedItem(5)])
    const { editStagedIdx, editStagedData, saveEditStaged } = useStagedEdit(stagedItems)
    editStagedIdx.value = 0
    editStagedData.value = stagedItem(9999999)

    saveEditStaged()

    expect(stagedItems.value[0]!.quantity).toBe(9999999)
    expect(vi.mocked(showToast).mock.calls.some((c) => c[0] === QUANTITY_RANGE_MESSAGE)).toBe(false)
  })

  it('saveEditOrder 越界时不发请求，并给出区间提示', async () => {
    const { detailData, editForm, saveEditOrder } = useOrderDetailEdit(async () => {})
    detailData.value = { id: 1, quantity: 5 } as never
    editForm.quantity = 0

    await saveEditOrder()

    expect(mocks.updateMock, '越界不得提交').not.toHaveBeenCalled()
    expect(vi.mocked(showToast).mock.calls.some((c) => c[0] === QUANTITY_RANGE_MESSAGE)).toBe(true)
  })

  it('saveEditOrder 合法时正常提交', async () => {
    mocks.updateMock.mockResolvedValue({})
    const { detailData, editForm, saveEditOrder } = useOrderDetailEdit(async () => {})
    detailData.value = { id: 7, quantity: 5, deduct_quantity: 0 } as never
    editForm.quantity = 42

    await saveEditOrder()

    expect(mocks.updateMock).toHaveBeenCalledWith(7, { quantity: 42, note: '' })
  })
})
