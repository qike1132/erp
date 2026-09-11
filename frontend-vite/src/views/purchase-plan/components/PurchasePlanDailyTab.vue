<template>
  <div class="sp-body">
    <div v-if="isLoading" class="sp-empty"><UiSpinner /></div>
    <div v-else-if="isError" class="sp-empty"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />加载失败 <button class="sp-retry-btn" aria-label="重试" @click="emit('refetch')">重试</button></div>
    <div v-else-if="!rows.length" class="sp-empty"><FontAwesomeIcon icon="inbox" aria-hidden="true" />本月暂无出货计划</div>
    <template v-else>
      <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>

      <div class="sp-cal-layout">
        <!-- 左：排产日历矩阵 -->
        <div class="sp-panel sp-cal-panel">
          <div class="sp-panel-head">
            <span>{{ m }} 月排产日历</span>
            <span class="xs">红=延期 · 琥珀=临期 · 绿=已完成</span>
          </div>
          <div class="sp-cal">
            <div class="sp-dow"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
            <div class="sp-grid">
              <div
                v-for="c in cells"
                :key="c.key"
                class="sp-cell"
                :class="cellClass(c)"
                @click="chooseCell(c)"
              >
                <template v-if="c.day">
                  <span class="d num">{{ c.day }}</span>
                  <template v-if="c.row && c.match">
                    <span v-if="c.status" class="st" :class="c.status.cls">{{ c.status.lbl }}</span>
                    <span class="q num">{{ c.row.totalQty }}<small>件</small></span>
                  </template>
                </template>
              </div>
            </div>
          </div>
          <div v-if="isSearching" class="sp-search-hint">搜索命中 {{ matchedDates.size }} 个排产日</div>
          <div class="sp-legend">
            <span><i class="lg-blank" />无计划</span>
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
// 每日计划 Tab —— 排产日历矩阵 + 右侧风险/客户栏（v5 方案）
import { computed } from 'vue';
import type { Row, CustSumItem } from './types';

const props = defineProps<{
  y: number;
  m: number;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  rows: Row[];
  filtered: Row[];
  customers: CustSumItem[];
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

type CellStatus = { cls: string; lbl: string } | null;

// 日历格子：从 rows 构建某月全部日期，按 7 列（周一开头）排列，状态信息并入格子一次算好
const cells = computed(() => {
  const firstDow = new Date(props.y, props.m - 1, 1).getDay();
  const lead = (firstDow + 6) % 7; // 0=周一开头
  const dim = new Date(props.y, props.m, 0).getDate();
  const byDate = new Map(props.rows.map(r => [r.date, r]));
  const arr: { key: string; day: number | null; row: Row | null; match: boolean; status: CellStatus }[] = [];
  for (let i = 0; i < lead; i++) arr.push({ key: 'lead-' + i, day: null, row: null, match: false, status: null });
  for (let d = 1; d <= dim; d++) {
    const iso = `${props.y}-${String(props.m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const row = byDate.get(iso) ?? null;
    arr.push({ key: iso, day: d, row, match: true, status: row ? statusFor(row) : null });
  }
  while (arr.length % 7 !== 0) arr.push({ key: 'trail-' + arr.length, day: null, row: null, match: false, status: null });
  return arr;
});

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

function cellClass(c: { day: number | null; row: Row | null; match: boolean; status: CellStatus }): string[] {
  const cls = ['sp-cell'];
  if (!c.day) return cls;
  if (isSearching.value && !c.match) { cls.push('sp-cell-blank'); return cls; }
  if (c.status === null) { cls.push('sp-cell-blank'); return cls; }
  cls.push('sp-cell-live');
  if (c.status.cls === 'st-r') cls.push('sp-cell-danger');
  else if (c.status.cls === 'st-a') cls.push('sp-cell-due');
  else cls.push('sp-cell-done');
  if (c.row && props.sel === c.row.date) cls.push('sp-cell-selected');
  return cls;
}

function chooseCell(c: { day: number | null; row: Row | null }): void {
  if (!c.row) return;
  selectDate(c.row.date);
}

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

/* 日历 */
.sp-cal { padding: 16px 18px; }
.sp-dow {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}
.sp-dow span {
  font-size: 12px;
  color: var(--color-muted, #8c96ad);
  text-align: center;
  font-weight: 600;
}
.sp-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
}
.sp-cell {
  min-height: 78px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  padding: 6px 8px;
  background: white;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
  cursor: default;
}
.sp-cell:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.06); }
.sp-cell-blank { background: #fafbfe; }
.sp-cell .d { font-size: 12px; color: var(--color-text-2, #5a6b8c); font-weight: 600; }
.sp-cell .q { font-size: 18px; font-weight: 800; color: var(--color-heading); margin-top: auto; line-height: 1; }
.sp-cell .q small { font-size: 10px; color: var(--color-muted, #8c96ad); font-weight: 600; }
.sp-cell .st {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 5px;
  width: fit-content;
}
.st-r { background: var(--color-danger-100); color: var(--color-danger-700); }
.st-a { background: var(--color-warning-100); color: var(--color-warning-700); }
.st-g { background: var(--color-success-100); color: var(--color-success-700); }

.sp-cell-live { cursor: pointer; }
.sp-cell-danger {
  border: 1.5px solid var(--color-danger-500);
  background: linear-gradient(180deg, #fff, var(--color-danger-100));
}
.sp-cell-due {
  border: 1.5px solid var(--color-warning-500);
  background: linear-gradient(180deg, #fff, var(--color-warning-100));
}
.sp-cell-done {
  border: 1.5px solid var(--color-success-500);
  background: linear-gradient(180deg, #fff, var(--color-success-100));
}
.sp-cell-selected {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
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
.lg-blank { background: #fafbfe; border: 1px solid var(--color-border-light, #e2e8f0); }
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