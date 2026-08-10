<template>
  <div :class="['m-skeleton', variant]">
    <!-- Dashboard -->
    <template v-if="variant === 'dashboard'">
      <div class="m-sk-dash-header">
        <div class="m-sk-line m-sk-line--sm" />
        <div class="m-sk-line m-sk-line--lg" />
      </div>
      <div class="m-sk-dash-grid">
        <div v-for="i in 4" :key="i" class="m-sk-stat-card">
          <div class="m-sk-box m-sk-box--sm" />
          <div class="m-sk-line m-sk-line--md" />
        </div>
      </div>
      <div class="m-sk-dash-grid m-sk-dash-grid--cols4">
        <div v-for="i in 4" :key="i" class="m-sk-quick-item">
          <div class="m-sk-box m-sk-box--md" />
          <div class="m-sk-line m-sk-line--xs" />
        </div>
      </div>
    </template>

    <!-- List -->
    <template v-else-if="variant === 'list'">
      <div v-for="i in count" :key="i" class="m-sk-list-item">
        <div class="m-sk-list-left">
          <div class="m-sk-box m-sk-box--sm" />
          <div class="m-sk-list-text">
            <div class="m-sk-line m-sk-line--md" />
            <div class="m-sk-line m-sk-line--sm" />
          </div>
        </div>
        <div class="m-sk-chevron" />
      </div>
    </template>

    <!-- Report -->
    <template v-else>
      <div class="m-sk-report-header">
        <div class="m-sk-line m-sk-line--lg" />
        <div class="m-sk-line m-sk-line--sm" />
      </div>
      <div class="m-sk-chart-area">
        <div class="m-sk-chart-bar" v-for="i in 6" :key="i" :style="{ height: 20 + Math.random() * 50 + '%' }" />
      </div>
      <div class="m-sk-report-rows">
        <div v-for="i in 3" :key="i" class="m-sk-line m-sk-line--full" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'dashboard' | 'list' | 'report'
  count?: number
}>(), {
  variant: 'list',
  count: 5,
})
</script>

<style scoped>
.m-skeleton {
  padding: var(--m-gap-md);
}

/* Shimmer base */
.m-sk-line,
.m-sk-box {
  background: linear-gradient(90deg, var(--m-skeleton-base) 25%, var(--m-skeleton-shine) 50%, var(--m-skeleton-base) 75%);
  background-size: 200% 100%;
  animation: m-shimmer 1.8s ease-in-out infinite;
  border-radius: 6px;
}

.m-sk-line--lg { width: 60%; height: 20px; }
.m-sk-line--md { width: 40%; height: 14px; }
.m-sk-line--sm { width: 55%; height: 12px; }
.m-sk-line--xs { width: 80%; height: 10px; }
.m-sk-line--full { width: 100%; height: 14px; }

.m-sk-box--sm { width: 36px; height: 36px; border-radius: 10px; }
.m-sk-box--md { width: 44px; height: 44px; border-radius: 12px; }

/* Dashboard */
.m-sk-dash-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 20px;
  padding-top: var(--m-safe-top);
}

.m-sk-dash-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 20px;
}
.m-sk-dash-grid--cols4 {
  grid-template-columns: repeat(4, 1fr);
}

.m-sk-stat-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  background: var(--m-bg-surface);
  border-radius: var(--m-radius-card);
}

.m-sk-quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 12px 8px;
}

/* List */
.m-sk-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: var(--m-border-subtle);
}

.m-sk-list-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.m-sk-list-text {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.m-sk-chevron {
  width: 8px;
  height: 8px;
  border-top: 2px solid var(--m-skeleton-base);
  border-right: 2px solid var(--m-skeleton-base);
  transform: rotate(45deg);
}

/* Report */
.m-sk-report-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.m-sk-chart-area {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 120px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--m-bg-surface);
  border-radius: var(--m-radius-card);
}

.m-sk-chart-bar {
  flex: 1;
  background: linear-gradient(180deg, var(--m-skeleton-base), var(--m-skeleton-shine));
  border-radius: 4px 4px 0 0;
  animation: m-shimmer 1.8s ease-in-out infinite;
  background-size: 200% 100%;
}

.m-sk-report-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
