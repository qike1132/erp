<template>
  <div class="sp-factory-box">
    <span class="sp-factory-label">工厂</span>
    <div class="sp-factory-seg" role="tablist" aria-label="工厂筛选">
      <button
        v-for="opt in options"
        :key="opt.value"
        role="tab"
        :aria-selected="modelValue === opt.value"
        :class="['sp-factory-pill', { 'is-active': modelValue === opt.value }]"
        :data-f="opt.value"
        :data-tone="factoryTone(opt.value)"
        @click="emit('update:modelValue', opt.value)"
      >
        <i v-if="opt.value !== 'all'" class="sp-factory-dot" />
        {{ opt.label }}
        <span v-if="opt.count != null" class="sp-factory-cnt num">{{ fmt(opt.count) }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
// 工厂分段控件 —— 与「月份」同属「限定数据范围」的维度，故并排在第二行。
// 切换后整页（KPI / 日历 / 当日明细 / SKU 表）跟着收敛到所选工厂。
import { computed } from 'vue';
import { orderFactories, factoryTone } from './factoryMeta';

const props = defineProps<{
  modelValue: string;
  /** 当月实际出现过的工厂名（东莞/湖北/未标注…） */
  factories: string[];
  /** 各工厂当月计划总量，用于角标 */
  totals: Record<string, number>;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
}>();

/** 全部 → 东莞 → 湖北 → 其余（未标注等）按字典序 */
const options = computed(() => {
  const total = Object.values(props.totals).reduce((a, b) => a + b, 0);
  return [
    { value: 'all', label: '全部', count: total },
    ...orderFactories(props.factories).map(f => ({ value: f, label: f, count: props.totals[f] ?? 0 })),
  ];
});

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN');
}
</script>

<style scoped lang="scss">
.sp-factory-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-md, 14px);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  padding: 0 12px;
  flex-shrink: 0;
}

.sp-factory-label {
  font-size: 12px;
  font-weight: 800;
  color: var(--color-text-muted, #64748b);
  white-space: nowrap;
}

.sp-factory-seg {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  background: var(--color-slate-100, #f1f5f9);
  border-radius: 10px;
}

.sp-factory-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 13px;
  border: none;
  border-radius: 8px;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s ease, color 0.2s ease;
}

.sp-factory-pill:hover {
  color: var(--color-primary-600);
}

.sp-factory-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-slate-300, #cbd5e1);
  flex-shrink: 0;
}

/* 色点与选中态配色走 factoryTone 的色档（非状态色，避免与红/黄/绿语义冲突） */
.sp-factory-pill[data-tone='dg'] .sp-factory-dot { background: var(--color-primary-500, #5b8def); }
.sp-factory-pill[data-tone='hb'] .sp-factory-dot { background: var(--color-purple-500, #8b5cf6); }

.sp-factory-pill.is-active {
  background: white;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.10);
  color: var(--color-primary-700, #2d5ab8);
}

.sp-factory-pill.is-active[data-tone='hb'] { color: var(--color-purple-700, #6d28d9); }

.sp-factory-cnt {
  font-size: 11px;
  font-weight: 700;
  opacity: 0.65;
}

@media (max-width: 900px) {
  .sp-factory-box {
    width: 100%;
    overflow-x: auto;
  }
}
</style>
