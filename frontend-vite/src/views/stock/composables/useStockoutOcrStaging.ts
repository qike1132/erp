/**
 * 出货域的 OCR 草稿 → 前端暂存出货条目映射（纯函数）。
 *
 * 识别与三道闸门在共享的 useOcrPaste（components/ocr）里；这里只决定「确认后长什么样」：
 * 落点是出货页的前端暂存列表（staged），确认后复用既有的批量提交流程。
 */
import type { OcrDraftItem, OcrStagingContext } from '@/components/ocr/types'
import type { StagedStockout } from '@/types'

export function buildStockoutStagedItems(
  drafts: OcrDraftItem[],
  { date, fallbackCustomer }: OcrStagingContext,
): StagedStockout[] {
  const base = Date.now()
  return drafts.map((draft, i) => ({
    // 同毫秒批量入列时用下标保证 id 唯一
    id: base + i,
    product_id: String(draft.product_id), // 闸门已拦未匹配行
    product_name: draft.product_name,
    customer: draft.customer || fallbackCustomer,
    date,
    quantity: draft.quantity,
    note: draft.note || '',
  }))
}
