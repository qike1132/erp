import { computed, type Ref } from 'vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

export type TabType = 'order' | 'stockin' | 'stockout' | 'deduction'

export interface TabConfig {
  label: string
  endpoint: string
  dateKey: string
  countKey: string
  dateLabel: string
  countLabel: string
  noteKey: string
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
  },
  stockin: {
    label: '备货流水',
    endpoint: '/reports/stockin-logs',
    dateKey: 'stockin_date',
    countKey: 'stockin_count',
    dateLabel: '备货时间',
    countLabel: '备货数量',
    noteKey: 'note',
  },
  stockout: {
    label: '出货流水',
    endpoint: '/reports/stockout-logs',
    dateKey: 'stockout_date',
    countKey: 'stockout_count',
    dateLabel: '出货时间',
    countLabel: '出货数量',
    noteKey: 'note',
  },
  deduction: {
    label: '备货抵扣流水',
    endpoint: '/reports/deduction-logs',
    dateKey: 'deduction_time',
    countKey: 'deduction_count',
    dateLabel: '抵扣时间',
    countLabel: '抵扣数量',
    noteKey: 'order_note',
  },
}

export const REPORT_TABS: { value: TabType; label: string }[] = [
  { value: 'order', label: '订单流水' },
  { value: 'stockin', label: '备货流水' },
  { value: 'stockout', label: '出货流水' },
  { value: 'deduction', label: '备货抵扣流水' },
]

export type ReportEndpoint = 'orderLogs' | 'stockinLogs' | 'stockoutLogs' | 'deductionLogs'

const ENDPOINT_MAP: Record<TabType, ReportEndpoint> = {
  order: 'orderLogs',
  stockin: 'stockinLogs',
  stockout: 'stockoutLogs',
  deduction: 'deductionLogs',
}

export function useReportConfig(activeTab: Ref<TabType>) {
  const currentCfg = computed(() => TAB_CONFIG[activeTab.value])

  function currentTabEndpoint(): ReportEndpoint {
    return ENDPOINT_MAP[activeTab.value]
  }

  const reportColumns = computed<TableColumn[]>(() => [
    // 列宽按比例分配（配合表格的 table-layout: fixed 才是硬约束）；
    // 不约束时产品名与备注会把余量吃光，日期/数量被挤成窄条
    { field: 'date', header: currentCfg.value.dateLabel, align: 'center', width: '16%' },
    { field: 'customer', header: '客户', align: 'center', width: '14%' },
    { field: 'product_name', header: '产品名称', align: 'left', width: '28%' },
    { field: 'quantity', header: currentCfg.value.countLabel, align: 'center', width: '16%', sortable: true },
    { field: 'note', header: activeTab.value === 'deduction' ? '订单备注' : '备注', align: 'left', width: '26%' },
  ])

  return { currentCfg, currentTabEndpoint, reportColumns }
}