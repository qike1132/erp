import type { UnprocessedOrder, UnprocessedOrderItem } from '@/types'

export const RESUME_STORAGE_PREFIX = 'fb_bom_order_resume_v1:'
export const RESUME_TTL_MS = 24 * 60 * 60 * 1000

export type ResumePhase =
  | 'CONFIGURING' | 'RETURNING' | 'RESTORING_REVALIDATING'
  | 'WAITING_NEXT_BOM' | 'RESUMING' | 'RESUME_FAILED'
  | 'DONE' | 'CANCELLED' | 'ABORTED'

export interface ResumeProduct {
  product_id: number
  product_name: string
  product_barcode?: string | null
}

export interface ResumeSource {
  composite_id: string
  record_type: 'order' | 'stockin'
  source_order_id: number
  order_no: string
}

export interface PurchaseViewSnapshot {
  active_tab: 'active' | 'history'
  purchase_page: number
  unprocessed_page: number
  selected_ids: number[]
  main_scroll_top: number
  table_scroll_left: number
}

export interface BomResumeAttemptV1 {
  schema_version: 1
  attempt_id: string
  idempotency_key: string
  owner_id: number
  phase: ResumePhase
  return_route: '/purchase'
  source: ResumeSource
  pending_products: ResumeProduct[]
  current_product_id: number
  view: PurchaseViewSnapshot
  last_error?: string
  created_at: number
  updated_at: number
  expires_at: number
}

export interface CreateResumeAttemptInput {
  attempt_id?: string
  owner_id: number
  source: ResumeSource
  pending_products: ResumeProduct[]
  current_product_id: number
  view: PurchaseViewSnapshot
  now?: number
}

const PHASES = new Set<ResumePhase>([
  'CONFIGURING', 'RETURNING', 'RESTORING_REVALIDATING', 'WAITING_NEXT_BOM',
  'RESUMING', 'RESUME_FAILED', 'DONE', 'CANCELLED', 'ABORTED',
])
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function positiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function validProduct(value: unknown): value is ResumeProduct {
  if (!value || typeof value !== 'object') return false
  const product = value as Partial<ResumeProduct>
  return positiveInteger(product.product_id) && typeof product.product_name === 'string'
}

function validSource(value: unknown): value is ResumeSource {
  if (!value || typeof value !== 'object') return false
  const source = value as Partial<ResumeSource>
  if (!source.record_type || !['order', 'stockin'].includes(source.record_type)) return false
  if (!positiveInteger(source.source_order_id) || typeof source.order_no !== 'string') return false
  return source.composite_id === `${source.record_type}:${source.source_order_id}`
}

function validView(value: unknown): value is PurchaseViewSnapshot {
  if (!value || typeof value !== 'object') return false
  const view = value as Partial<PurchaseViewSnapshot>
  return (
    (view.active_tab === 'active' || view.active_tab === 'history')
    && positiveInteger(view.purchase_page) && positiveInteger(view.unprocessed_page)
    && Array.isArray(view.selected_ids) && view.selected_ids.every(positiveInteger)
    && typeof view.main_scroll_top === 'number' && view.main_scroll_top >= 0
    && typeof view.table_scroll_left === 'number' && view.table_scroll_left >= 0
  )
}

function validAttempt(value: unknown, ownerId: number, now: number): value is BomResumeAttemptV1 {
  if (!value || typeof value !== 'object') return false
  const attempt = value as Partial<BomResumeAttemptV1>
  return (
    attempt.schema_version === 1
    && typeof attempt.attempt_id === 'string' && UUID_PATTERN.test(attempt.attempt_id)
    && attempt.idempotency_key === `po-resume:${attempt.attempt_id}`
    && attempt.owner_id === ownerId && PHASES.has(attempt.phase as ResumePhase)
    && attempt.return_route === '/purchase' && validSource(attempt.source)
    && Array.isArray(attempt.pending_products) && attempt.pending_products.every(validProduct)
    && positiveInteger(attempt.current_product_id) && validView(attempt.view)
    && typeof attempt.created_at === 'number' && typeof attempt.updated_at === 'number'
    && typeof attempt.expires_at === 'number' && attempt.created_at <= now
    && attempt.expires_at === attempt.created_at + RESUME_TTL_MS && now <= attempt.expires_at
  )
}

export function createResumeAttempt(input: CreateResumeAttemptInput): BomResumeAttemptV1 {
  const now = input.now ?? Date.now()
  const attemptId = input.attempt_id ?? crypto.randomUUID()
  const attempt: BomResumeAttemptV1 = {
    schema_version: 1,
    attempt_id: attemptId,
    idempotency_key: `po-resume:${attemptId}`,
    owner_id: input.owner_id,
    phase: 'CONFIGURING',
    return_route: '/purchase',
    source: input.source,
    pending_products: input.pending_products,
    current_product_id: input.current_product_id,
    view: input.view,
    created_at: now,
    updated_at: now,
    expires_at: now + RESUME_TTL_MS,
  }
  if (!validAttempt(attempt, input.owner_id, now)) throw new Error('续提上下文参数无效')
  writeResumeAttempt(attempt)
  return attempt
}

export function writeResumeAttempt(attempt: BomResumeAttemptV1): void {
  if (!validAttempt(attempt, attempt.owner_id, attempt.updated_at)) {
    throw new Error('续提上下文无效，已停止跳转')
  }
  try {
    sessionStorage.setItem(
      `${RESUME_STORAGE_PREFIX}${attempt.attempt_id}`,
      JSON.stringify(attempt),
    )
  } catch {
    throw new Error('当前浏览器无法保存续提上下文')
  }
}

export function readResumeAttempt(
  attemptId: string,
  ownerId: number,
  now: number = Date.now(),
): BomResumeAttemptV1 | null {
  const key = `${RESUME_STORAGE_PREFIX}${attemptId}`
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!validAttempt(parsed, ownerId, now)) {
      sessionStorage.removeItem(key)
      return null
    }
    return parsed
  } catch {
    try {
      sessionStorage.removeItem(key)
    } catch {
      // storage 整体不可用时已无法读取；按无上下文处理，禁止继续写。
    }
    return null
  }
}

export function consumeResumeAttempt(attemptId: string): void {
  try {
    sessionStorage.removeItem(`${RESUME_STORAGE_PREFIX}${attemptId}`)
  } catch {
    // 已消费页面即使 storage 被禁用也不得重新发写请求；内存态由调用方同步终结。
  }
}

export function parseResumeSource(row: Partial<UnprocessedOrder>): ResumeSource | null {
  const recordType = row.record_type
  const sourceId = row.source_order_id ?? row.id
  if ((recordType !== 'order' && recordType !== 'stockin') || !positiveInteger(sourceId)) return null
  const compositeId = `${recordType}:${sourceId}`
  if (row.composite_id !== compositeId) return null
  return {
    composite_id: compositeId,
    record_type: recordType,
    source_order_id: sourceId,
    order_no: typeof row.order_no === 'string' ? row.order_no : '',
  }
}

function toResumeProduct(item: Partial<UnprocessedOrderItem>): ResumeProduct | null {
  if (!positiveInteger(item.product_id)) return null
  return {
    product_id: item.product_id,
    product_name: typeof item.product_name === 'string' ? item.product_name : '',
    product_barcode: item.product_barcode ?? null,
  }
}

export function missingProducts(row: Partial<UnprocessedOrder>): ResumeProduct[] {
  if (Array.isArray(row.items) && row.items.length > 0) {
    const missing = row.items
      .filter((item) => item.has_bom === false)
      .map(toResumeProduct)
      .filter((item): item is ResumeProduct => item !== null)
    if (missing.length > 0) return missing
  }
  const fallback = toResumeProduct({
    product_id: row.product_id ?? undefined,
    product_name: row.product_name,
    product_barcode: row.barcode ?? null,
  })
  return fallback ? [fallback] : []
}

export function firstMissingProduct(row: Partial<UnprocessedOrder>): ResumeProduct | null {
  return missingProducts(row)[0] ?? null
}
