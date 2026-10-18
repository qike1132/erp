/**
 * 出货暂存的可用量闸门（2026-10-17 审计 P2-45 / 2026-10-18 OCR 复评）。
 *
 * 从 StockOutTab.vue 抽出，原因：该文件已贴 400 行门禁上限，而闸门逻辑
 * （产品级累计 + 批次级累计）被「新增 / 编辑 / OCR 暂存」三条路径共用。
 *
 * 口径：**同产品 + 同客户**的「已暂存量（可排除自身）+ 本次数量」不得超过
 * 该产品的可出货量（`/stock/available-shipment`）。OCR 暂存与手工录入同构，
 * 因此三条入口都必须过同一道闸门——否则任一路径都能把总量推出超额，
 * 只在批量提交时被后端拒（表现为「部分出货成功」）。
 */
import type { Ref } from 'vue'
import { stockApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { StagedStockout } from '@/types'

export interface ProductAvailabilityGate {
  productId: string
  customer: string
  quantity: number
  /** 编辑路径排除被编辑项自身（它已计入 staged，不排除会把可用量算小） */
  excludeId?: number
}

/** 请求序号：快速切换 SKU/客户时丢弃过期响应（F-FE-DESK-CORE-02） */
let shipReqSeq = 0

export function useStockOutAvailabilityGates(staged: Ref<StagedStockout[]>) {
  /**
   * 拉取指定产品/客户的可出货量。参数缺省回落到调用方当前表单值。
   * 返回 undefined 表示「拿不到可用量」（缺产品/客户、请求失败）——调用方应放行，
   * 由后端做最终校验，避免前端因一次失败就锁死用户操作。
   */
  async function fetchAvailableShipment(
    productId?: string | number,
    customer?: string,
  ): Promise<number | undefined> {
    const pid = productId
    const cust = customer
    if (!pid || !cust) return undefined
    const seq = ++shipReqSeq
    try {
      const data = await stockApi.availableShipment(Number(pid), cust)
      if (seq !== shipReqSeq) return undefined // 已有更新的请求在途，丢弃过期响应
      return data.data?.available_quantity
    } catch {
      return undefined
    }
  }

  /** 同产品/客户的已暂存合计（排除自身） */
  function stagedTotalFor(productId: string, customer: string, excludeId?: number): number {
    return staged.value
      .filter((s) => s.product_id === productId && s.customer === customer
        && s.id !== excludeId)
      .reduce((sum, s) => sum + (s.quantity || 0), 0)
  }

  /**
   * 产品级累计闸门。返回 true 表示放行。
   */
  async function checkProductAvailability(opts: ProductAvailabilityGate): Promise<boolean> {
    if (!opts.productId || !opts.customer) return true
    const avail = await fetchAvailableShipment(opts.productId, opts.customer)
    if (avail === undefined) return true
    const stagedSameProduct = stagedTotalFor(opts.productId, opts.customer, opts.excludeId)
    const effectiveAvail = avail - stagedSameProduct
    if (opts.quantity > effectiveAvail) {
      showToast(
        `出货数量超过可出货量！可出货: ${effectiveAvail}（已暂存 ${stagedSameProduct}）`,
        'error',
      )
      return false
    }
    return true
  }

  return {
    fetchAvailableShipment,
    stagedTotalFor,
    checkProductAvailability,
  }
}
