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

/** 排产日历单日卡片（由 PurchasePlanDailyTab 派生，供 PlanDayCard 渲染） */
export interface PlanDayCard {
  date: string;
  label: string;
  match: boolean;
  status: DayCardStatus;
  /** 预览明细，最多 PREVIEW_LIMIT 条 */
  items: { customer: string; product: string; qty: number }[];
  /** 未在 items 中展示的剩余条数 */
  extra: number;
  /** 当日计划总条数（items 可能被截断，故单独记录） */
  planCount: number;
  totalQty: number;
  customerCount: number;
}
