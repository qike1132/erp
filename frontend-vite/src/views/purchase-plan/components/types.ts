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

/** 当日明细里的单个客户分组：客户名 + 当日该客户合计 + 其下全部产品（不截断） */
export interface PlanDayCustomerGroup {
  customer: string;
  /** 该客户当日计划总量 */
  qty: number;
  /** status 取值与后端 getShipmentStatus 一致：completed / partial / pending */
  products: { product: string; qty: number; status: string }[];
}

/** 风险条目：某日延期或临期（≤3 天）且尚未出完 */
export interface RiskItem {
  date: string;
  qty: number;
  cust: string;
  kind: 'overdue' | 'due';
  lbl: string;
}
