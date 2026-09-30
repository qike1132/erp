/**
 * useFactoryTableRows —— 「工厂内部订单」页签的行模型与率/数量读写胶水。
 *
 * 2026-09-30 从 `SummaryFactoryTab.vue` **纯逻辑搬移**（函数体逐字未改、模板零改动）：
 * 唯一动机是让该 SFC 落到「单 .vue ≤ 400 行」的硬门禁之下（搬移前 427 行）。
 *
 * 行模型：优先「按 SKU 展开」（每个 SKU 一块物料）；数据不足时回退「订单级单块」——
 * 两条路径产出**同一形状**的行，模板只有一套（零回归靠回退路径保证）。
 *
 * 按 SKU 模式下每行携带落库坐标 coord，率/数量的读写仍走既有按坐标的机制，
 * 因此「同物料跨 SKU 联动」天然成立（同一坐标 = 同一份状态）。
 *
 * 依赖方向（**务必保持单向**）：本模块从 `useSummaryModal`（类型 + 既有纯函数）与
 * `perSkuRows`（Task 2 冻结行模型）取值；二者均不反向依赖本模块，无环。
 */
import { computed } from 'vue'
import type { EmitFn } from 'vue'
import { factoryQtyDisplayValue, buildSkuDisplayLines } from './useSummaryModal'
import { buildPerSkuRows, materialKeyOf } from './perSkuRows'
import type { PerSkuRow } from './perSkuRows'
import type { FactorySummaryData, FactoryGroup, FabricItem, SkuDisplayLine } from './useSummaryModal'

/** 组件 props（自 `SummaryFactoryTab.vue` 的 `defineProps` 逐字抽出，组件与本模块两处共用）。 */
export interface FactoryTabProps {
  factoryData: FactorySummaryData
  editMode: boolean
  lossRate: number
  orderCount: number
  /** 损耗率自动落库的可见反馈状态（缺省视为 idle；由 useSummaryModal 提供） */
  lossRateSaveState?: 'idle' | 'saving' | 'saved' | 'error'
  /** 各单损耗率不一致（缺省视为 false；由 useSummaryModal 提供）→ 输入框旁提示 */
  lossRateMixed?: boolean
  /** 每个布料行当前的损耗率，形状 [gi][si][fi]；缺省回退 lossRate */
  fabricLossRates?: number[][][]
  /** 每个布料行内各明细损耗率是否不一致，形状 [gi][si][fi] */
  fabricLossRateMixed?: boolean[][][]
  /** 每个分组的订单级损耗率（「备品数量」列的唯一口径），形状 [gi]；缺省回退 lossRate */
  groupSpareRates?: number[]
}

/** 组件 emit（自 `SummaryFactoryTab.vue` 的 `defineEmits` 逐字抽出，组件与本模块两处共用）。 */
export type FactoryTabEmit = {
  close: []
  toggleEditMode: [enable: boolean]
  saveEdits: []
  updateQty: [gi: number | string, si: number | string, fi: number | string, value: string]
  /** 统一损耗率输入的归一化值（已夹取到 0..1000）。防抖由父组件负责。 */
  lossRateInput: [rate: number]
  /** 单个布料行损耗率输入的归一化值（已夹取到 0..1000）。防抖由父组件负责。 */
  fabricLossRateInput: [gi: number, si: number, fi: number, rate: number]
  exportFactory: []
  printFactory: []
}

type RowItem = {
  gi: number
  row: PerSkuRow
  group: FactoryGroup
  /** 回退模式下由订单级物料合成的行；按 SKU 模式下恒为 null */
  legacy: { si: number; fi: number; fabric: FabricItem; supplierName: string } | null
}

export function useFactoryTableRows(props: FactoryTabProps, emit: EmitFn<FactoryTabEmit>) {
  /** 取第 gi/si/fi 个布料行当前损耗率；未提供时回退统一损耗率。 */
  function rateForFabric(gi: number, si: number, fi: number): number {
    const v = props.fabricLossRates?.[gi]?.[si]?.[fi]
    return typeof v === 'number' && Number.isFinite(v) ? v : props.lossRate
  }

  /**
   * 该分组的订单级率（「备品数量」列的唯一口径）：分组值优先，缺省回退顶部「统一损耗率」。
   * 注意：**不读 `fabricLossRates`** —— 逐布料行的材料损耗率不得影响备品（见文件头说明）。
   */
  function spareRateForGroup(gi: number): number {
    const v = props.groupSpareRates?.[gi]
    return typeof v === 'number' && Number.isFinite(v) ? v : props.lossRate
  }

  /**
   * 每个汇总分组的逐 SKU 展示行（按 gi 索引，供「产品名称 / 订单数量 / 备品数量」三列共用）。
   */
  const groupSkuLines = computed<SkuDisplayLine[][]>(() =>
    (props.factoryData?.groups || []).map((g, gi) => buildSkuDisplayLines(g, spareRateForGroup(gi))),
  )

  /**
   * 行模型：优先「按 SKU 展开」（每个 SKU 一块物料）；数据不足时回退「订单级单块」——
   * 两条路径产出**同一形状**的行，模板只有一套（零回归靠回退路径保证）。
   *
   * 按 SKU 模式下每行携带落库坐标 coord，率/数量的读写仍走既有按坐标的机制，
   * 因此「同物料跨 SKU 联动」天然成立（同一坐标 = 同一份状态）。
   */
  const flatRows = computed<RowItem[]>(() => {
    const groups = props.factoryData?.groups || []
    const out: RowItem[] = []

    groups.forEach((group, gi) => {
      const perSku = buildPerSkuRows(group, spareRateForGroup(gi))
      if (perSku.length > 0) {
        perSku.forEach((row) => out.push({ gi, row, group, legacy: null }))
        return
      }
      // 回退：订单级物料 + 逐 SKU 名堆叠（与改动前逐字一致）
      const suppliers = group.suppliers || []
      const totalRows = suppliers.reduce((s, sup) => s + (sup.fabrics?.length || 0), 0)
      let index = 0
      suppliers.forEach((supplier, si) => {
        ;(supplier.fabrics || []).forEach((fabric, fi) => {
          const lines = groupSkuLines.value[gi] || []
          out.push({
            gi, group, legacy: { si, fi, fabric, supplierName: supplier.supplier_name },
            row: {
              skuIdx: 0,
              cellLines: lines,
              isFirstSkuRow: index === 0,
              skuRowSpan: totalRows,
              isFirstSupplierRow: fi === 0,
              supplierRowSpan: supplier.fabrics?.length || 0,
              supplierName: supplier.supplier_name,
              materialName: fabric.fabric_name,
              specification: fabric.specification || '',
              unit: fabric.unit || '',
              baseQuantity: parseFloat(String(fabric.quantity)) || 0,
              coord: { si, fi },
              itemIds: fabric.item_ids || (fabric.item_id ? [fabric.item_id] : []),
              noBom: false,
            },
          })
          index++
        })
      })
    })
    return out
  })

  /** 该行的落库坐标：按 SKU 模式下取 row.coord；回退模式取 legacy 坐标。 */
  function rowCoord(r: RowItem): { si: number; fi: number } | null {
    return r.legacy ? { si: r.legacy.si, fi: r.legacy.fi } : r.row.coord
  }

  /** 每个组的总行数（客户列 rowspan）；两种模式同一算法。 */
  const groupRowCounts = computed<number[]>(() => {
    const counts: number[] = []
    flatRows.value.forEach((r) => { counts[r.gi] = (counts[r.gi] || 0) + 1 })
    return counts
  })

  /** 每个组第一个数据行在 flatRows 里的下标（客户列 rowspan 的锚点）。 */
  const groupFirstRowIndex = computed<Record<number, number>>(() => {
    const first: Record<number, number> = {}
    flatRows.value.forEach((r, ri) => { if (first[r.gi] === undefined) first[r.gi] = ri })
    return first
  })

  function isGroupFirstRow(gi: number, ri: number): boolean {
    return ri === groupFirstRowIndex.value[gi]
  }

  /** 该行的率：按坐标取（只读行无坐标 → 0，模板不会给输入框）。 */
  function rowRate(item: RowItem): number {
    const c = rowCoord(item)
    return c ? rateForFabric(item.gi, c.si, c.fi) : 0
  }

  /** 该行的基准数量：回退模式取落库布料数量；按 SKU 模式取后端给的基准量。 */
  function rowBaseQty(item: RowItem): number {
    return item.legacy
      ? parseFloat(String(item.legacy.fabric.quantity)) || 0
      : item.row.baseQuantity
  }

  /** 编辑态数量输入框值（精确加放值，保存时由 updateFactoryQty 反推真值）。 */
  function editRowQty(item: RowItem): number {
    const c = rowCoord(item)
    return c ? factoryQtyDisplayValue(rowBaseQty(item), rateForFabric(item.gi, c.si, c.fi), true) : rowBaseQty(item)
  }

  /** 非编辑态数量展示值（加放后向上取整）。 */
  function displayRowQty(item: RowItem): number {
    const c = rowCoord(item)
    return c ? factoryQtyDisplayValue(rowBaseQty(item), rateForFabric(item.gi, c.si, c.fi), false) : rowBaseQty(item)
  }

  /** 每个物料键在多少个行里出现（>1 ⇒ 跨 SKU 共用同一行明细，编辑会联动）。 */
  const sharedMaterialKeys = computed<Set<string>>(() => {
    const counts = new Map<string, number>()
    flatRows.value.forEach((r) => {
      if (r.legacy || r.row.noBom) return
      const k = materialKeyOf({
        supplier_name: r.row.supplierName, material_name: r.row.materialName,
        specification: r.row.specification, unit: r.row.unit,
      })
      counts.set(k, (counts.get(k) || 0) + 1)
    })
    const shared = new Set<string>()
    counts.forEach((n, k) => { if (n > 1) shared.add(k) })
    return shared
  })

  /** 编辑态提示文案：该物料跨 SKU 共用一行 ⇒ 明示改动会影响所有 SKU（spec §4.3 的可见性要求）。 */
  function sharedMaterialTitle(item: RowItem): string {
    if (item.legacy || item.row.noBom) return ''
    const k = materialKeyOf({
      supplier_name: item.row.supplierName, material_name: item.row.materialName,
      specification: item.row.specification, unit: item.row.unit,
    })
    return sharedMaterialKeys.value.has(k)
      ? '该物料各 SKU 共用采购明细中的同一行，改动会影响所有 SKU'
      : ''
  }

  /** 该行行率是否「各明细不一致」（落库快照 loss_rate_mixed）；只读/占位行恒 false。 */
  function isRowRateMixed(item: RowItem): boolean {
    const c = rowCoord(item)
    if (!c) return false
    return props.fabricLossRateMixed?.[item.gi]?.[c.si]?.[c.fi] === true
  }

  /** 率输入：按坐标提交（沿用既有 emit，不新增契约）。 */
  function onRowRateInput(item: RowItem, e: Event): void {
    const c = rowCoord(item)
    if (!c) return
    const val = parseFloat((e.target as HTMLInputElement).value)
    emit('fabricLossRateInput', item.gi, c.si, c.fi, Number.isNaN(val) || val < 0 ? 0 : Math.min(val, 1000))
  }

  /** 数量提交：按坐标提交 —— 同一物料的多行共享同一坐标，故联动天然成立。 */
  function onRowQtyChange(item: RowItem, e: Event): void {
    const c = rowCoord(item)
    if (!c) return
    emit('updateQty', item.gi, c.si, c.fi, (e.target as HTMLInputElement).value)
  }

  return {
    flatRows,
    groupRowCounts,
    isGroupFirstRow,
    rowCoord,
    rowRate,
    editRowQty,
    displayRowQty,
    sharedMaterialTitle,
    isRowRateMixed,
    onRowRateInput,
    onRowQtyChange,
  }
}
