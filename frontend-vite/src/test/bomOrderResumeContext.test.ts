import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  RESUME_STORAGE_PREFIX,
  RESUME_TTL_MS,
  consumeResumeAttempt,
  createResumeAttempt,
  firstMissingProduct,
  parseResumeSource,
  readResumeAttempt,
  writeResumeAttempt,
  type BomResumeAttemptV1,
  type PurchaseViewSnapshot,
} from '@/utils/bomOrderResume'

const view: PurchaseViewSnapshot = {
  active_tab: 'active',
  purchase_page: 2,
  unprocessed_page: 3,
  selected_ids: [8, 9],
  main_scroll_top: 120,
  table_scroll_left: 30,
}

function createAttempt(now = 1_000_000): BomResumeAttemptV1 {
  return createResumeAttempt({
    attempt_id: '11111111-1111-4111-8111-111111111111',
    owner_id: 7,
    source: {
      composite_id: 'order:42', record_type: 'order', source_order_id: 42, order_no: 'SO-42',
    },
    pending_products: [{ product_id: 5, product_name: '产品五', product_barcode: '6905' }],
    current_product_id: 5,
    view,
    now,
  })
}

describe('BOM 续提 v1 上下文', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('round-trip 保留 typed 来源、固定幂等键、24h TTL 与视图快照', () => {
    const attempt = createAttempt()
    expect(attempt.idempotency_key).toBe(`po-resume:${attempt.attempt_id}`)
    expect(attempt.expires_at - attempt.created_at).toBe(RESUME_TTL_MS)
    expect(RESUME_TTL_MS).toBe(24 * 60 * 60 * 1000)
    expect(readResumeAttempt(attempt.attempt_id, 7, attempt.created_at + 1)).toEqual(attempt)
    expect(sessionStorage.getItem(`${RESUME_STORAGE_PREFIX}${attempt.attempt_id}`)).toBeTruthy()
  })

  it('owner 不符、过期、版本或结构篡改均 fail closed 并清除', () => {
    const attempt = createAttempt()
    expect(readResumeAttempt(attempt.attempt_id, 8, attempt.created_at + 1)).toBeNull()
    writeResumeAttempt(createAttempt())
    expect(readResumeAttempt(attempt.attempt_id, 7, attempt.expires_at + 1)).toBeNull()
    sessionStorage.setItem(`${RESUME_STORAGE_PREFIX}${attempt.attempt_id}`, JSON.stringify({
      ...attempt, schema_version: 2,
    }))
    expect(readResumeAttempt(attempt.attempt_id, 7, attempt.created_at + 1)).toBeNull()
    sessionStorage.setItem(`${RESUME_STORAGE_PREFIX}${attempt.attempt_id}`, JSON.stringify({
      ...attempt, source: { ...attempt.source, composite_id: 'stockin:42' },
    }))
    expect(readResumeAttempt(attempt.attempt_id, 7, attempt.created_at + 1)).toBeNull()
    expect(sessionStorage.getItem(`${RESUME_STORAGE_PREFIX}${attempt.attempt_id}`)).toBeNull()
  })

  it('storage 写失败向调用方抛错，消费后旧 URL 读不到上下文', () => {
    const attempt = createAttempt()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(() => writeResumeAttempt(attempt)).toThrow('无法保存续提上下文')
    vi.restoreAllMocks()
    writeResumeAttempt(attempt)
    consumeResumeAttempt(attempt.attempt_id)
    expect(readResumeAttempt(attempt.attempt_id, 7, attempt.created_at + 1)).toBeNull()
  })
})

describe('入口来源与最新缺 BOM SKU 解析', () => {
  it('接受 order/stockin typed ID，拒绝撞型、裸 ID 与非正整数', () => {
    expect(parseResumeSource({
      composite_id: 'stockin:9', record_type: 'stockin', source_order_id: 9, order_no: 'SI-9',
    })).toEqual({
      composite_id: 'stockin:9', record_type: 'stockin', source_order_id: 9, order_no: 'SI-9',
    })
    expect(parseResumeSource({ composite_id: 'order:9', record_type: 'stockin', source_order_id: 9 })).toBeNull()
    expect(parseResumeSource({ composite_id: '9', record_type: 'order', source_order_id: 9 })).toBeNull()
    expect(parseResumeSource({ composite_id: 'order:0', record_type: 'order', source_order_id: 0 })).toBeNull()
  })

  it('从最新 items 取首个缺 BOM SKU；仅旧数据无 items 时回退顶层产品', () => {
    expect(firstMissingProduct({
      items: [
        { id: 1, product_id: 1, product_name: '一', quantity: 1, has_bom: true },
        { id: 2, product_id: 2, product_name: '二', quantity: 1, has_bom: false },
        { id: 3, product_id: 3, product_name: '三', quantity: 1, has_bom: false },
      ],
      product_id: 99,
    })?.product_id).toBe(2)
    expect(firstMissingProduct({ product_id: 8, product_name: '旧产品' })?.product_id).toBe(8)
    expect(firstMissingProduct({
      items: [{ id: 1, product_id: 7, product_name: '接口未回 has_bom', quantity: 1 }],
      product_id: 8,
      product_name: '顶层兜底产品',
      has_bom: false,
    })?.product_id).toBe(8)
    expect(firstMissingProduct({ items: [], product_id: 0 })).toBeNull()
  })

  it('storage 整体不可用时读取失败也必须返回 null，不能把权限异常抛给页面', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readResumeAttempt('11111111-1111-4111-8111-111111111111', 7)).toBeNull()
    getItem.mockRestore()
    removeItem.mockRestore()
  })
})
