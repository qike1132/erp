import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'
import { printHtml } from '@/utils/print'

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
  const editMode = ref(false)
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
    if (!enable) factoryData.value = JSON.parse(JSON.stringify(factoryOriginalData.value))
    editMode.value = enable
  }

  function updateFactoryQty(gi: number, si: number, fi: number, value: number) {
    factoryData.value?.groups?.[gi]?.suppliers?.[si]?.fabrics?.[fi] &&
      (factoryData.value.groups[gi].suppliers[si].fabrics[fi].quantity = value)
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
        if (sRes.success) supplierData.value = JSON.parse(JSON.stringify(sRes))
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
    const data = factoryData.value
    let tableHtml = ''
    data.groups?.forEach((group) => {
      const suppliers = group.suppliers || []
      let globalFabricIdx = 0
      suppliers.forEach((supplier) => {
        supplier.fabrics?.forEach((fabric) => {
          tableHtml += '<tr>'
          if (globalFabricIdx === 0) {
            const rowCount = suppliers.reduce((s, sup) => s + (sup.fabrics?.length || 0), 0)
            tableHtml += `<td rowspan="${rowCount}" style="border:1px solid #333;padding:8px;text-align:center;font-weight:bold;">${group.customer_name}</td>`
            tableHtml += `<td rowspan="${rowCount}" style="border:1px solid #333;padding:8px;text-align:center;">${group.product_name}</td>`
            const qty = parseFloat(String(group.product_quantity || group.order_quantity || 0))
            const qtyStr = qty % 1 === 0 ? String(parseInt(String(qty))) : qty.toFixed(2).replace(/\.?0+$/, '')
            tableHtml += `<td rowspan="${rowCount}" style="border:1px solid #333;padding:8px;text-align:center;">${qtyStr}</td>`
          }
          tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:center;">${supplier.supplier_name}</td>`
          tableHtml += `<td style="border:1px solid #333;padding:8px;">${fabric.fabric_name}</td>`
          tableHtml += `<td style="border:1px solid #333;padding:8px;">${fabric.specification || ''}</td>`
          tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${fabric.quantity} ${fabric.unit || ''}</td>`
          tableHtml += '</tr>'
          globalFabricIdx++
        })
      })
    })
    printHtml('工厂内部采购订单汇总', `<table><thead><tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody>${tableHtml}</tbody></table>`)
  }

  function printSupplier() {
    if (!supplierData.value) return
    let tableHtml = ''
    supplierGroups.value.forEach((g) => {
      g.materials.forEach((m, mi) => {
        tableHtml += '<tr>'
        if (mi === 0)
          tableHtml += `<td rowspan="${g.materials.length}" style="border:1px solid #333;padding:8px;text-align:center;font-weight:bold;">${g.supplierName}</td>`
        tableHtml += `<td style="border:1px solid #333;padding:8px;">${m.material_name}</td>`
        tableHtml += `<td style="border:1px solid #333;padding:8px;">${m.specification || ''}</td>`
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${m.total_quantity} ${m.unit || ''}</td>`
        tableHtml += '</tr>'
      })
    })
    printHtml('供应商采购订单汇总', `<table><thead><tr><th>供应商</th><th>物料名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody>${tableHtml}</tbody></table>`)
  }

  return reactive({
    open,
    tab,
    factoryData,
    supplierData,
    editMode,
    orderIds,
    supplierGroups,
    supplierGrandTotal,
    factoryGrandTotal,
    openSummary,
    close,
    toggleEditMode,
    updateFactoryQty,
    saveFactoryEdits,
    printFactory,
    printSupplier,
  })
}
