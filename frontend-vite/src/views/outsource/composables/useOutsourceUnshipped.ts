/**
 * useOutsourceUnshipped.ts — 未到货（未发完）明细导出/打印
 *
 * 口径（用户裁决）：未到数量 = 订单数量 - 已发数量，跨全部湖北订单聚合。
 * 数据源：GET /outsource/unshipped（后端聚合），前端负责 XLS 导出与打印预览。
 */
import { ref } from 'vue'
import { outsourceApi, type UnshippedProcessItem } from '@/api/outsource'
import { useExport } from '@/composables/useExport'
import { downloadXls } from '@/utils/xls'
import { escapeHtml, printHtml } from '@/utils/print'
import { toast } from '@/composables/useToast'

/** 未到货明细表头（导出 XLS = 打印预览同源；按用户确认样式，不含「订单号」列） */
export const UNSHIPPED_HEADERS = [
  '客户', '下单时间', '产品名称', '产品条码', '工序', '订单数量', '已发数量', '未到数量',
]

/** 未到货明细各列宽度（px），用于导出 XLS 列宽分配（列数与 UNSHIPPED_HEADERS 一致） */
export const UNSHIPPED_COL_WIDTHS = [130, 130, 220, 130, 90, 90, 90, 90]

/**
 * Excel 文本格式样式：13 位产品条码等长数字串默认会被 Excel 按数字解析，
 * 显示成科学计数法（6.97895E+12）且丢失精度；强制文本格式保证完整显示。
 * 浏览器（打印预览）会忽略该 CSS，无副作用。
 */
const EXCEL_TEXT_STYLE = ` style="mso-number-format:'\\@'"`

/**
 * 未到货明细分组键：同一订单 + 同一 SKU 的多道工序合并前 4 列
 * （客户/下单时间/产品名称/产品条码）。用 order_id 而非纯文本键，
 * 避免不同订单恰好同客户同日期同产品时被误合并。
 */
function unshippedGroupKey(it: UnshippedProcessItem): string {
  return `${it.order_id}::${it.product_barcode ?? ''}::${it.product_name ?? ''}`
}

/**
 * 构建未到货明细 tbody HTML（导出/打印共用单一真源，便于单测直接导入）。
 *
 * 列序与用户确认的样式一致（不含「订单号」）：
 * 客户 / 下单时间 / 产品名称 / 产品条码 / 工序 / 订单数量 / 已发数量 / 未到数量。
 * 同一订单同一 SKU 的多道工序，前 4 列 rowspan 合并到首行；工序与数量列逐工序各占一行。
 */
export function buildUnshippedTbody(items: UnshippedProcessItem[]): string {
  // 后端已按 order_date/order_id/order_item_id/sort_order 排序，同组工序连续出现
  const groups: UnshippedProcessItem[][] = []
  let curKey: string | null = null
  for (const it of items) {
    const key = unshippedGroupKey(it)
    if (key !== curKey) {
      groups.push([])
      curKey = key
    }
    groups[groups.length - 1]!.push(it)
  }

  let html = ''
  for (const group of groups) {
    const first = group[0]!
    const spanAttr = group.length > 1 ? ` rowspan="${group.length}"` : ''
    group.forEach((it, idx) => {
      const cells: string[] = []
      if (idx === 0) {
        cells.push(`<td${spanAttr}>${escapeHtml(first.customer || '-')}</td>`)
        cells.push(`<td${spanAttr}>${escapeHtml(first.order_date || '-')}</td>`)
        cells.push(`<td${spanAttr}>${escapeHtml(first.product_name || '-')}</td>`)
        cells.push(`<td${spanAttr}${EXCEL_TEXT_STYLE}>${escapeHtml(first.product_barcode || '-')}</td>`)
      }
      cells.push(`<td>${escapeHtml(it.process_type)}</td>`)
      cells.push(`<td>${escapeHtml(String(it.target_qty))}</td>`)
      cells.push(`<td>${escapeHtml(String(it.shipped_qty))}</td>`)
      cells.push(`<td>${escapeHtml(String(it.remaining))}</td>`)
      html += `<tr>${cells.join('')}</tr>`
    })
  }
  return html
}

/** 未到货明细导出/打印业务逻辑（/outsource 页头按钮） */
export function useOutsourceUnshipped() {
  const { exporting, runExport } = useExport()
  /** 明细加载中（导出/打印共用），防止双击重复请求 */
  const loading = ref(false)

  /** 拉取未到货明细；失败返回 null（已 toast） */
  async function fetchUnshipped(): Promise<UnshippedProcessItem[] | null> {
    loading.value = true
    try {
      return await outsourceApi.unshipped()
    } catch {
      toast.error('加载未到货明细失败')
      return null
    } finally {
      loading.value = false
    }
  }

  /** 空明细统一拦截：无数据时不进入导出/打印流程（避免「无数据」与「成功」双提示） */
  function isEmpty(items: UnshippedProcessItem[]): boolean {
    if (items.length === 0) {
      toast.warning('当前没有未到货（未发完）的工序')
      return true
    }
    return false
  }

  /** 一键导出未到货明细为 XLS */
  async function handleExport() {
    const items = await fetchUnshipped()
    if (items === null || isEmpty(items)) return
    runExport(() => {
      const thead = `<tr>${UNSHIPPED_HEADERS.map((h, i) => `<th style="width:${UNSHIPPED_COL_WIDTHS[i]}px">${h}</th>`).join('')}</tr>`
      const tbody = buildUnshippedTbody(items)
      const date = new Date().toISOString().slice(0, 10)
      const html = `<div style="text-align:center;margin-bottom:20px;"><h2>湖北未到货明细（${items.length} 条）</h2></div><table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`
      downloadXls(html, `湖北未到货明细_${date}.xls`)
    })
  }

  /** 一键打印未到货明细（样式与导出 XLS / 用户确认样式一致：居中 + 合并单元格垂直居中） */
  async function handlePrint() {
    const items = await fetchUnshipped()
    if (items === null || isEmpty(items)) return
    const thead = `<tr>${UNSHIPPED_HEADERS.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>`
    const tbody = buildUnshippedTbody(items)
    const printStyle = `
      body { font-family: SimSun, 宋体; padding: 20px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border: 1px solid #333; padding: 8px; font-size: 13px; text-align: center; vertical-align: middle; }
      th { background: #e6e6e6; }
    `
    printHtml(`湖北未到货明细（${items.length} 条）`, `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`, printStyle)
    toast.success(`已发送 ${items.length} 条未到货明细至打印预览`)
  }

  return { exporting, loading, handleExport, handlePrint }
}
