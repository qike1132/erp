/**
 * 出货域的 OCR 草稿 → 前端暂存出货条目映射（纯函数）。
 *
 * 识别与三道闸门在共享的 useOcrPaste（components/ocr）里；这里只决定「确认后长什么样」：
 * 落点是出货页的前端暂存列表（staged），确认后复用既有的批量提交流程。
 */
import type { OcrDraftItem, OcrStagingContext } from '@/components/ocr/types'
import type { StagedStockout } from '@/types'

/** 按「产品 + 客户」分组的暂存条目（2026-10-18 OCR 复评：OCR 批量入暂存前
 *  要按组合并后过一次可用量闸门——串行逐条会让前几条的计入影响后几条的可用量，
 *  合并后一次请求既省往返又与「同组已暂存 + 本批合计」口径一致）。 */
export function groupByProductCustomer(items: StagedStockout[]): StagedStockout[][] {
  const byGroup = new Map<string, StagedStockout[]>()
  for (const it of items) {
    const key = `${it.product_id}|${it.customer}`
    byGroup.set(key, [...(byGroup.get(key) ?? []), it])
  }
  return [...byGroup.values()]
}

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
