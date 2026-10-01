<template>
  <!-- 发货单页页头右侧动作组：状态切换 + 导出/打印未到货 + 批量发货，与 TAB 导航同一行（用户裁决） -->
  <div class="osa-actions">
    <div class="osa-confirm-filter">
      <button
        type="button"
        :class="['osa-filter-btn', { 'is-active': statusFilter === 'shipped' }]"
        @click="emit('setStatus', 'shipped')"
      >待收货({{ shippedCount }})</button>
      <button
        type="button"
        :class="['osa-filter-btn', { 'is-active': statusFilter === 'received' }]"
        @click="emit('setStatus', 'received')"
      >已完成({{ receivedCount }})</button>
    </div>
    <button
      type="button"
      class="osa-btn"
      :disabled="exporting || unshippedLoading"
      @click="emit('export')"
    >
      <FontAwesomeIcon icon="file-csv" aria-hidden="true" /> 导出未到货
    </button>
    <button
      type="button"
      class="osa-btn"
      :disabled="exporting || unshippedLoading"
      @click="emit('print')"
    >
      <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印未到货
    </button>
    <button
      v-if="canShip"
      type="button"
      class="osa-btn osa-btn--primary"
      @click="emit('ship')"
    >
      <FontAwesomeIcon icon="truck-fast" aria-hidden="true" /> 发货
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourceShipmentActions.vue — 发货单页页头动作组（方案B + 用户裁决布局）
 *
 * 与 HubeiRouteTabs 同行置于页头右侧：待收货/已完成 状态切换、导出/打印未到货
 * （自外发进度页迁入）、批量发货（仅非贝乐用户可见）。
 * 状态与业务由父组件持有，本组件纯展示 + 事件上抛。
 * FontAwesomeIcon 为 main.ts 全局注册，无需导入。
 */
defineProps<{
  shippedCount: number
  receivedCount: number
  statusFilter: 'shipped' | 'received'
  exporting: boolean
  unshippedLoading: boolean
  canShip: boolean
}>()

const emit = defineEmits<{
  setStatus: [status: 'shipped' | 'received']
  export: []
  print: []
  ship: []
}>()
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

.osa-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

/* 状态切换（待收货/已完成，沿用 beile-order 未确认/已确认 视觉） */
.osa-confirm-filter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--color-border-light, #e2e8f0);
}
.osa-filter-btn {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--color-text-secondary, #6b7280);
  background: #fff;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 9px;
  cursor: pointer;
  font-family: inherit;
  user-select: none;
  transition: all 0.15s ease;
}
.osa-filter-btn:hover {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.osa-filter-btn.is-active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #3b82f6), var(--color-primary-600, #2563eb));
  border-color: var(--color-primary-600, #2563eb);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.25);
}

.osa-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.osa-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #2563eb);
  background: var(--color-primary-50, #eff6ff);
}
.osa-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.osa-btn--primary {
  color: #fff;
  background: var(--color-primary-600, #2563eb);
  border-color: var(--color-primary-600, #2563eb);
}
.osa-btn--primary:hover:not(:disabled) {
  color: #fff;
  background: var(--color-primary-700, #1d4ed8);
}
</style>
