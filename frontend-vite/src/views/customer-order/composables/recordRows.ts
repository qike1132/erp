import type { OrderRecord } from './types'

/** 摊平后的表格行（一行一个 SKU；多 SKU 订单末尾追加一行合计） */
export interface RecordRow {
  /** 全局唯一行键（订单与备货 id 会撞号，故含来源与 SKU 序号） */
  _rowKey: string
  /** 分组键：同订单恒等（供跨行合并）；合计行另取一值，避免被并进合并格 */
  _g: string
  /**
   * 三个订单级列的**分组字段**（值都等于 `_g`）。
   *
   * 为什么要有三个而不是共用一个：`UiDataTable` 的插槽名是 `column-body-${col.field}`，
   * 而 PrimeVue 又要求「参与分组的列，其 field 必须在 groupRowsBy 里」。若三列共用一个 field，
   * 三个列插槽会同名、无法分别渲染。故给三列各自的 field 名，值相同 —— 分组的比较是按
   * **列自己那个 field** 做的，所以三列各自与 `_g` 比较，得到同一个跨行数。
   * 真正的显示值（日期/单号/客户）仍从行上的 order_date / order_no / customer 取。
   */
  _g_date: string
  _g_no: string
  _g_cust: string
  /** 是否为合计行 */
  _isSum: boolean
  /** 原始订单/备货行，供操作列与详情使用 */
  _source: OrderRecord
  order_date: string
  order_no: string
  customer: string
  record_type: 'order' | 'stockin'
  product_name: string
  quantity: number
}

/** 合计行的行内标签（落在产品名称列） */
export const SUM_ROW_LABEL = '合计'

/**
 * 把「一行一订单」的记录摊平成「一行一 SKU」（多 SKU 订单末尾追加一行合计）。
 *
 * 为什么要摊平：一张订单可含多个 SKU，而列表一行只能有一个数量格。原先把 SKU 名与数量一起
 * 堆在产品名称格里，数量就落在了产品名称列的中间，与「数量」列毫不相干。摊平后每个 SKU 的
 * 数量都落在数量列，订单级字段（时间/编号/客户）由组件做跨行合并。
 *
 * 分组键 `_g` 必须是**按订单唯一**的值，不能拿时间或客户代替：生产数据里
 * PO-20260930-0011/0012/0013 的时间都是 `2026-09-30 00:00`、客户也大量重复，
 * 用它们做分组键会让相邻不同订单的单元格被误并成一个大格。
 * 合计行的 `_g` 另取一值，这样它自己成一组，不会被并进 SKU 行的合并格里。
 */
export function flattenRecordRows(records: OrderRecord[]): RecordRow[] {
  const rows: RecordRow[] = []
  /** 三个订单级列的分组字段取同一个值，靠列名区分（见 RecordRow 的说明） */
  const groupFields = (key: string) => ({ _g_date: key, _g_no: key, _g_cust: key })

  for (const rec of records) {
    // 订单与备货来自不同表，id 各自从 1 开始会撞号，故分组键含来源
    const group = `${rec.record_type}#${rec.id}`
    const base = {
      _source: rec,
      order_date: rec.order_date ?? '',
      order_no: rec.order_no ?? '',
      customer: rec.customer ?? '',
      record_type: rec.record_type,
    }
    const items = rec.items ?? []

    if (items.length === 0) {
      // 无 SKU 明细的订单/备货：按记录自身回退为 1 行，不让整单从列表里消失
      rows.push({
        ...base,
        ...groupFields(group),
        _rowKey: `${group}#0`,
        _g: group,
        _isSum: false,
        product_name: rec.product?.name || '-',
        quantity: rec.quantity ?? 0,
      })
      continue
    }

    items.forEach((item, idx) => {
      rows.push({
        ...base,
        ...groupFields(group),
        _rowKey: `${group}#${idx}`,
        _g: group,
        _isSum: false,
        product_name: item.product_name || '-',
        quantity: item.quantity ?? 0,
      })
    })

    // 只在多 SKU 时补合计行：单 SKU 订单那一行本身就是总量
    if (items.length > 1) {
      rows.push({
        ...base,
        // 合计行与 SKU 行**共用分组键**：这样「时间/编号/客户」的合并格会一直盖到合计行，
        // 视觉上合计属于这一单（合计行不再重复渲染那三格的显示值，插槽按 _isSum 跳过）。
        ...groupFields(group),
        // 行键仍要唯一，故单独加后缀
        _rowKey: `${group}#sum`,
        _g: group,
        _isSum: true,
        product_name: SUM_ROW_LABEL,
        quantity: rec.quantity ?? 0,
      })
    }
  }

  return rows
}
