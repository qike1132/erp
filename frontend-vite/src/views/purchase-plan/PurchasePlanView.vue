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
          >排产日历</button>
          <button
            role="tab"
            :aria-selected="viewTab === 'summary'"
            :class="['sp-tab', { 'sp-tab-active': viewTab === 'summary' }]"
            @click="viewTab = 'summary'"
          >月度汇总</button>
        </div>

        <PurchasePlanToolbar
          v-model:global-kw="globalKw"
          :view-tab="viewTab"
          :y="y"
          :m="m"
          @prev-month="prevMonth"
          @next-month="nextMonth"
          @export="viewTab === 'daily' ? exportCSV() : exportSkuCSV()"
          @create="showCreate = true"
        />
      </div>

      <div class="sp-kpi-strip-wrap">
        <div class="sp-kpi-strip">
          <div class="sp-kpi">
            <span class="sp-kpi-l">本月计划</span>
            <span class="sp-kpi-v num">{{ sKpi.allQty }}</span>
            <span class="sp-kpi-s num">{{ allQtyNum }}件</span>
          </div>
          <div class="sp-kpi">
            <span class="sp-kpi-l">本月已出</span>
            <span class="sp-kpi-v num" :class="allShippedNum > 0 ? '' : 'sp-kpi-v-r'">{{ sKpi.allShipped }}</span>
          </div>
          <div class="sp-kpi">
            <span class="sp-kpi-l">剩余</span>
            <span class="sp-kpi-v num sp-kpi-v-a">{{ sKpi.allRemain }}</span>
          </div>
          <div class="sp-kpi sp-kpi-rate">
            <span class="sp-kpi-l">完成率</span>
            <span class="sp-kpi-v num" :class="sKpi.pct <= 0 ? 'sp-kpi-v-r' : ''">{{ sKpi.pct }}%</span>
            <div class="sp-meter"><i :class="kpiMeterCls" :style="{ width: sKpi.pct + '%' }" /></div>
          </div>
          <div class="sp-kpi">
            <span class="sp-kpi-l" :class="risks.delayedCount > 0 ? 'sp-kpi-l-r' : ''">▲ 已延期</span>
            <span class="sp-kpi-v num" :class="risks.delayedCount > 0 ? 'sp-kpi-v-r' : ''">{{ risks.delayedCount }}</span>
            <span v-if="risks.delayedCount > 0" class="sp-kpi-s num">{{ risks.delayedQty }}件 · 最多{{ risks.maxDays }}天</span>
          </div>
          <div class="sp-kpi">
            <span class="sp-kpi-l" :class="risks.expiringCount > 0 ? 'sp-kpi-l-a' : ''">⧗ 临期≤3天</span>
            <span class="sp-kpi-v num" :class="risks.expiringCount > 0 ? 'sp-kpi-v-a' : ''">{{ risks.expiringCount }}</span>
            <span v-if="risks.expiringCount > 0" class="sp-kpi-s num">{{ risks.expiringQty }}件</span>
          </div>
        </div>
      </div>

      <PurchasePlanDailyTab
        v-if="viewTab === 'daily'"
        v-model:sel="sel"
        :y="y"
        :m="m"
        :is-loading="isLoading"
        :is-error="isError"
        :is-fetching="isFetching"
        :rows="rows"
        :filtered="filtered"
        :customers="allCustomers"
        :sku-date-index="skuDateIndex"
        @refetch="refetch()"
      />

      <PurchasePlanMonthlySummary
        v-else
        v-model:cust-filter="custFilter"
        v-model:sku-page="skuPage"
        :loading="isLoading && !d"
        :error="isError"
        :fetching="isFetching"
        :has-data="summaryCustomers.length > 0"
        :customers="allCustomers"
        :sorted-sku-list="sortedSkuList"
        :paginated-sku-list="paginatedSkuList"
        :sku-total-pages="skuTotalPages"
        :sku-sort-field="skuSortField"
        :sku-sort-dir="skuSortDir"
        @toggle-sku-sort="toggleSkuSort"
        @open-sku-detail="openSkuDetail"
        @refetch="refetch"
      />
    </div>

    <PlanDetailDialog v-model:open="planDialogOpen" :detail="selDetail" :y="y" :m="m" />
    <SkuDetailDialog v-model:open="skuDetailOpen" :barcode="skuDetailBarcode" :name="skuDetailName" :date-detail="skuDateDetail" />
  </div>

  <PlanDetailDrawer v-model:visible="drwOpen" :plan-id="drwId" @edited="onEdited" />
  <CreateShipmentPlanDialog v-model:open="showCreate" @created="onCreated" @imported="onImported" />
</template>

<script setup lang="ts">
import { ref, computed, watch, defineAsyncComponent } from 'vue';
import { useQueryClient } from '@tanstack/vue-query';
import { useDebounceFn } from '@vueuse/core';
import { showToast } from '@/composables/useToast';
import { useExport } from '@/composables/useExport';
import { downloadCsv, buildCsvRow } from '@/utils/csv';
import PurchasePlanMonthlySummary from './components/PurchasePlanMonthlySummary.vue';
import PurchasePlanDailyTab from './components/PurchasePlanDailyTab.vue';
import PurchasePlanToolbar from './components/PurchasePlanToolbar.vue';
import { usePurchasePlanData } from './composables/usePurchasePlanData';
import { useSkuSummary } from './composables/useSkuSummary';
import type { CustSumItem } from './components/types';

// 弹窗/抽屉组件懒加载，减少首屏 chunk 体积（仅在用户交互时才加载）
const PlanDetailDrawer = defineAsyncComponent(() => import('./components/PlanDetailDrawer.vue'));
const CreateShipmentPlanDialog = defineAsyncComponent(() => import('./components/CreateShipmentPlanDialog.vue'));
const PlanDetailDialog = defineAsyncComponent(() => import('./components/PlanDetailDialog.vue'));
const SkuDetailDialog = defineAsyncComponent(() => import('./components/SkuDetailDialog.vue'));

const qc = useQueryClient();

const t = new Date();
const y = ref(t.getFullYear());
const m = ref(t.getMonth() + 1);
const globalKw = ref('');
// 搜索防抖：250ms 内连续按键只触发一次 computed 重算，避免每次输入全量过滤
const debouncedKw = ref('');
const _flushDebounced = useDebounceFn((v: string) => { debouncedKw.value = v; }, 250);
watch(globalKw, (v) => _flushDebounced(v));
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
watch([y, m], () => { sel.value = ''; globalKw.value = ''; debouncedKw.value = ''; });
watch(viewTab, () => { globalKw.value = ''; debouncedKw.value = ''; });

const { d, isLoading, isFetching, isError, refetch, rows, skuSummary, skuDateIndex, customers } = usePurchasePlanData(y, m, viewTab);

const allCustomers = computed<CustSumItem[]>(() => {
  return [...customers.value].sort((a, b) => b.remaining_qty - a.remaining_qty);
});

const summaryCustomers = computed<CustSumItem[]>(() => {
  if (!custFilter.value) return allCustomers.value;
  return allCustomers.value.filter(c => c.customer_name === custFilter.value);
});

const sKpi = computed(() => {
  const cs = summaryCustomers.value;
  let planQty = 0, shipQty = 0, remainQty = 0;
  for (const c of cs) {
    planQty += Number(c.plan_qty || 0);
    shipQty += Number(c.shipped_qty || 0);
    remainQty += Number(c.remaining_qty || 0);
  }
  const pct = planQty > 0 ? Math.floor(shipQty / planQty * 1000) / 10 : 0;
  return {
    allQty: String(planQty),
    allShipped: String(shipQty),
    allRemain: String(remainQty),
    pct,
  };
});

const allShippedNum = computed(() => Number(sKpi.value.allShipped || 0));
const allQtyNum = computed(() => Number(sKpi.value.allQty || 0));
const kpiMeterCls = computed(() => {
  const p = sKpi.value.pct;
  if (p <= 0) return 'sp-meter-r';
  if (p < 100) return 'sp-meter-a';
  return 'sp-meter-g';
});

const {
  skuSortField, skuSortDir, skuPage, skuTotalPages, paginatedSkuList, sortedSkuList,
  skuDateDetail, skuDetailOpen, skuDetailBarcode, skuDetailName, skuDetailCustomer,
  openSkuDetail, toggleSkuSort,
} = useSkuSummary({ skuSummary, skuDateIndex, custFilter, globalKw: debouncedKw, viewTab });

// 使用防抖后的搜索值，避免每次按键触发全量过滤
const filtered = computed(() => {
  if (!debouncedKw.value || viewTab.value !== 'daily') return rows.value;
  const k = debouncedKw.value.toLowerCase();
  return rows.value.filter(r => r.date.includes(k) || r.customerNames.some(n => n.toLowerCase().includes(k)));
});

// 按需查找，避免每次 rows 变化都预建 Map（rows 通常 ≤31 条，find 开销可忽略）
const selDetail = computed(() => {
  if (!sel.value) return null;
  return rows.value.find(r => r.date === sel.value) ?? null;
});

// 延期 / 临期风险汇总，用于顶栏 KPI 阈值条展示
const risks = computed(() => {
  const now = new Date(); now.setHours(0, 0, 0, 0);
  const MS = 86400000;
  const r = { delayedCount: 0, delayedQty: 0, maxDays: 0, expiringCount: 0, expiringQty: 0 };
  for (const row of rows.value) {
    if (row._shippedPct === 100 || row._pendingCount <= 0) continue;
    const diff = Math.round((new Date(row.date + 'T00:00:00').getTime() - now.getTime()) / MS);
    if (diff < 0) { r.delayedCount++; r.delayedQty += row.totalQty; r.maxDays = Math.max(r.maxDays, -diff); }
    else if (diff <= 3) { r.expiringCount++; r.expiringQty += row.totalQty; }
  }
  return r;
});

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
function onEdited() { qc.invalidateQueries({ queryKey: ['pp-agg'] }); qc.invalidateQueries({ queryKey: ['pp-day'] }); }
function onCreated() { showCreate.value = false; qc.invalidateQueries({ queryKey: ['pp-agg'] }); qc.invalidateQueries({ queryKey: ['pp-day'] }); }

/**
 * 批量导入完成。
 * 与 onCreated 的差异：
 *   1. 不关闭对话框——导入结果（成功/失败条数、失败明细、导出入口）需要停留供查看；
 *   2. 跳转到数据所属月份——导入的计划可能不属于当前浏览月份，
 *      若只刷新不跳月，新数据会因月度筛选而不可见。
 */
function onImported(month?: string) {
  // 清空搜索词与客户筛选：残留的筛选条件会把新导入的数据过滤掉，
  // 表现为「导入成功但列表看不到」，与数据未入库难以区分。
  globalKw.value = ''
  debouncedKw.value = ''
  custFilter.value = ''
  sel.value = ''
  if (month) {
    const [yy, mm] = month.split('-').map(Number)
    if (yy && mm) {
      y.value = yy
      m.value = mm
    }
  }
  // skuPage 由 useSkuSummary 内的 watch 监听筛选变化自动归位，此处无需手动重置
  qc.invalidateQueries({ queryKey: ['pp-agg'] })
  qc.invalidateQueries({ queryKey: ['pp-day'] })
}

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

/* KPI 阈值条（v5）：计划/已出/剩余/完成率/延期/临期 */
.sp-kpi-strip-wrap {
  padding: 12px 24px 4px;
  flex-shrink: 0;
}

.sp-kpi-strip {
  display: flex;
  align-items: stretch;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}

.sp-kpi {
  flex: 1;
  min-width: 0;
  padding: 11px 16px;
  border-right: 1px solid var(--color-border-light, #e2e8f0);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sp-kpi:last-child { border-right: none; }
.sp-kpi-rate { flex: 1.4; }
.sp-kpi-l {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted, #5a6b8c);
  white-space: nowrap;
}
.sp-kpi-l-r { color: var(--color-danger-600); }
.sp-kpi-l-a { color: var(--color-warning-600); }
.sp-kpi-v {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
  margin-top: 3px;
}
.sp-kpi-v-r { color: var(--color-danger-600); }
.sp-kpi-v-a { color: var(--color-warning-600); }
.sp-kpi-s {
  font-size: 11px;
  color: var(--color-text-muted, #8c96ad);
  white-space: nowrap;
  margin-top: 3px;
  text-align: left;
}
.sp-meter {
  height: 6px;
  border-radius: 3px;
  background: #edf0f6;
  overflow: hidden;
  margin-top: 8px;
  max-width: 220px;
}
.sp-meter > i {
  display: block;
  height: 100%;
  border-radius: 3px;
}
.sp-meter-r { background: var(--color-danger-500, #e04042); }
.sp-meter-a { background: var(--color-warning-500, #f59e0b); }
.sp-meter-g { background: var(--color-success-500, #2a9a5b); }
</style>
