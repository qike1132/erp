<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <HeaderTabs />
        <div class="sp-header-content">
          <div class="sp-header-left">
            <div class="sp-tab-group" role="tablist">
              <button
                role="tab"
                :aria-selected="viewTab === 'daily'"
                :class="['sp-tab', { 'sp-tab-active': viewTab === 'daily' }]"
                @click="viewTab = 'daily'"
              >每日计划</button>
              <button
                role="tab"
                :aria-selected="viewTab === 'summary'"
                :class="['sp-tab', { 'sp-tab-active': viewTab === 'summary' }]"
                @click="viewTab = 'summary'"
              >月度汇总</button>
            </div>
          </div>
        </div>
      </div>

      <div class="sp-toolbar">
        <div class="sp-toolbar-actions">
          <div class="sp-nav">
            <button class="sp-nav-btn" @click="prevMonth" aria-label="上一页"><i class="fas fa-chevron-left"  aria-hidden="true" /></button>
            <span class="sp-nav-label">{{ y }}年{{ String(m).padStart(2, '0') }}月</span>
            <button class="sp-nav-btn" @click="nextMonth" aria-label="下一页"><i class="fas fa-chevron-right"  aria-hidden="true" /></button>
          </div>
          <UiSearchInput v-model="globalKw" :placeholder="viewTab === 'daily' ? '搜索日期、客户...' : '搜索产品、SKU、客户...'" @clear="globalKw = ''" />
          <button class="sp-action-btn" @click="viewTab === 'daily' ? exportCSV() : exportSkuCSV()">导出</button>
          <button class="sp-action-btn sp-action-btn-primary" @click="showCreate = true"><i class="fas fa-plus"  aria-hidden="true" />新建</button>
        </div>
        <div v-if="summaryCustomers.length" class="sp-toolbar-stats-wrapper">
          <div class="sp-toolbar-stats">
            <div class="sp-stat">
              <span class="sp-stat-label">总计划</span>
              <span class="sp-stat-value">{{ sKpi.allQty }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-label">已出</span>
              <span class="sp-stat-value sp-stat-success">{{ sKpi.allShipped }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-label">剩余</span>
              <span class="sp-stat-value sp-stat-warning">{{ sKpi.allRemain }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="viewTab === 'daily'" class="sp-body">
        <div v-if="isLoading && !d" class="sp-empty"><UiSpinner /></div>
        <div v-else-if="isError" class="sp-empty"><i class="fas fa-exclamation-circle"  aria-hidden="true" />加载失败 <button class="sp-retry-btn" @click="refetch()">重试</button></div>
        <div v-else-if="!rows.length" class="sp-empty"><i class="fas fa-inbox"  aria-hidden="true" />本月暂无出货计划</div>
        <template v-else>
        <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>
        <div>
          <div class="sp-day-grid">
            <div
              v-for="(r, idx) in filtered"
              :key="r.date"
              class="sp-day-card"
              :class="{
                'sp-day-selected': sel === r.date,
              }"
              @click="sel = sel === r.date ? '' : r.date"
            >
              <div class="sp-day-header">
                <span class="sp-day-badge">{{ r._fullDate }}：{{ fmtQty(r.totalQty) }}</span>
                <span v-if="r._pendingCount > 0" class="sp-day-alert" :class="getAlertClass(r.date)">{{ getAlertLabel(r.date) }}</span>
                <span v-else-if="r._shippedPct === 100" class="sp-day-alert sp-day-done"><i class="fas fa-check"  aria-hidden="true" /> 完成</span>
              </div>

              <div class="sp-day-body">
                <span v-for="(cn, i) in r.customerNames.slice(0, 5)" :key="cn" class="sp-day-customer-tag">
                  {{ cn }}
                </span>
                <span v-if="r.customerNames.length > 5" class="sp-day-more-tag">
                  +{{ r.customerNames.length - 5 }}家客户
                </span>            </div>
          </div>
          </div>
        </div>
        </template>
      </div>

      <PurchasePlanMonthlySummary
        v-else
        :loading="sLoading && !sData"
        :error="sError"
        :fetching="sFetching"
        :has-data="summaryCustomers.length > 0"
        :customers="allCustomers"
        v-model:cust-filter="custFilter"
        :sorted-sku-list="sortedSkuList"
        :paginated-sku-list="paginatedSkuList"
        v-model:sku-page="skuPage"
        :sku-total-pages="skuTotalPages"
        :sku-sort-field="skuSortField"
        :sku-sort-dir="skuSortDir"
        @toggle-sku-sort="toggleSkuSort"
        @open-sku-detail="openSkuDetail"
        @refetch="refetchSummary"
      />
    </div>

    <PlanDetailDialog v-model:open="planDialogOpen" :detail="selDetail" />
    <SkuDetailDialog v-model:open="skuDetailOpen" :barcode="skuDetailBarcode" :name="skuDetailName" :date-detail="skuDateDetail" />
  </div>

  <PlanDetailDrawer v-model:visible="drwOpen" :plan-id="drwId" @edited="onEdited" />
  <CreateShipmentPlanDialog v-model:open="showCreate" @created="onCreated" />
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query';
import { planApi } from '@/api';
import { showToast } from '@/composables/useToast';
import { downloadCsv, buildCsvRow } from '@/utils/csv';
import HeaderTabs from '@/layouts/components/HeaderTabs.vue';
import PlanDetailDrawer from './components/PlanDetailDrawer.vue';
import CreateShipmentPlanDialog from './components/CreateShipmentPlanDialog.vue';
import PlanDetailDialog from './components/PlanDetailDialog.vue';
import SkuDetailDialog from './components/SkuDetailDialog.vue';
import PurchasePlanMonthlySummary from './components/PurchasePlanMonthlySummary.vue';
import type { Plan, Row, CustSumItem, SkuRow, SkuDateItem } from './components/types';

const qc = useQueryClient();

const t = new Date();
const y = ref(t.getFullYear());
const m = ref(t.getMonth() + 1);
const globalKw = ref('');
const sel = ref('');
const showCreate = ref(false);
const drwOpen = ref(false);
const drwId = ref(0);
const viewTab = ref<'daily' | 'summary'>('daily');
const skuSortField = ref('customer');
const skuSortDir = ref<'asc' | 'desc'>('desc');
const custFilter = ref('');
const skuDetailOpen = ref(false);
const skuDetailBarcode = ref('');
const skuDetailName = ref('');
const skuDetailCustomer = ref('');

const planDialogOpen = computed({
  get: () => !!sel.value,
  set: (v: boolean) => { if (!v) sel.value = ''; },
});

watch(globalKw, () => { if (viewTab.value === 'daily') sel.value = ''; });
watch([y, m], () => { sel.value = ''; globalKw.value = ''; });
watch(viewTab, () => { globalKw.value = ''; });

const WDS = ['日', '一', '二', '三', '四', '五', '六'];

const { data: d, isLoading, isFetching, isError, refetch } = useQuery({
  queryKey: ['pp-monthly', () => y.value, () => m.value],
  queryFn: async () => {
    const res = (await planApi.monthly({ year: y.value, month: m.value })) as any;
    // 冻结返回数据，阻止 Vue 对 20K+ 明细做深层响应式转换，降低内存和 CPU 开销
    return res ? Object.freeze(JSON.parse(JSON.stringify(res))) : res;
  },
  staleTime: 5 * 60 * 1000,
  gcTime: 30 * 60 * 1000,
  retry: 1,
  retryDelay: 2000,
  placeholderData: keepPreviousData,
});

function refetchAll() { refetch(); refetchSummary(); }

const { data: sData, isLoading: sLoading, isFetching: sFetching, isError: sError, refetch: refetchSummary } = useQuery({
  queryKey: ['pp-summary', () => y.value, () => m.value],
  queryFn: async () => (await planApi.customerSummary({ year: y.value, month: m.value })) as any,
  staleTime: 5 * 60 * 1000,
  gcTime: 30 * 60 * 1000,
  retry: 1,
  retryDelay: 2000,
  placeholderData: keepPreviousData,
  enabled: () => viewTab.value === 'summary',
});

const allCustomers = computed<CustSumItem[]>(() => {
  const arr = (sData.value?.customers ?? []) as CustSumItem[];
  return [...arr].sort((a, b) => b.remaining_qty - a.remaining_qty);
});

const summaryCustomers = computed<CustSumItem[]>(() => {
  if (!custFilter.value) return allCustomers.value;
  return allCustomers.value.filter(c => c.customer_name === custFilter.value);
});

const sKpi = computed(() => {
  const cs = summaryCustomers.value;
  const kpi0 = custFilter.value ? String(cs[0]?.plan_qty || 0) + ' 件' : cs.length + ' 客户';
  const lbl0 = custFilter.value ? cs[0]?.customer_name || '—' : '客户合计';
  const planQty = cs.reduce((s, c) => s + Number(c.plan_qty || 0), 0);
  const shipQty = cs.reduce((s, c) => s + Number(c.shipped_qty || 0), 0);
  const remainQty = cs.reduce((s, c) => s + Number(c.remaining_qty || 0), 0);
  const pct = planQty > 0 ? Math.floor(shipQty / planQty * 1000) / 10 : 0;
  return {
    kpi0,
    lbl0,
    allQty: String(planQty),
    allShipped: String(shipQty),
    allRemain: String(remainQty),
    pct,
  };
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

const filtered = computed(() => {
  if (!globalKw.value || viewTab.value !== 'daily') return rows.value;
  const k = globalKw.value.toLowerCase();
  return rows.value.filter(r => r.date.includes(k) || r.customerNames.some(n => n.toLowerCase().includes(k)));
});

const rowMap = computed(() => {
  const mp = new Map<string, Row>();
  for (const r of rows.value) mp.set(r.date, r);
  return mp;
});

const selDetail = computed(() => sel.value ? rowMap.value.get(sel.value) ?? null : null);

function fmtQty(n: number): string {
  return String(n);
}

function getShipmentStatus(quantity: number, shippedQty: number): string {
  if (shippedQty >= quantity) return 'completed';
  if (shippedQty > 0) return 'partial';
  return 'pending';
}

function getDaysDiff(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr + 'T00:00:00');
  return Math.ceil((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function getAlertClass(dateStr: string): string {
  const diff = getDaysDiff(dateStr);
  if (diff < 0) return 'sp-day-overdue';
  if (diff <= 3) return 'sp-day-due-soon';
  return '';
}

function getAlertLabel(dateStr: string): string {
  const diff = getDaysDiff(dateStr);
  if (diff < 0) return '延期 ' + Math.abs(diff) + ' 天';
  if (diff === 0) return '今日出货';
  if (diff <= 3) return '临期 ' + diff + ' 天';
  return '';
}

function toggleSkuSort(field: string) {
  if (skuSortField.value === field) {
    skuSortDir.value = skuSortDir.value === 'asc' ? 'desc' : 'asc';
  } else {
    skuSortField.value = field;
    skuSortDir.value = 'desc';
  }
}

function exportSkuCSV() {
  const list = sortedSkuList.value;
  if (!list.length) { showToast('无数据', 'error'); return; }
  const h = buildCsvRow(['客户名称', '产品名称', '商品条码', '计划数量', '已出货', '待出货', '进度']);
  const ls = [h];
  for (const s of list) ls.push(buildCsvRow([s.customer_name, s.product_name, s.barcode, s.plan_qty, s.shipped_qty, s.remain_qty, s._pct + '%']));
  downloadCsv(ls, `SKU月度统计_${y.value}年${m.value}月.csv`);
  showToast('导出成功', 'success');
}

function prevMonth() { m.value = m.value === 1 ? 12 : m.value - 1; if (m.value === 12) y.value--; }
function nextMonth() { m.value = m.value === 12 ? 1 : m.value + 1; if (m.value === 1) y.value++; }
function onEdited() { qc.invalidateQueries({ queryKey: ['pp-monthly'] }); qc.invalidateQueries({ queryKey: ['pp-summary'] }); }
function onCreated() { showCreate.value = false; qc.invalidateQueries({ queryKey: ['pp-monthly'] }); qc.invalidateQueries({ queryKey: ['pp-summary'] }); }

function exportCSV() {
  const rl = filtered.value;
  if (!rl.length) { showToast('无数据', 'error'); return; }
  const h = buildCsvRow(['日期', '星期', '客户数', '计划条目数', '总量(件)', '客户']);
  const ls = [h];
  for (const r of rl) ls.push(buildCsvRow([r.date, `周${r._weekday}`, r.customerCount, r.planCount, r.totalQty, r.customerNames.join('、')]));
  downloadCsv(ls, `出货计划_${y.value}年${m.value}月_日汇总.csv`);
  showToast('导出成功', 'success');
}
</script>

<style scoped>
.sp-container {
  height: 100%;
  padding: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.sp-header-content {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  flex: 1;
}

.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.sp-header-left {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.sp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 24px;
  flex-wrap: wrap;
}

.sp-toolbar-stats-wrapper {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: flex-end;
}

.sp-toolbar-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  height: 45px;
  box-sizing: border-box;
  border-radius: var(--radius-input, 12px);
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: transparent;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.sp-toolbar-stats:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.sp-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0;
}

.sp-stat + .sp-stat {
  padding-left: 12px;
  border-left: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-stat-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.sp-stat-value {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.sp-stat-success {
  color: var(--color-success-600);
}

.sp-stat-success .sp-stat-value {
  color: var(--color-success-600);
}

.sp-stat-warning {
  color: var(--color-warning-600);
}

.sp-stat-warning .sp-stat-value {
  color: var(--color-warning-600);
}


.sp-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.sp-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  width: fit-content;
}

.sp-tab {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  font-family: inherit;
}

.sp-tab:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.sp-tab-active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

.sp-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.sp-nav-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-input, 12px);
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
  flex-shrink: 0;
}

.sp-nav-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-nav-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-heading);
  min-width: 90px;
  text-align: center;
  user-select: none;
}

.sp-nav-today {
  padding: 5px 12px;
  border-radius: var(--radius-input, 12px);
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--color-primary-200);
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  cursor: pointer;
  transition: background 0.3s ease;
  font-family: inherit;
  flex-shrink: 0;
}

.sp-nav-today:hover {
  background: var(--color-primary-100);
}

.sp-search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  background: white;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  min-width: 180px;
  box-sizing: border-box;
}

.sp-search-box i {
  color: var(--color-text-muted);
  font-size: 12px;
}

.sp-search-box input {
  border: none;
  background: transparent;
  font-size: 14px;
  padding: 10px 0;
  outline: none;
  flex: 1;
  color: var(--color-heading);
  font-family: inherit;
  min-width: 0;
}

.sp-search-box input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.sp-search-box input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

.sp-search-box:focus-within {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(91, 141, 239, 0.1);
}

.sp-search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: var(--color-border-light, #e2e8f0);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
  padding: 0;
  flex-shrink: 0;
}

.sp-search-clear:hover {
  background: var(--color-primary-100);
  color: var(--color-primary-600);
}

.sp-search-clear i {
  font-size: 10px;
}


.sp-action-btn {
  padding: 7px 14px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-primary-600);
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.sp-action-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-action-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-action-btn-primary:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  opacity: 0.95;
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.25);
}

.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-day-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.sp-day-card {
  padding: 18px;
  border-radius: 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
  position: relative;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 260px;
  overflow: hidden;
}

.sp-day-card:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.sp-day-selected {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

.sp-day-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 0 8px;
  margin-top: -10px;
  flex-shrink: 0;
}

.sp-day-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 700;
  border-radius: 6px;
  white-space: nowrap;
}

.sp-day-alert {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.sp-day-due-soon {
  background: var(--color-warning-100);
  color: var(--color-warning-700);
}

.sp-day-overdue {
  background: var(--color-danger-100);
  color: var(--color-danger-700);
}

.sp-day-done {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.sp-day-customer-tag {
  display: block;
  font-size: 14px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1.2;
}

.sp-day-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
  min-height: 0;
  flex: 1;
}

.sp-day-more-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  padding: 3px 10px;
  border-radius: 10px;
  cursor: pointer;
}

.sp-day-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sp-day-metric {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.sp-day-metric-val {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.sp-day-metric-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted);
}

.sp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.sp-empty i {
  font-size: 28px;
  opacity: 0.5;
}

/* Fetching progress bar */
.sp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.sp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: sp-progress-slide 1s ease-in-out infinite;
}
@keyframes sp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.sp-retry-btn {
  margin-top: 6px;
  padding: 4px 16px;
  border: 1px solid var(--color-border, #d0d5dd);
  border-radius: 6px;
  background: var(--color-bg, #fff);
  color: var(--color-text, #344054);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}
.sp-retry-btn:hover {
  background: var(--color-bg-hover, #f2f4f7);
}

.sp-modal-badge {
  padding: 5px 12px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 13px;
  font-weight: 600;
}

.sp-sidebar-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-input);
  background: white;
  margin-bottom: 12px;
}

.sp-sidebar-search i {
  color: var(--color-text-muted);
  font-size: 12px;
}

.sp-sidebar-search input {
  border: none;
  background: transparent;
  font-size: 14px;
  padding: 10px 0;
  outline: none;
  flex: 1;
  color: var(--color-heading);
  font-family: inherit;
}

.sp-sidebar-search input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.sp-sidebar-search input::placeholder {
  color: var(--color-text-muted);
  opacity: 1;
}

.sp-modal-main-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.sp-modal-main-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-modal-main-meta {
  font-size: 13px;
  color: var(--color-text-muted);
}

.sp-plan-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sp-plan-progress-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}

.sp-plan-progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(135deg, var(--color-success-400), var(--color-success-600));
  transition: width 0.4s ease;
}

.sp-progress-done {
  background: linear-gradient(135deg, var(--color-success-500), var(--color-success-700));
}

.sp-plan-progress-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  min-width: 36px;
  text-align: right;
}

.sp-status-done {
  padding: 5px 12px;
  border-radius: 8px;
  background: var(--color-success-50);
  color: var(--color-success-600);
  font-size: 12px;
  font-weight: 600;
}

.sp-status-partial {
  padding: 5px 12px;
  border-radius: 8px;
  background: var(--color-warning-50);
  color: var(--color-warning-600);
  font-size: 12px;
  font-weight: 600;
}

.sp-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.sp-modal-footer-btn {
  padding: 8px 18px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light);
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
}

.sp-modal-footer-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-modal-footer-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-modal-footer-btn-primary:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  opacity: 0.95;
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.25);
}
</style>
