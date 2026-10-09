// 备货计划页的「工厂维度」拆分（从 PurchasePlanView 抽出，保持视图文件精简）。
//
// 设计取舍：后端一次性返回整月聚合（含每行的 factories 按厂拆分、每个 SKU 的 factory），
// 前端本地切换工厂，切换零延迟、无需二次请求。见 purchase_plan_queries.py 的
// _aggregate_monthly_rows / _build_monthly_rows_list。
import { computed, type ComputedRef, type Ref } from 'vue';
import type { CustSumItem, Row, SkuDateItem, SkuRow } from '../components/types';

/** 工厂筛选值：'all' 表示全部；其余为具体工厂名（东莞/湖北/未标注） */
export type FactoryFilter = 'all' | string;

export function useFactorySplit(opts: {
  factory: Ref<FactoryFilter>;
  rows: ComputedRef<Row[]>;
  skuSummary: ComputedRef<SkuRow[]>;
  skuDateIndex: ComputedRef<Record<string, SkuDateItem[]>>;
  customers: ComputedRef<CustSumItem[]>;
}) {
  const { factory, rows: rawRows, skuSummary: rawSku, skuDateIndex: rawIdx, customers: rawCust } = opts;
  const isAll = computed(() => factory.value === 'all');

  /** 按工厂过滤后的每日聚合行；该日该厂无计划则整日不出现 */
  const rows = computed<Row[]>(() => {
    if (isAll.value) return rawRows.value;
    const f = factory.value;
    const out: Row[] = [];
    for (const r of rawRows.value) {
      const agg = r.factories?.[f];
      if (!agg) continue;
      out.push({
        ...r,
        totalQty: agg.qty,
        customerCount: agg.custN,
        // 与「全部」视图同口径：planCount / _producedCount / _pendingCount 都数明细行
        planCount: agg.rowN,
        _producedCount: agg.completedN,
        _pendingCount: agg.pendingN,
        _producedPct: agg.pct,
        // customerNames 必须收敛到本厂，否则导出 / 风险清单 / 搜索会带出他厂客户
        customerNames: agg.custNames,
      });
    }
    return out;
  });

  /** 按工厂过滤后的 SKU 汇总 */
  const skuSummary = computed<SkuRow[]>(() =>
    isAll.value ? rawSku.value : rawSku.value.filter(s => s.factory === factory.value),
  );

  /** 按工厂过滤后的 SKU 日期索引（键为「客户|产品」，只保留命中工厂的键） */
  const skuDateIndex = computed<Record<string, SkuDateItem[]>>(() => {
    if (isAll.value) return rawIdx.value;
    const keys = new Set(skuSummary.value.map(s => `${s.customer_name}|${s.product_name}`));
    const out: Record<string, SkuDateItem[]> = {};
    for (const [k, v] of Object.entries(rawIdx.value)) {
      if (keys.has(k)) out[k] = v;
    }
    return out;
  });

  /** 按工厂过滤后的客户汇总（取该客户在该厂的拆分桶） */
  const customers = computed<CustSumItem[]>(() => {
    if (isAll.value) return rawCust.value;
    const f = factory.value;
    const out: CustSumItem[] = [];
    for (const c of rawCust.value) {
      const agg = c.factories?.[f];
      if (!agg) continue;
      out.push({
        customer_id: c.customer_id,
        customer_name: c.customer_name,
        plan_qty: agg.plan_qty,
        inventory_qty: agg.inventory_qty,
        produced_qty: agg.produced_qty,
        remaining_qty: agg.remaining_qty,
        warning_count: agg.warning_count,
        factories: c.factories,
      });
    }
    return out;
  });

  /** 当月实际出现过的工厂名（用于控件计数与「未标注」兜底） */
  const availableFactories = computed<string[]>(() => {
    const set = new Set<string>();
    for (const r of rawRows.value) for (const f of Object.keys(r.factories ?? {})) set.add(f);
    return [...set];
  });

  /** 各工厂当月的计划总量（控件角标） */
  const factoryTotals = computed<Record<string, number>>(() => {
    const m: Record<string, number> = {};
    for (const r of rawRows.value) {
      for (const [f, a] of Object.entries(r.factories ?? {})) m[f] = (m[f] ?? 0) + a.qty;
    }
    return m;
  });

  return { rows, skuSummary, skuDateIndex, customers, availableFactories, factoryTotals };
}
