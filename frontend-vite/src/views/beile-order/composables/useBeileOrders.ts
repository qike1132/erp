/**
 * useBeileOrders.ts — 湖北订单列表数据逻辑
 *
 * 从 BeileOrderTab.vue 下沉的逻辑：查询（vue-query）、筛选、分页、
 * 确认状态切换、订单确认（乐观更新）、
 * 选中/导出/打印（原 BeileOrderTab 头部桥接逻辑上提至此）。
 *
 * HubeiView 调用 provideBeileOrders() 创建唯一实例并 provide，
 * BeileOrderTab 通过 injectBeileOrders() 注入同一实例，
 * 消除 ref 反向桥接导致的父子联动重渲染。
 */
import { reactive, computed, ref, watch, provide, inject, onUnmounted, type InjectionKey } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import type { OrderItem } from '@/types'
import type { OrderListApiResponse } from '@/api/order'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { useExport } from '@/composables/useExport'
import { downloadXls } from '@/utils/xls'
import { escapeHtml, printHtml } from '@/utils/print'

/** 每页条数选项（分页组件下拉可选） */
export const PAGE_SIZE_OPTIONS = [18, 30, 50, 100]

/**
 * 未下单固定文案（与后端 409 detail 逐字一致，设计 §11.4）：
 * - TOAST：前端门控前置拦截时的 toast 文案；
 * - TIP：数量列「未下单」徽章 / 确认按钮禁用态的 hover tooltip。
 */
export const NOT_ORDERED_TOAST = '请先在采购中心完成下单'
export const NOT_ORDERED_TIP = '该订单未在采购中心完成下单'
export const NOT_ORDERED_DETAIL = '该订单未在采购中心完成下单，请先在采购中心完成下单后再确认'

/** 湖北订单行：OrderItem 在后端实际响应中还包含 order_no / customer / product（未在 OrderItem 类型中声明） */
export type BeileOrderRow = OrderItem & {
  order_no?: string
  customer?: string
  record_type?: 'order' | 'stockin'
  factories?: string[]
  /** 后端 beile-list 返回的首个 SKU 产品图路径 */
  product_image?: string | null
  /** 湖北订单确认状态：confirmed=false 即「未确认订单」 */
  confirmed?: boolean
  confirmed_at?: string
  confirmed_by?: string
  /**
   * 订单级下单数量（合计口径，方案 C 修正后）：
   * - order 行 / 备货**精确**匹配 → 该来源自身逐 SKU 快照「按产品名 MAX 去重再求和」；
   *   逐 SKU 快照不可得时回退 completed 采购单 product_quantity 的 MAX；
   * - 备货**模糊**匹配（无精确逐 SKU 行） → **null**（模糊匹配只决定 is_ordered，不产出数量，
   *   D-R2-1）；此消费方一律按 `!= null` 守卫后再用，绝不用 `?? 0` 渲染成 0；
   * - 未下单 → 原数量。
   */
  purchase_order_qty?: number | null
  /**
   * 订单级备品数量（生产数量的计算输入，独立展示列已删除）：口径同 purchase_order_qty；
   * 备货模糊匹配降级时为 null；未下单 = 0。
   */
  spare_quantity?: number | null
  /** 损耗率快照(千分之几)：未下单 / 历史 NULL = null */
  spare_rate?: number | null
  /** 是否已下单（存在 status='completed' 的关联采购单） */
  is_ordered?: boolean
  product?: { id: number; name: string; barcode: string; image: string }
}

/** SKU 是否匹配关键字（产品名称或条码） */
function skuMatchesKeyword(sku: { product_name?: string | null; product_barcode?: string | null }, kw: string): boolean {
  return (sku.product_name || '').toLowerCase().includes(kw)
    || (sku.product_barcode || '').toLowerCase().includes(kw)
}

// ==================== 逐 SKU 数量口径（页面 = 导出 = 打印 单一真源） ====================
// 方案 C：后端已持久化 purchase_order_sku 逐 SKU 快照，并在 /beile-list 的 items[] 上注入
// purchase_order_qty / spare_quantity / is_ordered / per_sku_source。以下函数是「数量口径」的
// 唯一权威实现，BeileOrderRow.vue、导出/打印两处共用，杜绝口径再次漂移。

/**
 * 数量口径计算所需的「最小 SKU 字段集」。
 *
 * OrderSKU（页面逐 SKU 行）与导出/打印用的「无明细回落行」都满足该形状，
 * 使同一套口径函数（skuOrderQty / skuProductionQty / skuIsOrdered）可被
 * 页面、导出 XLS、打印预览三处复用，而无需强转完整 OrderSKU。
 */
export type SkuQtyFields = {
  /** SKU 行主键（页面逐 SKU 行有；无明细回落行无）——供 v-for 稳定 key 用 */
  id?: number
  product_name?: string | null
  product_barcode?: string | null
  quantity?: number
  purchase_order_qty?: number | null
  spare_quantity?: number | null
  per_sku_source?: 'po_sku' | 'order_level'
}

/**
 * 行内可见 SKU（页面行与导出/打印共用同一真源）：
 * 应用产品筛选时仅保留名称/条码命中者；命中为空则回退全部（避免空列表）。
 *
 * 泛型保留入参元素类型：页面传入 OrderSKU[] 仍得到 OrderSKU[]（需要 `id`），
 * 导出回落的 `SkuQtyFields[]` 亦不被丢失类型信息。
 */
export function filterVisibleSkus<T extends SkuQtyFields>(items: T[], keyword: string): T[] {
  const kw = keyword.trim().toLowerCase()
  if (!kw) return items
  const matched = items.filter((s) => skuMatchesKeyword(s, kw))
  return matched.length > 0 ? matched : items
}

/**
 * 逐 SKU「订单数量」：
 * 1) 命中逐 SKU 快照（per_sku_source === 'po_sku'）→ 该 SKU 实际下单量（同 SKU 拆多供应商取 MAX）；
 * 2) 单 SKU 行且整行已下单**且订单级数量可得**（purchase_order_qty != null）→ 回退订单级值；
 *    ⚠️ 订单级数量为 null（备货模糊匹配降级）时必须落到规则 3 —— 否则会被 `?? 0` 渲染成 0（新的错误显示）；
 * 3) 其余 → 该 SKU 客户订单原数量（始终准确可得）。
 */
export function skuOrderQty(row: BeileOrderRow, sku: SkuQtyFields): number {
  if (sku.per_sku_source === 'po_sku' && sku.purchase_order_qty != null) return sku.purchase_order_qty
  if (row.is_ordered === true && (row.items?.length ?? 0) === 1 && row.purchase_order_qty != null) {
    return row.purchase_order_qty
  }
  return sku.quantity || 0
}

/**
 * 逐 SKU「生产数量」：
 * 1) 命中逐 SKU 快照 → 该 SKU 下单量 + 该 SKU 备品量；
 * 2) 单 SKU 行且整行已下单**且订单级数量可得** → 回退订单级 (下单量 + 备品量)；
 *    ⚠️ 订单级数量为 null 时不回退（否则会把 null 当 0 编造生产数量）；
 * 3) 其余 → null（展示「—」）。订单级标量无法拆分到 SKU，宁可显示「—」也不编造数字。
 */
export function skuProductionQty(row: BeileOrderRow, sku: SkuQtyFields): number | null {
  if (sku.per_sku_source === 'po_sku' && sku.purchase_order_qty != null) {
    return (sku.purchase_order_qty || 0) + (sku.spare_quantity || 0)
  }
  if (row.is_ordered === true && (row.items?.length ?? 0) === 1 && row.purchase_order_qty != null) {
    return row.purchase_order_qty + (row.spare_quantity ?? 0)
  }
  return null
}

/**
 * 逐 SKU 的「订单数量」是否来自采购单实际下单量（决定是否加粗）。
 * 加粗 ⇔ 该数值确实来自采购单：
 * 1) 命中逐 SKU 快照（per_sku_source === 'po_sku'）→ 真·采购单实际下单量；
 * 2) 单 SKU 行且整行已下单**且订单级数量可得**（purchase_order_qty != null）→ 订单级即等于该 SKU。
 * ⚠️ 订单级数量为 null（备货模糊匹配降级，D-R2-1）时该 SKU 显示的是**自身订单原数量回退值**，
 *    并非采购单实际下单量 → **不加粗**（与 skuOrderQty / skuProductionQty 守卫口径一致）。
 */
export function skuIsOrdered(row: BeileOrderRow, sku: SkuQtyFields): boolean {
  if (sku.per_sku_source === 'po_sku') return true
  return row.is_ordered === true && (row.items?.length ?? 0) === 1 && row.purchase_order_qty != null
}

// ==================== 列布局单一真源（页面表头 = 行块网格，逐列同源） ====================
// 2026-10-15 多 SKU 改版：页面从「一行一单」改为「一行一 SKU + 订单级列跨行合并」
// （对齐 /report 订单流水的方案 C）。订单级列（类型/单号/时间/客户/工厂/小义开单/
// 确认/备注）在行块内跨 `span` 行合并；SKU 列（产品名称/条码/订单数量/生产数量）逐行。
// 列序 / 列宽 / 可见性由本表唯一决定，BeileOrderTab（表头）与 BeileOrderRow（行块）
// 共用，杜绝两处列定义漂移导致错位。

export type BeileColScope = 'order' | 'sku'

export interface BeileCol {
  key: string
  label: string
  /** 列宽（px）；'flex' = 末列弹性占满剩余宽度 */
  width: number | 'flex'
  align: 'left' | 'center'
  /** order = 订单级（跨行合并）；sku = 逐 SKU 行 */
  scope: BeileColScope
}

/** 行块内单行高度（px）：SKU 行 / 订单级跨行格的每行高一致（虚拟滚动定高基准） */
export const BEILE_ROW_HEIGHT = 44

/**
 * 计算当前可见列（按视觉顺序）。可见性：
 * - select（打印权限）：canPrint
 * - confirmStatus / confirmAction：随 confirmStatus 筛选互斥显隐（与旧实现一致）
 * 其余列恒可见。
 */
export function beileColumns(opts: { canPrint: boolean; confirmStatus: string }): BeileCol[] {
  const cols: BeileCol[] = []
  if (opts.canPrint) cols.push({ key: 'select', label: '', width: 40, align: 'center', scope: 'order' })
  cols.push(
    { key: 'type', label: '订单类型', width: 70, align: 'center', scope: 'order' },
    { key: 'orderNo', label: '订单号', width: 145, align: 'center', scope: 'order' },
    { key: 'date', label: '下单时间', width: 140, align: 'center', scope: 'order' },
    { key: 'customer', label: '客户名称', width: 125, align: 'center', scope: 'order' },
    { key: 'factory', label: '工厂', width: 85, align: 'center', scope: 'order' },
    { key: 'productName', label: '产品名称', width: 495, align: 'center', scope: 'sku' },
    { key: 'orderQty', label: '订单数量', width: 90, align: 'center', scope: 'sku' },
    { key: 'prodQty', label: '生产数量', width: 90, align: 'center', scope: 'sku' },
    { key: 'opened', label: '小义开单', width: 90, align: 'center', scope: 'order' },
  )
  if (opts.confirmStatus !== 'unconfirmed') {
    cols.push({ key: 'confirmStatus', label: '确认状态', width: 90, align: 'center', scope: 'order' })
  }
  if (opts.confirmStatus !== 'confirmed') {
    cols.push({ key: 'confirmAction', label: '确认操作', width: 110, align: 'center', scope: 'order' })
  }
  cols.push({ key: 'note', label: '备注', width: 'flex', align: 'left', scope: 'order' })
  return cols
}

/** CSS Grid 列模板（表头与行块共用，保证逐列对齐） */
export function beileGridTemplate(cols: BeileCol[]): string {
  return cols.map((c) => (c.width === 'flex' ? 'minmax(160px, 1fr)' : `${c.width}px`)).join(' ')
}

/** 水平滚动最小宽度 = 各列宽之和（弹性列按 160px 保底） */
export function beileMinWidth(cols: BeileCol[]): number {
  return cols.reduce((sum, c) => sum + (c.width === 'flex' ? 160 : c.width), 0)
}

// ==================== 订单块视图模型（BeileOrderRow 的 computed 群） ====================

/**
 * 订单块的可见 SKU 明细（页面行 / 导出打印 / 块高预估三处共用单一真源）：
 * 无 items 明细的备货记录回落为单行（订单级 product_name/quantity）。
 */
export function visibleSkus(item: BeileOrderRow, keyword: string): SkuQtyFields[] {
  const base: SkuQtyFields[] = (item.items && item.items.length > 0)
    ? item.items
    : [{ product_name: item.product_name ?? null, product_barcode: null, quantity: item.quantity ?? 0 }]
  return filterVisibleSkus(base, keyword)
}

/**
 * 订单块视图模型：可见 SKU 明细 + 订单级列合并跨度。
 * 页面 grid-row 跨行、导出 rowspan、虚拟滚动块高预估都由此派生，杜绝三处分叉。
 */
export function beileBlockView(
  item: BeileOrderRow,
  keyword: string,
): { skus: SkuQtyFields[]; span: number } {
  const skus = visibleSkus(item, keyword)
  return { skus, span: skus.length }
}

/** useBeileOrderBlock 入参形状：BeileOrderRow.vue 的 props（响应式传入，computed 才能追踪） */
export interface BeileOrderBlockOptions {
  item: BeileOrderRow
  confirmStatus: string
  selectable: boolean
  keyword?: string
}

/**
 * 订单块视图模型：列拆分 / 单元格定位 / 可见 SKU。
 * 从 BeileOrderRow.vue 抽出（组件 ≤400 行门禁），布局与数量口径仍与
 * 导出 buildSummaryTbody 同源（AC-12）。传入 props 实例即可，
 * 内部 computed 直接读 opts.xxx 保持响应式追踪（勿预先解构）。
 */
export function useBeileOrderBlock(opts: BeileOrderBlockOptions) {
  const cols = computed<BeileCol[]>(() => beileColumns({
    canPrint: opts.selectable,
    confirmStatus: opts.confirmStatus,
  }))
  const orderCols = computed(() => cols.value.filter((c) => c.scope === 'order'))
  const skuCols = computed(() => cols.value.filter((c) => c.scope === 'sku'))

  /** 列 key → grid-column 序号（1 基） */
  const colIndex = computed(() => {
    const m = new Map<string, number>()
    cols.value.forEach((c, i) => m.set(c.key, i + 1))
    return m
  })

  const blockStyle = computed(() => ({
    gridTemplateColumns: beileGridTemplate(cols.value),
    // 行高下限 44px、上限随内容（对齐 /report 订单流水）：产品名称换行超过一行时
    // 行随之增高、完整显示；若写死 44px，长名称会被 `.bo-td` 的 overflow:hidden 裁掉
    // （实证 PO-20261015-2585 有 40 字名称）。
    // 虚拟滚动为变高模式（dynamicHeight），按实测块高定位，故允许行高变化。
    gridAutoRows: `minmax(${BEILE_ROW_HEIGHT}px, auto)`,
  }))

  /** 单元格显式定位：span>1 即跨行合并（等效 rowspan） */
  function cellStyle(key: string, row: number, span: number) {
    return {
      gridColumn: String(colIndex.value.get(key) ?? 1),
      gridRow: span > 1 ? `${row} / span ${span}` : String(row),
    }
  }

  /**
   * 可见 SKU（与导出/打印 buildSummaryTbody 的 filterVisibleSkus 同源）：
   * 无 items 明细的备货记录回落为单行（订单级 product_name / quantity）。
   */
  /** 块视图模型（可见 SKU / 合并跨度）：与导出、块高预估共用单一真源 */
  const blockView = computed(() => beileBlockView(opts.item, opts.keyword || ''))
  const skus = computed<SkuQtyFields[]>(() => blockView.value.skus)
  /** 订单级列的合并跨度 = 逐 SKU 行数 */
  const span = computed(() => blockView.value.span)

  return {
    orderCols,
    skuCols,
    blockStyle,
    cellStyle,
    skus,
    span,
  }
}

// ==================== 汇总表（导出 XLS = 打印预览，与页面同一真源） ====================

/**
 * 汇总表「小义开单」列口径（订单级事实，与 /beile-order 页面同源）：
 * is_ordered === true → 「已开单」；否则 → 「未开单」。
 */
export function summaryOpenedLabel(item: BeileOrderRow): string {
  return item.is_ordered === true ? '已开单' : '未开单'
}

/** 生产数量单元格文本：null（无法派生）→ 「—」 */
function summaryProductionText(v: number | null): string {
  return v === null ? '—' : String(v)
}

/**
 * 构建汇总表 tbody HTML（页面 = 导出 XLS = 打印预览同源，AC-12）。
 *
 * 粒度（任务书 D.13 裁决）：
 * - 「产品名称 / 订单数量 / 生产数量」**逐 SKU 输出**，复用页面同一真源函数
 *   （skuOrderQty / skuProductionQty），不再整段 rowspan 到订单级；
 * - 「小义开单」为订单级事实，保持整单 rowspan；
 * - 「订单类型 / 下单时间 / 客户名称 / 工厂」为订单级，整单 rowspan。
 *
 * @param items 待输出订单行（导出=当前展示页；打印=选中行）
 * @param keyword 已应用的产品关键字：与页面行一致，仅输出命中该关键字的 SKU
 */
export function buildSummaryTbody(items: BeileOrderRow[], keyword: string): string {
  let html = ''
  for (const item of items) {
    const type = item.record_type === 'stockin' ? '备货' : '订单'
    const factory = (item.factories || ['湖北']).join(', ')
    // 订单级列（订单类型 / 订单号 / 下单时间 / 客户名称 / 工厂）：整单 rowspan
    const orderCells = [type, item.order_no || '-', item.order_date || '', item.customer || '', factory]
    const openedText = summaryOpenedLabel(item)
    const note = item.note || ''

    // 可见 SKU / 合并跨度：与页面行块、块高预估共用单一真源（beileBlockView）
    const { skus, span } = beileBlockView(item, keyword)
    const spanAttr = span > 1 ? ` rowspan="${span}"` : ''

    skus.forEach((sku, idx) => {
      const cells: string[] = []
      if (idx === 0) {
        for (const c of orderCells) cells.push(`<td${spanAttr}>${escapeHtml(c)}</td>`)
      }
      cells.push(`<td>${escapeHtml(sku.product_name || '-')}</td>`)
      cells.push(`<td>${escapeHtml(String(skuOrderQty(item, sku)))}</td>`)
      cells.push(`<td>${escapeHtml(summaryProductionText(skuProductionQty(item, sku)))}</td>`)
      if (idx === 0) cells.push(`<td${spanAttr}>${escapeHtml(openedText)}</td>`)
      cells.push(`<td>${idx === 0 ? escapeHtml(note) : ''}</td>`)
      html += `<tr>${cells.join('')}</tr>`
    })
  }
  return html
}

/** 湖北订单列表：查询 + 筛选 + 分页 + 确认流程 + 选中/导出/打印 */
export function useBeileOrders() {
  /** 当前每页条数，可由分页组件修改 */
  const perPage = ref(18)

  /**
   * 输入文本与已应用筛选分离：
   * - filters.productKw / filters.customer = 输入框显示文本（用户自由键入，不触发筛选）
   * - appliedProduct / appliedCustomer = 已确认的筛选值（选择建议 / 点击查询后生效）
   */
  const filters = reactive({  productKw: '', customer: '' })
  const appliedProduct = ref('')
  const appliedCustomer = ref('')

  /** 确认状态筛选：unconfirmed=未确认 / confirmed=已确认（默认未确认） */
  const confirmStatus = ref('unconfirmed')

  const page = ref(1)

  const currentPage = computed(() => page.value)

  const {
    data: ordersData,
    isLoading,
    isFetching,
    /**
     * 首屏/翻页请求失败（2026-10-30 审计 A-M32）。
     *
     * 原先只取 isLoading，失败时 data 为空、loading 结束，模板落到「暂无订单」——
     * 5xx/超时被渲染成「没有数据」这一业务结论，用户不会重试也不会报障。
     */
    isError,
    refetch,
  } = useQuery({
    /**
     * 湖北订单列表查询 key：随筛选/分页变化（乐观更新时复用同一 key）。
     * 已加入 appliedProduct：产品筛选改为服务端生效（`product`）后，
     * 关键字变化必须触发重新查询（P-2 / RC-5）。
     */
    queryKey: ['beile-orders', appliedCustomer, appliedProduct, confirmStatus, () => page.value, () => perPage.value],
    queryFn: () =>
      orderApi.beileList({
        customer: appliedCustomer.value || undefined,
        // 产品筛选服务端生效（按 SKU 名/条码）。
        // ⚠️ 后端 Query 参数名是 `product`（见 endpoints/order.py::list_beile_orders），
        //    不是 `product_kw` —— 写错会被 FastAPI 静默忽略、等同无筛选（RC-5 失效）。
        product: appliedProduct.value || undefined,
        confirm_status: confirmStatus.value || undefined,
        page: page.value,
        per_page: perPage.value,
      }),
    // 「每次显示都取数」：本查询会被 persistQueryClient 存进 sessionStorage，恢复的
    // 快照自带 dataUpdatedAt；若沿用 staleTime，刷新/切回本页时快照被判「新鲜」→ 不重取
    // → 显示客户订单删除前的旧列表（实测延迟 30s）。
    //   staleTime: 0            —— 任何时刻都视为过期，显示即允许重取
    //   refetchOnMount: 'always'—— 挂载（刷新/路由进入）必定重取
    //   refetchOnWindowFocus    —— 切回本标签页必定重取（WS 可能正好断线，不能只靠推送）
    // keepPreviousData 保证仍先渲染缓存（秒开），校正结果随即覆盖。
    staleTime: 0,
    gcTime: 60_000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  })

  /** 服务端返回的订单列表（已应用 customer 筛选与分页） */
  const orders = computed<BeileOrderRow[]>(() => (ordersData.value?.data ?? []) as BeileOrderRow[])
  const totalItems = computed(() => ordersData.value?.total ?? 0)
  const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage.value)))

  /** 湖北订单确认流程：未确认订单总数（全局，列表顶部横幅用） */
  const unconfirmedCount = computed(() => ordersData.value?.unconfirmed_count ?? 0)

  /**
   * 客户端二次过滤：当前页订单中 product_name/barcode 模糊匹配。
   * 仅当 appliedProduct 有值时才过滤（选择建议或点击查询后生效），
   * 自由键入不触发过滤，避免输入中途表格发生抖动。
   * 匹配任一 SKU（名称或条码），而不只是订单首个产品。
   */
  const displayOrders = computed<BeileOrderRow[]>(() => {
    const kw = appliedProduct.value.trim().toLowerCase()
    if (!kw) return orders.value
    return orders.value.filter((o) => {
      if ((o.product_name || '').toLowerCase().includes(kw)) return true
      return (o.items || []).some((s) => skuMatchesKeyword(s, kw))
    })
  })

  /** URL order_id 参数：高亮对应订单行（通知点击跳转场景） */
  const route = useRoute()
  const highlightId = computed<string | null>(() => {
    const oid = route.query.order_id
    return oid ? String(oid) : null
  })

  /** 由父组件在用户点击自动补全候选项时调用 */
  function applyProductFilter(name: string) {
    appliedProduct.value = name
  }

  /** 由父组件在用户点击客户候选项时调用 */
  function applyCustomerFilter(name: string) {
    appliedCustomer.value = name
  }

  function handleSearch() {
    // 点击查询按钮：将输入框当前文本确认为筛选值
    appliedProduct.value = filters.productKw
    appliedCustomer.value = filters.customer
    refetch()
  }

  function handleReset() {
    filters.productKw = ''
    filters.customer = ''
    appliedProduct.value = ''
    appliedCustomer.value = ''
    page.value = 1
    refetch()
  }

  function goPage(p: number) {
    page.value = p
  }

  /** 切换确认状态筛选并回到第一页 */
  function setConfirmStatus(v: string) {
    confirmStatus.value = v
    page.value = 1
  }

  /** 确认中订单 id 集合（防止重复点击，按钮禁用态依赖） */
  // F1a-09（2026-10-24 审计）：与 rowKey 同款复合键——裸 id 会让订单/备货
  // 撞号时互相误禁用/误拦截（rowKey 注释自证 id 可能撞号）。
  const confirmingIds = ref<Set<string>>(new Set())

  const queryClient = useQueryClient()

  /** 当前查询 key（乐观更新 setQueryData 复用；须与 useQuery 的 queryKey 完全一致） */
  const queryKey = computed(() =>
    ['beile-orders', appliedCustomer.value, appliedProduct.value, confirmStatus.value, page.value, perPage.value] as const,
  )

  /**
   * 确认湖北订单/备货：未确认的订单与备货记录均显示确认按钮，
   * 确认后由后端落库 confirmed_at。在「未确认」筛选下成功后立即
   * 从列表移除该行并递减未确认计数，无需等待定时刷新；
   * 其他筛选下照常 refetch。
   *
   * 门控（PRD P0-4 前端侧 / CR-1 收敛）：仅当「**未确认 且 未下单**」时
   * toast 拦截，不发请求；已确认的历史记录不会触发门控（既无动作也无风险）；
   * 后端另有 409 兜底（双端拦截）。
   */
  async function handleConfirm(item: BeileOrderRow) {
    if (item.confirmed) return
    // 门控（CR-1 收敛）：此处 item.confirmed 必为假，仅需判「未下单」
    if (item.is_ordered === false) {
      toast.error(NOT_ORDERED_TOAST)
      return
    }
    const confirmKey = rowKey(item)
    if (confirmingIds.value.has(confirmKey)) return
    confirmingIds.value.add(confirmKey)
    try {
      const isStockin = item.record_type === 'stockin'
      const res = isStockin
        ? await orderApi.confirmBeileStockin(item.id)
        : await orderApi.confirmBeileOrder(item.id)
      toast.success(res.message || (isStockin ? '备货已确认' : '订单已确认'))
      if (confirmStatus.value === 'unconfirmed') {
        queryClient.setQueryData<OrderListApiResponse>(queryKey.value, (old) => {
          if (!old) return old
          // 订单与备货来自不同表，id 可能撞号，需同时匹配 record_type
          const data = ((old.data || []) as BeileOrderRow[]).filter((o) => !(o.id === item.id && o.record_type === item.record_type))
          return {
            ...old,
            data,
            total: Math.max(0, (old.total ?? 0) - 1),
            unconfirmed_count: Math.max(0, (old.unconfirmed_count ?? 0) - 1),
          }
        })
        // 当前页被清空且不是第一页时回退一页
        if (orders.value.length === 0 && page.value > 1) {
          page.value -= 1
        }
      } else {
        await refetch()
      }
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || '确认失败')
    } finally {
      confirmingIds.value.delete(confirmKey)
    }
  }

  // ==================== 选中（导出 / 批量打印） ====================
  /**
   * 行选中键：record_type + id 复合。订单（Order）与备货（StockIn）来自不同表，
   * id 可能撞号（后端 handleConfirm 注释同源提示），纯 id 作键会让勾选串扰到
   * 另一类记录 → 导出/打印多带未勾选的行。
   */
  function rowKey(item: Pick<BeileOrderRow, 'id' | 'record_type'>): string {
    return `${item.record_type ?? 'order'}:${item.id}`
  }

  /** 选中的行键集合（rowKey 复合键） */
  const selectedIds = ref<Set<string>>(new Set())
  const selectedCount = computed(() => selectedIds.value.size)

  /** 当前展示列表是否有数据（导出按钮启用条件） */
  const hasDisplayOrders = computed(() => displayOrders.value.length > 0)

  /** 当前页是否全选 */
  const isAllSelected = computed(() =>
    displayOrders.value.length > 0 && displayOrders.value.every((o) => selectedIds.value.has(rowKey(o))),
  )

  /** 切换单行选中（直接 mutate reactive Set，避免 O(n) 拷贝） */
  function toggleSelect(item: Pick<BeileOrderRow, 'id' | 'record_type'>) {
    const key = rowKey(item)
    if (selectedIds.value.has(key)) selectedIds.value.delete(key)
    else selectedIds.value.add(key)
  }

  /** 全选 / 取消全选当前页 */
  function toggleSelectAll(checked: boolean) {
    if (checked) {
      displayOrders.value.forEach((o) => selectedIds.value.add(rowKey(o)))
    } else {
      displayOrders.value.forEach((o) => selectedIds.value.delete(rowKey(o)))
    }
  }

  // ==================== 导出 / 打印 ====================
  const authStore = useAuthStore()
  const { exporting, runExport } = useExport()

  /** 权限：确认 / 导出 / 打印（超级管理员自动放行） */
  const canConfirm = computed(() => authStore.hasPermission('beile_order_confirm'))
  const canExport = computed(() => authStore.hasPermission('beile_order_export'))
  const canPrint = computed(() => authStore.hasPermission('beile_order_print'))

  /** 汇总表列头（含产品明细）：产品名称后依次「订单数量」「生产数量」「小义开单」（页面 = 导出 XLS = 打印预览同源，AC-12）。
   *  「产品条码」列已删除（2026-10-15 用户裁决）：页面/导出/打印三处同步去掉，宽度并入产品名称。
   *  「备品数量」独立列已删除（用户裁决 2026-09-18）：spare_quantity 仅作为生产数量的计算输入，不再单独展示 */
  const SUMMARY_HEADERS = [
    '订单类型', '订单号', '下单时间', '客户名称', '工厂', '产品名称', '订单数量', '生产数量', '小义开单', '备注',
  ]

  /** 汇总表各列宽度（px），用于导出 XLS 列宽分配（列数与 SUMMARY_HEADERS 一致） */
  const SUMMARY_COL_WIDTHS = [90, 160, 120, 130, 80, 350, 90, 90, 90, 180]

  // 汇总表 tbody 的构建（含逐 SKU 粒度）已提到模块作用域：`buildSummaryTbody(items, keyword)`，
  // 以便被导出/打印复用，并可被单测直接导入验证（页面 = 导出 = 打印 单一真源，AC-12）。

  /**
   * 导出范围为「已勾选」的行（BUG 修复：原实现恒导出当前页全部，与用户勾选不一致）：
   * - 有勾选 → 仅导出勾选的订单/备货（导出文件内容 == 勾选集合）；
   * - 无勾选 → 导出当前页全部（未表达勾选意图时的兜底，保持既有能力——
   *   仅导出权限无打印权限的用户看不到复选框，不能被强制要求勾选）。
   * 返回 (targets, selectedCount)：selectedCount>0 时标题附条数便于核对。
   */
  function exportTargets(): { targets: BeileOrderRow[]; selectedCount: number } {
    if (selectedCount.value > 0) {
      const targets = displayOrders.value.filter((o) => selectedIds.value.has(rowKey(o)))
      return { targets, selectedCount: targets.length }
    }
    return { targets: displayOrders.value, selectedCount: 0 }
  }

  /** 导出为 XLS：有勾选仅导勾选行，无勾选导出当前页 */
  function handleExport() {
    const { targets, selectedCount: picked } = exportTargets()
    if (targets.length === 0) {
      // 勾选已全部失效（如确认流程移除了勾选行）或列表被并发清空——不产生空文件
      toast.warning(picked > 0 ? '勾选的订单已不在当前列表，请重新勾选' : '当前页暂无数据可导出')
      return
    }
    runExport(() => {
      const thead = `<tr>${SUMMARY_HEADERS.map((h, i) => `<th style="width:${SUMMARY_COL_WIDTHS[i]}px">${h}</th>`).join('')}</tr>`
      const tbody = buildSummaryTbody(targets, appliedProduct.value)
      const statusLabel = confirmStatus.value === 'unconfirmed' ? '未确认' : '已确认'
      const title = `湖北订单汇总（${statusLabel}${picked > 0 ? `·已选 ${picked} 条` : ''}）`
      const html = `<div style="text-align:center;margin-bottom:20px;"><h2>${title}</h2></div><table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`
      // F1a-08（2026-10-24 审计）：toISOString 恒为 UTC——北京 08:00 前导出
      // 文件名差一天；本地日期拼接与 useOrderForm.ts:88 的既有修法一致。
      const now = new Date()
      const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      downloadXls(html, `湖北订单_${statusLabel}_${date}.xls`)
    })
  }

  /** 批量打印选中订单汇总表 */
  function handlePrint() {
    const targets = displayOrders.value.filter((o) => selectedIds.value.has(rowKey(o)))
    if (targets.length === 0) {
      toast.warning('请先勾选要打印的订单')
      return
    }
    const thead = `<tr>${SUMMARY_HEADERS.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>`
    const tbody = buildSummaryTbody(targets, appliedProduct.value)
    const printStyle = `
      body { font-family: SimSun, 宋体; padding: 20px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border: 1px solid #333; padding: 8px; font-size: 13px; text-align: center; }
      th { background: #e6e6e6; }
    `
    printHtml(`湖北订单汇总（${targets.length} 条）`, `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`, printStyle)
    toast.success(`已发送 ${targets.length} 条订单至打印预览`)
  }

  // ==================== watchers ====================
  // 已确认的客户筛选变化时回到首页
  watch(() => appliedCustomer.value, () => {
    page.value = 1
  })

  // 产品筛选（含键入自动应用 / 下拉选择）变化时回到首页：
  // 原实现仅客户筛选回首页，翻到后页再筛选会停在空页（显示「未匹配」）
  watch(appliedProduct, () => {
    page.value = 1
  })

  /**
   * 自由键入自动应用（BUG-1 修复）：
   * /beile-order 页搜索框无查询按钮（HubeiView :show-actions="false"），
   * appliedProduct 仅在「点击下拉建议项」时更新；用户直接键入关键字
   * （如「变形金刚」）后未点建议 → 列表完全不过滤 → 出现大量不相关结果。
   * 停顿 600ms 自动把输入文本确认为筛选值（服务端 product 过滤 + 客户端
   * displayOrders 二次过滤同键生效）；清空输入由 HubeiSearchBar 的 reset
   * 事件走 handleReset，此处兜底同步复位 appliedProduct。
   * 600ms > 下拉搜索防抖 500ms，快速连续键入不会逐键触发查询抖动。
   */
  let applyKwTimer: ReturnType<typeof setTimeout> | null = null
  watch(() => filters.productKw, (val) => {
    if (applyKwTimer) {
      clearTimeout(applyKwTimer)
      applyKwTimer = null
    }
    const v = val.trim()
    if (!v) {
      if (appliedProduct.value) appliedProduct.value = ''
      return
    }
    if (v === appliedProduct.value.trim()) return
    applyKwTimer = setTimeout(() => {
      applyKwTimer = null
      appliedProduct.value = v
    }, 600)
  })

  onUnmounted(() => {
    if (applyKwTimer) clearTimeout(applyKwTimer)
  })

  // 每页条数变化时回到第一页
  watch(perPage, () => {
    page.value = 1
  })

  // 翻页 / 筛选变化时清空选中（滚动归位由 BeileOrderTab 处理）
  watch([page, appliedProduct, appliedCustomer, confirmStatus], () => {
    selectedIds.value = new Set()
  })

  return {
    PAGE_SIZE_OPTIONS,
    perPage,
    filters,
    appliedProduct,
    appliedCustomer,
    confirmStatus,
    page,
    currentPage,
    totalItems,
    totalPages,
    isLoading,
    isFetching,
    isError,
    refetch,
    orders,
    unconfirmedCount,
    displayOrders,
    highlightId,
    applyProductFilter,
    applyCustomerFilter,
    handleSearch,
    handleReset,
    goPage,
    setConfirmStatus,
    confirmingIds,
    handleConfirm,
    // 选中
    rowKey,
    selectedIds,
    selectedCount,
    hasDisplayOrders,
    isAllSelected,
    toggleSelect,
    toggleSelectAll,
    // 确认 / 导出 / 打印
    canConfirm,
    canExport,
    canPrint,
    exporting,
    handleExport,
    handlePrint,
  }
}

// ==================== provide/inject：HubeiView 与 BeileOrderTab 共享同一状态实例 ====================
export type BeileOrdersHandle = ReturnType<typeof useBeileOrders>
export const BEILE_ORDERS_KEY: InjectionKey<BeileOrdersHandle> = Symbol('beile-orders')

/** 在父组件（HubeiView）调用：创建状态实例并 provide 给子组件 */
export function provideBeileOrders(): BeileOrdersHandle {
  const bo = useBeileOrders()
  provide(BEILE_ORDERS_KEY, bo)
  return bo
}

/** 在子组件（BeileOrderTab）调用：注入父组件 provide 的状态实例 */
export function injectBeileOrders(): BeileOrdersHandle {
  const bo = inject(BEILE_ORDERS_KEY)
  if (!bo) throw new Error('injectBeileOrders 必须在调用了 provideBeileOrders 的组件树内使用')
  return bo
}
