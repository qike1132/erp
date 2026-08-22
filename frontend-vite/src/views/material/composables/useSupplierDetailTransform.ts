// 供应商详情数据处理：snake_case → camelCase 映射 + 乐观更新逻辑
// 从 MaterialView.vue 抽出，消除视图层 60+ 行数据处理职责
import type { Ref } from 'vue'
import type { SupplierDetailApiResponse } from '@/api/material'
import type { RegItem } from '@/api/material'
import type { SupMatItem, SupplierDetail } from '../material-types'

/** 计算完成百分比：全部到货返回 100，否则上限 99.9 */
function computePct(ordered: number, received: number): number {
  if (ordered <= 0) return 0
  if (received >= ordered) return 100
  return Math.min(Math.round((received / ordered) * 100 * 10) / 10, 99.9)
}

/** 将后端 snake_case 聚合响应映射为前端 camelCase SupplierDetail（纯字段重命名，O(n) 线性扫描） */
export function mapSupplierDetail(data: SupplierDetailApiResponse): SupplierDetail {
  return {
    supplierGroups: data.supplier_groups.map((g) => ({
      supplierName: g.supplier_name,
      items: g.items.map((m) => ({
        name: m.name,
        ordered: m.ordered,
        received: m.received,
        remaining: m.remaining,
        pct: m.pct,
        subItems: m.sub_items as SupMatItem[],
        unit: m.unit,
        spec: m.spec,
      })),
      totalOrdered: g.total_ordered,
      totalReceived: g.total_received,
      pct: g.pct,
    })),
    totalOrdered: data.total_ordered,
    totalReceived: data.total_received,
    totalPct: data.total_pct,
  }
}

/** 乐观更新供应商详情对话框中对应物料的收货数量与进度（含供应商级与全局汇总） */
export function updateSupplierDialogLocally(
  supplierDetail: Ref<SupplierDetail | null>,
  showSupplierDialog: Ref<boolean>,
  receiveItem: { name: string; received: number; subItems: SupMatItem[] },
  newReceived: number,
): void {
  if (!showSupplierDialog.value || !supplierDetail.value) return
  const delta = newReceived - receiveItem.received
  if (delta <= 0) return
  for (const g of supplierDetail.value.supplierGroups) {
    let groupChanged = false
    for (const m of g.items) {
      if (m.name === receiveItem.name && m.subItems.some((s) => receiveItem.subItems.some((rs) => rs.id === s.id))) {
        m.received += delta
        m.remaining = m.ordered - m.received
        m.pct = computePct(m.ordered, m.received)
        groupChanged = true
      }
    }
    if (groupChanged) {
      g.totalReceived = g.items.reduce((s, m) => s + m.received, 0)
      const gComplete = g.items.every((m) => m.received >= m.ordered)
      g.pct = computePct(g.totalOrdered, gComplete ? g.totalOrdered : g.totalReceived)
    }
  }
  const allComplete = supplierDetail.value.supplierGroups.every((g) => g.items.every((m) => m.received >= m.ordered))
  supplierDetail.value.totalReceived = supplierDetail.value.supplierGroups.reduce(
    (s, g) => s + g.items.reduce((s2, m) => s2 + m.received, 0),
    0,
  )
  supplierDetail.value.totalPct = computePct(
    supplierDetail.value.totalOrdered,
    allComplete ? supplierDetail.value.totalOrdered : supplierDetail.value.totalReceived,
  )
}

/** 乐观更新登记详情对话框中对应物料的收货数量与进度 */
export function updateDetailDialogLocally(
  detailData: Ref<{ items?: RegItem[]; id: number } | null>,
  showDetailDialog: Ref<boolean>,
  receiveItemId: number,
  newReceived: number,
): void {
  if (!showDetailDialog.value || !detailData.value) return
  const dItem = (detailData.value.items || []).find((i: RegItem) => i.id === receiveItemId)
  if (!dItem) return
  dItem.received_quantity = newReceived
  const dOrdered = parseFloat(String(dItem.ordered_quantity || 0))
  dItem.remaining_quantity = dOrdered - newReceived
  dItem.progress = computePct(dOrdered, newReceived)
}
