<template>
  <div class="sk-stat-row">
    <div class="sk-stat-card sk-stat-primary">
      <div class="sk-stat-value">{{ regular }}</div>
      <div class="sk-stat-label">常规订单</div>
    </div>
    <div class="sk-stat-card sk-stat-warning">
      <div class="sk-stat-value">{{ custom }}</div>
      <div class="sk-stat-label">定制订单</div>
    </div>
    <div class="sk-stat-card sk-stat-success">
      <div class="sk-stat-value">{{ stockin }}</div>
      <div class="sk-stat-label">备货数量</div>
    </div>
    <div class="sk-stat-card sk-stat-info">
      <div class="sk-stat-value">{{ regular + custom + stockin }}</div>
      <div class="sk-stat-label">总订单</div>
    </div>
    <div class="sk-stat-card sk-stat-stock">
      <div class="sk-stat-value">{{ available }}</div>
      <div class="sk-stat-label">可用库存</div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  regular: number;
  custom: number;
  stockin: number;
  available: number;
}>();
</script>

<style scoped>
.sk-stat-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-left: auto;
}
.sk-stat-card {
  border-radius: 10px;
  padding: 8px 14px;
  text-align: center;
  border: 1px solid transparent;
  transition: box-shadow 0.3s ease;
}
.sk-stat-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.sk-stat-value {
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 1px;
  font-variant-numeric: tabular-nums;
}
.sk-stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
}
.sk-stat-primary { background: var(--color-primary-50); border-color: var(--color-primary-200); }
.sk-stat-primary .sk-stat-value { color: var(--color-primary-600); }
.sk-stat-warning { background: var(--color-warning-50); border-color: var(--color-warning-200); }
.sk-stat-warning .sk-stat-value { color: var(--color-warning-600); }
.sk-stat-success { background: var(--color-success-50); border-color: var(--color-success-200); }
.sk-stat-success .sk-stat-value { color: var(--color-success-600); }
.sk-stat-info { background: var(--color-info-50); border-color: var(--color-info-200); }
.sk-stat-info .sk-stat-value { color: var(--color-info-600); }
.sk-stat-stock { background: #f0fdf4; border-color: #bbf7d0; }
.sk-stat-stock .sk-stat-value { color: #16a34a; }
@media (max-width: 900px) {
  .sk-stat-row { flex-wrap: wrap; gap: 6px; }
}
</style>