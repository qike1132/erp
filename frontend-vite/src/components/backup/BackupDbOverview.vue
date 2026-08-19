<template>
  <div class="bk-section">
    <div class="bk-section-label">数据库概览</div>
    <div v-if="loading" class="bk-loading-inline"><UiSpinner /></div>
    <div v-else-if="tables.length" class="bk-table-stats">
      <div class="bk-stat-item">
        <div class="bk-stat-val">{{ tables.length }}</div>
        <div class="bk-stat-lb">数据表</div>
      </div>
      <div class="bk-stat-item">
        <div class="bk-stat-val">{{ totalRows }}</div>
        <div class="bk-stat-lb">总记录数</div>
      </div>
    </div>
    <div v-if="tables.length" class="bk-table-list">
      <div v-for="t in tables" :key="t.name" class="bk-table-row">
        <span class="bk-table-name">{{ t.name }}</span>
        <span class="bk-table-count">{{ t.rows >= 0 ? t.rows : '?' }} 行</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const props = defineProps<{
  tables: { name: string; rows: number }[]
  loading: boolean
}>()

const totalRows = computed(() =>
  props.tables.reduce((sum, t) => sum + (t.rows >= 0 ? t.rows : 0), 0),
)
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }
.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.bk-loading-inline {
  text-align: center;
  padding: 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}
.bk-table-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}
.bk-stat-item {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-radius: var(--radius-sm);
  padding: 12px 18px;
  flex: 1;
  text-align: center;
}
.bk-stat-val {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-primary-600);
}
.bk-stat-lb {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
.bk-table-list {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
}
.bk-table-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light);
  transition: background 0.2s ease, transform 0.2s ease;
}
.bk-table-row:last-child { border-bottom: none; }
.bk-table-row:hover {
  background: var(--color-primary-50);
  transform: translateX(4px);
}
.bk-table-name {
  font-weight: 500;
  color: var(--color-text);
  font-family: monospace;
  font-size: 12px;
}
.bk-table-count {
  color: var(--color-text-secondary);
  font-size: 12px;
}
</style>