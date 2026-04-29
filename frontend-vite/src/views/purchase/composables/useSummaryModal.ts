import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'
import { printHtml } from '@/utils/print'

export function useSummaryModal() {
  const open = ref(false)
  const tab = ref<'factory' | 'supplier'>('factory')
  const factoryData = ref<any>(null)
  const factoryOriginalData = ref<any>(null)
  const supplierData = ref<any>(null)
  const editMode = ref(false)
  const orderIds = ref<number[]>([])

  const supplierGroups = computed(() => {
    if (!supplierData.value?.materials) return []
    const groups: { supplierName: string; materials: any[] }[] = []
    const map: Record<string, any[]> = {}
    const order: string[] = []
    supplierData.value.materials.forEach((m: any) => {
      const s = m.supplier_name || '未指定供应商'
      if (!map[s]) {
        map[s] = []
        order.push(s)
      }
      map[s].push(m)
    })
    order.forEach((s) => groups.push({ supplierName: s, materials: map[s] }))
    return groups
  })

  const supplierGrandTotal = computed(() => {
    let t = 0
    supplierGroups.value.forEach((g) => g.materials.forEach((m) => (t += parseFloat(m.total_quantity) || 0)))
    return t
  })

  const factoryGrandTotal = computed(() => {
    let t = 0
    factoryData.value?.groups?.forEach((g: any) =>
      g.suppliers?.forEach((s: any) => s.fabrics?.forEach((f: any) => (t += parseFloat(f.quantity) || 0))),
    )
    return t
  })

  async function openSummary(ids: number[]) {
    orderIds.value = ids
    const [fRes, sRes] = await Promise.all([
      purchaseApi.factorySummary(ids) as any,
      purchaseApi.supplierSummary(ids) as any,
    ])
    if (!fRes.success || !sRes.success) throw new Error(fRes.message || sRes.message || '汇总失败')
    factoryData.value = JSON.parse(JSON.stringify(fRes))
    factoryOriginalData.value = JSON.parse(JSON.stringify(fRes))
    supplierData.value = JSON.parse(JSON.stringify(sRes))
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
    const edits: any[] = []
    const current = factoryData.value
    const original = factoryOriginalData.value
    if (current?.groups && original?.groups) {
      current.groups.forEach((group: any, gi: number) => {
        ;(group.suppliers || []).forEach((supplier: any, si: number) => {
          ;(supplier.fabrics || []).forEach((fabric: any, fi: number) => {
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
    const res = (await purchaseApi.saveFactoryEdits(edits)) as any
    if (res.success) {
      // 保存成功后重新获取汇总数据，确保工厂和供应商标签页同步
      const [fRes, sRes] = await Promise.all([
        purchaseApi.factorySummary(orderIds.value) as any,
        purchaseApi.supplierSummary(orderIds.value) as any,
      ])
      factoryData.value = JSON.parse(JSON.stringify(fRes))
      factoryOriginalData.value = JSON.parse(JSON.stringify(fRes))
      supplierData.value = JSON.parse(JSON.stringify(sRes))
      editMode.value = false
      return res
    }
    throw new Error(res.message || '保存失败')
  }

  function close() {
    open.value = false
    orderIds.value = []
  }

  function printFactory() {
    if (!factoryData.value) return
    const data = factoryData.value
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
            const qty = parseFloat(group.product_quantity || group.order_quantity || 0)
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
