<template>
  <div class="sp-tab-group" role="tablist" aria-label="工厂筛选">
    <button
      v-for="opt in options"
      :key="opt.value"
      role="tab"
      :aria-selected="modelValue === opt.value"
      :class="['sp-tab', { 'sp-tab-active': modelValue === opt.value }]"
      :data-f="opt.value"
      :data-tone="factoryTone(opt.value)"
      @click="emit('update:modelValue', opt.value)"
    >
      <i class="sp-factory-dot" />
      {{ opt.label }}
      <span v-if="opt.count != null" class="sp-factory-cnt num">{{ fmt(opt.count) }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
// 工厂 Tab 组 —— 头部第一行左侧（视图 Tab 在其右），与「月份」同属「限定数据范围」的维度。
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

/** 东莞 → 湖北 → 其余（未标注等）按字典序 */
const options = computed(() =>
  orderFactories(props.factories).map(f => ({ value: f, label: f, count: props.totals[f] ?? 0 })),
);

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN');
}
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;

.sp-factory-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-slate-300, #cbd5e1);
  flex-shrink: 0;
}

/* 色点与选中态配色走 factoryTone 的色档（非状态色，避免与红/黄/绿语义冲突） */
.sp-tab[data-tone='dg'] .sp-factory-dot { background: var(--color-primary-500, #5b8def); }
.sp-tab[data-tone='hb'] .sp-factory-dot { background: var(--color-purple-500, #8b5cf6); }

.sp-tab-active[data-tone='dg'] { background: var(--color-primary-50, #eff5ff); color: var(--color-primary-700, #2d5ab8); }
.sp-tab-active[data-tone='hb'] { background: var(--color-purple-50, #f5f3ff); color: var(--color-purple-700, #6d28d9); }
.sp-tab-active[data-tone='other'] { background: var(--color-slate-100, #f1f5f9); color: var(--color-text-secondary, #475569); }

.sp-factory-cnt {
  font-size: 11px;
  font-weight: 700;
  opacity: 0.65;
}
</style>
