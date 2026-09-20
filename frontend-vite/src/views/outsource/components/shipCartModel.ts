/**
 * shipCartModel.ts — 批量发货弹窗的纯函数领域模型
 *
 * 聚合（待发货面板 → 挑选项/清单行）、数量拆分（合并数量 → 按订单分摊）、
 * 校验口径都集中在此；组件层（父弹窗 / 左右栏子组件）只做状态与渲染。
 * 所有函数不依赖 Vue 响应式 API，可脱离组件单测。
 */
import type { Shipment, ShippableProcessItem } from '@/api/outsource'

/** 提交结果（判别联合：ok=true 必有 shipments，ok=false 必有 error，模板内可窄化） */
export type ShipResult = { ok: true; shipments: Shipment[] } | { ok: false; error: string }

/** 左栏挑选项：按产品名聚合（跨订单、跨客户合并，PO 号不作为展示信息） */
export interface PickGroup {
  key: string
  productName: string
  /** 该产品覆盖的订单（勾选时整组加入清单） */
  orderIds: number[]
  /** 覆盖的订单数，用于提示该产品跨多张订单 */
  orderCount: number
}

export interface OrderOption {
  order_id: number
  order_no: string
  customer: string
}

/** 合并工序的填写状态：同一 SKU 的同一工序跨订单共享一个数量框 */
export interface MergedInput {
  /** 跨订单合计发货数量（提交时按订单顺序拆分到各订单） */
  qty: number
  /** 是否参与本次发货（取消勾选=不发该工序） */
  on: boolean
}

/** 合并后的工序行：同一 SKU 的同一工序跨订单合并为一行 */
export interface CartProcessRow {
  /** 合并键：产品名 + 工序名 */
  key: string
  processType: string
  /** 该工序在各订单下的原始行（提交时按订单顺序拆分数量） */
  entries: ShippableProcessItem[]
  /** 跨订单订单总量合计（订单要求的全部数量） */
  targetQty: number
  /** 跨订单剩余未发合计，即该行数量上限 */
  remaining: number
  /** 填写状态（跨重算保持同一响应式对象） */
  input: MergedInput
}

/** 清单中的产品：同一产品名跨订单（含跨客户）合并为一张卡 */
export interface CartProduct {
  /** 产品名（合并键） */
  key: string
  productName: string
  /** 该产品覆盖的订单 */
  orderIds: number[]
  /** 按工序合并后的行 */
  processes: CartProcessRow[]
}

/** 合并键：产品名 + 工序名 */
export function mergeKey(productName: string, processType: string): string {
  return `${productName}||${processType}`
}

/** 行的产品名（接口允许为空，展示与聚合统一回退占位名） */
export function productNameOf(row: ShippableProcessItem): string {
  return row.product_name || '未命名产品'
}

/** 该产品在各订单下的工序行 */
export function productRows(rows: ShippableProcessItem[], productName: string): ShippableProcessItem[] {
  return rows.filter((r) => productNameOf(r) === productName)
}

/** 订单基础信息（提交按订单生成发货单），按首次出现顺序去重 */
export function buildOrderOptions(list: ShippableProcessItem[]): OrderOption[] {
  const orderMap = new Map<number, OrderOption>()
  for (const r of list) {
    if (!orderMap.has(r.order_id)) {
      orderMap.set(r.order_id, { order_id: r.order_id, order_no: r.order_no, customer: r.customer })
    }
  }
  return [...orderMap.values()]
}

/** 左栏挑选项：两级聚合（订单+产品去重 → 产品名跨订单合并），按产品名排序 */
export function buildPickGroups(list: ShippableProcessItem[]): PickGroup[] {
  // 1) 订单+产品：同一 SKU 的多道工序会返回多行，先按「订单+产品」去重，保证订单 ID 不重复；
  // 2) 产品名：跨订单、跨客户合并（实测 16 组产品分布在 2-8 张订单），合并为一个挑选项。
  const perOrderProduct = new Map<string, { productName: string; orderId: number }>()
  for (const r of list) {
    const name = productNameOf(r)
    const opKey = `${r.order_id}||${name}`
    if (!perOrderProduct.has(opKey)) {
      perOrderProduct.set(opKey, { productName: name, orderId: r.order_id })
    }
  }
  const pickMap = new Map<string, PickGroup>()
  for (const item of perOrderProduct.values()) {
    const g = pickMap.get(item.productName)
    if (g) {
      g.orderIds.push(item.orderId)
    } else {
      pickMap.set(item.productName, {
        key: item.productName, productName: item.productName,
        orderIds: [item.orderId], orderCount: 1,
      })
    }
  }
  return [...pickMap.values()]
    .map((g) => ({ ...g, orderCount: g.orderIds.length }))
    .sort((a, b) => a.productName.localeCompare(b.productName))
}

/**
 * 右栏清单视图模型：同一产品的同一工序跨订单合并为一行。
 *
 * ⚠️ 会向传入的 mergedInputs 写入缺失键的默认值（qty=剩余合计, on=true）——
 * 这是「跨重算保持用户已填数量」的既有行为：Map 由调用方（父组件）持有并传入，
 * 首次构建补默认值，后续重算发现键已存在则原样保留，不会覆盖用户输入。
 */
export function buildCartGroups(
  rows: ShippableProcessItem[],
  cartProducts: string[],
  mergedInputs: Map<string, MergedInput>,
): CartProduct[] {
  const out: CartProduct[] = []
  for (const name of cartProducts) {
    const list = productRows(rows, name)
    if (!list.length) continue
    // 按工序名合并：同一 SKU 的同一工序跨订单合成一行
    const procMap = new Map<string, ShippableProcessItem[]>()
    for (const r of list) {
      const arr = procMap.get(r.process_type)
      if (arr) arr.push(r)
      else procMap.set(r.process_type, [r])
    }
    const processes: CartProcessRow[] = []
    for (const [processType, entries] of procMap) {
      const key = mergeKey(name, processType)
      let input = mergedInputs.get(key)
      if (!input) {
        input = { qty: entries.reduce((s, e) => s + e.remaining, 0), on: true }
        mergedInputs.set(key, input)
      }
      processes.push({
        key, processType, entries,
        targetQty: entries.reduce((s, e) => s + e.target_qty, 0),
        remaining: entries.reduce((s, e) => s + e.remaining, 0),
        input,
      })
    }
    out.push({
      key: name,
      productName: name,
      orderIds: [...new Set(list.map((r) => r.order_id))],
      processes,
    })
  }
  return out
}

/**
 * 把某工序填写的合计数量按订单顺序拆分到各订单。
 * 依次填满每张订单的剩余量，返回实际发货的 { 订单行, 数量 }（数量为 0 的订单不返回）。
 */
export function splitQty(r: CartProcessRow): { row: ShippableProcessItem; quantity: number }[] {
  let left = Number(r.input.qty)
  if (!Number.isFinite(left) || left <= 0) return []
  const out: { row: ShippableProcessItem; quantity: number }[] = []
  for (const row of r.entries) {
    if (left <= 0) break
    const take = Math.min(row.remaining, left)
    if (take > 0) {
      out.push({ row, quantity: take })
      left -= take
    }
  }
  return out
}

/**
 * 单行计入合计的数量：仅已勾选且取值合法时计入，否则记 0。
 * 非法值不参与求和，避免超限输入把合计拉大（合计口径与实际可提交量一致）。
 */
export function rowQty(r: CartProcessRow): number {
  if (!r.input.on || isRowInvalid(r)) return 0
  return Number(r.input.qty) || 0
}

/**
 * 工序行数量是否非法：空 / 非有限 / 非整数 / <1 / 超过跨订单剩余合计。
 * 已取消的工序不参与提交，不计入非法（后端 quantity 为 int，前端同口径校验）。
 */
export function isRowInvalid(r: CartProcessRow): boolean {
  if (!r.input.on) return false
  const n = Number(r.input.qty)
  return !Number.isFinite(n) || !Number.isInteger(n) || n < 1 || n > r.remaining
}
