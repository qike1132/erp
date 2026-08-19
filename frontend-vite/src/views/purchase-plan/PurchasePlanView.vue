<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
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

      <PurchasePlanToolbar
        v-model:global-kw="globalKw"
        :view-tab="viewTab"
        :y="y"
        :m="m"
        :has-summary="summaryCustomers.length > 0"
        :s-kpi="sKpi"
        @prev-month="prevMonth"
        @next-month="nextMonth"
        @export="viewTab === 'daily' ? exportCSV() : exportSkuCSV()"
        @create="showCreate = true"
      />

      <PurchasePlanDailyTab
        v-if="viewTab === 'daily'"
        :is-loading="isLoading"
        :d="d"
        :is-error="isError"
        :is-fetching="isFetching"
        :rows="rows"
        :filtered="filtered"
        v-model:sel="sel"
        @refetch="refetch()"
      />

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
import { useQueryClient } from '@tanstack/vue-query';
import { showToast } from '@/composables/useToast';
import { useExport } from '@/composables/useExport';
import { downloadCsv, buildCsvRow } from '@/utils/csv';
import PlanDetailDrawer from './components/PlanDetailDrawer.vue';
import CreateShipmentPlanDialog from './components/CreateShipmentPlanDialog.vue';
import PlanDetailDialog from './components/PlanDetailDialog.vue';
import SkuDetailDialog from './components/SkuDetailDialog.vue';
import PurchasePlanMonthlySummary from './components/PurchasePlanMonthlySummary.vue';
import PurchasePlanDailyTab from './components/PurchasePlanDailyTab.vue';
import PurchasePlanToolbar from './components/PurchasePlanToolbar.vue';
import { usePurchasePlanData } from './composables/usePurchasePlanData';
import { useSkuSummary } from './composables/useSkuSummary';
import type { Row, CustSumItem } from './components/types';

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
const custFilter = ref('');

const planDialogOpen = computed({
  get: () => !!sel.value,
  set: (v: boolean) => { if (!v) sel.value = ''; },
});

watch(globalKw, () => { if (viewTab.value === 'daily') sel.value = ''; });
watch([y, m], () => { sel.value = ''; globalKw.value = ''; });
watch(viewTab, () => { globalKw.value = ''; });

const { d, isLoading, isFetching, isError, refetch, sData, sLoading, sFetching, sError, refetchSummary, rows, skuSummary } = usePurchasePlanData(y, m, viewTab);

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

const {
  skuSortField, skuSortDir, skuPage, skuTotalPages, paginatedSkuList, sortedSkuList,
  skuDateDetail, skuDetailOpen, skuDetailBarcode, skuDetailName, skuDetailCustomer,
  openSkuDetail, toggleSkuSort,
} = useSkuSummary({ d, skuSummary, custFilter, globalKw, viewTab });

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

const { runExport } = useExport({ start: false });

function exportCSV() {
  const rl = filtered.value;
  if (!rl.length) { showToast('无数据', 'error'); return; }
  const h = buildCsvRow(['日期', '星期', '客户数', '计划条目数', '总量(件)', '客户']);
  const ls = [h];
  for (const r of rl) ls.push(buildCsvRow([r.date, `周${r._weekday}`, r.customerCount, r.planCount, r.totalQty, r.customerNames.join('、')]));
  runExport(() => downloadCsv(ls, `出货计划_${y.value}年${m.value}月_日汇总.csv`));
}
</script>

<style scoped lang="scss">
@use './purchase-plan-common.scss' as *;
.sp-container {
  height: 100%;
  padding: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
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
</style>
