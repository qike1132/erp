/**
 * 汇总下单「按 SKU 展开物料明细」的行模型（纯函数，可独立测试）。
 *
 * 设计要点：**每个按 SKU 的物料行都映射回落库明细的坐标 `(si, fi)`** ——
 * 因为同一物料在库里只有一行（跨 SKU 共用），于是：
 *   - 损耗率、编辑态数量这些既有机制（都按坐标寻址）**原样复用**；
 *   - 「同物料跨 SKU 联动」天然成立（同一坐标 = 同一份状态），无需新增联动代码。
 *
 * 落库明细里找不到对应的物料（BOM 在生成后被新增）时 `coord = null` —— 该行只读，
 * 绝不允许把编辑写进别的明细。
 *
 * 依赖方向（**务必保持单向**）：本模块只从 `useSummaryModal.ts` 取**类型**
 * （`import type`，编译期擦除）；绝不引入它的任何**值** —— 因为 `useSummaryModal.ts`
 * 反过来要用本模块的 `buildPerSkuRows`，若本模块再 import 它的值就构成循环导入
 * （Vite/vitest 下会拿到 `undefined` 绑定）。`calcSpareQuantity` / `summaryMaterialKey`
 * 两个无依赖纯函数因此**从 useSummaryModal.ts 移入本模块**，由后者反向重导出，
 * 以保住既有测试「从 useSummaryModal 导入」的写法。
 */
import type { FactoryGroup } from './useSummaryModal'

export interface SkuMaterial {
  supplier_name: string
  material_name: string
  specification: string
  unit: string
  quantity: number
}

/**
 * 备品数量（口径 A：**只用订单级损耗率**）。
 *
 * `备品 = ceil(订单数量 × 订单级率‰)`，与后端 `calc_spare_quantity` 同口径；
 * 屏幕「备品数量」列、打印预览、Excel 导出共用这一处来源。
 *
 * **自定义（逐布料行）损耗率不参与本计算**（2026-09-30 用户裁决）：
 * 逐行率装的是**材料损耗**（实测 400-1000‰，即 40%-100%），备品率是 0.5%-3%
 * 量级，两者差 1-2 个数量级。曾把逐行率当备品率用，生产实证单张单虚高 30 倍
 * （备品 150 → 4500、生产数量 14500），故明确分离：行率只驱动「数量」列加放。
 *
 * 防御口径：非法/非有限/<= 0 → `0`（率未设时备品确实是 0，是确定值而非缺失）。
 */
export function calcSpareQuantity(orderQty: number, rate: number): number {
  const q = Number.isFinite(orderQty) ? orderQty : 0
  const r = Number.isFinite(rate) ? rate : 0
  if (q <= 0 || r <= 0) return 0
  return Math.ceil((q * r) / 1000)
}

/**
 * 汇总物料键：`供应商 + 物料名 + 规格 + 单位`。
 *
 * 后端工厂汇总（fabric）与供应商汇总（material）同源，均按
 * (供应商, 物料, 规格, 单位) 聚合，故两侧可用同一键一一对应。
 * 用 `\u0000` 分隔，避免字段值本身含分隔符时发生键碰撞。
 */
export function summaryMaterialKey(
  supplierName: string | null | undefined,
  materialName: string | null | undefined,
  specification: string | null | undefined,
  unit: string | null | undefined,
): string {
  return [supplierName || '未指定供应商', materialName || '', specification || '', unit || ''].join('\u0000')
}

export interface PerSkuRow {
  skuIdx: number
  /** 该 SKU 块在左侧「产品名称/订单数量/备品数量」三列里要显示的文本行（per-SKU 模式恒 1 行） */
  cellLines: { name: string; qty: number; spare: number; isTotal: boolean }[]
  isFirstSkuRow: boolean
  skuRowSpan: number
  isFirstSupplierRow: boolean
  supplierRowSpan: number
  supplierName: string
  materialName: string
  specification: string
  unit: string
  baseQuantity: number
  /** 该物料在落库明细中的坐标；无对应明细时为 null（只读行） */
  coord: { si: number; fi: number } | null
  itemIds: number[]
  /** 该 SKU 无 BOM 明细时的占位行（保留块结构，不隐藏该 SKU） */
  noBom: boolean
}

/** 物料键：与工厂页/供应商页同源（复用 summaryMaterialKey，不另造一套）。 */
export function materialKeyOf(m: {
  supplier_name?: string; material_name?: string; specification?: string; unit?: string
}): string {
  return summaryMaterialKey(m.supplier_name, m.material_name, m.specification, m.unit)
}

/** 落库明细索引：物料键 → 坐标 / item_ids / 落库数量。 */
function buildStoredIndex(group: FactoryGroup) {
  const index = new Map<string, { coord: { si: number; fi: number }; itemIds: number[]; storedQuantity: number }>()
  ;(group.suppliers || []).forEach((supplier, si) => {
    ;(supplier.fabrics || []).forEach((fabric, fi) => {
      const key = materialKeyOf({
        supplier_name: supplier.supplier_name,
        material_name: fabric.fabric_name,
        specification: fabric.specification,
        unit: fabric.unit,
      })
      const itemIds = fabric.item_ids || (fabric.item_id ? [fabric.item_id] : [])
      index.set(key, {
        coord: { si, fi },
        itemIds,
        storedQuantity: parseFloat(String(fabric.quantity)) || 0,
      })
    })
  })
  return index
}

/** 是否具备「按 SKU 展开」的数据（否则调用方回退现状）。 */
function hasPerSkuMaterials(group: FactoryGroup): boolean {
  const skus = group.skus || []
  return skus.length > 0 && skus.some((s) => (s.materials?.length || 0) > 0)
}

/**
 * 构建「每个 SKU 一块」的扁平行列表。
 *
 * 返回 `[]` 表示数据不足（旧后端 / 无 BOM / SKU 名解析不出）→ 调用方回退订单级单块，
 * 与改动前逐字一致（单 SKU 单因此天然零回归）。
 *
 * **块内顺序：原样保留后端给出的物料顺序**，不再本地重排。
 * 原因：本地 `localeCompare` 的排序结果**随运行环境 locale 变化**（本机 zh-CN 下
 * 「共享布 < 「新加布」<「B专有布」，而 en-US 下拉丁字母整体排在汉字之前），
 * 既无法与后端稳定序一致、又让渲染顺序不可预期；后端返回的顺序才是唯一稳定真值。
 */
export function buildPerSkuRows(group: FactoryGroup, groupRate: number): PerSkuRow[] {
  if (!hasPerSkuMaterials(group)) return []
  const stored = buildStoredIndex(group)
  const rows: PerSkuRow[] = []

  ;(group.skus || []).forEach((sku, skuIdx) => {
    const materials = (sku.materials || []) as SkuMaterial[]
    if (materials.length === 0) {
      // 该 SKU 没有 BOM 明细（或后端解析不出产品）：**保留块结构**渲染一条占位行，
      // 不隐藏该 SKU —— 否则用户会以为它被漏掉了。整组都无 materials 时上层
      // hasPerSkuMaterials 已判否、根本走不到这里（那种情况回退订单级单块）。
      const skuQty = parseFloat(String(sku.order_qty ?? 0)) || 0
      rows.push({
        skuIdx,
        cellLines: [{ name: sku.product_name || '', qty: skuQty, spare: calcSpareQuantity(skuQty, groupRate), isTotal: false }],
        isFirstSkuRow: true,
        skuRowSpan: 1,
        isFirstSupplierRow: false,
        supplierRowSpan: 0,
        supplierName: '',
        materialName: '',
        specification: '',
        unit: '',
        baseQuantity: 0,
        coord: null,
        itemIds: [],
        noBom: true,
      })
      return
    }
    const skuQty = parseFloat(String(sku.order_qty ?? 0)) || 0
    const supplierCounts = new Map<string, number>()
    materials.forEach((m) => supplierCounts.set(m.supplier_name, (supplierCounts.get(m.supplier_name) || 0) + 1))
    const seenSupplier = new Set<string>()

    materials.forEach((m, i) => {
      const key = materialKeyOf(m)
      const hit = stored.get(key)
      const isFirstSupplierRow = !seenSupplier.has(m.supplier_name)
      seenSupplier.add(m.supplier_name)
      rows.push({
        skuIdx,
        cellLines: [{
          name: sku.product_name || '',
          qty: skuQty,
          spare: calcSpareQuantity(skuQty, groupRate),
          isTotal: false,
        }],
        isFirstSkuRow: i === 0,
        skuRowSpan: materials.length,
        isFirstSupplierRow,
        supplierRowSpan: supplierCounts.get(m.supplier_name) || 0,
        supplierName: m.supplier_name,
        materialName: m.material_name,
        specification: m.specification,
        unit: m.unit,
        baseQuantity: parseFloat(String(m.quantity)) || 0,
        coord: hit?.coord ?? null,
        itemIds: hit?.itemIds ?? [],
        noBom: false,
      })
    })
  })
  return rows
}

/**
 * 数量差异：**逐键**比较「各 SKU 基准量之和」与「落库真值」（按物料键）。
 *
 * 两个方向都算差异（spec §2.3「逐键比较」）：
 *   - 两侧都有的键：`|Σ推算 − 落库| > 0.005` 才算差异；
 *   - 只在落库侧的键（手工加进采购明细的物料、或 BOM 生成后被删除的物料）：
 *     `Σ推算 = 0`，落库 > 0 即为差异 —— 否则用户在按 SKU 视图里看不到
 *     「采购明细里有、BOM 里没有」这件事实；
 *   - 只在 BOM 侧的新增物料（落库没有）**不算差异**（那是新增物料，不是数量不符）。
 *
 * 容差 0.005 —— 数量落库为 2 位小数，避免浮点尾差误报。返回空数组表示无差异。
 */
export function computeQuantityDiff(
  group: FactoryGroup, rows: PerSkuRow[],
): { materialName: string; perSku: number; stored: number }[] {
  if (rows.length === 0) return []
  const stored = buildStoredIndex(group)
  const nameOfStoredKey = (key: string) => key.split('\u0000')[1] || ''
  const summed = new Map<string, number>()
  rows.forEach((r) => {
    if (r.noBom) return   // 占位行不对应任何物料，不参与比对
    const key = materialKeyOf({
      supplier_name: r.supplierName, material_name: r.materialName,
      specification: r.specification, unit: r.unit,
    })
    summed.set(key, (summed.get(key) ?? 0) + r.baseQuantity)
  })

  const diffs: { materialName: string; perSku: number; stored: number }[] = []
  // 1) 遍历按 SKU 侧的键：既覆盖「两侧都有」的键，也覆盖「只在 BOM 侧」的新增物料
  //    （落库没有 → 不是差异，跳过）。
  summed.forEach((perSku, key) => {
    const hit = stored.get(key)
    if (!hit) return                       // 只出现在 BOM、落库里没有 → 不是「差异」，是新增物料
    const perSkuRounded = Math.round(perSku * 100) / 100
    if (Math.abs(perSkuRounded - hit.storedQuantity) > 0.005) {
      diffs.push({ materialName: nameOfStoredKey(key), perSku: perSkuRounded, stored: hit.storedQuantity })
    }
  })
  // 2) 只在落库侧的键：Σ 推算 = 0 ⇒ 按 spec「逐键比较」的口径同样是差异
  //    （例如手工加进采购明细的物料、或 BOM 生成后被删掉的物料）。
  stored.forEach((hit, key) => {
    if (summed.has(key)) return
    if (Math.abs(hit.storedQuantity) > 0.005) {
      diffs.push({ materialName: nameOfStoredKey(key), perSku: 0, stored: hit.storedQuantity })
    }
  })
  return diffs
}
