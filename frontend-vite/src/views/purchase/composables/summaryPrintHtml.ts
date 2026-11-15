/**
 * 汇总下单「打印 / 导出」HTML 拼装层（**纯函数，无响应式状态、不发请求**）。
 *
 * 从 `useSummaryModal.ts` 拆出（该文件当时 1400+ 行，状态与字符串拼装混在一起）：
 * 本模块只做「数据 → HTML 字符串」，坐标全部来自入参。
 *
 * 依赖方向（避免运行时循环依赖）：
 * - 本模块 → `perSkuRows.ts`（叶子纯函数）；
 * - 类型从 `useSummaryModal.ts` **type-only** 导入（编译期擦除，不产生运行时环）；
 * - `useSummaryModal.ts` 反向 re-export 本模块符号，既有导入路径逐字不变。
 */
import { escapeHtml } from '@/utils/print'
import { fmtQty } from '@/utils/formatQty'
import {
  calcSpareQuantity,
  ceilMagnifiedByLossRate,
  buildPerSkuRows,
  buildRowDisplayQuantities,
  computeQuantityDiff,
  buildStoredRows,
  allocateOrderDisplayQuantities,
} from './perSkuRows'
import type { PerSkuRow } from './perSkuRows'
import type {
  FactoryGroup,
  FactorySummaryData,
  MaterialItem,
  SupplierGroup,
  SkuDisplayLine,
} from './useSummaryModal'

/**
 * 订单数量取数：产品数量优先，缺失时回退订单数量。
 * 非法/缺失输入兜底 0。屏幕表格、打印预览、Excel 导出共用这一处来源。
 */
export function getGroupOrderQty(group: FactoryGroup): number {
  const v = parseFloat(String(group.product_quantity || group.order_quantity || 0))
  return Number.isNaN(v) ? 0 : v
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
export const SUMMARY_PRINT_STYLE = `
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
 * 该分组是否需要「角色名称」列（2026-11-08 用户要求：单角色/无角色的采购订单
 * 不显示该列，只有多角色产品才显示）。
 *
 * 判定按**数据实际出现的角色名**去重计数（含回退模式 fabrics 的并列名按 `/` 拆分）：
 * - 0 或 1 个角色名 → 不需要（单角色产品不必区分）；
 * - ≥2 个不同角色名 → 需要。
 * 用数据而非产品配置判定，保证「屏幕有列 ⇔ 打印有列」且历史单（无 role_quantities）同样适用。
 */
export function hasMultiRole(group: FactoryGroup): boolean {
  const names = new Set<string>()
  const add = (raw: string | undefined) => {
    const text = (raw || '').trim()
    if (!text) return
    // 回退模式的 role_display 是并列名（`角色A/角色B`）——按分隔符拆开分别计数
    // （分隔符与后端 `_factory.ROLE_DISPLAY_SEP` 一致）
    text.split('/').forEach((n) => {
      const t = n.trim()
      if (t) names.add(t)
    })
  }
  // 有 skus 明细时以它为准（权威口径）；只有回退模式（无 skus 数据）才看 fabrics 的并列名
  const hasSkuData = (group.skus || []).some((sku) => (sku.materials || []).length > 0)
  if (hasSkuData) {
    ;(group.skus || []).forEach((sku) => (sku.materials || []).forEach((m) => add(m.role_display)))
  } else {
    ;(group.suppliers || []).forEach((sup) => (sup.fabrics || []).forEach((f) => add(f.role_display)))
  }
  return names.size >= 2
}

/** 整份汇总数据是否需要「角色名称」列（任一分组多角色即显示——列是表格级的）。 */
export function anyGroupMultiRole(data: FactorySummaryData): boolean {
  return (data.groups || []).some((g) => hasMultiRole(g))
}

/**
 * 工厂表格表头（12 列 = 含角色名称列；11 列 = 单角色/无角色订单隐藏该列）。
 *
 * `FACTORY_TABLE_HEAD` 保留为「含角色名称」形态（多角色订单），供既有调用与测试复用；
 * 打印 / 导出按 `anyGroupMultiRole(data)` 选形态，保证屏幕与打印同列。
 */
export function factoryTableHead(showRoleColumn: boolean): string {
  if (!showRoleColumn) {
    return '<tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>备品数量</th>' +
      '<th>产品部位</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>损耗率</th><th>数量</th><th>单位</th></tr>'
  }
  return FACTORY_TABLE_HEAD
}

export const FACTORY_TABLE_HEAD =
  '<tr><th>客户</th><th>产品名称</th><th>角色名称</th><th>订单数量</th><th>备品数量</th>' +
  '<th>产品部位</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>损耗率</th><th>数量</th><th>单位</th></tr>'

/**
 * 「按 SKU 展开」的组渲染：每 SKU 一块物料行，组末附差异对照块。
 *
 * 左侧三列（产品名称 / 订单数量 / 备品数量）按 SKU 块合并（rowspan = 该块行数），
 * 客户列跨**整组**（只在组首行渲染一次）—— 与屏幕 `SummaryFactoryTab.vue` 同构。
 * 返回空串表示数据不足（旧后端 / 无 BOM），调用方回退订单级单块（零回归）。
 */
function buildPerSkuGroupHtml(
  group: FactoryGroup, gi: number, spareRate: number, lossRate: number, fabricRates?: number[][][],
  showRoleColumn = true,
): string {
  const perSkuRows = buildPerSkuRows(group, spareRate)
  if (perSkuRows.length === 0) return ''
  // 数量列与屏幕/供应商同源：手工调整 → 落库真值加放并按 SKU 分摊；
  // 否则逐 SKU BOM 推算（唯一判定见 perSkuRows.buildRowDisplayQuantities）。
  const displayQtys = buildRowDisplayQuantities(
    group, perSkuRows, (si, fi) => fabricRates?.[gi]?.[si]?.[fi] ?? lossRate,
  )

  let tableHtml = ''
  let cursor = 0
  let blockNo = 0
  while (cursor < perSkuRows.length) {
    const blockStart = cursor
    const skuIdx = perSkuRows[cursor]!.skuIdx
    const block: PerSkuRow[] = []
    while (cursor < perSkuRows.length && perSkuRows[cursor]!.skuIdx === skuIdx) {
      block.push(perSkuRows[cursor]!)
      cursor++
    }
    block.forEach((row, i) => {
      const displayQty = displayQtys[blockStart + i] ?? row.baseQuantity
      tableHtml += '<tr>'
      const line = row.cellLines[0]
      if (i === 0) {
        // 客户列：整组只出现一次（rowspan = 该组全部行数）；误写成「每块都渲染」会与表头错位。
        if (blockNo === 0) {
          tableHtml += `<td rowspan="${perSkuRows.length}" style="font-weight:bold;">${escapeHtml(group.customer_name)}</td>`
        }
        // 名称格：按角色拆分数量时，SKU 总量挪到名称格副行（合计 N）——总量信息不丢
        const totalSub = row.hasRoleQtySplit
          ? `<div style="font-size:10px;color:#8e8e93;">合计 ${escapeHtml(fmtQty(line?.qty ?? 0))}</div>`
          : ''
        tableHtml += `<td rowspan="${block.length}">${escapeHtml(line?.name || '')}${totalSub}</td>`
      }
      // 角色名称（列序：在订单数量左边；2026-11-08 用户要求隐藏款标记挂在角色名上）。
      // 角色段首行渲染，rowspan=段行数；span=1 时不输出 rowspan（与屏幕同 DOM 口径）。
      if (showRoleColumn && row.isFirstRoleRow) {
        const roleSpan = row.roleRowSpan > 1 ? ` rowspan="${row.roleRowSpan}"` : ''
        const hiddenMark = row.roleIsHidden
          ? '<div style="font-size:10px;color:#8e8e93;">（隐藏款）</div>'
          : ''
        tableHtml += `<td${roleSpan}>${escapeHtml(row.roleDisplay)}${hiddenMark}</td>`
      }
      if (i === 0) {
        if (row.hasRoleQtySplit) {
          // 按角色拆分：首行必为首个角色段段首——渲染该角色段的订单数量格与备品格
          // （各 rowspan=段行数）。备品也按角色逐段算（ceil(该角色数量 × 订单级率‰)）。
          tableHtml += `<td rowspan="${row.roleRowSpan}">${escapeHtml(fmtQty(row.roleQuantity ?? 0))}</td>`
          tableHtml += `<td rowspan="${row.roleRowSpan}">${escapeHtml(fmtQty(row.roleSpare ?? 0))}</td>`
        } else {
          tableHtml += `<td rowspan="${block.length}">${escapeHtml(fmtQty(line?.qty ?? 0))}</td>`
          tableHtml += `<td rowspan="${block.length}">${escapeHtml(fmtQty(line?.spare ?? 0))}</td>`
        }
      } else if (row.hasRoleQtySplit && row.isFirstRoleRow) {
        // 后续角色段首行：名称被块级 rowspan 覆盖，只渲染该角色段的订单数量/备品格
        // （rowspan=roleRowSpan 与屏幕同一套行模型）
        tableHtml += `<td rowspan="${row.roleRowSpan}">${escapeHtml(fmtQty(row.roleQuantity ?? 0))}</td>`
        tableHtml += `<td rowspan="${row.roleRowSpan}">${escapeHtml(fmtQty(row.roleSpare ?? 0))}</td>`
      }
      if (row.noBom) {
        // 占位行：角色格已渲染（空，隐藏角色列时不渲染），剩余
        // 部位/供应商/布料/规格/损耗率/数量/单位 = 7 列（隐藏角色列时 8 列）
        tableHtml += `<td colspan="${showRoleColumn ? 7 : 8}" style="color:#8e8e93;">无 BOM 明细</td>`
        tableHtml += '</tr>'
        return
      }
      // 列序与屏幕 thead 严格一致：产品部位 → 供应商（子段首行 + rowspan）。
      // rowspan 按连续段计算，与屏幕同一套行模型。
      tableHtml += `<td>${escapeHtml(row.partDisplay)}</td>`
      if (row.isFirstSupplierRow) {
        tableHtml += `<td rowspan="${row.supplierRowSpan}" style="font-weight:bold;">${escapeHtml(row.supplierName)}</td>`
      }
      tableHtml += `<td>${escapeHtml(row.materialName)}</td>`
      tableHtml += `<td>${escapeHtml(row.specification)}</td>`
      if (row.coord) {
        const rowRate = fabricRates?.[gi]?.[row.coord.si]?.[row.coord.fi] ?? lossRate
        tableHtml += `<td>${escapeHtml(String(rowRate))}</td>`
        tableHtml += `<td>${displayQty}</td>`
      } else {
        // 无落库坐标（BOM 生成后新增的物料）：**必须与屏幕同源** —— 屏幕
        // `SummaryFactoryTab.vue` 对无坐标行渲染率 '—'、数量取基准量（不加放）。
        // 曾在此回退 lossRate 并加放，导致同一张单屏幕「— / 20」而打印「10 / 21」。
        tableHtml += '<td>—</td>'
        tableHtml += `<td>${displayQty}</td>`
      }
      tableHtml += `<td>${escapeHtml(row.unit)}</td>`
      tableHtml += '</tr>'
    })
    blockNo++
  }

  // 差异对照块：与屏幕同源（打印件不能对差异保持沉默）。
  tableHtml += buildDiffBlockHtml(group, perSkuRows, spareRate, showRoleColumn)
  return tableHtml
}

/**
 * 差异对照块（打印/导出版，结构镜像屏幕 `SummaryDiffBlock.vue`）。
 *
 * 列数必须仍是 **12**：标签跨「客户/产品名称/订单数量/备品数量」4 列（`colspan=4`，
 * 跨本块全部行）+ 角色名称 + 产品部位 + 供应商（段内 rowspan）+ 布料名称/规格型号/损耗率/数量/单位 5 格。
 * 行数据来自 `buildStoredRows` —— 与屏幕**同一个纯函数**，故两边天然同构：
 * 损耗率取该落库行快照率、数量为按该率加放派生值。无差异时返回空串（不渲染）。
 */
function buildDiffBlockHtml(
  group: FactoryGroup, perSkuRows: PerSkuRow[], spareRate: number, showRoleColumn = true,
): string {
  const diffs = computeQuantityDiff(group, perSkuRows)
  if (diffs.length === 0) return ''

  const detail = diffs
    .map((d) => `${d.partName ? d.partName + '·' : ''}${d.materialName}（推算 ${fmtQty(d.perSku)} / 实际 ${fmtQty(d.stored)}）`)
    .join('、')
  const totalCols = showRoleColumn ? 12 : 11
  let tableHtml = `<tr><td colspan="${totalCols}" style="background:#fffaf0;color:#7a4a00;">⚠ 以下物料含手工调整：上方「数量」已按实际下单值显示，BOM 推算值为：${escapeHtml(detail)}</td></tr>`

  const storedRows = buildStoredRows(group, () => spareRate)
  storedRows.forEach((r, i) => {
    tableHtml += '<tr>'
    if (i === 0) {
      // 标签恒跨 2 列（客户/产品名称）；角色列存在时其后紧跟角色格（条件渲染），
      // 不存在时直接接订单/备品空位（列总数随 showRoleColumn 12 / 11 自适应）
      tableHtml += `<td colspan="2" rowspan="${storedRows.length}" style="font-weight:bold;background:#fffaf0;color:#7a4a00;">实际下单（含手工调整）</td>`
    }
    // 列序与主表一致（角色名称 → 订单数量/备品数量(空) → 产品部位 → 供应商 → 布料名称…）：
    // 落库明细侧没有订单数量/备品数量两个值，留空格对齐列位（2026-11-08 列序调整）。
    if (showRoleColumn) {
      tableHtml += `<td style="background:#fffaf0;">${escapeHtml(r.roleDisplay)}</td>`
    }
    tableHtml += '<td style="background:#fffaf0;"></td>'
    tableHtml += '<td style="background:#fffaf0;"></td>'
    tableHtml += `<td style="background:#fffaf0;">${escapeHtml(r.partDisplay)}</td>`
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

    // 角色名称列：整份数据任一分组多角色才显示（单角色/无角色订单隐藏该列，2026-11-08 用户要求）。
    const showRoleColumn = anyGroupMultiRole(data)
    // 优先「按 SKU 展开」：每 SKU 一块物料 + 组末差异对照块；数据不足则回退订单级单块。
    const perSkuHtml = buildPerSkuGroupHtml(group, gi, spareRate, lossRate, fabricRates, showRoleColumn)
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
          // 列序（2026-11-08）：角色名称在订单数量左边——角色格逐行渲染（回退模式无角色段），
          // 订单数量/备品数量随客户/产品一起按整块 rowspan。
        }
        if (showRoleColumn) {
          tableHtml += `<td>${escapeHtml(fabric.role_display || '')}</td>`
        }
        if (globalFabricIdx === 0) {
          const rowCount = suppliers.reduce((s: number, sup: SupplierGroup) => s + (sup.fabrics?.length || 0), 0)
          const skuLines = buildSkuDisplayLines(group, spareRate)
          const cell = (pick: (l: SkuDisplayLine) => string) =>
            skuLines
              .map((l) => (l.isTotal ? `<strong>${escapeHtml(pick(l))}</strong>` : escapeHtml(pick(l))))
              .join('<br>')
          tableHtml += `<td rowspan="${rowCount}">${cell((l) => fmtQty(l.qty))}</td>`
          tableHtml += `<td rowspan="${rowCount}">${cell((l) => fmtQty(l.spare))}</td>`
        }
        // 列序与屏幕 thead 严格一致：产品部位 → 供应商（供应商含 rowspan）。
        tableHtml += `<td>${escapeHtml(fabric.part_display || fabric.part_name || '')}</td>`
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

export function buildSupplierHtml(groups: { supplierName: string; materials: MaterialItem[] }[]): string {
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
      tableHtml += `<td>${supplierOrderBreakdownHtml(m)}</td>`
      tableHtml += '</tr>'
    })
  })
  return tableHtml
}

/** 打印预览「来源订单」格：逐单「单号×展示数量」（与主行合计对齐），无明细显示 —。 */
function supplierOrderBreakdownHtml(m: MaterialItem): string {
  const lines = allocateOrderDisplayQuantities(m.total_quantity, m.orders || [])
  if (lines.length === 0) return '—'
  return lines
    .map((o) => `${escapeHtml(o.order_no)}×${escapeHtml(qtyDisplayText(o.quantity))}`)
    .join('<br>')
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
