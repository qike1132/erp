import { computed, type Ref } from 'vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

export type TabType = 'order' | 'stockin' | 'stockout' | 'deduction' | 'return'

export interface TabConfig {
  label: string
  endpoint: string
  dateKey: string
  countKey: string
  dateLabel: string
  countLabel: string
  noteKey: string
  /** 「单号」列的表头（2026-10-13 起五个 tab 统一为「订单号」；列里的值仍是各自的单号） */
  noLabel: string
  /** 「单号」列的取值键（订单 tab 用 order_no；其余 tab 用 record_no） */
  noKey: string
}

export const TAB_CONFIG: Record<TabType, TabConfig> = {
  order: {
    label: '订单流水',
    endpoint: '/reports/order-logs',
    dateKey: 'order_date',
    countKey: 'order_count',
    dateLabel: '下单时间',
    countLabel: '数量',
    noteKey: 'note',
    noLabel: '订单号',
    noKey: 'order_no',
  },
  stockin: {
    label: '备货流水',
    endpoint: '/reports/stockin-logs',
    dateKey: 'stockin_date',
    countKey: 'stockin_count',
    dateLabel: '备货时间',
    countLabel: '备货数量',
    noteKey: 'note',
    noLabel: '订单号',
    noKey: 'record_no',
  },
  stockout: {
    label: '出货流水',
    endpoint: '/reports/stockout-logs',
    dateKey: 'stockout_date',
    countKey: 'stockout_count',
    dateLabel: '出货时间',
    countLabel: '出货数量',
    noteKey: 'note',
    noLabel: '订单号',
    noKey: 'record_no',
  },
  deduction: {
    label: '备货抵扣流水',
    endpoint: '/reports/deduction-logs',
    dateKey: 'deduction_time',
    countKey: 'deduction_count',
    dateLabel: '抵扣时间',
    countLabel: '抵扣数量',
    noteKey: 'order_note',
    // 抵扣行的「单号」= 被抵扣的订单号（用户诉求：看清是哪张订单）
    noLabel: '订单号',
    noKey: 'order_no',
  },
  return: {
    label: '退货流水',
    endpoint: '/reports/return-logs',
    dateKey: 'return_date',
    countKey: 'return_count',
    dateLabel: '退货时间',
    countLabel: '退货数量',
    // 退货的备注列展示「原因；备注」合并串（行内编辑仍按分开的 reason/note 回写）
    noteKey: 'note_display',
    noLabel: '订单号',
    noKey: 'record_no',
  },
}

export const REPORT_TABS: { value: TabType; label: string }[] = [
  { value: 'order', label: '订单流水' },
  { value: 'stockin', label: '备货流水' },
  { value: 'stockout', label: '出货流水' },
  { value: 'deduction', label: '备货抵扣流水' },
  { value: 'return', label: '退货流水' },
]

export type ReportEndpoint = 'orderLogs' | 'stockinLogs' | 'stockoutLogs' | 'deductionLogs' | 'returnLogs'

const ENDPOINT_MAP: Record<TabType, ReportEndpoint> = {
  order: 'orderLogs',
  stockin: 'stockinLogs',
  stockout: 'stockoutLogs',
  deduction: 'deductionLogs',
  return: 'returnLogs',
}

export function useReportConfig(activeTab: Ref<TabType>, canManageRowActions?: Ref<boolean>) {
  const currentCfg = computed(() => TAB_CONFIG[activeTab.value])

  function currentTabEndpoint(): ReportEndpoint {
    return ENDPOINT_MAP[activeTab.value]
  }

  const reportColumns = computed<TableColumn[]>(() => {
    // 2026-10-13 改版：单号列可见、时间到分、末列由「状态」改「备注」。
    // 列宽按比例分配（配合表格 table-layout: fixed 才是硬约束），各分支合计 100%。
    // 2026-10-13 v2：订单流水不再有独立的「展开」空列（▶ 按钮已删），子行树线挪进「时间」列做
    // 前缀 → 首列（时间）与其余四个 tab 一样贴住左边框（参照 /stock 的「客户」列）。
    // 五个 tab 列集相同（订单流水的平铺行/母行-明细共用同一套列），故共用同一套列宽。
    // 权限门控：无对应行内权限的用户整列不渲染（连表头一起），不留空壳「操作」列；缺省 fail-closed。
    const withActions = canManageRowActions?.value ?? false
    const cfg = currentCfg.value

    // 2026-10-31 用户反馈：下单时间/订单号列过宽，导致「产品名称」显示不全。
    // 重分配：前三列各收 1~2pp、条码/数量/备注同步收紧，产品名称 20%→29%（无操作列时 22%→32%）。
    // 2026-10-31 二轮：时间/订单号再各收 2pp（11%/12%），腾出的宽度继续给产品名称。
    const columns: TableColumn[] = [
      { field: 'date', header: cfg.dateLabel, align: 'left', width: withActions ? '11%' : '12%' },
      { field: 'no', header: cfg.noLabel, align: 'left', width: withActions ? '12%' : '13%' },
      { field: 'customer', header: '客户', align: 'left', width: withActions ? '10%' : '11%' },
      { field: 'product_name', header: '产品名称', align: 'left', width: withActions ? '33%' : '36%' },
      { field: 'product_barcode', header: '条码', align: 'left', width: withActions ? '10%' : '11%' },
      { field: 'quantity', header: cfg.countLabel, align: 'center', width: withActions ? '8%' : '9%', sortable: true },
      { field: 'note', header: activeTab.value === 'deduction' ? '订单备注' : '备注', align: 'left', width: withActions ? '7%' : '8%' },
    ]
    if (withActions) columns.push({ field: 'actions', header: '操作', align: 'center', width: '9%' })
    return columns
  })

  return { currentCfg, currentTabEndpoint, reportColumns }
}
