// SKU 月度汇总的排序 / 分页 / 明细弹窗逻辑（从 PurchasePlanView.vue 抽出，行为不变）
import { ref, computed, watch, type Ref, type ComputedRef } from 'vue';
import type { Plan, SkuRow, SkuDateItem } from '../components/types';
import { WDS, getShipmentStatus } from './usePurchasePlanData';

export function useSkuSummary(opts: {
  d: Ref<Record<string, unknown> | undefined>;
  skuSummary: ComputedRef<SkuRow[]>;
  custFilter: Ref<string>;
  globalKw: Ref<string>;
  viewTab: Ref<'daily' | 'summary'>;
}) {
  const { d, skuSummary, custFilter, globalKw, viewTab } = opts;

  const skuSortField = ref('customer');
  const skuSortDir = ref<'asc' | 'desc'>('desc');
  const skuDetailOpen = ref(false);
  const skuDetailBarcode = ref('');
  const skuDetailName = ref('');
  const skuDetailCustomer = ref('');

  const sortedSkuList = computed<SkuRow[]>(() => {
    let list = [...skuSummary.value];
    if (custFilter.value) {
      list = list.filter(s => s.customer_name === custFilter.value);
    }
    if (globalKw.value && viewTab.value === 'summary') {
      const k = globalKw.value.toLowerCase();
      list = list.filter(s =>
        s.barcode.toLowerCase().includes(k) ||
        s.product_name.toLowerCase().includes(k) ||
        s.customer_name.toLowerCase().includes(k)
      );
    }
    const fieldMap: Record<string, keyof SkuRow> = { customer: 'customer_name', barcode: 'barcode', plan: 'plan_qty', shipped: 'shipped_qty', remain: 'remain_qty' };
    const sf = fieldMap[skuSortField.value] ?? 'plan_qty';
    const sd = skuSortDir.value === 'asc' ? 1 : -1;
    // compute total plan_qty per customer
    const custTotal: Record<string, number> = {};
    for (const s of list) {
      custTotal[s.customer_name] = (custTotal[s.customer_name] || 0) + s.plan_qty;
    }
    list.sort((a, b) => {
      const av = a[sf], bv = b[sf];
      let cmp: number;
      if (typeof av === 'string' && typeof bv === 'string') {
        cmp = av.localeCompare(bv);
      } else {
        cmp = ((av as number) - (bv as number));
      }
      if (cmp !== 0) return cmp * sd;
      // primary: customer group by total plan_qty desc
      const ct = (custTotal[b.customer_name] || 0) - (custTotal[a.customer_name] || 0);
      if (ct !== 0) return ct;
      // secondary: within customer, plan_qty desc
      return b.plan_qty - a.plan_qty;
    });
    return list;
  });

  const skuPage = ref(1);
  const skuPageSize = 30;

  const skuTotalPages = computed(() => Math.max(1, Math.ceil(sortedSkuList.value.length / skuPageSize)));
  const paginatedSkuList = computed<SkuRow[]>(() => {
    const start = (skuPage.value - 1) * skuPageSize;
    return sortedSkuList.value.slice(start, start + skuPageSize);
  });

  // Reset page when filters/sort/search change
  watch([custFilter, skuSortField, skuSortDir, globalKw], () => { skuPage.value = 1; });

  const skuDateDetail = computed<SkuDateItem[]>(() => {
    const pbd = (d.value?.plans_by_date ?? {}) as Record<string, Plan[]>;
    const pn = skuDetailName.value;
    const cn = skuDetailCustomer.value;
    if (!pn) return [];
    const byDate: Record<string, SkuDateItem> = {};
    for (const [dateStr, plans] of Object.entries(pbd)) {
      if (!plans?.length) continue;
      for (const p of plans) {
        if (p.product_name !== pn || p.customer_name !== cn) continue;
        if (!byDate[dateStr]) {
          const dt = new Date(dateStr + 'T00:00:00');
          byDate[dateStr] = { date: dateStr, day: dt.getDate(), weekday: WDS[dt.getDay()] || '?', qty: 0, customer: p.customer_name || '未知客户', status: getShipmentStatus(p.quantity, p.shipped_qty) };
        }
        byDate[dateStr].qty += Number(p.quantity || 0);
      }
    }
    const result = Object.values(byDate);
    result.sort((a, b) => a.date.localeCompare(b.date));
    return result;
  });

  function openSkuDetail(payload: { barcode: string; name: string; customer: string }) {
    skuDetailBarcode.value = payload.barcode;
    skuDetailName.value = payload.name;
    skuDetailCustomer.value = payload.customer;
    skuDetailOpen.value = true;
  }

  function toggleSkuSort(field: string) {
    if (skuSortField.value === field) {
      skuSortDir.value = skuSortDir.value === 'asc' ? 'desc' : 'asc';
    } else {
      skuSortField.value = field;
      skuSortDir.value = 'desc';
    }
  }

  return {
    skuSortField,
    skuSortDir,
    skuPage,
    skuTotalPages,
    paginatedSkuList,
    sortedSkuList,
    skuDateDetail,
    skuDetailOpen,
    skuDetailBarcode,
    skuDetailName,
    skuDetailCustomer,
    openSkuDetail,
    toggleSkuSort,
  };
}
