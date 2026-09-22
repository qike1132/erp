export interface Plan {
  detail_id: number;
  plan_id: number;
  customer_name: string;
  product_name: string;
  barcode: string;
  quantity: number;
  shipped_qty: number;
  remaining_qty: number;
  plan_date: string;
  shipment_status: string;
}

export interface Row {
  date: string;
  _dayNum: number;
  _weekday: string;
  customerCount: number;
  planCount: number;
  totalQty: number;
  _isPeak: boolean;
  _shippedCount: number;
  _pendingCount: number;
  _shippedPct: number;
  customerNames: string[];
  plans?: Plan[];
  _byCustomer?: Record<string, Plan[]>;
  _fullDate: string;
}

export interface CustSumItem {
  customer_id: number;
  customer_name: string;
  plan_qty: number;
  inventory_qty: number;
  shipped_qty: number;
  remaining_qty: number;
  warning_count: number;
}

export interface SkuRow {
  barcode: string;
  product_name: string;
  plan_qty: number;
  shipped_qty: number;
  remain_qty: number;
  customer_name: string;
  _pct: number;
  _odd: boolean;
}

export interface SkuDateItem {
  date: string;
  day: number;
  weekday: string;
  qty: number;
  customer: string;
  status: string;
}

/** 日历卡片的日期状态标记（样式类 + 展示文案），无状态时为 null */
export type DayCardStatus = { cls: string; lbl: string } | null;

/** 日历卡片内的单个客户分组：客户名 + 当日该客户合计 + 其下产品明细 */
export interface PlanDayCustomerGroup {
  customer: string;
  /** 该客户当日计划总量 */
  qty: number;
  products: { product: string; qty: number }[];
}

/** 排产日历单日卡片（由 PurchasePlanDailyTab 派生，供 PlanDayCard 渲染） */
export interface PlanDayCard {
  date: string;
  label: string;
  match: boolean;
  status: DayCardStatus;
  /** 按客户分组后的展示数据，已按产品行数预算裁剪 */
  groups: PlanDayCustomerGroup[];
  /** 未在 groups 中展示的计划条数 */
  extra: number;
  /** 因整组截断而未展示的客户数（用于让汇总文案与实际可见内容一致） */
  extraCustomers: number;
  /** 当日计划总条数（groups 可能被截断，故单独记录） */
  planCount: number;
  totalQty: number;
  customerCount: number;
}
