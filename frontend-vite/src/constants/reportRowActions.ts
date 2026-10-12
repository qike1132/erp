/**
 * /report 行内「编辑/删除」权限码 ↔ TAB 的**单一来源**。
 *
 * 顺序 = 报表页 tab 顺序（views/report/composables/useReportConfig.ts 的 REPORT_TABS）：
 * 订单流水 / 备货流水 / 出货流水 / 备货抵扣流水 / 退货流水。
 *
 * 两个消费方：
 * - views/report/composables/useReportRowActions.ts —— TAB_ROW_PERMISSIONS（行内按钮放行码）
 * - views/user/components/PermissionDetailPanel.vue —— /user「分配权限」弹窗按 TAB 归组显示
 *
 * `resource` 即权限码前缀：`${resource}_edit` / `${resource}_delete`。
 * 后端对应 stock.py /in/edit|delete、order.py、auxiliary.py 的判权与
 * shared_models/user.py 的 NO_MANAGE_INHERIT，改这里要一起改。
 */
export interface RowActionTab {
  /** 权限码前缀 */
  resource: string
  /** 与报表页 tab 完全一致的显示名 */
  label: string
}

export const ROW_ACTION_TABS: readonly RowActionTab[] = [
  { resource: 'order', label: '订单流水' },
  { resource: 'stockin', label: '备货流水' },
  { resource: 'stockout', label: '出货流水' },
  { resource: 'deduction', label: '备货抵扣流水' },
  { resource: 'return', label: '退货流水' },
]
