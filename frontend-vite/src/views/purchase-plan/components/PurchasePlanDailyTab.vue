<template>
  <div class="sp-body">
    <div v-if="isLoading" class="sp-empty"><UiSpinner /></div>
    <div v-else-if="isError" class="sp-empty"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />加载失败 <button class="sp-retry-btn" aria-label="重试" @click="emit('refetch')">重试</button></div>
    <div v-else-if="!rows.length" class="sp-empty"><FontAwesomeIcon icon="inbox" aria-hidden="true" />本月暂无出货计划</div>
    <template v-else>
      <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>

      <div class="sp-cal-layout">
        <!-- 左：排产日历 -->
        <div class="sp-panel sp-cal-panel">
          <div class="sp-panel-head">
            <span>{{ m }} 月排产日历</span>
            <span class="xs">红=延期 · 琥珀=临期 · 绿=已完成</span>
          </div>
          <div class="sp-cal">
            <div class="sp-day-grid">
              <PlanDayCard
                v-for="c in dayCards"
                :key="c.date"
                :card="c"
                :sel="sel"
                @select="selectDate"
              />
            </div>
          </div>
          <div v-if="isSearching" class="sp-search-hint">搜索命中 {{ matchedDates.size }} 个排产日</div>
          <div class="sp-legend">
            <span><i class="lg-r" />延期</span>
            <span><i class="lg-a" />临期≤3天</span>
            <span><i class="lg-g" />已完成</span>
          </div>
        </div>

        <!-- 右：风险预警 + 客户分布 -->
        <div class="sp-side">
          <div class="sp-panel">
            <div class="sp-panel-head">风险预警</div>
            <div v-if="!riskItems.length" class="sp-panel-empty">本月暂无待处理风险</div>
            <div v-else class="sp-rlist">
              <div v-for="it in riskItems" :key="it.date" class="sp-rcard" @click="selectDate(it.date)">
                <div>
                  <div class="dt num">{{ it.date.slice(5).replace('-', '/') }} · {{ it.qty }}件</div>
                  <div class="cust">{{ it.cust }}</div>
                </div>
                <span class="rtag" :class="it.kind === 'overdue' ? 'rtag-r' : 'rtag-a'">{{ it.lbl }}</span>
              </div>
            </div>
          </div>

          <div class="sp-panel">
            <div class="sp-panel-head">客户出货分布</div>
            <div v-if="!distRows.length" class="sp-panel-empty">暂无数据</div>
            <div v-else class="sp-dist">
              <div v-for="row in distRows" :key="row.name" class="dist-row">
                <span class="nm" :title="row.name">{{ row.name }}</span>
                <div class="tk"><i :class="row.top ? 'tk-primary' : 'tk-weak'" :style="{ width: row.w + '%' }" /></div>
                <span class="pc num">{{ row.w }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// 每日计划 Tab —— 排产日历卡片 + 右侧风险/客户栏（v5 方案）
// 仅渲染有计划的日子：每天一张卡片，卡片内逐行列「客户 / 产品 / 数量」。
import { computed } from 'vue';
import PlanDayCard from './PlanDayCard.vue';
import type { Row, CustSumItem, SkuDateItem, DayCardStatus } from './types';

const props = defineProps<{
  y: number;
  m: number;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  rows: Row[];
  filtered: Row[];
  customers: CustSumItem[];
  skuDateIndex: Record<string, SkuDateItem[]>;
  sel: string;
}>();

const emit = defineEmits<{
  'update:sel': [value: string];
  refetch: [];
}>();

const TODAY = new Date();
TODAY.setHours(0, 0, 0, 0);
const DAY_MS = 86400000;

function getDaysDiff(dateStr: string): number {
  return Math.round((new Date(dateStr + 'T00:00:00').getTime() - TODAY.getTime()) / DAY_MS);
}

type CellStatus = DayCardStatus;

const matchedDates = computed(() => new Set(props.filtered.map(r => r.date)));
const isSearching = computed(() => props.filtered.length > 0 && props.filtered.length < props.rows.length);

function statusFor(row: Row): CellStatus {
  if (row._shippedPct === 100) return { cls: 'st-g', lbl: '✓ 完成' };
  if (row._pendingCount <= 0) return null;
  const diff = getDaysDiff(row.date);
  if (diff < 0) return { cls: 'st-r', lbl: '延期 ' + Math.abs(diff) + '天' };
  if (diff === 0) return { cls: 'st-r', lbl: '今日出货' };
  if (diff <= 3) return { cls: 'st-a', lbl: '临期 ' + diff + '天' };
  return null;
}

// sku_date_index 的键为「客户|产品」，此处按日期反转成 日期 → 明细行 的索引
const itemsByDate = computed(() => {
  const map = new Map<string, { customer: string; product: string; qty: number }[]>();
  for (const [key, entries] of Object.entries(props.skuDateIndex ?? {})) {
    const sep = key.indexOf('|');
    const customer = sep < 0 ? key : key.slice(0, sep);
    const product = sep < 0 ? '' : key.slice(sep + 1);
    for (const e of entries) {
      const list = map.get(e.date);
      if (list) list.push({ customer, product, qty: e.qty });
      else map.set(e.date, [{ customer, product, qty: e.qty }]);
    }
  }
  for (const list of map.values()) list.sort((a, b) => b.qty - a.qty);
  return map;
});

// 每天一张卡片：只保留有计划的日期，无计划的日期不渲染
// 计划条数可能很多，卡片内只预览前 PREVIEW_LIMIT 条，其余折叠为「还有 N 条」
const PREVIEW_LIMIT = 3;
const dayCards = computed(() =>
  props.rows.map(row => {
    const all = itemsByDate.value.get(row.date) ?? [];
    return {
      date: row.date,
      label: `${row._fullDate} 周${row._weekday}`,
      match: !isSearching.value || matchedDates.value.has(row.date),
      status: statusFor(row),
      items: all.slice(0, PREVIEW_LIMIT),
      extra: Math.max(0, all.length - PREVIEW_LIMIT),
      planCount: all.length,
      totalQty: row.totalQty,
      customerCount: row.customerCount,
    };
  }),
);

function selectDate(date: string): void {
  emit('update:sel', props.sel === date ? '' : date);
}

// 风险条目：延期或临期(≤3天)且未完成
const riskItems = computed(() => {
  const list: { date: string; qty: number; cust: string; kind: 'overdue' | 'due'; lbl: string }[] = [];
  for (const r of props.rows) {
    if (r._shippedPct === 100 || r._pendingCount <= 0) continue;
    const diff = getDaysDiff(r.date);
    if (diff < 0) list.push({ date: r.date, qty: r.totalQty, cust: r.customerNames[0] ?? '', kind: 'overdue', lbl: '延期 ' + Math.abs(diff) + '天' });
    else if (diff <= 3) list.push({ date: r.date, qty: r.totalQty, cust: r.customerNames[0] ?? '', kind: 'due', lbl: diff === 0 ? '今日出货' : '临期 ' + diff + '天' });
  }
  list.sort((a, b) => getDaysDiff(a.date) - getDaysDiff(b.date));
  return list;
});

// 客户出货分布（按计划量占比）
const distRows = computed(() => {
  const list = props.customers;
  const max = Math.max(0, ...list.map(c => Number(c.plan_qty || 0)));
  return list.slice(0, 5).map((c, i) => ({
    name: c.customer_name,
    w: max > 0 ? Math.round(Number(c.plan_qty || 0) / max * 100) : 0,
    top: i === 0,
  }));
});
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;
.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-cal-layout {
  display: grid;
  grid-template-columns: 1fr 344px;
  gap: 16px;
  align-items: start;
}

@media (max-width: 960px) {
  .sp-cal-layout {
    grid-template-columns: 1fr;
  }
}

.sp-panel {
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}

.sp-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 18px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
}
.sp-panel-head .xs {
  font-size: 12px;
  color: var(--color-text-3, var(--color-muted, #8c96ad));
  font-weight: 500;
}

/* 排产日历：仅计划日卡片（卡片自身样式见 PlanDayCard.vue） */
.sp-cal { padding: 16px 18px; }
.sp-day-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.sp-search-hint { padding: 6px 18px; font-size: 12px; color: var(--color-primary-600); }
.sp-legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 18px 14px;
  font-size: 12px;
  color: var(--color-muted, #8c96ad);
}
.sp-legend span { display: inline-flex; align-items: center; gap: 6px; }
.sp-legend i { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.lg-r { background: var(--color-danger-100); }
.lg-a { background: var(--color-warning-100); }
.lg-g { background: var(--color-success-100); }

/* 右侧 */
.sp-side { display: flex; flex-direction: column; gap: 16px; }
.sp-panel-empty { padding: 22px 18px; font-size: 13px; color: var(--color-muted, #8c96ad); text-align: center; }

.sp-rlist { padding: 2px 12px; }
.sp-rcard {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 6px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  cursor: pointer;
}
.sp-rcard:last-child { border-bottom: none; }
.sp-rcard:hover { background: var(--color-primary-50); }
.sp-rcard .dt { font-size: 13px; font-weight: 800; color: var(--color-heading); }
.sp-rcard .cust { font-size: 12px; color: var(--color-text-2, #5a6b8c); margin-top: 2px; }
.rtag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  margin-left: auto;
  white-space: nowrap;
}
.rtag-r { background: var(--color-danger-100); color: var(--color-danger-700); }
.rtag-a { background: var(--color-warning-100); color: var(--color-warning-700); }

.sp-dist { padding: 12px 18px 14px; }
.dist-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.dist-row .nm { font-size: 12px; color: var(--color-text-2, #5a6b8c); width: 88px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dist-row .tk { flex: 1; height: 8px; background: #edf0f6; border-radius: 4px; overflow: hidden; }
.dist-row .tk > i { display: block; height: 100%; border-radius: 4px; }
.tk-primary { background: var(--color-primary-500); }
.tk-weak { background: #c4d0e8; }
.dist-row .pc { font-size: 12px; color: var(--color-muted, #8c96ad); width: 40px; text-align: right; }
</style>
