export interface Plan {
  detail_id: number;
  plan_id: number;
  customer_name: string;
  product_name: string;
  barcode: string;
  quantity: number;
  produced_qty: number;
  remaining_qty: number;
  plan_date: string;
  /** 产品所属工厂（东莞/湖北/未标注） */
  factory?: string;
}

/** 某工厂在某日的聚合（后端 rows[].factories 的值） */
export interface FactoryDayAgg {
  /** 该厂当日计划量 */
  qty: number;
  /** 该厂当日已生产量 */
  produced: number;
  /** 该厂当日完成率（0-100） */
  pct: number;
  /** 该厂当日客户数（去重） */
  custN: number;
  /** 该厂当日产品数（去重） */
  prodN: number;
  /** 该厂当日明细行数（与日级 planCount 同口径） */
  rowN: number;
  /** 该厂当日已完成行数（与日级 _producedCount 同口径） */
  completedN: number;
  /** 该厂当日未完成行数（与日级 _pendingCount 同口径） */
  pendingN: number;
  /** 该厂当日客户名列表（供筛选后重算导出/风险清单展示） */
  custNames: string[];
}

/** 客户级按工厂拆分（后端 customers[].factories 的值） */
export interface FactoryCustAgg {
  plan_qty: number;
  inventory_qty: number;
  produced_qty: number;
  remaining_qty: number;
  warning_count: number;
}

export interface Row {
  date: string;
  _dayNum: number;
  _weekday: string;
  customerCount: number;
  planCount: number;
  totalQty: number;
  _isPeak: boolean;
  _producedCount: number;
  _pendingCount: number;
  _producedPct: number;
  customerNames: string[];
  plans?: Plan[];
  _byCustomer?: Record<string, Plan[]>;
  _fullDate: string;
  /** 按工厂拆分的当日聚合，键为工厂名（东莞/湖北/未标注） */
  factories?: Record<string, FactoryDayAgg>;
}

export interface CustSumItem {
  customer_id: number;
  customer_name: string;
  plan_qty: number;
  inventory_qty: number;
  produced_qty: number;
  remaining_qty: number;
  warning_count: number;
  /** 该客户按工厂拆分，键为工厂名 */
  factories?: Record<string, FactoryCustAgg>;
}

export interface SkuRow {
  barcode: string;
  product_name: string;
  plan_qty: number;
  produced_qty: number;
  remain_qty: number;
  customer_name: string;
  /** 产品所属工厂（东莞/湖北/未标注） */
  factory?: string;
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
  /** 产品所属工厂 */
  factory?: string;
}

/** 当日明细里的单个客户分组：客户名 + 当日该客户合计 + 其下全部产品（不截断） */
export interface PlanDayCustomerGroup {
  customer: string;
  /** 该客户当日计划总量 */
  qty: number;
  /** status 取值与后端 getShipmentStatus 一致：completed / partial / pending */
  products: { product: string; qty: number; status: string; factory?: string }[];
}

/** 风险条目：某日延期或临期（≤3 天）且尚未出完 */
export interface RiskItem {
  date: string;
  qty: number;
  cust: string;
  kind: 'overdue' | 'due';
  lbl: string;
}
