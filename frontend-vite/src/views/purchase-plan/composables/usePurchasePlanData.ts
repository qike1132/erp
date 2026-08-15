// 每日计划与月度客户汇总的数据查询与解析逻辑（从 PurchasePlanView.vue 抽出，行为不变）
import { computed, type Ref } from 'vue';
import { useQuery, keepPreviousData } from '@tanstack/vue-query';
import { planApi } from '@/api';
import type { Plan, Row, SkuRow } from '../components/types';

// 星期缩写（下标与 Date.getDay() 对齐，周日=日）
export const WDS = ['日', '一', '二', '三', '四', '五', '六'];

// 判断单条计划的出货状态：完成 / 部分 / 未出
export function getShipmentStatus(quantity: number, shippedQty: number): string {
  if (shippedQty >= quantity) return 'completed';
  if (shippedQty > 0) return 'partial';
  return 'pending';
}

export function usePurchasePlanData(y: Ref<number>, m: Ref<number>, viewTab: Ref<'daily' | 'summary'>) {
  const { data: d, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['pp-monthly', () => y.value, () => m.value],
    queryFn: async () => {
      const res = await planApi.monthly({ year: y.value, month: m.value });
      // 冻结返回数据，阻止 Vue 对 20K+ 明细做深层响应式转换，降低内存和 CPU 开销
      return res ? Object.freeze(JSON.parse(JSON.stringify(res))) : res;
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
    retryDelay: 2000,
    placeholderData: keepPreviousData,
  });

  const { data: sData, isLoading: sLoading, isFetching: sFetching, isError: sError, refetch: refetchSummary } = useQuery({
    queryKey: ['pp-summary', () => y.value, () => m.value],
    queryFn: async () => await planApi.customerSummary({ year: y.value, month: m.value }),
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
    retryDelay: 2000,
    placeholderData: keepPreviousData,
    enabled: () => viewTab.value === 'summary',
  });

  // ---- 单次遍历 plans_by_date，同时生成 rows + skuSummary ----
  const _parsed = computed(() => {
    const pbd = (d.value?.plans_by_date ?? {}) as Record<string, Plan[]>;
    const list: Row[] = [];
    const byKey: Record<string, { customer_name: string; barcode: string; product_name: string; plan: number; shipped: number; remain: number; }> = {};
    for (const [ds, pl] of Object.entries(pbd)) {
      if (!pl?.length) continue;
      const dt = new Date(ds + 'T00:00:00');
      const ns = new Set(pl.map(p => p.customer_name));
      const tq = pl.reduce((s, p) => s + Number(p.quantity || 0), 0);
      const shippedQty = pl.reduce((s, p) => s + Number(p.shipped_qty || 0), 0);
      const shipped = pl.filter(p => getShipmentStatus(p.quantity, p.shipped_qty) === 'completed').length;
      const pending = pl.filter(p => getShipmentStatus(p.quantity, p.shipped_qty) !== 'completed').length;
      const byCust: Record<string, Plan[]> = {};
      for (const p of pl) {
        const cn = p.customer_name || '未知';
        if (!byCust[cn]) byCust[cn] = [];
        byCust[cn].push(p);
        // 同步构建 skuSummary（不做custFilter过滤，保持rows独立）
        const customerName = p.customer_name || '未知客户';
        const pn = p.product_name || '—';
        const key = `${customerName}|${pn}`;
        if (!byKey[key]) byKey[key] = { customer_name: customerName, barcode: p.barcode || '—', product_name: pn, plan: 0, shipped: 0, remain: 0 };
        byKey[key].plan += Number(p.quantity || 0);
        byKey[key].shipped += Number(p.shipped_qty || 0);
        byKey[key].remain += Number(p.remaining_qty || 0);
      }
      const _fullDate = `${dt.getMonth() + 1}月${dt.getDate()}日`;
      list.push({ date: ds, _dayNum: dt.getDate(), _weekday: WDS[dt.getDay()] || '?', customerCount: ns.size, planCount: pl.length, totalQty: tq, _isPeak: false, _shippedCount: shipped, _pendingCount: pending, _shippedPct: tq > 0 ? Math.floor(shippedQty / tq * 1000) / 10 : 0, customerNames: [...ns].sort(), plans: pl, _byCustomer: byCust, _fullDate });
    }
    list.sort((a, b) => a.date.localeCompare(b.date));
    let maxP = 0;
    for (const r of list) { if (r.planCount > maxP) maxP = r.planCount; }
    for (const r of list) { r._isPeak = r.planCount === maxP && maxP > 0; }
    const skuList: SkuRow[] = [];
    for (const v of Object.values(byKey)) {
      skuList.push({
        barcode: v.barcode,
        product_name: v.product_name,
        plan_qty: v.plan,
        shipped_qty: v.shipped,
        remain_qty: v.remain,
        customer_name: v.customer_name,
        _pct: v.plan > 0 ? Math.floor(v.shipped / v.plan * 1000) / 10 : 0,
        _odd: false,
      });
    }
    skuList.sort((a, b) => a.customer_name.localeCompare(b.customer_name) || a.barcode.localeCompare(b.barcode));
    return { rows: list, skuSummary: skuList };
  });

  const rows = computed<Row[]>(() => _parsed.value.rows);
  const skuSummary = computed<SkuRow[]>(() => _parsed.value.skuSummary);

  return { d, isLoading, isFetching, isError, refetch, sData, sLoading, sFetching, sError, refetchSummary, rows, skuSummary };
}
