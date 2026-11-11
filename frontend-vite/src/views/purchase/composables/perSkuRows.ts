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
 * 以及展示派生的 `magnifyByLossRate` / `ceilMagnifiedByLossRate` 等无依赖纯函数
 * 因此**从 useSummaryModal.ts 移入本模块**，由后者反向重导出，
 * 以保住既有测试「从 useSummaryModal 导入」的写法。
 * （`buildStoredRows` 需要按率加放取整，而它必须是叶子纯函数 —— 故这两个函数
 * 必须住在这里，不能反过来从 useSummaryModal.ts 取。）
 */
import type { FactoryGroup } from './useSummaryModal'

export interface SkuMaterial {
  supplier_name: string
  material_name: string
  /** 聚合键里的部位（**只用于键**：合并模式下后端会清空它以与无部位明细匹配） */
  part_name?: string
  /**
   * 「产品部位」列的展示文本（后端 `compose_part_display` 产出的唯一真值）。
   * 合并模式下可能是多部位（如 `身体/头部`），或带固定标记 `未标注`；
   * 旧后端不返回该字段时回退 `part_name`。
   */
  part_display?: string
  specification: string
  unit: string
  quantity: number
  /**
   * 「角色名称」列展示文本（后端按 BOM 的 role_id 归属产出，多角色共用同一物料时
   * 用 `/` 并列，如 `角色A/角色B`；默认 BOM 或无角色为空串）。
   */
  role_display?: string
  /** 该行所属角色 id（后端聚合键成员，role_quantities 按它匹配；默认 BOM/旧后端为空） */
  role_id?: number | null
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
 * 汇总物料键：`供应商 + 物料名 + 规格 + 单位 + 部位 + 角色`。
 *
 * 后端工厂汇总（fabric）与供应商汇总（material）同源，均按
 * (供应商, 物料, 规格, 单位, 部位) 聚合，故两侧可用同一键一一对应。
 * 用 `\u0000` 分隔，避免字段值本身含分隔符时发生键碰撞。
 *
 * `roleId`（2026-11-11 口径）：工厂汇总拆行至「角色 × 部位」粒度——同物料
 * 不同角色各自成行（数量/损耗率/编辑互不串行）。**未传（undefined）时键不含
 * 角色段**：供应商页（合并口径，用户裁决保持不动）与旧后端数据因此零行为变化；
 * `null`（默认 BOM 段）显式传入时用哨兵 `r0`，与角色行区分。
 */
export function summaryMaterialKey(
  supplierName: string | null | undefined,
  materialName: string | null | undefined,
  specification: string | null | undefined,
  unit: string | null | undefined,
  partName?: string | null,
  roleId?: number | null,
): string {
  const base = [
    supplierName || '未指定供应商', materialName || '', specification || '', unit || '', partName || '',
  ].join('\u0000')
  return roleId === undefined ? base : `${base}\u0000r${roleId ?? 0}`
}

/**
 * 损耗加放纯函数：按损耗率（千分之几）放大数量，四舍五入到 2 位小数。
 *
 * 语义 = `qty × (1 + lossRate / 1000)`。屏幕「数量」列、工厂/供应商合计、
 * 打印预览、Excel 导出共用这一处来源。
 *
 * 本函数**只做展示派生**，绝不写回 factoryData / supplierData ——
 * 原始数量才是落库唯一真值，放大值永远只是预览。
 *
 * 防御口径：非法输入（NaN / Infinity / 非数字）按 0 处理；
 * `lossRate = 0` 时同样执行「两位小数四舍五入」，保证与既有输出逐字一致、零回归。
 */
export function magnifyByLossRate(qty: number, lossRate: number): number {
  const v = Number.isFinite(qty) ? qty : 0
  const r = Number.isFinite(lossRate) ? lossRate : 0
  return Math.round((v + v * (r / 1000)) * 100) / 100
}

/**
 * 损耗加放后的「数量」展示值（向上取整）：屏幕表格、打印预览、Excel 导出共用。
 * 只在展示层取整，原始数量仍是落库唯一真值，保存反推仍使用精确的 magnifyByLossRate。
 */
export function ceilMagnifiedByLossRate(qty: number, lossRate: number): number {
  return Math.ceil(magnifyByLossRate(qty, lossRate))
}

/**
 * 「来源订单」逐单展示数量：把物料行的展示合计按各单原始数量占比分配为整数。
 *
 * 主行「数量」是损耗率加放后向上取整的采购量（与工厂内部订单同源）；来源明细若直接
 * 展示后端原始数量，会出现 8.33 这类小数、且与主行合计对不上。本函数用最大余数法
 * 把合计拆回各单：合计为整数时每单也是整数，且 Σ 明细 === 合计；
 * 合计带小数（BOM 回退等异常行）时按分（0.01）分配，仍保证相等。
 *
 * 纯展示派生，不回写任何落库数量。
 */
export function allocateOrderDisplayQuantities(
  displayTotal: number,
  orders: { order_no: string; quantity: number }[],
): { order_no: string; quantity: number }[] {
  if (orders.length === 0) return []
  const total = Number.isFinite(displayTotal) ? displayTotal : 0
  // 整数合计按「个」分配，保证输出是整数；非整数合计按「分」分配，保住 2 位精度
  const scale = Math.abs(total - Math.round(total)) < 1e-9 ? 1 : 100
  const units = Math.max(0, Math.round(total * scale))
  const weights = orders.map((o) => (Number.isFinite(o.quantity) && o.quantity > 0 ? o.quantity : 0))
  const weightTotal = weights.reduce((sum, w) => sum + w, 0)
  const shares = weightTotal > 0
    ? weights.map((w) => (units * w) / weightTotal)
    : weights.map(() => units / orders.length)

  const allocated = shares.map((v) => Math.floor(v))
  let remaining = units - allocated.reduce((sum, v) => sum + v, 0)
  // 余数按小数部分从大到小分配；并列时保持原顺序，保证展示稳定
  const byRemainder = shares
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i)
  for (let k = 0; k < byRemainder.length && remaining > 0; k++, remaining--) {
    const idx = byRemainder[k]!.i
    allocated[idx] = (allocated[idx] ?? 0) + 1
  }
  return orders.map((o, i) => ({ order_no: o.order_no, quantity: (allocated[i] ?? 0) / scale }))
}

/**
 * 损耗率归一化：与后端 `fastapi_app/services/purchase_utils.py::normalize_spare_rate` 同源。
 *
 * - `null` / `undefined` → `null`（语义为「没有值」，由调用方决定是否回退）；
 * - 非数值 / 非有限值（NaN / Infinity）→ `0`；
 * - `< 0` → `0`；`> 1000` → `1000`（与输入框 max=1000 一致）。
 */
function normalizeLossRate(rate: unknown): number | null {
  if (rate === null || rate === undefined) return null
  const value = typeof rate === 'number' ? rate : Number(rate)
  if (!Number.isFinite(value)) return 0
  if (value < 0) return 0
  if (value > 1000) return 1000
  return value
}

/**
 * 明细行的**有效损耗率**（千分之几）：逐行 loss_rate → 订单级 spare_rate → 0。
 *
 * 与后端 `fastapi_app/services/purchase_utils.py::resolve_item_loss_rate` 逐字同源。
 * 「数量」列（最终采购数量）与「金额」列（计价数量）必须用同一个损耗率，
 * 否则同一行会按两个数量计价，采购单总金额也会低于实际采购额。
 *
 * 显式的 0 视为有效值（不再回退订单级），与后端一致；
 * 逐行值非法（NaN / 负数 / 超上限）时按**归一化后的值**生效，不回退订单级 ——
 * 后端也是这样（它只对 None 回退），两边必须一致。
 */
export function resolveItemLossRate(itemLossRate: unknown, orderSpareRate: unknown): number {
  const itemRate = normalizeLossRate(itemLossRate)
  if (itemRate !== null) return itemRate
  const orderRate = normalizeLossRate(orderSpareRate)
  if (orderRate !== null) return orderRate
  return 0
}

export interface PerSkuRow {
  skuIdx: number
  /** 该 SKU 块在左侧「产品名称/订单数量/备品数量」三列里要显示的文本行（per-SKU 模式恒 1 行） */
  cellLines: { name: string; qty: number; spare: number; isTotal: boolean }[]
  isFirstSkuRow: boolean
  skuRowSpan: number
  /** 该行是否为「角色段」首行（角色格只在此行渲染，其余行由 rowspan 覆盖） */
  isFirstRoleRow: boolean
  /** 该角色段的行数（角色格 rowspan；角色连续成块，见 buildPerSkuRows 的连续段预计算） */
  roleRowSpan: number
  /** 该行是否为「(角色, 供应商) 连续子段」首行（供应商格只在此行渲染） */
  isFirstSupplierRow: boolean
  /** 该供应商子段的行数（供应商格 rowspan；**不是**全 SKU 计数，见连续段预计算注释） */
  supplierRowSpan: number
  supplierName: string
  materialName: string
  /** 聚合键里的部位（参与 `materialKeyOf`，合并模式下为空） */
  partName: string
  /** 「产品部位」列展示文本（可能多部位）；与 `partName` **刻意分离**，避免污染物料键 */
  partDisplay: string
  /** 「角色名称」列展示文本（多角色共用同一物料时并列，默认 BOM 为空串） */
  roleDisplay: string
  /** 该行所属角色 id（与后端聚合键同源；默认 BOM / 旧后端为 null） */
  roleId: number | null
  specification: string
  unit: string
  baseQuantity: number
  /** 该物料在落库明细中的坐标；无对应明细时为 null（率/数量退回「—/基准量」展示） */
  coord: { si: number; fi: number } | null
  itemIds: number[]
  /**
   * 数量编辑锁定原因（空串 = 可编辑）。锁定的两种：
   * 1. 无落库坐标（BOM 生成后新增的物料）——无率可显示、无明细可写；
   * 2. **同一 SKU 内多个角色共用同一采购明细行**——按角色分行后每行只是该角色的
   *    分配量，而明细是合并总量；编辑框若预载/写回总量会把「改分量」的意图写成
   *    「改总量」。**只锁数量编辑**：损耗率与展示走 coord 正常显示（一条明细一个率，
   *    各角色共用；生产反馈 2026-11-08：「在心里·肚皮」的损耗率显示 — 即此误伤）。
   */
  readonlyReason: string
  /**
   * 「订单数量」列按角色段拆分（2026-11-08 需求）：true = 该 SKU 带后端
   * role_quantities（与物料分配同源），「订单数量」列在每个角色段渲染该角色的
   * 数量格（rowspan=roleRowSpan），SKU 总量挪到「产品名称」格副行显示；
   * false（非盲盒 / 旧数据 / 无 BOM 占位行）= 保持 SKU 级大格，零行为变化。
   */
  hasRoleQtySplit: boolean
  /** 该角色段的数量（hasRoleQtySplit 时恒非 null；null = 不拆分走大格） */
  roleQuantity: number | null
  /**
   * 该角色段的**备品数量**（2026-11-08 用户要求：备品也按角色逐段算，不合并）：
   * ceil(该角色数量 × 订单级率‰)。hasRoleQtySplit 时恒非 null；null = 不拆分走大格。
   */
  roleSpare: number | null
  /** 该角色是否隐藏款（数量格里加标记，便于工厂区分常规/随箱配比） */
  roleIsHidden: boolean
  /** 该 SKU 无 BOM 明细时的占位行（保留块结构，不隐藏该 SKU） */
  noBom: boolean
}

/** 物料键：与工厂页/供应商页同源（复用 summaryMaterialKey，不另造一套）。
 *  供应商页调用（不传 role）键退化为合并口径；工厂页（perSku/stored）传 role 拆行。 */
export function materialKeyOf(m: {
  supplier_name?: string; material_name?: string; specification?: string; unit?: string
  part_name?: string; role_id?: number | null; withRole?: boolean
}): string {
  return summaryMaterialKey(
    m.supplier_name, m.material_name, m.specification, m.unit, m.part_name,
    m.withRole ? (m.role_id ?? null) : undefined,
  )
}

/** 落库明细索引：物料键（含角色）→ 坐标 / item_ids / 落库数量。 */
function buildStoredIndex(group: FactoryGroup) {
  const index = new Map<string, { coord: { si: number; fi: number }; itemIds: number[]; storedQuantity: number }>()
  ;(group.suppliers || []).forEach((supplier, si) => {
    ;(supplier.fabrics || []).forEach((fabric, fi) => {
      // 工厂侧键含 role（后端 fabrics 行带 role_id；旧后端无该字段 → null 哨兵，
      // 与 skus[].materials 的默认 BOM 行同键，零回归）
      const key = materialKeyOf({
        supplier_name: supplier.supplier_name,
        material_name: fabric.fabric_name,
        specification: fabric.specification,
        unit: fabric.unit,
        part_name: fabric.part_name,
        role_id: (fabric as { role_id?: number | null }).role_id,
        withRole: true,
      })
      const itemIds = fabric.item_ids || (fabric.item_id ? [fabric.item_id] : [])
      // 无落库明细的 BOM 行（BOM 生成后新增 / 旧单未生成）不建坐标：coord=null 只读，
      // 避免出现可编辑但保存时 item_ids 为空、静默不落库的输入框。
      if (itemIds.length === 0) return
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
        isFirstRoleRow: true,
        roleRowSpan: 1,
        isFirstSupplierRow: false,
        supplierRowSpan: 0,
        supplierName: '',
        materialName: '',
        partName: '',
        partDisplay: '',
        roleDisplay: '',
        roleId: null,
        specification: '',
        unit: '',
        baseQuantity: 0,
        coord: null,
        itemIds: [],
        readonlyReason: '',
        // 占位行没有物料段，无从按角色拆分数量——保持 SKU 级大格（总量在数量格里）
        hasRoleQtySplit: false,
        roleQuantity: null,
        roleSpare: null,
        roleIsHidden: false,
        noBom: true,
      })
      return
    }
    const skuQty = parseFloat(String(sku.order_qty ?? 0)) || 0
    // 同一 SKU 内「同角色同部位」的同一物料键出现多次 → 锁**数量编辑**：
    // 2026-11-11 拆行口径下键已含 role_id，多角色各成一行、键互不相同，
    // 原先「多角色共用一行」的锁定自然解除（每行有自己的坐标与 item_ids）。
    // 剩余会命中的场景：同角色同部位内 BOM 真的配了重复物料行（合并进同一明细行）。
    const keyCounts = new Map<string, number>()
    materials.forEach((m) => {
      const k = materialKeyOf({ ...m, withRole: true })
      keyCounts.set(k, (keyCounts.get(k) || 0) + 1)
    })
    // 连续段预计算（**表格对齐的基础**）：角色段 + 段内「(角色, 供应商)」子段。
    // 物料按角色排序后，同一供应商会出现在多个角色段里（互不相邻）——供应商格
    // 的 rowspan 必须按「连续子段」算；按全 SKU 计数会把中间其它供应商的行也
    // 罩进去，直接造成表头与数据错位（2026-11-08 生产反馈）。
    const roleRunSpan = new Map<number, number>()      // 段首行号 -> 角色段行数
    const supplierRunSpan = new Map<number, number>()  // 子段首行号 -> 供应商子段行数
    for (let i = 0; i < materials.length;) {
      const roleName = materials[i]!.role_display || ''
      let j = i
      while (j < materials.length && (materials[j]!.role_display || '') === roleName) j++
      roleRunSpan.set(i, j - i)
      for (let k = i; k < j;) {
        const sup = materials[k]!.supplier_name
        let l = k
        while (l < j && materials[l]!.supplier_name === sup) l++
        supplierRunSpan.set(k, l - k)
        k = l
      }
      i = j
    }

    // 「订单数量」按角色段拆分（2026-11-08 需求）：role_quantities 与物料分配
    // 同源（后端同一次 allocate 产出）。键用 role_id（null=默认 BOM 段）；
    // 匹配不到时兜底 0（同源下不会发生，宁可显示 0 也不能让该段缺数量格——缺格
    // 会让后续整行错位）。
    const roleQtyList = sku.role_quantities || []
    const hasRoleQtySplit = roleQtyList.length > 0
    const roleQtyMap = new Map<string, { qty: number; hidden: boolean }>()
    roleQtyList.forEach((r) => {
      roleQtyMap.set(String(r.role_id ?? 'null'), {
        qty: parseFloat(String(r.quantity)) || 0,
        hidden: !!r.is_hidden,
      })
    })
    const roleQtyOf = (rid: number | null | undefined): number | null => {
      if (!hasRoleQtySplit) return null
      const hit = roleQtyMap.get(String(rid ?? 'null'))
      return hit ? hit.qty : 0
    }
    const roleHiddenOf = (rid: number | null | undefined): boolean => {
      if (!hasRoleQtySplit) return false
      return roleQtyMap.get(String(rid ?? 'null'))?.hidden || false
    }

    materials.forEach((m, i) => {
      const key = materialKeyOf({ ...m, withRole: true })
      const hit = stored.get(key)
      const sharedInSku = (keyCounts.get(key) || 0) > 1
      const roleQty = roleQtyOf(m.role_id)
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
        isFirstRoleRow: roleRunSpan.has(i),
        roleRowSpan: roleRunSpan.get(i) || 0,
        isFirstSupplierRow: supplierRunSpan.has(i),
        supplierRowSpan: supplierRunSpan.get(i) || 0,
        supplierName: m.supplier_name,
        materialName: m.material_name,
        partName: m.part_name || '',
        // 展示取后端拼好的文本：合并模式下 `part_name` 恒为空（那是聚合键），
        // 若这里回退到 `part_name` 整列就会空白（2026-11-05 生产缺陷）。
        partDisplay: m.part_display || m.part_name || '',
        roleDisplay: m.role_display || '',
        roleId: m.role_id ?? null,
        specification: m.specification,
        unit: m.unit,
        baseQuantity: parseFloat(String(m.quantity)) || 0,
        // 坐标恢复指向落库明细（率/数量展示的读源）；是否锁数量编辑由 readonlyReason 表达
        coord: hit?.coord ?? null,
        itemIds: hit?.itemIds ?? [],
        readonlyReason: sharedInSku
          ? '该物料在同一角色同一部位内被 BOM 重复配置、合并为采购明细的同一行；如需调整总量请在采购明细中修改'
          : '',
        hasRoleQtySplit,
        roleQuantity: roleQty,
        roleSpare: roleQty != null ? calcSpareQuantity(roleQty, groupRate) : null,
        roleIsHidden: roleHiddenOf(m.role_id),
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
): { materialName: string; partName: string; perSku: number; stored: number }[] {
  if (rows.length === 0) return []
  const stored = buildStoredIndex(group)
  const nameOfStoredKey = (key: string) => key.split('\u0000')[1] || ''
  const partOfStoredKey = (key: string) => key.split('\u0000')[4] || ''
  const summed = new Map<string, number>()
  rows.forEach((r) => {
    if (r.noBom) return   // 占位行不对应任何物料，不参与比对
    // 键含角色（与 buildStoredIndex 同口径）：角色行各比对各自的落库量
    const key = materialKeyOf({
      supplier_name: r.supplierName, material_name: r.materialName,
      specification: r.specification, unit: r.unit, part_name: r.partName,
      role_id: r.roleId, withRole: true,
    })
    summed.set(key, (summed.get(key) ?? 0) + r.baseQuantity)
  })

  const diffs: { materialName: string; partName: string; perSku: number; stored: number }[] = []
  // 1) 遍历按 SKU 侧的键：既覆盖「两侧都有」的键，也覆盖「只在 BOM 侧」的新增物料
  //    （落库没有 → 不是差异，跳过）。
  summed.forEach((perSku, key) => {
    const hit = stored.get(key)
    if (!hit) return                       // 只出现在 BOM、落库里没有 → 不是「差异」，是新增物料
    const perSkuRounded = Math.round(perSku * 100) / 100
    if (Math.abs(perSkuRounded - hit.storedQuantity) > 0.005) {
      diffs.push({
        materialName: nameOfStoredKey(key), partName: partOfStoredKey(key),
        perSku: perSkuRounded, stored: hit.storedQuantity,
      })
    }
  })
  // 2) 只在落库侧的键：Σ 推算 = 0 ⇒ 按 spec「逐键比较」的口径同样是差异
  //    （例如手工加进采购明细的物料、或 BOM 生成后被删掉的物料）。
  stored.forEach((hit, key) => {
    if (summed.has(key)) return
    if (Math.abs(hit.storedQuantity) > 0.005) {
      diffs.push({
        materialName: nameOfStoredKey(key), partName: partOfStoredKey(key),
        perSku: 0, stored: hit.storedQuantity,
      })
    }
  })
  return diffs
}

/**
 * 对照块的一行（列序与**主表**一致的后 5 格：布料名称 | 规格型号 | 损耗率 | 数量 | 单位）。
 *
 * 率与数量在此**与主表同源**算好：率取该落库行的快照率（缺省回退该组订单级率），
 * 数量为按该率加放后向上取整（`ceilMagnifiedByLossRate`）——组件 / 打印因此保持
 * 「纯展示」，不会出现同一张表里两个「数量」口径不一致。供应商/段信息供渲染 `rowspan`。
 *
 * 屏幕（`useFactoryTableRows.storedRowsOf`）与打印/导出（`buildFactoryHtml`）
 * **共用本函数产出**，故两边的对照块结构天然一致（打印件不会对差异保持沉默）。
 */
export interface StoredRow {
  supplierName: string
  /** 该行是否为本供应商段首行（供应商格只在此行渲染，其余行由 rowspan 覆盖） */
  isSupplierFirst: boolean
  /** 本供应商段行数（供应商格的 rowspan） */
  supplierSpan: number
  fabricName: string
  /** 聚合键里的部位（差异匹配用，与主表物料键同源） */
  partName: string
  /** 「产品部位」列展示文本（可能多部位，见 `SkuMaterial.part_display`） */
  partDisplay: string
  /** 「角色名称」列展示文本（与主表同源；旧后端不返回该字段时为空串） */
  roleDisplay: string
  specification: string
  unit: string
  /** 该落库行的损耗率（快照率优先，缺省回退 `rateOf`） */
  rate: number
  /** 「数量」列展示值（与主表同源：按 rate 加放后向上取整） */
  displayQuantity: number
}

/**
 * 该组落库物料行（按供应商分段），率与数量按主表同源口径算好：
 * `rate = f.loss_rate ?? rateOf(si, fi)`；数量 = `ceil(该率加放)`。
 *
 * 形参是纯回退函数（不依赖任何 composable 状态）：屏幕传「该组订单级率」、
 * 打印传同一个率 —— 两侧因此得到逐字一致的行。
 */
export function buildStoredRows(
  group: FactoryGroup, rateOf: (si: number, fi: number) => number,
): StoredRow[] {
  const out: StoredRow[] = []
  ;(group.suppliers || []).forEach((supplier, si) => {
    const fabrics = supplier.fabrics || []
    fabrics.forEach((f, fi) => {
      const rate = f.loss_rate ?? rateOf(si, fi)
      out.push({
        supplierName: supplier.supplier_name,
        isSupplierFirst: fi === 0,
        supplierSpan: fabrics.length,
        fabricName: f.fabric_name,
        partName: f.part_name || '',
        partDisplay: f.part_display || f.part_name || '',
        roleDisplay: f.role_display || '',
        specification: f.specification || '',
        unit: f.unit || '',
        rate,
        displayQuantity: ceilMagnifiedByLossRate(parseFloat(String(f.quantity)) || 0, rate),
      })
    })
  })
  return out
}
