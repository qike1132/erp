<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <PurchasePlanHeader
          v-model:factory="factory"
          v-model:global-kw="globalKw"
          :y="y"
          :m="m"
          :factories="availableFactories"
          :factory-totals="factoryTotals"
          :kpi="kpi"
          :can-manage="canManage"
          @prev="prevMonth"
          @next="nextMonth"
          @export="exportCSV"
          @create="showCreate = true"
        />
      </div>

      <!-- Z02-R6：库存映射降级时空值会伪装成「没货」，必须在数字旁边说明，而不是让用户自己发现 -->
      <div v-if="inventoryDegraded" class="pp-degraded" role="alert">
        本次库存数据获取超时，下方「库存 / 缺口」数字不可信（显示为 0 不代表真的没货），请稍后重试。
      </div>

      <!-- 审计 #4：生产进度分配降级时后端返回全 0，0 会被当成「一件都没生产」的真值 -->
      <div v-if="fifoDegraded" class="pp-degraded pp-fifo-degraded" role="alert">
        本次生产进度分配失败，下方「已生产 / 待生产」显示为 0 不代表真的没生产，请稍后重试。
      </div>

      <!-- 方案B（2026-11-28 owner 拍板）：单视图合并原「排产日历/月度汇总」两 Tab ——
           月维度看客户 chips + SKU 月度统计，日维度看月历格子与当日明细主区。 -->
      <PurchasePlanBoard
        v-model:sel="sel"
        v-model:cust-filter="custFilter"
        v-model:sku-page="skuPage"
        :y="y"
        :m="m"
        :factory="factory"
        :is-loading="isLoading"
        :is-error="isError"
        :is-fetching="isFetching"
        :rows="rows"
        :filtered="filtered"
        :sku-date-index="skuDateIndex"
        :customers="allCustomers"
        :risk-items="riskItems"
        :sorted-sku-list="sortedSkuList"
        :paginated-sku-list="paginatedSkuList"
        :sku-total-pages="skuTotalPages"
        :sku-sort-field="skuSortField"
        :sku-sort-dir="skuSortDir"
        @refetch="refetch"
        @toggle-sku-sort="toggleSkuSort"
        @open-sku-detail="openSkuDetail"
        @export-sku="exportSkuCSV"
      />

      <SkuDetailDialog v-model:open="skuDetailOpen" :barcode="skuDetailBarcode" :name="skuDetailName" :date-detail="skuDateDetail" />
    </div>
  </div>

  <CreateShipmentPlanDialog
    v-model:open="showCreate"
    :can-manage="canManage"
    @created="onCreated"
    @succeeded="refreshPlans"
    @imported="onImported"
  />
</template>

<script setup lang="ts">
import { ref, computed, watch, defineAsyncComponent } from 'vue';
import { useQueryClient } from '@tanstack/vue-query';
import { useDebounceFn } from '@vueuse/core';
import { showToast } from '@/composables/useToast';
import { useExport } from '@/composables/useExport';
import { downloadCsv, buildCsvRow } from '@/utils/csv';
import PurchasePlanHeader from './components/PurchasePlanHeader.vue';
import PurchasePlanBoard from './components/PurchasePlanBoard.vue';
import { usePurchasePlanData } from './composables/usePurchasePlanData';
import { useSkuSummary } from './composables/useSkuSummary';
import { useAuthStore } from '@/stores/auth';
import { useFactorySplit, type FactoryFilter } from './composables/useFactorySplit';
import { useDefaultTodaySelection } from './composables/useDefaultTodaySelection';
import { daysFromToday, startOfToday } from './components/dayStatus';
import type { CustSumItem, RiskItem, Row } from './components/types';

// 弹窗组件懒加载，减少首屏 chunk 体积（仅在用户交互时才加载）
const CreateShipmentPlanDialog = defineAsyncComponent(() => import('./components/CreateShipmentPlanDialog.vue'));
const SkuDetailDialog = defineAsyncComponent(() => import('./components/SkuDetailDialog.vue'));

const qc = useQueryClient();

const authStore = useAuthStore();
/** 新建/导入/模板下载后端都要求 production_plan_manage：只读用户不该看到入口后白填一遍 */
const canManage = computed(() => authStore.hasPermission('production_plan_manage'));

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
const custFilter = ref('');
// 工厂筛选（作用于整页）：默认东莞，当月无东莞数据时回落到当月首个工厂
const factory = ref<FactoryFilter>('东莞');

watch(globalKw, () => { sel.value = ''; });
watch([y, m], () => { globalKw.value = ''; debouncedKw.value = ''; });
// 切工厂后，原来选中的客户可能在新工厂下无数据，清掉避免空白页
// （选中的日期交给 useDefaultTodaySelection 决定，不再这里清）
watch(factory, () => { custFilter.value = ''; });

const {
  isLoading, isFetching, isError, refetch,
  rows: rawRows, skuSummary: rawSkuSummary, skuDateIndex: rawSkuDateIndex, customers: rawCustomers,
  inventoryDegraded, fifoDegraded,
} = usePurchasePlanData(y, m);

// 工厂维度拆分：一次性拿到整月聚合后本地切换，切换零延迟（见 useFactorySplit）。
// 下游的 rows / skuSummary / skuDateIndex / customers 全部是「已按工厂过滤」的视图。
const { rows, skuSummary, skuDateIndex, customers, availableFactories, factoryTotals } = useFactorySplit({
  factory,
  rows: rawRows,
  skuSummary: rawSkuSummary,
  skuDateIndex: rawSkuDateIndex,
  customers: rawCustomers,
});

// 默认选中今天：数据到达 / 换月 / 换工厂时把 sel 落到今天（若今天在本月且有排产），
// 省去用户手点一天才能看到日明细；用户手动改选后本次上下文不再覆盖（见 composable）。
useDefaultTodaySelection({ y, m, factory, rows, sel });

// 切月后若该工厂当月已无计划，回落到当月首个工厂——否则控件不再渲染该厂药丸，
// 会出现「没有任何药丸处于选中态、页面却是空的」的困惑状态。
watch(availableFactories, (list) => {
  if (!list.includes(factory.value)) factory.value = list[0] ?? '';
});

const allCustomers = computed<CustSumItem[]>(() => {
  return [...customers.value].sort((a, b) => b.remaining_qty - a.remaining_qty);
});

// 使用防抖后的搜索值，避免每次按键触发全量过滤（月历淡化未命中日 + SKU 表过滤同源）
const filtered = computed(() => {
  if (!debouncedKw.value) return rows.value;
  const k = debouncedKw.value.toLowerCase();
  return rows.value.filter(r => r.date.includes(k) || r.customerNames.some(n => n.toLowerCase().includes(k)));
});

// 风险汇总：延期 / 临期(≤3天)且尚未出完。信息条给天数，明细交给月历下方风险条与格子标记。
const TODAY_MS = startOfToday();
const riskItems = computed<RiskItem[]>(() => {
  const list: RiskItem[] = [];
  for (const r of rows.value) {
    if (r._producedPct === 100 || r._pendingCount <= 0) continue;
    const diff = daysFromToday(r.date, TODAY_MS);
    if (diff < 0) {
      list.push({ date: r.date, qty: r.totalQty, cust: r.customerNames[0] ?? '', kind: 'overdue', lbl: '延期 ' + Math.abs(diff) + '天' });
    } else if (diff <= 3) {
      list.push({ date: r.date, qty: r.totalQty, cust: r.customerNames[0] ?? '', kind: 'due', lbl: diff === 0 ? '今日出货' : '临期 ' + diff + '天' });
    }
  }
  list.sort((a, b) => daysFromToday(a.date, TODAY_MS) - daysFromToday(b.date, TODAY_MS));
  return list;
});

const planQtyNum = computed(() => allCustomers.value.reduce((n, c) => n + Number(c.plan_qty || 0), 0));

// 打包一行信息条所需值（方案B 口径：计划 / 客户 / SKU / 峰值日 / 风险，全部数量口径）。
const kpi = computed(() => {
  const peak = rows.value.reduce<Row | null>((acc, r) => (!acc || r.totalQty > acc.totalQty ? r : acc), null);
  return {
    planQty: planQtyNum.value,
    planDays: rows.value.length,
    custN: allCustomers.value.length,
    skuN: new Set(skuSummary.value.map(s => s.product_name)).size,
    peakDay: peak ? Number(peak.date.slice(8)) : 0,
    peakQty: peak ? peak.totalQty : 0,
    riskDays: riskItems.value.length,
    riskOverdue: riskItems.value.filter(i => i.kind === 'overdue').length,
    riskExpiring: riskItems.value.filter(i => i.kind === 'due').length,
    riskQty: riskItems.value.reduce((n, i) => n + i.qty, 0),
  };
});

const {
  skuSortField, skuSortDir, skuPage, skuTotalPages, paginatedSkuList, sortedSkuList,
  skuDateDetail, skuDetailOpen, skuDetailBarcode, skuDetailName,
  openSkuDetail, toggleSkuSort,
} = useSkuSummary({ skuSummary, skuDateIndex, custFilter, globalKw: debouncedKw });

// 切工厂会整体换掉 SKU 列表，页码必须归位：停在第 2 页而新列表只有 1 页时，
// 分页控件（totalPages<=1 时隐藏）会消失，表格整片空白且无法退回。
watch(factory, () => { skuPage.value = 1; });

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
function onCreated() { showCreate.value = false; refreshPlans(); }
/** 部分成功：只刷新列表，不关闭对话框（H6：失败草稿要留在表单里可重试）。 */
function refreshPlans() { qc.invalidateQueries({ queryKey: ['pp-agg'] }); }

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
.sp-container {
  height: 100%;
  padding: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.pp-degraded {
  padding: 8px 16px;
  background: var(--color-warning-50);
  color: var(--color-warning-700);
  font-size: var(--fs-caption);
  font-weight: 600;
}
</style>
