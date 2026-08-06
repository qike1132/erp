import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'
import { printHtml } from '@/utils/print'
import { fmtQty } from '@/utils/formatQty'

function buildFactoryHtml(data: { groups?: any[] }): string {
  let tableHtml = ''
  data.groups?.forEach((group: any) => {
    const suppliers = group.suppliers || []
    let globalFabricIdx = 0
    suppliers.forEach((supplier: any) => {
      supplier.fabrics?.forEach((fabric: any) => {
        tableHtml += '<tr>'
        if (globalFabricIdx === 0) {
          const rowCount = suppliers.reduce((s: number, sup: any) => s + (sup.fabrics?.length || 0), 0)
          tableHtml += `<td rowspan="${rowCount}" style="border:1px solid #333;padding:8px;text-align:center;font-weight:bold;">${group.customer_name}</td>`
          tableHtml += `<td rowspan="${rowCount}" style="border:1px solid #333;padding:8px;text-align:center;">${group.product_name}</td>`
          const qty = parseFloat(String(group.product_quantity || group.order_quantity || 0))
          const qtyStr = fmtQty(qty)
          tableHtml += `<td rowspan="${rowCount}" style="border:1px solid #333;padding:8px;text-align:center;">${qtyStr}</td>`
        }
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:center;">${supplier.supplier_name}</td>`
        tableHtml += `<td style="border:1px solid #333;padding:8px;">${fabric.fabric_name}</td>`
        tableHtml += `<td style="border:1px solid #333;padding:8px;">${fabric.specification || ''}</td>`
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${fmtQty(fabric.quantity)} ${fabric.unit || ''}</td>`
        tableHtml += '</tr>'
        globalFabricIdx++
      })
    })
  })
  return tableHtml
}

function buildSupplierHtml(groups: { supplierName: string; materials: any[] }[]): string {
  let tableHtml = ''
  groups.forEach((g) => {
    g.materials.forEach((m: any, mi: number) => {
      tableHtml += '<tr>'
      if (mi === 0)
        tableHtml += `<td rowspan="${g.materials.length}" style="border:1px solid #333;padding:8px;text-align:center;font-weight:bold;">${g.supplierName}</td>`
      tableHtml += `<td style="border:1px solid #333;padding:8px;">${m.material_name}</td>`
      tableHtml += `<td style="border:1px solid #333;padding:8px;">${m.specification || ''}</td>`
      tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${fmtQty(m.total_quantity)} ${m.unit || ''}</td>`
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

interface FabricItem {
  fabric_name: string
  specification?: string
  quantity: number
  unit?: string
  item_ids?: number[]
  item_id?: number
}

interface SupplierGroup {
  supplier_name: string
  fabrics: FabricItem[]
}

interface FactoryGroup {
  customer_name: string
  product_name: string
  product_quantity?: number
  order_quantity?: number
  suppliers: SupplierGroup[]
}

interface FactorySummaryData {
  success: boolean
  message?: string
  groups: FactoryGroup[]
}

interface MaterialItem {
  material_name: string
  specification?: string
  total_quantity: number
  unit?: string
  supplier_name?: string
}

interface SupplierSummaryData {
  success: boolean
  message?: string
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

  const supplierGrandTotal = computed(() => {
    let t = 0
    supplierGroups.value.forEach((g) => g.materials.forEach((m) => (t += parseFloat(String(m.total_quantity)) || 0)))
    return t
  })

  const factoryGrandTotal = computed(() => {
    let t = 0
    factoryData.value?.groups?.forEach((g) =>
      g.suppliers?.forEach((s) => s.fabrics?.forEach((f) => (t += parseFloat(String(f.quantity)) || 0))),
    )
    return t
  })

  async function openSummary(ids: number[]) {
    orderIds.value = ids
    const [fRes, sRes] = await Promise.all([
      purchaseApi.factorySummary(ids) as unknown as FactorySummaryData,
      purchaseApi.supplierSummary(ids) as unknown as SupplierSummaryData,
    ])
    if (!fRes.success || !sRes.success) throw new Error(fRes.message || sRes.message || '汇总失败')
    factoryData.value = JSON.parse(JSON.stringify(fRes))
    factoryOriginalData.value = JSON.parse(JSON.stringify(fRes))
    supplierData.value = JSON.parse(JSON.stringify(sRes))
    supplierOriginalData.value = JSON.parse(JSON.stringify(sRes))
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
      factoryData.value = JSON.parse(JSON.stringify(factoryOriginalData.value))
      supplierData.value = JSON.parse(JSON.stringify(supplierOriginalData.value))
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
      factoryOriginalData.value = JSON.parse(JSON.stringify(factoryData.value))
      try {
        const sRes = await purchaseApi.supplierSummary(orderIds.value) as unknown as SupplierSummaryData
        if (sRes.success) {
          supplierData.value = JSON.parse(JSON.stringify(sRes))
          supplierOriginalData.value = JSON.parse(JSON.stringify(sRes))
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
  }

  function printFactory() {
    if (!factoryData.value) return
    const tableHtml = buildFactoryHtml(factoryData.value)
    printHtml('工厂内部采购订单汇总', `<table><thead><tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody>${tableHtml}</tbody></table>`)
  }

  function printSupplier() {
    if (!supplierData.value) return
    const tableHtml = buildSupplierHtml(supplierGroups.value)
    printHtml('供应商采购订单汇总', `<table><thead><tr><th>供应商</th><th>物料名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody>${tableHtml}</tbody></table>`)
  }

  function exportFactory() {
    if (!factoryData.value) return
    const tableHtml = buildFactoryHtml(factoryData.value)
    const html = `<div style="text-align:center;margin-bottom:20px"><h2>工厂内部采购订单汇总</h2></div><table><thead><tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody>${tableHtml}</tbody></table>`
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
    supplierGrandTotal,
    factoryGrandTotal,
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
