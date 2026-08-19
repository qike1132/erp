<template>
  <div class="coq-toolbar">
    <div class="coq-toolbar-left">
      <h2 class="coq-title">下单查询</h2>
      <span v-if="total > 0" class="coq-count">{{ total }}</span>
    </div>
    <div class="coq-toolbar-right">
      <button class="coq-btn coq-btn-ghost" @click="$emit('toggleFilter')" :aria-label="filterExpanded ? '收起' : '高级'">
        <FontAwesomeIcon icon="sliders-h" aria-hidden="true" />
        <span>{{ filterExpanded ? '收起' : '高级' }}</span>
      </button>
      <button class="coq-btn coq-btn-primary" @click="$emit('export')" aria-label="导出">
        <FontAwesomeIcon icon="file-export" aria-hidden="true" />
        <span>导出</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  total: number
  filterExpanded: boolean
}>()

defineEmits<{
  toggleFilter: []
  export: []
}>()
</script>

<style scoped>
.coq-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px 12px;
}

.coq-toolbar-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.coq-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--coq-text);
  letter-spacing: -0.01em;
}

.coq-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--coq-slate);
  font-variant-numeric: tabular-nums;
}

.coq-count::before {
  content: '·';
  margin-right: 6px;
  color: var(--coq-border);
}

.coq-toolbar-right {
  display: flex;
  gap: 8px;
  align-items: center;
}

.coq-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--coq-bg);
  color: var(--coq-text-secondary);
  white-space: nowrap;
  font-family: inherit;
  line-height: 1.4;
}

.coq-btn i {
  font-size: 11px;
}

.coq-btn:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
  background: var(--coq-blue-light);
}

.coq-btn-ghost {
  border-color: transparent;
  background: transparent;
}

.coq-btn-ghost:hover {
  border-color: var(--coq-border);
  background: var(--coq-bg-soft);
}

.coq-btn-primary {
  background: var(--coq-navy);
  border-color: var(--coq-navy);
  color: #fff;
}

.coq-btn-primary:hover {
  background: var(--coq-navy-deep);
  border-color: var(--coq-navy-deep);
  color: #fff;
}
</style>