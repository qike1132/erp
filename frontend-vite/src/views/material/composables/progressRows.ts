/**
 * progressRows.ts — 来料进度表格的行/组整形（纯函数，无 Vue 依赖）
 *
 * 2026-11-08 二次改版：owner 指出「这页面只是登记到货时间以及到货数量」，
 * 依据只有 material_registration.registration_date + 明细 received_quantity，
 * 系统里**没有约定交期**。因此：
 *  · 不再出现「逾期 / 延期」——那是需要 promise date 才能成立的判断，属虚构；
 *  · 时间维度改为如实呈现「到货日期 + 已等 N 天」，N≥30 且未收齐标为「久未收齐」，
 *    阈值沿用后端 stats/distribution 的 30 天口径（同一 SQL 事实，只换措辞）；
 *  · 行 = 一条登记里的一行物料（登记 × 供应商 × 物料），表格扁平铺开；
 *  · 供应商/订单只是**分组维度**（视图模式），不是卡片层级。
 */
import type { ProgressOrderRow, SupplierGroupRow } from './useMaterialRegistrations'

/** 「久未收齐」阈值：与后端 stats/distribution 的 30 天口径一致 */
export const SLOW_DAYS = 30

export type RowStatus = 'todo' | 'partial' | 'done'
export type GroupMode = 'supplier' | 'order' | 'none'

/** 表格的一行：一条登记中的一行物料 */
export interface ProgressRow {
  key: string
  orderNo: string
  poCreateTime: string
  customerName: string
  productName: string
  supplierName: string
  materialName: string
  specification: string
  unit: string
  ordered: number
  received: number
  remaining: number
  /** 0-100 整数 */
  progress: number
  /** 该批到货登记日期 YYYY-MM-DD（后端序列化口径） */
  arrivedDate: string
  /** 距今天数（当天 = 0）；日期缺失为 null */
  ageDays: number | null
  /** 已等 ≥ SLOW_DAYS 天且仍未收齐 */
  isSlow: boolean
}

export interface ProgressGroup {
  key: string
  /** 分组标题（供应商名 / 订单号 / 空 = 不分组） */
  label: string
  /** 标题副文本（供应商组=覆盖单数，订单组=客户） */
  sublabel: string
  rows: ProgressRow[]
  /** 已收齐的物料项数 */
  doneCount: number
  /** 久未收齐的物料项数 */
  slowCount: number
  /** 最近一次到货日期（YYYY-MM-DD） */
  latestDate: string
  /** 组内最大已等天数 */
  oldestAgeDays: number | null
  /** 组内单位一致时给出采购/已到合计，否则 null（跨单位求和无意义） */
  unit: string | null
  orderedTotal: number | null
  receivedTotal: number | null
  /** 组进度：仅在单位一致时给出（数量加权），否则 null → 界面只报项数 */
  progressPct: number | null
}

export interface ProgressSummary {
  total: number
  todo: number
  partial: number
  done: number
  slow: number
}

/** 解析 YYYY-MM-DD 为 UTC 零点时间戳；非法返回 null（日期越界不交给 Date.UTC 自动进位） */
function parseUtcDay(s: string | undefined | null): number | null {
  if (!s) return null
  const [y, m, d] = s.split('-').map(Number)
  if (!y || !m || !d || m < 1 || m > 12 || d < 1 || d > 31) return null
  return Date.UTC(y, m - 1, d)
}

/** 距今自然日数：当天 0，未来为负；日期非法或缺失返回 null */
export function ageInDays(date: string | null | undefined, now: Date): number | null {
  const t = parseUtcDay(date)
  if (t == null) return null
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  return Math.round((today - t) / 86_400_000)
}

/** 多 SKU 订单的产品名并列表述（详情放 title，不在此拼接长串） */
export function productLabel(order: ProgressOrderRow): string {
  if (order.skuItems && order.skuItems.length > 1) {
    const names = order.skuItems.map((s) => s.product_name).filter(Boolean)
    if (names.length > 2) return `${names.slice(0, 2).join(' · ')} 等 ${names.length} 个`
    if (names.length) return names.join(' · ')
  }
  return order.productName || '—'
}

/** 行状态：只表达数量事实（未到 / 部分 / 已到齐），时间风险另由 isSlow 表达 */
export function rowStatus(r: ProgressRow): RowStatus {
  if (r.ordered > 0 && r.received >= r.ordered) return 'done'
  return r.received > 0 ? 'partial' : 'todo'
}

function toRow(
  order: ProgressOrderRow,
  group: SupplierGroupRow,
  materialName: string,
  item: SupplierGroupRow['items'][number],
  key: string,
  now: Date,
): ProgressRow {
  const ordered = item.ordered_quantity
  const received = item.received_quantity
  const ageDays = ageInDays(group.registrationDate, now)
  return {
    key,
    orderNo: order.orderNo,
    poCreateTime: order.poCreateTime,
    customerName: order.customerName || '—',
    productName: productLabel(order),
    supplierName: group.supplierName,
    materialName,
    specification: item.specification || '',
    unit: item.unit || '',
    ordered,
    received,
    remaining: Math.max(ordered - received, 0),
    progress: ordered > 0 ? Math.round((received / ordered) * 100) : 0,
    arrivedDate: group.registrationDate || '',
    ageDays,
    isSlow: ageDays != null && ageDays >= SLOW_DAYS && received < ordered,
  }
}

/**
 * 摊平为表格行：一行 = 订单 × 供应商 × 到货批次 × 物料。
 * 同一供应商的多批登记**不合并**——到货日期不同，合并会抹掉「哪一批还没收齐」。
 */
export function flattenProgressRows(orders: ProgressOrderRow[], now: Date): ProgressRow[] {
  const out: ProgressRow[] = []
  for (const order of orders) {
    order.groups.forEach((group, gi) => {
      group.items.forEach((item, ii) => {
        out.push(toRow(order, group, item.material_name, item, `${order.orderNo}|${gi}|${ii}`, now))
      })
    })
  }
  return out
}

/** 表格统计（用于筛选条计数与空态文案） */
export function summarizeProgressRows(rows: ProgressRow[]): ProgressSummary {
  let todo = 0
  let partial = 0
  let done = 0
  let slow = 0
  for (const r of rows) {
    const s = rowStatus(r)
    if (s === 'todo') todo += 1
    else if (s === 'partial') partial += 1
    else done += 1
    if (r.isSlow) slow += 1
  }
  return { total: rows.length, todo, partial, done, slow }
}

function compareRows(a: ProgressRow, b: ProgressRow): number {
  // 等得久的在前；同日按订单号、物料名，保证稳定
  const ageA = a.ageDays ?? -1
  const ageB = b.ageDays ?? -1
  if (ageA !== ageB) return ageB - ageA
  if (a.orderNo !== b.orderNo) return a.orderNo < b.orderNo ? -1 : 1
  return a.materialName.localeCompare(b.materialName, 'zh-Hans-CN')
}

/** 汇总组头统计（跨单位时 progressPct/合计给 null，只报项数） */
function buildGroup(key: string, label: string, sublabel: string, rows: ProgressRow[]): ProgressGroup {
  const sorted = [...rows].sort(compareRows)
  const units = new Set(sorted.map((r) => r.unit).filter(Boolean))
  const unit = units.size === 1 ? [...units][0]! : null
  const orderedTotal = unit ? sorted.reduce((s, r) => s + r.ordered, 0) : null
  const receivedTotal = unit ? sorted.reduce((s, r) => s + r.received, 0) : null
  const latestDate = sorted.reduce((acc, r) => (r.arrivedDate > acc ? r.arrivedDate : acc), '')
  const ages = sorted.map((r) => r.ageDays).filter((n): n is number => n != null)
  return {
    key,
    label,
    sublabel,
    rows: sorted,
    doneCount: sorted.filter((r) => rowStatus(r) === 'done').length,
    slowCount: sorted.filter((r) => r.isSlow).length,
    latestDate,
    oldestAgeDays: ages.length ? Math.max(...ages) : null,
    unit,
    orderedTotal,
    receivedTotal,
    progressPct: unit && orderedTotal && receivedTotal != null ? Math.round((receivedTotal / orderedTotal) * 100) : null,
  }
}

/**
 * 分组：供应商 / 订单 / 不分组。
 * 组顺序按「组内最久已等天数」倒序——最该处理的排在最前，而不是按字母。
 */
export function groupProgressRows(rows: ProgressRow[], mode: GroupMode): ProgressGroup[] {
  if (mode === 'none') {
    return rows.length ? [buildGroup('all', '', '', rows)] : []
  }
  const buckets = new Map<string, ProgressRow[]>()
  for (const r of rows) {
    const key = mode === 'supplier' ? r.supplierName : r.orderNo
    const list = buckets.get(key)
    if (list) list.push(r)
    else buckets.set(key, [r])
  }
  const groups: ProgressGroup[] = []
  for (const [key, list] of buckets) {
    if (mode === 'supplier') {
      const orders = new Set(list.map((r) => r.orderNo)).size
      groups.push(buildGroup(key, key, `${orders} 单 · ${list.length} 项`, list))
    } else {
      groups.push(buildGroup(key, key, list[0]?.customerName || '', list))
    }
  }
  return groups.sort((a, b) => {
    const ag = a.oldestAgeDays ?? -1
    const bg = b.oldestAgeDays ?? -1
    if (ag !== bg) return bg - ag
    return a.label.localeCompare(b.label, 'zh-Hans-CN')
  })
}
