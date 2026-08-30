import { ref, computed, reactive, toRaw } from 'vue'
import { purchaseApi } from '@/api'
import { escapeHtml, printHtml } from '@/utils/print'
import { fmtQty } from '@/utils/formatQty'

// structuredClone 无法克隆 Vue 响应式 Proxy（报 "could not be cloned"）。
// 先 toRaw 取回原始纯对象，再做结构化深克隆；传入纯对象时 toRaw 原样返回，同样安全。
function cloneRaw<T>(v: T): T {
  return structuredClone(toRaw(v) as T)
}

/**
 * 订单时间标签：展示实际下单时间（选中订单中最晚的 create_time，回退 order_date）。
 * 时间值由调用方（usePurchaseActions.handleSummary）从订单列表计算后传入 openSummary。
 */
function orderTimeLabel(orderTime: string): string {
  const value = orderTime ? escapeHtml(orderTime) : '—'
  return `<div style="text-align:right;font-size:12px;color:#555;margin-bottom:10px;">订单时间：${value}</div>`
}

/**
 * 备品数量 = ceil(订单数量 × 损耗率‰)。
 * 损耗率 ≤ 0 或 qty 非法/非正时返回 0。屏幕表格、打印预览、Excel 导出共用这一处来源。
 */
export function calcSpareQuantity(qty: number, lossRate: number): number {
  if (!lossRate || lossRate <= 0 || !Number.isFinite(qty) || qty <= 0) return 0
  return Math.ceil(qty * (lossRate / 1000))
}

/**
 * 订单数量取数：产品数量优先，缺失时回退订单数量。
 * 与 calcSpareQuantity 共用同一防御口径：非法/缺失输入兜底 0。
 * 屏幕表格、打印预览、Excel 导出共用这一处来源。
 */
export function getGroupOrderQty(group: FactoryGroup): number {
  const v = parseFloat(String(group.product_quantity || group.order_quantity || 0))
  return Number.isNaN(v) ? 0 : v
}

/**
 * 汇总下单打印专用样式（A4 零页边距 + 单行不换行 + 全格居中）。
 *
 * 设计要点（保证打印预览与实际打印输出一致、跨浏览器稳定）：
 * 1. @page margin:0 —— 上下左右页边距全部置 0，最大化利用 A4 打印区域；
 *    同时 html/body margin/padding 归零兜底，避免部分浏览器忽略 @page 规则。
 * 2. th/td white-space:nowrap —— 每行数据强制单行显示，禁止折行；
 *    word-break/overflow-wrap 归 normal，杜绝 CJK 断词导致的意外换行。
 * 3. th/td text-align:center —— 所有单元格内容居中对齐。
 * 4. 样式只保留一处来源（stylesheets），单元格不设内联对齐/边框样式，
 *    预览与打印渲染同一份文档、同一套规则，天然一致。
 * 5. print-color-adjust:exact —— 表头灰底在物理打印时不丢失。
 * 6. 字号 12px + 紧凑内边距，保证 9 列内容在 A4 纵向宽度内完整落纸。
 */
const SUMMARY_PRINT_STYLE = `
  @page { size: A4; margin: 0; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: SimSun, 宋体, serif; color: #000; }
  h2 { margin: 0 0 10px; font-size: 18px; line-height: 1.4; }
  table { width: 100%; border-collapse: collapse; table-layout: auto; }
  th, td {
    border: 1px solid #333;
    padding: 6px 8px;
    font-size: 12px;
    text-align: center;
    vertical-align: middle;
    white-space: nowrap;
    overflow-wrap: normal;
    word-break: normal;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  thead th { background: #e6e6e6; font-weight: bold; }
`

export function buildFactoryHtml(data: FactorySummaryData, lossRate: number): string {
  let tableHtml = ''
  data.groups?.forEach((group) => {
    const suppliers: SupplierGroup[] = group.suppliers || []
    let globalFabricIdx = 0
    suppliers.forEach((supplier) => {
      supplier.fabrics?.forEach((fabric) => {
        tableHtml += '<tr>'
        if (globalFabricIdx === 0) {
          const rowCount = suppliers.reduce((s: number, sup: SupplierGroup) => s + (sup.fabrics?.length || 0), 0)
          tableHtml += `<td rowspan="${rowCount}" style="font-weight:bold;">${escapeHtml(group.customer_name)}</td>`
          tableHtml += `<td rowspan="${rowCount}">${escapeHtml(group.product_name)}</td>`
          const qty = getGroupOrderQty(group)
          tableHtml += `<td rowspan="${rowCount}">${escapeHtml(fmtQty(qty))}</td>`
          tableHtml += `<td rowspan="${rowCount}">${escapeHtml(fmtQty(calcSpareQuantity(qty, lossRate)))}</td>`
        }
        tableHtml += `<td style="font-weight:bold;">${escapeHtml(supplier.supplier_name)}</td>`
        tableHtml += `<td>${escapeHtml(fabric.fabric_name)}</td>`
        tableHtml += `<td>${escapeHtml(fabric.specification || '')}</td>`
        tableHtml += `<td>${escapeHtml(fmtQty(fabric.quantity))}</td>`
        tableHtml += `<td>${escapeHtml(fabric.unit || '')}</td>`
        tableHtml += '</tr>'
        globalFabricIdx++
      })
    })
  })
  return tableHtml
}

function buildSupplierHtml(groups: { supplierName: string; materials: MaterialItem[] }[]): string {
  let tableHtml = ''
  groups.forEach((g) => {
    g.materials.forEach((m: MaterialItem, mi: number) => {
      tableHtml += '<tr>'
      if (mi === 0)
        tableHtml += `<td rowspan="${g.materials.length}" style="font-weight:bold;">${escapeHtml(g.supplierName)}</td>`
      tableHtml += `<td>${escapeHtml(m.material_name)}</td>`
      tableHtml += `<td>${escapeHtml(m.specification || '')}</td>`
      tableHtml += `<td>${escapeHtml(fmtQty(m.total_quantity))} ${escapeHtml(m.unit || '')}</td>`
      tableHtml += '</tr>'
    })
  })
  return tableHtml
}

function downloadAsXls(html: string, filename: string) {
  const bom = '\uFEFF'
  const style = `<style>body{font-family:SimSun,宋体;padding:20px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #333;padding:8px;font-size:13px}th{background:#e6e6e6}</style>`
  const fullHtml = `<html><head><meta charset="utf-8">${style}</head><body>${html}</body></html>`
  const blob = new Blob([bom + fullHtml], { type: 'application/vnd.ms-excel;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}

export interface FabricItem {
  fabric_name: string
  specification?: string
  quantity: number
  unit?: string
  item_ids?: number[]
  item_id?: number
}

export interface SupplierGroup {
  supplier_name: string
  fabrics: FabricItem[]
}

export interface FactoryGroup {
  customer_name: string
  product_name: string
  product_quantity?: number
  order_quantity?: number
  suppliers: SupplierGroup[]
}

/** 工厂内部采购汇总响应（/purchase/factory-summary） */
export interface FactorySummaryData {
  success: boolean
  message?: string
  /** 选中订单数（模板展示用） */
  order_count?: number
  groups: FactoryGroup[]
}

/** 供应商采购汇总响应中的物料行（/purchase/supplier-summary） */
export interface MaterialItem {
  material_name: string
  specification?: string
  total_quantity: number
  unit?: string
  supplier_name?: string
}

/** 供应商采购汇总响应（/purchase/supplier-summary） */
export interface SupplierSummaryData {
  success: boolean
  message?: string
  /** 选中订单数（模板展示用） */
  order_count?: number
  materials: MaterialItem[]
}

interface SaveFactoryEditsResponse {
  success: boolean
  message?: string
}

export function useSummaryModal() {
  const open = ref(false)
  const tab = ref<'factory' | 'supplier'>('factory')
  const factoryData = ref<FactorySummaryData | null>(null)
  const factoryOriginalData = ref<FactorySummaryData | null>(null)
  const supplierData = ref<SupplierSummaryData | null>(null)
  const supplierOriginalData = ref<SupplierSummaryData | null>(null)
  const editMode = ref(false)
  const lossRate = ref(0)
  const orderIds = ref<number[]>([])
  const supplierOrder = ref<string[]>([])
  /** 订单时间（选中订单中最晚 create_time，回退 order_date；由 openSummary 调用方传入） */
  const orderTime = ref('')

  const supplierGroups = computed(() => {
    if (!supplierData.value?.materials) return []
    const groups: { supplierName: string; materials: MaterialItem[] }[] = []
    const map: Record<string, MaterialItem[]> = {}
    const newOrder: string[] = []
    supplierData.value.materials.forEach((m) => {
      const s = m.supplier_name || '未指定供应商'
      if (!map[s]) {
        map[s] = []
        newOrder.push(s)
      }
      map[s].push(m)
    })
    const order = supplierOrder.value.length > 0 ? supplierOrder.value : newOrder
    order.forEach((s) => {
      if (map[s]) groups.push({ supplierName: s, materials: map[s] })
    })
    newOrder.forEach((s) => {
      if (!order.includes(s) && map[s]) groups.push({ supplierName: s, materials: map[s] })
    })
    return groups
  })

  async function openSummary(ids: number[], orderTimeValue?: string) {
    orderIds.value = ids
    orderTime.value = orderTimeValue || ''
    const [fRes, sRes] = await Promise.all([
      purchaseApi.factorySummary(ids) as unknown as FactorySummaryData,
      purchaseApi.supplierSummary(ids) as unknown as SupplierSummaryData,
    ])
    if (!fRes.success || !sRes.success) throw new Error(fRes.message || sRes.message || '汇总失败')
    factoryData.value = structuredClone(fRes)
    factoryOriginalData.value = structuredClone(fRes)
    supplierData.value = structuredClone(sRes)
    supplierOriginalData.value = structuredClone(sRes)
    const initOrder: string[] = []
    sRes.materials?.forEach((m) => {
      const s = m.supplier_name || '未指定供应商'
      if (!initOrder.includes(s)) initOrder.push(s)
    })
    supplierOrder.value = initOrder
    editMode.value = false
    tab.value = 'factory'
    open.value = true
  }

  function toggleEditMode(enable: boolean) {
    if (!enable) {
      factoryData.value = cloneRaw(factoryOriginalData.value)
      supplierData.value = cloneRaw(supplierOriginalData.value)
      lossRate.value = 0
    }
    editMode.value = enable
  }

  function updateFactoryQty(gi: number, si: number, fi: number, value: number) {
    const fabric = factoryData.value?.groups?.[gi]?.suppliers?.[si]?.fabrics?.[fi]
    if (!fabric) return
    const oldQty = parseFloat(String(fabric.quantity)) || 0
    const diff = value - oldQty
    fabric.quantity = value

    if (diff !== 0 && supplierData.value?.materials) {
      const fabricName = fabric.fabric_name
      const spec = fabric.specification || ''
      const unit = fabric.unit || ''
      const supplierName = factoryData.value?.groups?.[gi]?.suppliers?.[si]?.supplier_name
      supplierData.value.materials.forEach((m) => {
        if (
          m.material_name === fabricName &&
          (m.specification || '') === spec &&
          (m.unit || '') === unit &&
          (m.supplier_name || '未指定供应商') === (supplierName || '未指定供应商')
        ) {
          m.total_quantity = Math.round(((parseFloat(String(m.total_quantity)) || 0) + diff) * 100) / 100
        }
      })
    }
  }

  function applyLossRate(rate: number) {
    lossRate.value = rate
    if (!factoryOriginalData.value?.groups) return
    factoryData.value?.groups?.forEach((group, gi) => {
      group.suppliers?.forEach((supplier, si) => {
        supplier.fabrics?.forEach((fabric, fi) => {
          const originalFabric = factoryOriginalData.value?.groups?.[gi]?.suppliers?.[si]?.fabrics?.[fi]
          if (originalFabric) {
            const originalQty = parseFloat(String(originalFabric.quantity)) || 0
            const newQty = originalQty + originalQty * (rate / 1000)
            fabric.quantity = Math.round(newQty * 100) / 100
          }
        })
      })
    })
    if (supplierOriginalData.value?.materials) {
      supplierData.value?.materials?.forEach((m, mi) => {
        const origM = supplierOriginalData.value?.materials?.[mi]
        if (origM) {
          const originalQty = parseFloat(String(origM.total_quantity)) || 0
          const newQty = originalQty + originalQty * (rate / 1000)
          m.total_quantity = Math.round(newQty * 100) / 100
        }
      })
    }
  }

  async function saveFactoryEdits() {
    const edits: { item_ids: number[]; quantity: number }[] = []
    const current = factoryData.value
    const original = factoryOriginalData.value
    if (current?.groups && original?.groups) {
      current.groups.forEach((group, gi) => {
        ;(group.suppliers || []).forEach((supplier, si) => {
          ;(supplier.fabrics || []).forEach((fabric, fi) => {
            const origFabric = original.groups?.[gi]?.suppliers?.[si]?.fabrics?.[fi]
            if (origFabric && fabric.quantity !== origFabric.quantity) {
              const itemIds = fabric.item_ids || (fabric.item_id ? [fabric.item_id] : [])
              if (itemIds.length > 0) edits.push({ item_ids: itemIds, quantity: fabric.quantity })
            }
          })
        })
      })
    }
    if (edits.length === 0) {
      editMode.value = false
      return
    }
    const res = await purchaseApi.saveFactoryEdits(edits) as unknown as SaveFactoryEditsResponse
    if (res.success) {
      edits.forEach((edit) => {
        factoryData.value?.groups?.forEach((group) => {
          ;(group.suppliers || []).forEach((supplier) => {
            ;(supplier.fabrics || []).forEach((fabric) => {
              const itemIds = fabric.item_ids || (fabric.item_id ? [fabric.item_id] : [])
              if (edit.item_ids.some((id) => itemIds.includes(id))) {
                fabric.quantity = edit.quantity
              }
            })
          })
        })
      })
      factoryOriginalData.value = cloneRaw(factoryData.value)
      try {
        const sRes = await purchaseApi.supplierSummary(orderIds.value) as unknown as SupplierSummaryData
        if (sRes.success) {
          supplierData.value = structuredClone(sRes)
          supplierOriginalData.value = structuredClone(sRes)
        }
      } catch { /* 非关键，忽略 */ }
      editMode.value = false
      return res
    }
    throw new Error(res.message || '保存失败')
  }

  function close() {
    open.value = false
    orderIds.value = []
    supplierOrder.value = []
    orderTime.value = ''
  }

  function printFactory() {
    if (!factoryData.value) return
    const tableHtml = buildFactoryHtml(factoryData.value, lossRate.value)
    printHtml(
      '工厂内部采购订单汇总',
      `${orderTimeLabel(orderTime.value)}<table><thead><tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>备品数量</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>数量</th><th>单位</th></tr></thead><tbody>${tableHtml}</tbody></table>`,
      SUMMARY_PRINT_STYLE,
    )
  }

  function printSupplier() {
    if (!supplierData.value) return
    const tableHtml = buildSupplierHtml(supplierGroups.value)
    printHtml(
      '供应商采购订单汇总',
      `${orderTimeLabel(orderTime.value)}<table><thead><tr><th>供应商</th><th>物料名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody>${tableHtml}</tbody></table>`,
      SUMMARY_PRINT_STYLE,
    )
  }

  function exportFactory() {
    if (!factoryData.value) return
    const tableHtml = buildFactoryHtml(factoryData.value, lossRate.value)
    const html = `<div style="text-align:center;margin-bottom:20px"><h2>工厂内部采购订单汇总</h2></div><table><thead><tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>备品数量</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>数量</th><th>单位</th></tr></thead><tbody>${tableHtml}</tbody></table>`
    downloadAsXls(html, '工厂内部采购汇总.xls')
  }

  async function exportSupplier() {
    if (!supplierData.value) return
    if (orderIds.value.length === 0) return
    try {
      await purchaseApi.supplierSummaryExport(orderIds.value)
    } catch (e) {
      throw new Error((e as Error).message || '导出失败')
    }
  }

  return reactive({
    open,
    tab,
    factoryData,
    supplierData,
    editMode,
    lossRate,
    orderIds,
    supplierGroups,
    openSummary,
    close,
    toggleEditMode,
    updateFactoryQty,
    applyLossRate,
    saveFactoryEdits,
    printFactory,
    printSupplier,
    exportFactory,
    exportSupplier,
  })
}
