<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <!-- 外层必须是纵向容器：.page-card-header 是 flex-wrap:nowrap 的横向 flex，
             两行直接放进去会被并排摆开。 -->
        <div class="sp-head">
          <div class="sp-head-row1">
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
              @export="viewTab === 'daily' ? exportCSV() : exportSkuCSV()"
              @create="showCreate = true"
            />
          </div>

          <!-- 第二行：月份上下文 + 工厂筛选 + 该月汇总。
               切月与切工厂都作用于整页（KPI 与两个 Tab 都跟着变），所以与 KPI 同行，
               而不是挤在右上角与「新建」抢位置。 -->
          <div class="sp-head-row2">
            <PurchasePlanMonthNav
              :y="y"
              :m="m"
              @prev="prevMonth"
              @next="nextMonth"
              @reset="resetMonth"
            />
            <PurchasePlanFactoryFilter
              v-model="factory"
              :factories="availableFactories"
              :totals="factoryTotals"
            />
            <PurchasePlanKpiStrip
              :plan-qty="planQtyNum"
              :produced-qty="producedQtyNum"
              :remain-qty="remainQtyNum"
              :pct="sKpi.pct"
              :plan-days="rows.length"
              :risk-days="riskDays"
              :risk-overdue="risks.delayedCount"
              :risk-expiring="risks.expiringCount"
              :risk-qty="riskQty"
            />
          </div>
        </div>
      </div>

      <PurchasePlanDailyTab
        v-if="viewTab === 'daily'"
        v-model:sel="sel"
        :y="y"
        :m="m"
        :factory="factory"
        :is-loading="isLoading"
        :is-error="isError"
        :is-fetching="isFetching"
        :rows="rows"
        :filtered="filtered"
        :sku-date-index="skuDateIndex"
        @refetch="refetch()"
        @open-full="openFullDay"
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

      <PlanDetailDialog v-model:open="planDialogOpen" :detail="selDetail" :y="y" :m="m" :factory="factory" />
      <SkuDetailDialog v-model:open="skuDetailOpen" :barcode="skuDetailBarcode" :name="skuDetailName" :date-detail="skuDateDetail" />
    </div>
  </div>

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
import PurchasePlanMonthNav from './components/PurchasePlanMonthNav.vue';
import PurchasePlanKpiStrip from './components/PurchasePlanKpiStrip.vue';
import PurchasePlanFactoryFilter from './components/PurchasePlanFactoryFilter.vue';
import { usePurchasePlanData } from './composables/usePurchasePlanData';
import { useSkuSummary } from './composables/useSkuSummary';
import { useFactorySplit, type FactoryFilter } from './composables/useFactorySplit';
import type { CustSumItem } from './components/types';

// 弹窗组件懒加载，减少首屏 chunk 体积（仅在用户交互时才加载）
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
const viewTab = ref<'daily' | 'summary'>('daily');
const custFilter = ref('');
// 工厂筛选（作用于整页）：'all' 表示全部工厂
const factory = ref<FactoryFilter>('all');

// 当日明细的呈现从「选中即弹窗」改为「右栏内联，点按钮才开弹窗」：
// sel 仍然只是「选中了哪一天」，弹窗开关与它解耦，右栏才有稳定的展示位。
const planDialogOpen = ref(false);

function openFullDay() {
  if (sel.value) planDialogOpen.value = true;
}

// sel 被清空（切月 / 切 Tab / 清搜索）时同步关掉弹窗，避免它挂着一个已失效的日期
watch(sel, (v) => { if (!v) planDialogOpen.value = false; });
watch(globalKw, () => { if (viewTab.value === 'daily') sel.value = ''; });
watch([y, m], () => { sel.value = ''; globalKw.value = ''; debouncedKw.value = ''; });
watch(viewTab, () => { globalKw.value = ''; debouncedKw.value = ''; });
// 切工厂后，原来选中的日期/客户可能在新工厂下无数据，一并清掉避免空白页
watch(factory, () => { sel.value = ''; custFilter.value = ''; });

const {
  d, isLoading, isFetching, isError, refetch,
  rows: rawRows, skuSummary: rawSkuSummary, skuDateIndex: rawSkuDateIndex, customers: rawCustomers,
} = usePurchasePlanData(y, m, viewTab);

// 工厂维度拆分：一次性拿到整月聚合后本地切换，切换零延迟（见 useFactorySplit）。
// 下游的 rows / skuSummary / skuDateIndex / customers 全部是「已按工厂过滤」的视图。
const { rows, skuSummary, skuDateIndex, customers, availableFactories, factoryTotals } = useFactorySplit({
  factory,
  rows: rawRows,
  skuSummary: rawSkuSummary,
  skuDateIndex: rawSkuDateIndex,
  customers: rawCustomers,
});

// 切月后若该工厂当月已无计划，回落到「全部」——否则控件不再渲染该厂药丸，
// 会出现「没有任何药丸处于选中态、页面却是空的」的困惑状态。
watch(availableFactories, (list) => {
  if (factory.value !== 'all' && !list.includes(factory.value)) factory.value = 'all';
});

const allCustomers = computed<CustSumItem[]>(() => {
  return [...customers.value].sort((a, b) => b.remaining_qty - a.remaining_qty);
});

const summaryCustomers = computed<CustSumItem[]>(() => {
  if (!custFilter.value) return allCustomers.value;
  return allCustomers.value.filter(c => c.customer_name === custFilter.value);
});

const sKpi = computed(() => {
  const cs = summaryCustomers.value;
  let planQty = 0, prodQty = 0, remainQty = 0;
  for (const c of cs) {
    planQty += Number(c.plan_qty || 0);
    prodQty += Number(c.produced_qty || 0);
    remainQty += Number(c.remaining_qty || 0);
  }
  const pct = planQty > 0 ? Math.floor(prodQty / planQty * 1000) / 10 : 0;
  return {
    allQty: String(planQty),
    allProduced: String(prodQty),
    allRemain: String(remainQty),
    pct,
  };
});

const planQtyNum = computed(() => Number(sKpi.value.allQty || 0));
const producedQtyNum = computed(() => Number(sKpi.value.allProduced || 0));
const remainQtyNum = computed(() => Number(sKpi.value.allRemain || 0));

const {
  skuSortField, skuSortDir, skuPage, skuTotalPages, paginatedSkuList, sortedSkuList,
  skuDateDetail, skuDetailOpen, skuDetailBarcode, skuDetailName,
  openSkuDetail, toggleSkuSort,
} = useSkuSummary({ skuSummary, skuDateIndex, custFilter, globalKw: debouncedKw, viewTab });

// 切工厂会整体换掉 SKU 列表，页码必须归位：停在第 2 页而新列表只有 1 页时，
// 分页控件（totalPages<=1 时隐藏）会消失，表格整片空白且无法退回。
watch(factory, () => { skuPage.value = 1; });

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

// 延期 / 临期风险汇总。原先在顶栏拆成「已延期」「临期≤3天」两格，与右栏风险清单
// 报的是同一件事 —— 现合并为一格「风险 N 天」，明细交给右栏清单与月历格子上的标记。
const risks = computed(() => {
  const now = new Date(); now.setHours(0, 0, 0, 0);
  const MS = 86400000;
  const r = { delayedCount: 0, delayedQty: 0, maxDays: 0, expiringCount: 0, expiringQty: 0 };
  for (const row of rows.value) {
    if (row._producedPct === 100 || row._pendingCount <= 0) continue;
    const diff = Math.round((new Date(row.date + 'T00:00:00').getTime() - now.getTime()) / MS);
    if (diff < 0) { r.delayedCount++; r.delayedQty += row.totalQty; r.maxDays = Math.max(r.maxDays, -diff); }
    else if (diff <= 3) { r.expiringCount++; r.expiringQty += row.totalQty; }
  }
  return r;
});

const riskDays = computed(() => risks.value.delayedCount + risks.value.expiringCount);
const riskQty = computed(() => risks.value.delayedQty + risks.value.expiringQty);

function exportSkuCSV() {
  const list = sortedSkuList.value;
  if (!list.length) { showToast('无数据', 'error'); return; }
  const h = buildCsvRow(['客户名称', '产品名称', '商品条码', '计划数量', '已生产', '待生产', '进度']);
  const ls = [h];
  for (const s of list) ls.push(buildCsvRow([s.customer_name, s.product_name, s.barcode, s.plan_qty, s.produced_qty, s.remain_qty, s._pct + '%']));
  downloadCsv(ls, `SKU月度统计_${y.value}年${m.value}月.csv`);
  showToast('导出成功', 'success');
}

function prevMonth() { m.value = m.value === 1 ? 12 : m.value - 1; if (m.value === 12) y.value--; }
function nextMonth() { m.value = m.value === 12 ? 1 : m.value + 1; if (m.value === 1) y.value++; }
function resetMonth() {
  const now = new Date();
  y.value = now.getFullYear();
  m.value = now.getMonth() + 1;
}
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

/* 头部两行：第一行「看哪个 Tab + 做什么」，第二行「看哪个月 + 这个月怎么样」。
   原先全部挤在一行，切月/搜索/导出/新建没有主次。 */
.sp-head {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.sp-head-row1 {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.sp-head-row2 {
  display: flex;
  align-items: stretch;
  gap: 16px;
  flex-wrap: wrap;
}

@media (max-width: 900px) {
  .sp-head-row2 {
    flex-direction: column;
    align-items: stretch;
  }
}

.sp-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  width: fit-content;
  flex-shrink: 0;
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
  white-space: nowrap;
}

.sp-tab:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}

.sp-tab-active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
</style>
