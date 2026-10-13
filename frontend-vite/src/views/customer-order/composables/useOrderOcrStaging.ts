/**
 * 客户订单页的 OCR 草稿 → 前端暂存条目映射（纯函数）。
 *
 * 识别与三道闸门在共享的 useOcrPaste（components/ocr）里；这里只决定「确认后长什么样」：
 * origin 标 ocr，落点仍是前端暂存区，确认后复用既有的批量提交流程。
 * 因此这里没有对应的写接口——识别错了用户可以在弹窗或暂存区里改、删。
 *
 * 本页「订单信息录入」与「备货信息录入」共用同一条识别链路，差别只在条目的 type：
 * 订单 → 'order'，备货 → 'stockin'；提交时按 type 分流到各自的接口
 * （见 useStagedItems 的 stagedOrders / stagedStockins）。
 */
import type { OcrDraftItem, OcrStagingContext } from '@/components/ocr/types'
import type { StagedItem } from './types'
import { genUid } from '@/utils/uid'

export function buildCustomerOrderStagedItems(
  drafts: OcrDraftItem[],
  { date, fallbackCustomer }: OcrStagingContext,
  type: StagedItem['type'] = 'order',
): StagedItem[] {
  return drafts.map((draft) => ({
    uid: genUid(),
    origin: 'ocr',
    type,
    customer: draft.customer || fallbackCustomer,
    productId: draft.product_id as number, // 闸门已拦未匹配行
    productName: draft.product_name,
    quantity: draft.quantity,
    date,
    note: draft.note || '',
    deductStock: false,
    deductQuantity: 0,
    // 分批出货计划（2026-10-06 v2）：仅订单类型有意义；OCR 导入条目默认无计划，可在暂存编辑弹窗补设
    shipmentPlans: [],
  }))
}
