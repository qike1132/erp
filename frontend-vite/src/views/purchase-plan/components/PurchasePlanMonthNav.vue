<template>
  <div class="sp-nav">
    <button class="sp-nav-btn" aria-label="上一月" @click="emit('prev')">
      <FontAwesomeIcon icon="chevron-left" aria-hidden="true" />
    </button>
    <span class="sp-nav-lbl">{{ y }}年{{ String(m).padStart(2, '0') }}月</span>
    <button class="sp-nav-btn" aria-label="下一月" @click="emit('next')">
      <FontAwesomeIcon icon="chevron-right" aria-hidden="true" />
    </button>
  </div>
</template>

<script setup lang="ts">
// 月份导航 —— 从 PurchasePlanToolbar 抽出，与搜索/导出/新建分开成两行：
// 切换月份作用于整个页面（KPI 与两个 Tab 都跟着变），属于「上下文」而非「操作」。

defineProps<{
  y: number
  m: number
}>()

const emit = defineEmits<{
  prev: []
  next: []
}>()
</script>

<style scoped lang="scss">
.sp-nav {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 3px;
  border-radius: var(--radius-input, 12px);
  border: 1.5px solid var(--color-border-light, #e2e8f0);
  background: white;
}

.sp-nav-btn {
  width: 30px;
  height: 28px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
  flex-shrink: 0;
}

.sp-nav-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.sp-nav-lbl {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-heading);
  min-width: 96px;
  text-align: center;
  user-select: none;
  font-variant-numeric: tabular-nums;
}


</style>
