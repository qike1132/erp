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
