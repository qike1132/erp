import { ref, computed, reactive, toRaw } from 'vue'
import { purchaseApi } from '@/api'
import { escapeHtml, printHtml } from '@/utils/print'
import { fmtQty } from '@/utils/formatQty'
import { calcSpareQuantity, summaryMaterialKey, magnifyByLossRate, ceilMagnifiedByLossRate, buildPerSkuRows, computeQuantityDiff, buildStoredRows } from './perSkuRows'
import type { PerSkuRow } from './perSkuRows'

// 这些纯函数已移入 perSkuRows.ts —— 本模块要用它的 buildPerSkuRows，
// 若此处再定义它们就构成互相 import（Vite/vitest 下会拿到 undefined 绑定）。
// 重导出仅为兼容既有导入路径，行为逐字不变。
export { calcSpareQuantity, summaryMaterialKey, magnifyByLossRate, ceilMagnifiedByLossRate } from './perSkuRows'

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
 * 订单数量取数：产品数量优先，缺失时回退订单数量。
 * 非法/缺失输入兜底 0。屏幕表格、打印预览、Excel 导出共用这一处来源。
 */
export function getGroupOrderQty(group: FactoryGroup): number {
  const v = parseFloat(String(group.product_quantity || group.order_quantity || 0))
  return Number.isNaN(v) ? 0 : v
}

// `magnifyByLossRate` / `ceilMagnifiedByLossRate` 已移入 `perSkuRows.ts`
// （`buildStoredRows` 需要它们做加放取整，而那个模块必须是叶子纯函数）；
// 由文件顶部的 re-export 保持既有导入路径可用，行为逐字不变。

/**
 * 工厂页签「数量」列的展示值（**工厂表 / 供应商表 / 打印 / 导出共用的唯一入口**）。
 *
 * - 非编辑态：按该行损耗率加放后向上取整（与工厂表可见整数一致）；
 * - 编辑态：返回精确加放值，与「自定义编辑」输入框加载值一致（便于保存时无损反推真值）。
 *
 * 供应商页签的「数量」在同一份工厂数据上调用本函数派生，故两侧天然同源：
 * 用户自定义调整工厂数量或逐行损耗率后，切到供应商页签立即看到同一数值（实时一致）。
 */
export function factoryQtyDisplayValue(baseQty: number, lossRate: number, editing: boolean): number {
  return editing ? magnifyByLossRate(baseQty, lossRate) : ceilMagnifiedByLossRate(baseQty, lossRate)
}

/**
 * 数量展示文本（供应商页签屏幕 / 打印 / 导出共用）：最多 2 位小数并消除浮点尾差。
 *
 * 与工厂页「数量」列同源派生值配合使用：**不额外补 1 位小数**，否则
 * 「工厂编辑态 10.05 → 供应商 10.1」这类舍入会造成两页签假性不一致。
 */
export function qtyDisplayText(val: unknown): string {
  const n = parseFloat(String(val ?? 0))
  if (!Number.isFinite(n)) return '0'
  return String(Math.round(n * 100) / 100)
}

/**
 * 损耗加放的逆运算：把「数量列展示的订单用量（已按损耗率放大）」还原为落库真值。
 *
 * 自定义编辑进入编辑态时输入框加载展示值（如 110），保存时用本函数按该行损耗率
 * 反推出原始布料用量（如 110 / (1 + 100‰) = 100），保证保存后仍按同一损耗率
 * 重算为 110，不产生复利、也不会把展示值误固化为原始数量。
 */
export function unmagnifyByLossRate(total: number, lossRate: number): number {
  const v = Number.isFinite(total) ? total : 0
  const r = Number.isFinite(lossRate) ? lossRate : 0
  const factor = 1 + r / 1000
  if (factor <= 0) return v
  return Math.round((v / factor) * 100) / 100
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

/**
 * 工厂汇总表的表头（**屏幕 / 打印预览 / Excel 导出共用同一列定义**）。
 *
 * 屏幕侧的表头在 `SummaryFactoryTab.vue`（同列同序）；此处仅供打印 / 导出拼装，
 * 抽成常量是为了消除原先 printFactory / exportFactory 两处逐字重复的 9 列表头
 * —— 加列时只改一处，避免「屏幕加了、打印没加」。
 */
export const FACTORY_TABLE_HEAD =
  '<tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>备品数量</th><th>供应商</th>' +
  '<th>布料名称</th><th>规格型号</th><th>损耗率</th><th>数量</th><th>单位</th></tr>'

/**
 * 「按 SKU 展开」的组渲染：每 SKU 一块物料行，组末附差异对照块。
 *
 * 左侧三列（产品名称 / 订单数量 / 备品数量）按 SKU 块合并（rowspan = 该块行数），
 * 客户列跨**整组**（只在组首行渲染一次）—— 与屏幕 `SummaryFactoryTab.vue` 同构。
 * 返回空串表示数据不足（旧后端 / 无 BOM），调用方回退订单级单块（零回归）。
 */
function buildPerSkuGroupHtml(
  group: FactoryGroup, gi: number, spareRate: number, lossRate: number, fabricRates?: number[][][],
): string {
  const perSkuRows = buildPerSkuRows(group, spareRate)
  if (perSkuRows.length === 0) return ''

  let tableHtml = ''
  let cursor = 0
  let blockNo = 0
  while (cursor < perSkuRows.length) {
    const skuIdx = perSkuRows[cursor]!.skuIdx
    const block: PerSkuRow[] = []
    while (cursor < perSkuRows.length && perSkuRows[cursor]!.skuIdx === skuIdx) {
      block.push(perSkuRows[cursor]!)
      cursor++
    }
    block.forEach((row, i) => {
      tableHtml += '<tr>'
      if (i === 0) {
        // 客户列：整组只出现一次（rowspan = 该组全部行数）；误写成「每块都渲染」会与表头错位。
        if (blockNo === 0) {
          tableHtml += `<td rowspan="${perSkuRows.length}" style="font-weight:bold;">${escapeHtml(group.customer_name)}</td>`
        }
        const line = row.cellLines[0]
        tableHtml += `<td rowspan="${block.length}">${escapeHtml(line?.name || '')}</td>`
        tableHtml += `<td rowspan="${block.length}">${escapeHtml(fmtQty(line?.qty ?? 0))}</td>`
        tableHtml += `<td rowspan="${block.length}">${escapeHtml(fmtQty(line?.spare ?? 0))}</td>`
      }
      if (row.noBom) {
        // 占位行：供应商 + 之后 5 列 = 6 列（左侧三列已在上方补齐）
        tableHtml += '<td colspan="6" style="color:#8e8e93;">无 BOM 明细</td>'
        tableHtml += '</tr>'
        return
      }
      if (row.isFirstSupplierRow) {
        tableHtml += `<td rowspan="${row.supplierRowSpan}" style="font-weight:bold;">${escapeHtml(row.supplierName)}</td>`
      }
      tableHtml += `<td>${escapeHtml(row.materialName)}</td>`
      tableHtml += `<td>${escapeHtml(row.specification)}</td>`
      if (row.coord) {
        const rowRate = fabricRates?.[gi]?.[row.coord.si]?.[row.coord.fi] ?? lossRate
        tableHtml += `<td>${escapeHtml(String(rowRate))}</td>`
        tableHtml += `<td>${ceilMagnifiedByLossRate(row.baseQuantity, rowRate)}</td>`
      } else {
        // 无落库坐标（BOM 生成后新增的物料）：**必须与屏幕同源** —— 屏幕
        // `SummaryFactoryTab.vue` 对无坐标行渲染率 '—'、数量取基准量（不加放）。
        // 曾在此回退 lossRate 并加放，导致同一张单屏幕「— / 20」而打印「10 / 21」。
        tableHtml += '<td>—</td>'
        tableHtml += `<td>${row.baseQuantity}</td>`
      }
      tableHtml += `<td>${escapeHtml(row.unit)}</td>`
      tableHtml += '</tr>'
    })
    blockNo++
  }

  // 差异对照块：与屏幕同源（打印件不能对差异保持沉默）。
  tableHtml += buildDiffBlockHtml(group, perSkuRows, spareRate)
  return tableHtml
}

/**
 * 差异对照块（打印/导出版，结构镜像屏幕 `SummaryDiffBlock.vue`）。
 *
 * 列数必须仍是 **10**：标签跨「客户/产品名称/订单数量/备品数量」4 列（`colspan=4`，
 * 跨本块全部行）+ 供应商（段内 rowspan）+ 布料名称/规格型号/损耗率/数量/单位 5 格。
 * 行数据来自 `buildStoredRows` —— 与屏幕**同一个纯函数**，故两边天然同构：
 * 损耗率取该落库行快照率、数量为按该率加放派生值。无差异时返回空串（不渲染）。
 */
function buildDiffBlockHtml(
  group: FactoryGroup, perSkuRows: PerSkuRow[], spareRate: number,
): string {
  const diffs = computeQuantityDiff(group, perSkuRows)
  if (diffs.length === 0) return ''

  const detail = diffs
    .map((d) => `${d.materialName}（推算 ${fmtQty(d.perSku)} / 实际 ${fmtQty(d.stored)}）`)
    .join('、')
  let tableHtml = `<tr><td colspan="10" style="background:#fffaf0;color:#7a4a00;">⚠ 本条「实际下单」含手工调整，与上方按 BOM 推算的明细不一致：${escapeHtml(detail)}</td></tr>`

  const storedRows = buildStoredRows(group, () => spareRate)
  storedRows.forEach((r, i) => {
    tableHtml += '<tr>'
    if (i === 0) {
      tableHtml += `<td colspan="4" rowspan="${storedRows.length}" style="font-weight:bold;background:#fffaf0;color:#7a4a00;">实际下单（含手工调整）</td>`
    }
    if (r.isSupplierFirst) {
      tableHtml += `<td rowspan="${r.supplierSpan}" style="background:#fffaf0;">${escapeHtml(r.supplierName)}</td>`
    }
    tableHtml += `<td style="background:#fffaf0;">${escapeHtml(r.fabricName)}</td>`
    tableHtml += `<td style="background:#fffaf0;">${escapeHtml(r.specification)}</td>`
    tableHtml += `<td style="background:#fffaf0;">${escapeHtml(fmtQty(r.rate))}</td>`
    tableHtml += `<td style="background:#fffaf0;">${r.displayQuantity}</td>`
    tableHtml += `<td style="background:#fffaf0;">${escapeHtml(r.unit)}</td>`
    tableHtml += '</tr>'
  })
  return tableHtml
}

export function buildFactoryHtml(
  data: FactorySummaryData, lossRate: number, fabricRates?: number[][][], groupRates?: number[],
): string {
  let tableHtml = ''
  data.groups?.forEach((group, gi) => {
    const suppliers: SupplierGroup[] = group.suppliers || []
    // 备品口径（A）：只用该分组的订单级率；分组未提供时回退传入的统一率
    const groupRate = groupRates?.[gi]
    const spareRate = typeof groupRate === 'number' && Number.isFinite(groupRate) ? groupRate : lossRate

    // 优先「按 SKU 展开」：每 SKU 一块物料 + 组末差异对照块；数据不足则回退订单级单块。
    const perSkuHtml = buildPerSkuGroupHtml(group, gi, spareRate, lossRate, fabricRates)
    if (perSkuHtml !== '') {
      tableHtml += perSkuHtml
      return
    }

    let globalFabricIdx = 0
    suppliers.forEach((supplier, si: number) => {
      const fabricCount = supplier.fabrics?.length || 0
      supplier.fabrics?.forEach((fabric, fi: number) => {
        const rowRate = fabricRates?.[gi]?.[si]?.[fi]
        const rate = typeof rowRate === 'number' && Number.isFinite(rowRate) ? rowRate : lossRate
        tableHtml += '<tr>'
        if (globalFabricIdx === 0) {
          const rowCount = suppliers.reduce((s: number, sup: SupplierGroup) => s + (sup.fabrics?.length || 0), 0)
          tableHtml += `<td rowspan="${rowCount}" style="font-weight:bold;">${escapeHtml(group.customer_name)}</td>`
          // 产品名称 / 订单数量 / 备品数量：与屏幕表格同源逐 SKU 分行（单 SKU 时即一行）。
          const skuLines = buildSkuDisplayLines(group, spareRate)
          const cell = (pick: (l: SkuDisplayLine) => string) =>
            skuLines
              .map((l) => (l.isTotal ? `<strong>${escapeHtml(pick(l))}</strong>` : escapeHtml(pick(l))))
              .join('<br>')
          tableHtml += `<td rowspan="${rowCount}">${cell((l) => l.name)}</td>`
          tableHtml += `<td rowspan="${rowCount}">${cell((l) => fmtQty(l.qty))}</td>`
          tableHtml += `<td rowspan="${rowCount}">${cell((l) => fmtQty(l.spare))}</td>`
        }
        if (fi === 0) {
          tableHtml += `<td rowspan="${fabricCount}" style="font-weight:bold;">${escapeHtml(supplier.supplier_name)}</td>`
        }
        tableHtml += `<td>${escapeHtml(fabric.fabric_name)}</td>`
        tableHtml += `<td>${escapeHtml(fabric.specification || '')}</td>`
        tableHtml += `<td>${escapeHtml(String(rate))}</td>`
        tableHtml += `<td>${escapeHtml(String(ceilMagnifiedByLossRate(parseFloat(String(fabric.quantity)) || 0, rate)))}</td>`
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
      tableHtml += `<td>${escapeHtml(qtyDisplayText(m.total_quantity))}</td>`
      tableHtml += `<td>${escapeHtml(m.unit || '')}</td>`
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
  /** 该布料行已落库的材料损耗率快照（千分之几）；null/缺省表示未单独配置 */
  loss_rate?: number | null
  /** 该布料行内各明细损耗率不一致 */
  loss_rate_mixed?: boolean
}

export interface SupplierGroup {
  supplier_name: string
  fabrics: FabricItem[]
}

/** 汇总分组的逐 SKU 展示明细（后端 factory-summary 返回） */
export interface SkuLine {
  product_name: string
  product_barcode?: string
  order_qty: number
  /**
   * 该 SKU 自己的物料明细（后端按 SKU 展开的**基准量** = BOM 单件用量 × 该 SKU 数量）。
   * 缺省/为空表示后端未提供（旧后端、无 BOM、SKU 名解析不出）→ 前端回退订单级单块。
   */
  materials?: { supplier_name: string; material_name: string; specification: string; unit: string; quantity: number }[]
}

/** 逐 SKU 展示行：屏幕表格 / 打印预览 / Excel 导出共用同一形状 */
export interface SkuDisplayLine {
  name: string
  qty: number
  /** 该行备品数量（口径 A：ceil(数量 × 订单级率‰)；多 SKU 时逐 SKU 取整后求和） */
  spare: number
  /** 订单级「合计」子行（仅多 SKU 时追加） */
  isTotal: boolean
}

/**
 * 逐 SKU 展示行 —— 屏幕「产品名称 / 订单数量 / 备品数量」三列、打印预览、Excel 导出
 * **共用这一处来源**，保证三者逐字一致。
 *
 * 口径（重要）：
 * - 逐 SKU 只有**订单数量**是权威的（来自 `purchase_order_sku` 快照）；
 * - **备品数量只用传入的订单级率 `rate`**（口径 A）：逐 SKU `ceil(qty × rate‰)`，
 *   多 SKU 时**逐 SKU 取整后求和**作为「合计」子行的备品 —— 与后端
 *   `resync_po_sku_spare` 及 /beile-order 的逐 SKU 口径一致；若改成「先求和再取整」，
 *   两页数字会出现对不上（如 3×1 件 @500‰：逐 SKU 3 件 vs 先求和 2 件）；
 * - **逐布料行（自定义）损耗率不参与备品** —— 那是材料损耗量级，见 `calcSpareQuantity`；
 * - 多 SKU 时追加一行「合计」，合计**数量**取**订单级真值** `getGroupOrderQty(group)`
 *   （= 采购单 `product_quantity`），不依赖逐 SKU 之和，避免快照与主表不一致时
 *   展示出「对不上」的数字；
 * - **物料数量在采购单侧是跨 SKU 合并值，无法拆分到 SKU**，故「布料名称 / 规格 / 数量」
 *   仍是订单级展示（与 /beile-order 已确立的口径一致，不编造无法追溯的数）；
 * - 单 SKU 或后端未返回 `skus` 时，只产出一行订单级数据 —— 与改动前逐字一致（零回归）。
 */
export function buildSkuDisplayLines(group: FactoryGroup, rate: number): SkuDisplayLine[] {
  const total = getGroupOrderQty(group)
  const skus = group.skus || []
  if (skus.length <= 1) {
    return [{
      name: group.product_name || '',
      qty: total,
      spare: calcSpareQuantity(total, rate),
      isTotal: false,
    }]
  }
  const lines: SkuDisplayLine[] = skus.map((s) => {
    const qty = parseFloat(String(s.order_qty ?? 0)) || 0
    return { name: s.product_name || '', qty, spare: calcSpareQuantity(qty, rate), isTotal: false }
  })
  // 合计备品 = 逐 SKU 取整后求和（与后端逐 SKU 口径一致，见函数头注释）
  lines.push({
    name: '合计',
    qty: total,
    spare: lines.reduce((sum, l) => sum + l.spare, 0),
    isTotal: true,
  })
  return lines
}

export interface FactoryGroup {
  customer_name: string
  product_name: string
  product_quantity?: number
  order_quantity?: number
  suppliers: SupplierGroup[]
  /** 逐 SKU 明细；旧后端不返回 → undefined（前端按订单级单行降级） */
  skus?: SkuLine[]
  /** 该工序分组（客户 × 产品）涉及的采购单 ID，用于按工序保存损耗率 */
  order_ids?: number[]
  /** 该工序分组已落库的损耗率快照；0 为合法已记录值，null/缺省表示未记录 */
  spare_rate?: number | null
  /** 该工序分组内各采购单损耗率不一致 */
  spare_rate_mixed?: boolean
}

/** 工厂内部采购汇总响应（/purchase/factory-summary） */
export interface FactorySummaryData {
  success: boolean
  message?: string
  /** 选中订单数（模板展示用） */
  order_count?: number
  /**
   * 本次汇总所涉采购单「已落库」的损耗率快照（后端 get_factory_order_summary 返回）。
   * 0 是合法的「已记录」值；未记录为 null / 缺省。旧后端不返回此字段 → undefined。
   */
  spare_rate?: number | null
  /** 各单损耗率不一致：true 时 spare_rate 恒为 null，供 UI 提示「各订单损耗率不一致」 */
  spare_rate_mixed?: boolean
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

/**
 * 从汇总数据播种各分组的订单级率（分组未单设时回退汇总级 `spare_rate`）。
 * 供 openSummary 首播与「取消编辑」回滚共用，保证两处口径一致。
 */
export function seedGroupSpareRates(data: FactorySummaryData | null): number[] {
  const fallback = typeof data?.spare_rate === 'number' && Number.isFinite(data.spare_rate)
    ? data.spare_rate
    : 0
  return (data?.groups || []).map((g) =>
    typeof g.spare_rate === 'number' && Number.isFinite(g.spare_rate) ? g.spare_rate : fallback,
  )
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
  /**
   * 服务端**当前已落库**的损耗率基线（openSummary 时按汇总接口的 spare_rate 播种，
   * 自动落库成功后同步更新）。供「取消编辑」时恢复到真值，而非错误地清零。
   */
  const persistedLossRate = ref(0)
  // 2026-10-18 OCR 评审：lossRateMixed 也需要「打开时的基线」，否则取消编辑
  // 会把「各单不一致」提示错误地恢复/抹掉。
  const persistedLossRateMixed = ref(false)
  /** 各单损耗率不一致（后端 spare_rate_mixed）：true 时 lossRate 显示 0 不代表「未设置过」 */
  const lossRateMixed = ref(false)
  /** 损耗率是否被用户交互过：仅在交互过时随动作提交 spare_rate（避免用 0 覆盖已存值） */
  const lossRateTouched = ref(false)
  const orderIds = ref<number[]>([])
  const supplierOrder = ref<string[]>([])
  /** 订单时间（选中订单中最晚 create_time，回退 order_date；由 openSummary 调用方传入） */
  const orderTime = ref('')
  /**
   * 损耗率自动落库的可见反馈状态。
   * idle：未发起 / 已复位；saving：有请求在途；saved：最后一次输入已成功落库；error：任一次发送失败。
   */
  const lossRateSaveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
  /** 每个布料行（物料 + 规格 + 单位）当前的损耗率展示值，形状 [gi][si][fi] */
  const fabricLossRates = ref<number[][][]>([])
  /**
   * 每个分组的**订单级损耗率**（形状 [gi]）—— 备品口径 A 的唯一来源。
   *
   * - 播种：openSummary 从 `group.spare_rate`（缺省回退汇总级 `spare_rate`）取；
   * - 变更：顶部「统一损耗率」批量为全部分组下发同一个值（与逐行率同一次交互）；
   * - **逐布料行（自定义）损耗率不写本状态** —— 那是材料损耗量级（40%-100%），
   *   与备品率（0.5%-3%）不是一个量级；混用会虚高（生产实证 30 倍）。
   */
  const groupSpareRates = ref<number[]>([])
  /** 每个布料行已落库的损耗率基线（取消编辑时恢复） */
  const fabricPersistedRates = ref<number[][][]>([])
  /** 每个布料行内各明细损耗率是否不一致 */
  const fabricLossRateMixed = ref<boolean[][][]>([])
  // 打开弹窗时的 mixed 基线（2026-10-17 审计 AUD-13：取消编辑要回到它，
  // 此前只有自赋值空操作，逐行率回了基线而 mixed 标记没有）
  const fabricLossRateMixedPersisted = ref<boolean[][][]>([])
  /** 每个布料行对应的明细 item_ids，用于按行保存损耗率 */
  const fabricItemIds = ref<number[][][][]>([])

  /**
   * 损耗率自动落库的串行化状态（**实例闭包内**，禁止模块级全局，避免多实例互相干扰）：
   * - drainPromise：当前「排空循环」的句柄，非空表示有请求在途 / 队列待排空；
   * - pendingRate：在途期间累积的**最新**待发率（中间值允许合并跳过）。
   */
  let drainPromise: Promise<void> | null = null
  let pendingRate: number | null = null
  /** 按布料行串行化损耗率保存，避免同一行快速连续输入产生乱序覆盖 */
  const fabricDrainPromises = new Map<string, Promise<void>>()
  const fabricPendingRates = new Map<string, number>()

  /**
   * 工厂页签「数量」列的当前展示值索引：key = (供应商,物料,规格,单位) → 汇总数量。
   *
   * 供应商页签的「数量」直接由此派生（见 supplierGroups），保证与工厂页签**同源**：
   * - 同一损耗率、同一取整口径，不再出现「工厂已加放、供应商未加放」的口径差；
   * - 用户自定义编辑工厂数量 / 逐行损耗率后，供应商页签立即反映同一数值（实时一致）。
   *
   * 编辑态取精确加放值（与输入框一致），非编辑态取向上取整值（与工厂表可见值一致）；
   * 多分组（客户 × 产品）落到同一物料键时按各行展示值累加，与工厂表可见行相加一致。
   */
  const factoryQtyByMaterialKey = computed(() => {
    const map = new Map<string, number>()
    factoryData.value?.groups?.forEach((group, gi) => {
      ;(group.suppliers || []).forEach((supplier, si) => {
        ;(supplier.fabrics || []).forEach((fabric, fi) => {
          const key = summaryMaterialKey(supplier.supplier_name, fabric.fabric_name, fabric.specification, fabric.unit)
          const baseQty = parseFloat(String(fabric.quantity)) || 0
          const qty = factoryQtyDisplayValue(baseQty, rateForFabric(gi, si, fi), editMode.value)
          // 累加后再四舍五入到 2 位小数：多分组落到同一物料键时消除浮点尾差，
          // 使展示值与工厂表「各行相加」严格逐字一致。
          map.set(key, Math.round(((map.get(key) || 0) + qty) * 100) / 100)
        })
      })
    })
    return map
  })

  const supplierGroups = computed(() => {
    if (!supplierData.value?.materials) return []
    const groups: { supplierName: string; materials: MaterialItem[] }[] = []
    const map: Record<string, MaterialItem[]> = {}
    const newOrder: string[] = []
    const factoryQty = factoryQtyByMaterialKey.value
    supplierData.value.materials.forEach((m) => {
      const s = m.supplier_name || '未指定供应商'
      if (!map[s]) {
        map[s] = []
        newOrder.push(s)
      }
      // 展示副本：与工厂页签「数量」列同源（见 factoryQtyByMaterialKey），**不写回 supplierData** ——
      // 原始数量是落库唯一真值；工厂侧无对应行（异常数据）时回退到按统一损耗率放大原始值。
      const derived = factoryQty.get(summaryMaterialKey(m.supplier_name, m.material_name, m.specification, m.unit))
      map[s].push({
        ...m,
        total_quantity: derived !== undefined
          ? derived
          : magnifyByLossRate(parseFloat(String(m.total_quantity)) || 0, lossRate.value),
      })
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

  /** 布料行稳定键：同一 (gi,si,fi) 在数组重排前后保持一致，供按行串行化。 */
  function fabricKey(gi: number, si: number, fi: number): string {
    return `${gi}-${si}-${fi}`
  }

  /**
   * 取第 gi/si/fi 个布料行当前损耗率。
   * 逐行率缺失/非法时回退「统一损耗率」，与工厂表「数量」列口径一致
   * （useFactoryTableRows.rateForFabric 同样回退 lossRate），保证展示与保存反推同源。
   */
  function rateForFabric(gi: number, si: number, fi: number): number {
    const v = fabricLossRates.value?.[gi]?.[si]?.[fi]
    return typeof v === 'number' && Number.isFinite(v) ? v : lossRate.value
  }

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
    // 逐布料行播种：优先取明细 loss_rate（有值则为该行已落库配置），
    // 否则回退到分组/订单级 spare_rate，保证旧订单零回归。
    const groups = fRes.groups || []
    const fallbackRate = typeof fRes.spare_rate === 'number' && Number.isFinite(fRes.spare_rate) ? fRes.spare_rate : 0
    // 分组订单级率（备品口径 A 的来源）：与逐行率同一次播种，规则收敛到 seedGroupSpareRates
    const seedGroupRates = seedGroupSpareRates(fRes)
    groupSpareRates.value = seedGroupRates
    const rates: number[][][] = []
    const persistedRates: number[][][] = []
    const mixedRates: boolean[][][] = []
    const itemIds: number[][][][] = []
    groups.forEach((g, gi) => {
      const groupFallback = seedGroupRates[gi] ?? fallbackRate
      const gRates: number[][] = []
      const gPersisted: number[][] = []
      const gMixed: boolean[][] = []
      const gItemIds: number[][][] = []
      ;(g.suppliers || []).forEach((s) => {
        const sRates: number[] = []
        const sPersisted: number[] = []
        const sMixed: boolean[] = []
        const sItemIds: number[][] = []
        ;(s.fabrics || []).forEach((f) => {
          const rate = typeof f.loss_rate === 'number' && Number.isFinite(f.loss_rate)
            ? (f.loss_rate as number)
            : groupFallback
          sRates.push(rate)
          sPersisted.push(rate)
          sMixed.push(f.loss_rate_mixed === true)
          sItemIds.push(f.item_ids || (f.item_id ? [f.item_id] : []))
        })
        gRates.push(sRates)
        gPersisted.push(sPersisted)
        gMixed.push(sMixed)
        gItemIds.push(sItemIds)
      })
      rates.push(gRates)
      persistedRates.push(gPersisted)
      mixedRates.push(gMixed)
      itemIds.push(gItemIds)
    })
    fabricLossRates.value = rates
    fabricPersistedRates.value = persistedRates
    fabricLossRateMixed.value = mixedRates
    fabricLossRateMixedPersisted.value = cloneRaw(mixedRates)
    fabricItemIds.value = itemIds
    // 回显播种：把汇总接口返回的「已落库损耗率」作为编辑基线。
    // - spare_rate 是 number（含 0）时原样回显；否则（null / 旧后端未提供 undefined）落 0，
    //   与改动前行为完全一致，零回归。
    // - lossRateTouched 必须保持 false：回显是「服务端状态」而非「用户交互」，
    //   若置 true，「打开看一眼 → 去完成某张订单」会把该率夹带提交（见 usePurchaseActions）。
    const raw = fRes.spare_rate
    const persisted = typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
    lossRate.value = persisted
    persistedLossRate.value = persisted
    lossRateTouched.value = false
    lossRateSaveState.value = 'idle'
    lossRateMixed.value = fRes.spare_rate_mixed === true
    persistedLossRateMixed.value = lossRateMixed.value
    tab.value = 'factory'
    open.value = true
  }

  function toggleEditMode(enable: boolean) {
    if (!enable) {
      // 取消编辑：丢弃本地改动与损耗率交互，回到服务端原值（数量永远是原始真值）。
      factoryData.value = cloneRaw(factoryOriginalData.value)
      supplierData.value = cloneRaw(supplierOriginalData.value)
      fabricLossRates.value = cloneRaw(fabricPersistedRates.value)
      fabricLossRateMixed.value = cloneRaw(fabricLossRateMixedPersisted.value)
      // 顶部统一损耗率同样回到服务端基线：此前漏了这一行，取消编辑后
      // 输入框仍显示用户改过的值，而逐行率已按持久值计算（同屏两套口径）。
      lossRate.value = persistedLossRate.value
      lossRateMixed.value = persistedLossRateMixed.value
      // 分组订单级率同样回到服务端基线（统一率交互随之丢弃）
      groupSpareRates.value = seedGroupSpareRates(factoryOriginalData.value)
      // 弹窗仍开着、服务端仍存着该率，故恢复到「已落库」基线而非清零，
      // 否则「打开看到 5 → 自定义编辑 → 取消编辑」会自相矛盾地变成 0。
      // 同时复位交互标记与保存反馈状态（saving/error 提示随之一并消失）。
      lossRateTouched.value = false
      lossRateSaveState.value = 'idle'
    }
    editMode.value = enable
  }

  /**
   * 编辑态逐行改数量：就地更新 factoryData 中该布料的真实数量（并同步供应商汇总），
   * 由「保存修改」统一落库。非编辑态展示的放大值不参与此处。
   */
  function updateFactoryQty(gi: number, si: number, fi: number, value: number) {
    const fabric = factoryData.value?.groups?.[gi]?.suppliers?.[si]?.fabrics?.[fi]
    if (!fabric) return
    // 自定义编辑输入框加载的是「订单用量展示值」（原始值 × (1 + 损耗率‰)），
    // 保存前必须按当前工序损耗率反推原始真值，避免把展示值固化入库。
    const newBase = unmagnifyByLossRate(value, rateForFabric(gi, si, fi))
    const oldQty = parseFloat(String(fabric.quantity)) || 0
    const diff = newBase - oldQty
    fabric.quantity = newBase

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

  /**
   * 用户交互损耗率（非编辑态输入）：只记录「率」与「已交互」标记。
   *
   * 本函数**不改动 factoryData / supplierData 的任何数量**。
   * 「损耗加放」后的数量是展示派生值，由 magnifyByLossRate 在渲染 / 合计 / 打印 / 导出时
   * 按原始数量实时计算（同一处来源）。原始数量只经编辑态「保存修改」落库；
   * 损耗率本身由 applyLossRateAndSave 落库。
   */
  function applyLossRate(rate: number) {
    lossRate.value = rate
    // 统一设置所有布料行：全局输入作为批量快捷入口，逐行输入可再单独覆盖。
    fabricLossRates.value = fabricLossRates.value.map((g) => g.map((ss) => ss.map(() => rate)))
    fabricLossRateMixed.value = fabricLossRateMixed.value.map((g) => g.map((ss) => ss.map(() => false)))
    // 订单级率同样批量下发全部分组（备品口径 A 的来源；逐行输入不会写这里）
    groupSpareRates.value = groupSpareRates.value.map(() => rate)
    lossRateMixed.value = false
    // 记录用户已交互损耗率：即使无布料改动，保存/下单时也要把率提交落库（PRD Q1）
    lossRateTouched.value = true
  }

  /**
   * 单次损耗率落库请求：只提交 spare_rate 与 order_ids，`edits` 恒为空。
   *
   * `edits` 恒空的理由：数量落库只走编辑态「保存修改」，
   * 自动落库只负责把用户输入的损耗率持久化到本次汇总涉及的采购单。
   */
  async function sendLossRateToOrders(rate: number, targetOrderIds: number[]) {
    const res = await purchaseApi.saveFactoryEdits(
      [],
      rate,
      targetOrderIds,
    ) as unknown as SaveFactoryEditsResponse
    if (!res.success) {
      throw new Error(res.message || '损耗率保存失败')
    }
  }

  async function sendLossRate(rate: number) {
    return sendLossRateToOrders(rate, orderIds.value)
  }

  /**
   * 把「刚成功落库的统一损耗率」同步为新的已落库基线（供「取消编辑」恢复）。
   *
   * 两条落库路径必须共用本函数，否则同一份基线各自维护会漂移：
   * - `applyLossRateAndSave`（顶部输入框自动落库，率已随请求发出）；
   * - `saveFactoryEdits`（编辑态「保存修改」，rateTouched 时才提交 spare_rate）。
   *
   * 同步范围（缺一即「同屏两套口径」）：
   * - persistedLossRate / persistedLossRateMixed：取消编辑时恢复的订单级基线；
   * - fabricPersistedRates / fabricLossRateMixedPersisted：逐布料行的基线与 mixed 标记
   *   （统一率输入会批量改写全部行，见 applyLossRate，故逐行基线必须一起刷新）；
   * - lossRateMixed / fabricLossRateMixed：本次已把所有单统一为该值，不一致标记清除；
   * - factoryOriginalData / factoryData：取消编辑时 groupSpareRates 从
   *   factoryOriginalData 重播、diff 也以它为基准，不同步就会回滚到打开时的旧分组率；
   *   factoryData 不同步则「取消编辑回新率、当前展示用旧率」同屏两套口径（OCR 2026-10-18）。
   */
  function syncPersistedLossRateBaseline(rate: number) {
    persistedLossRate.value = rate
    persistedLossRateMixed.value = false
    fabricPersistedRates.value = cloneRaw(fabricLossRates.value)
    fabricLossRateMixedPersisted.value = cloneRaw(fabricLossRateMixed.value)
    lossRateMixed.value = false
    const snapshot = factoryOriginalData.value
    if (snapshot) {
      snapshot.spare_rate = rate
      snapshot.groups?.forEach((g) => { g.spare_rate = rate })
    }
    // 当前展示口径一并刷新：编辑态 diff 与「取消编辑」回滚都以此为基准，
    // 只改基线不改展示会让同一屏幕同时存在新旧两套率。
    if (factoryData.value) {
      factoryData.value.spare_rate = rate
      factoryData.value.groups?.forEach((g) => { g.spare_rate = rate })
    }
  }

  /**
   * 用户交互损耗率后的自动落库（串行化 + 可见反馈）。
   *
   * 串行契约：
   *  1. 同一时刻至多一个 `factory-summary/save` 的损耗率请求在途；
   *  2. 在途期间到来的新率合并为「最新值」，等当前请求结束后再发（中间值可跳过）；
   *  3. 因此最后一次发出的 rate 恒等于用户最后一次输入，服务端不会出现乱序覆盖；
   *  4. `lossRateTouched` 仅在**最后一次输入成功落库**后才复位为 false。
   *
   * 失败契约：任一次发送失败 → 抛出（上层 toast）、`lossRateTouched` 保持 true、
   * 清空待发队列（用户重新输入即重试）、状态置 error。
   *
   * 并发调用者共享同一个「排空循环」句柄，故本轮成败对全部参与者一致。
   */
  async function applyLossRateAndSave(rate: number) {
    // 1) 先更新本地展示所依赖的率状态（数量为派生值，无需改写数据）
    applyLossRate(rate)
    // 2) 无目标采购单时不打网络，也不改变保存状态
    if (orderIds.value.length === 0) return

    // 3) 已有排空循环在跑：合并为最新待发值，复用同一句柄等待本轮结束
    if (drainPromise) {
      pendingRate = rate
      return drainPromise
    }

    // 4) 启动排空循环：每次发送前取走「期间累积的最新值」，保证最后发送 = 最后输入
    const run = (async () => {
      let next: number | null = rate
      try {
        while (next !== null) {
          // 目标采购单已失效（例如弹窗在途期间被关闭）：不再发送无 order_ids 的请求
          if (orderIds.value.length === 0) break
          lossRateSaveState.value = 'saving'
          const sent = next
          await sendLossRate(sent)
          // 本次发送该率已成功落库 → 同步「已落库」基线（供取消编辑时恢复），
          // 并清掉「各单不一致」标记（本次已把所有涉及单统一为该值）。
          syncPersistedLossRateBaseline(sent)
          next = pendingRate
          pendingRate = null
        }
        // 队列排空且目标仍有效：最后一次输入已成功落库 → 复位标记并给出成功反馈
        if (orderIds.value.length > 0) {
          lossRateTouched.value = false
          lossRateSaveState.value = 'saved'
        }
      } catch (err) {
        // 任一发送失败：清空待发队列（重新输入即重试），保留 lossRateTouched=true
        pendingRate = null
        lossRateSaveState.value = 'error'
        throw err
      } finally {
        drainPromise = null
      }
    })()
    drainPromise = run

    return run
  }

  /**
   * 单次布料损耗率落库请求：只提交该布料行对应明细的 loss_rate。
   * 数量落库仍只走编辑态「保存修改」，此处不携带 quantity。
   */
  async function sendFabricLossRate(itemIds: number[], rate: number) {
    const res = await purchaseApi.saveFactoryEdits(
      [{ item_ids: itemIds, loss_rate: rate }],
    ) as unknown as SaveFactoryEditsResponse
    if (!res.success) {
      throw new Error(res.message || '布料损耗率保存失败')
    }
  }

  /**
   * 单独修改某个布料行的损耗率：仅更新该行展示值（不触碰全局/其它行）。
   */
  function applyFabricLossRate(gi: number, si: number, fi: number, rate: number) {
    const row = fabricLossRates.value[gi]?.[si]
    if (!row || fi < 0 || fi >= row.length) return
    row[fi] = rate
    const mixedRow = fabricLossRateMixed.value[gi]?.[si]
    if (mixedRow) mixedRow[fi] = false
  }

  /**
   * 布料损耗率自动落库：按 (gi,si,fi) 串行化，同一行在途期间的新值合并为最新值。
   * 成功后同步该行的「已落库基线」（供取消编辑时恢复）。
   */
  async function applyFabricLossRateAndSave(gi: number, si: number, fi: number, rate: number) {
    applyFabricLossRate(gi, si, fi, rate)
    const targetItemIds = fabricItemIds.value?.[gi]?.[si]?.[fi] || []
    if (targetItemIds.length === 0) return

    const key = fabricKey(gi, si, fi)
    const existing = fabricDrainPromises.get(key)
    if (existing) {
      fabricPendingRates.set(key, rate)
      return existing
    }

    const run = (async () => {
      let next: number | null = rate
      try {
        while (next !== null) {
          const ids = fabricItemIds.value?.[gi]?.[si]?.[fi] || []
          if (ids.length === 0) break
          lossRateSaveState.value = 'saving'
          const sent = next
          await sendFabricLossRate(ids, sent)
          const persistedRow = fabricPersistedRates.value[gi]?.[si]
          if (persistedRow) persistedRow[fi] = sent
          const mixedRow = fabricLossRateMixed.value[gi]?.[si]
          if (mixedRow) mixedRow[fi] = false
          const mixedPersistedRow = fabricLossRateMixedPersisted.value[gi]?.[si]
          if (mixedPersistedRow) mixedPersistedRow[fi] = false
          next = fabricPendingRates.get(key) ?? null
          fabricPendingRates.delete(key)
        }
        if ((fabricItemIds.value?.[gi]?.[si]?.[fi] || []).length > 0) {
          lossRateSaveState.value = 'saved'
        }
      } catch (err) {
        fabricPendingRates.delete(key)
        lossRateSaveState.value = 'error'
        throw err
      } finally {
        fabricDrainPromises.delete(key)
      }
    })()
    fabricDrainPromises.set(key, run)
    return run
  }

  /**
   * 编辑态「保存修改」：以 `factoryData` 与 `factoryOriginalData` 的**差异**组装 edits。
   *
   * 二者现在都只承载原始真值（损耗加放不再就地改写数量），因此 diff 只会得到
   * 用户在编辑态真实改过的数量，天然不含任何「放大派生的伪编辑」。
   * 本函数的 diff 逻辑无需为损耗率改动做任何调整。
   */
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
    const rateTouched = lossRateTouched.value
    // 无任何布料改动且损耗率未被交互：无需请求（保持原直接退出行为）
    if (edits.length === 0 && !rateTouched) {
      editMode.value = false
      return
    }
    // 损耗率仅在交互过时提交；未交互则不发送 spare_rate（避免用 0 覆盖已存率）
    const res = await purchaseApi.saveFactoryEdits(
      edits,
      rateTouched ? lossRate.value : undefined,
      orderIds.value,
    ) as unknown as SaveFactoryEditsResponse
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
      if (rateTouched) {
        // 2026-10-18 OCR 评审：本路径同样把 spare_rate 落库了，基线必须同步，
        // 否则「保存修改」后再「取消编辑」会回滚到旧率；逐行基线也要同步。
        // 顺序很关键：必须**先**让共享函数把 factoryData 刷成新率，**再** clone 成基线；
        // 反过来的话 cloneRaw 会把尚未刷新的旧率固化进 factoryOriginalData，等于没同步。
        syncPersistedLossRateBaseline(lossRate.value)
        factoryOriginalData.value = cloneRaw(factoryData.value)
      } else {
        factoryOriginalData.value = cloneRaw(factoryData.value)
      }
      lossRateTouched.value = false
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
    // 关闭弹窗即丢弃「尚未落库的损耗率交互」：否则失败态残留的 lossRate/lossRateTouched
    // 会被后续 handleCompleteOrder/handleBatchComplete 读取，把陈旧损耗率推给无关订单。
    lossRate.value = 0
    lossRateTouched.value = false
    // 已落库基线随弹窗关闭复位：下次 openSummary 会按汇总接口的 spare_rate 重新播种。
    persistedLossRate.value = 0
    lossRateMixed.value = false
    persistedLossRateMixed.value = false
    fabricLossRates.value = []
    fabricPersistedRates.value = []
    fabricLossRateMixed.value = []
    fabricLossRateMixedPersisted.value = []
    groupSpareRates.value = []
    fabricItemIds.value = []
    fabricDrainPromises.clear()
    fabricPendingRates.clear()
    // 保存反馈随弹窗关闭复位（状态由下一次输入或关闭重置，不使用定时器）
    lossRateSaveState.value = 'idle'
  }

  function printFactory() {
    if (!factoryData.value) return
    const tableHtml = buildFactoryHtml(
      factoryData.value, lossRate.value, fabricLossRates.value, groupSpareRates.value,
    )
    printHtml(
      '工厂内部采购订单汇总',
      `${orderTimeLabel(orderTime.value)}<table><thead>${FACTORY_TABLE_HEAD}</thead><tbody>${tableHtml}</tbody></table>`,
      SUMMARY_PRINT_STYLE,
    )
  }

  function printSupplier() {
    if (!supplierData.value) return
    const tableHtml = buildSupplierHtml(supplierGroups.value)
    printHtml(
      '供应商采购订单汇总',
      `${orderTimeLabel(orderTime.value)}<table><thead><tr><th>供应商</th><th>物料名称</th><th>规格型号</th><th>数量</th><th>单位</th></tr></thead><tbody>${tableHtml}</tbody></table>`,
      SUMMARY_PRINT_STYLE,
    )
  }

  function exportFactory() {
    if (!factoryData.value) return
    const tableHtml = buildFactoryHtml(
      factoryData.value, lossRate.value, fabricLossRates.value, groupSpareRates.value,
    )
    const html = `<div style="text-align:center;margin-bottom:20px"><h2>工厂内部采购订单汇总</h2></div><table><thead>${FACTORY_TABLE_HEAD}</thead><tbody>${tableHtml}</tbody></table>`
    downloadAsXls(html, '工厂内部采购汇总.xls')
  }

  /**
   * 导出用数量行：直接取供应商页签**当前展示**的数量（与工厂页数量同源派生），
   * 随导出请求发给后端覆盖 Excel 数量，保证「导出 = 页面所见」。
   */
  function buildSupplierExportQuantities() {
    return supplierGroups.value.flatMap((g) =>
      g.materials.map((m) => ({
        supplier_name: g.supplierName,
        material_name: m.material_name,
        specification: m.specification || '',
        unit: m.unit || '',
        quantity: parseFloat(String(m.total_quantity)) || 0,
      })),
    )
  }

  async function exportSupplier() {
    if (!supplierData.value) return
    if (orderIds.value.length === 0) return
    try {
      await purchaseApi.supplierSummaryExport(
        orderIds.value,
        supplierGroups.value.length,
        buildSupplierExportQuantities(),
      )
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
    persistedLossRate,
    lossRateMixed,
    fabricLossRates,
    fabricLossRateMixed,
    groupSpareRates,
    lossRateTouched,
    lossRateSaveState,
    orderIds,
    supplierGroups,
    openSummary,
    close,
    toggleEditMode,
    updateFactoryQty,
    applyLossRate,
    applyLossRateAndSave,
    applyFabricLossRateAndSave,
    saveFactoryEdits,
    printFactory,
    printSupplier,
    exportFactory,
    exportSupplier,
  })
}
