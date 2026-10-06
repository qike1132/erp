/**
 * 订单域的 OCR 草稿 → 前端暂存条目映射（纯函数）。
 *
 * 识别与三道闸门在共享的 useOcrPaste（components/ocr）里；这里只决定「确认后长什么样」：
 * origin 标 ocr，落点仍是前端暂存区，确认后复用既有的批量提交流程。
 * 因此这里没有对应的写接口——识别错了用户可以在弹窗或暂存区里改、删。
 */
import type { OcrDraftItem, OcrStagingContext } from '@/components/ocr/types'
import type { StagedItem } from './types'
import { genUid } from '@/utils/uid'

export function buildOrderStagedItems(
  drafts: OcrDraftItem[],
  { date, fallbackCustomer }: OcrStagingContext,
): StagedItem[] {
  return drafts.map((draft) => ({
    uid: genUid(),
    origin: 'ocr',
    type: 'order',
    customer: draft.customer || fallbackCustomer,
    productId: draft.product_id as number, // 闸门已拦未匹配行
    productName: draft.product_name,
    quantity: draft.quantity,
    date,
    note: draft.note || '',
    deductStock: false,
    deductQuantity: 0,
    // 分批出货计划（2026-10-06 v2）：OCR 导入条目默认无计划，可在暂存编辑弹窗补设
    shipmentPlans: [],
  }))
}
