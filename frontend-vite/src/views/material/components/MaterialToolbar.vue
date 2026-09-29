<template>
  <div class="mr-toolbar">
    <div class="mr-title">
      <FontAwesomeIcon icon="truck" />
      <h1>来料进度</h1>
    </div>

    <div class="mr-search">
      <FontAwesomeIcon icon="search" class="mr-search-icon" />
      <input
        class="mr-search-input"
        :value="search"
        placeholder="搜订单号 / 客户 / 物料 / 供应商（当前页）"
        aria-label="搜索当前页来料进度"
        @input="emit('update:search', ($event.target as HTMLInputElement).value)"
        @keyup.enter="emit('search')"
      />
    </div>

    <div v-if="hasData" class="mr-kpi">
      <div class="kpi-item" title="部分到货的登记数">
        <div class="kpi-top"><span class="kpi-dot" style="background:#3a6bd6" /><span class="kpi-label">进行中登记</span></div>
        <span class="kpi-value">{{ fmt(stats.inProgress) }}</span>
      </div>
      <div class="kpi-item" title="尚无任何收货的登记数">
        <div class="kpi-top"><span class="kpi-dot" style="background:#9a6a00" /><span class="kpi-label">待收货登记</span></div>
        <span class="kpi-value">{{ fmt(stats.notStarted) }}</span>
      </div>
      <div class="kpi-item" title="登记超 30 天仍未收齐的物料数">
        <div class="kpi-top"><span class="kpi-dot" style="background:#d03b3b" /><span class="kpi-label">逾期物料</span></div>
        <span class="kpi-value" :class="{ 'kpi-danger': stats.overdueItems > 0 }">{{ fmt(stats.overdueItems) }}</span>
      </div>
      <div class="kpi-item" title="全部登记的已到货 / 采购总量">
        <div class="kpi-top"><span class="kpi-dot" style="background:#1e9e55" /><span class="kpi-label">总到货率</span></div>
        <span class="kpi-value">{{ stats.overallProgress }}%</span>
      </div>
    </div>

    <button v-if="canExport && hasData" class="mr-export-btn" aria-label="导出" @click="emit('export')">
      <FontAwesomeIcon icon="file-export" />导出
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * MaterialToolbar.vue — 来料进度单行工具条（方案A改版）
 *
 * 与 /stock 的 InventoryToolbar 同构：标题 · 搜索 · KPI · 导出一行收齐。
 * 纯受控组件（搜索词父级持有）；KPI 四格来自后端 stats 接口（父级传入），
 * 无数据时 KPI 与导出一并隐藏（一排 0 是噪音）。
 * 状态点色与 SupplierGroupCard 的四档一致（dataviz 校验档）。
 */
import type { ProgressStats } from '../composables/useMaterialRegistrations'

defineProps<{
  search: string
  stats: ProgressStats
  hasData: boolean
  canExport: boolean
}>()

const emit = defineEmits<{
  'update:search': [value: string]
  search: []
  export: []
}>()

/** 千分位（0 也显示，与 InventoryStatRow 口径一致） */
function fmt(n: number): string {
  return n.toLocaleString('en-US')
}
</script>

<style scoped lang="scss">
.mr-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 20px;
  min-height: 62px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  flex-shrink: 0;
  flex-wrap: wrap;
}
.mr-title { display: flex; align-items: center; gap: 9px; flex-shrink: 0; }
.mr-title svg { width: 18px; height: 18px; color: var(--color-primary-600, #3a6bd6); }
.mr-title h1 { font-size: 16px; font-weight: 700; color: var(--color-text, #1a1a2e); white-space: nowrap; }

.mr-search { position: relative; flex-shrink: 0; }
.mr-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); width: 13px; height: 13px; color: var(--color-text-muted, #64748b); pointer-events: none; }
.mr-search-input {
  width: 250px;
  padding: 7px 12px 7px 30px;
  font-size: 12.5px;
  font-family: inherit;
  border: 1.5px solid var(--color-border, #e4e7ed);
  border-radius: 9px;
  color: var(--color-text, #1a1a2e);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.mr-search-input::placeholder { color: var(--color-text-muted, #64748b); }
.mr-search-input:focus { border-color: var(--color-primary-500, #5b8def); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15); }

.mr-kpi { display: flex; align-items: center; margin-left: auto; flex-shrink: 0; }
.kpi-item { display: flex; flex-direction: column; gap: 1px; padding: 0 16px; cursor: default; }
.kpi-item + .kpi-item { border-left: 1px solid var(--color-border-light, #f0f2f5); }
.kpi-top { display: flex; align-items: center; gap: 5px; }
.kpi-dot { width: 6px; height: 6px; border-radius: 2px; flex-shrink: 0; }
.kpi-label { font-size: 11px; color: var(--color-text-secondary, #475569); font-weight: 500; white-space: nowrap; }
.kpi-value { font-size: 17px; font-weight: 700; color: var(--color-text, #1a1a2e); line-height: 1.2; white-space: nowrap; font-variant-numeric: tabular-nums; }
.kpi-value.kpi-danger { color: #d03b3b; }

.mr-export-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  color: var(--color-success-600, #1e9e55);
  background: white;
  border: 1.5px solid var(--color-success-200, #a6e8c0);
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  flex-shrink: 0;
}
.mr-export-btn:hover { background: var(--color-success-50, #e8f9ef); border-color: var(--color-success-500, #28c76f); }

@media (max-width: 1100px) {
  .mr-kpi { margin-left: 0; }
}
</style>
