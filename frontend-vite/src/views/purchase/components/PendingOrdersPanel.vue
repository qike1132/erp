<template>
  <div class="pc-section">
    <div class="pc-section-header">
      <div class="pc-section-title">
        <i class="fas fa-inbox" /> 审核订单
      </div>
      <div class="pc-section-actions">
        <button
          class="pc-btn pc-btn-success"
          :disabled="validSelectedCount === 0 || submitting"
          @click="$emit('oneClickGenerate')"
        >
          <i :class="submitting ? 'fas fa-spinner fa-spin' : 'fas fa-magic'" /> 一键审核订单 ({{ validSelectedCount }})
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="pc-loading-state">
      <i class="fas fa-spinner fa-spin" />
      <span>加载中...</span>
    </div>

    <!-- Empty -->
    <div v-else-if="orders.length === 0" class="pc-empty-state">
      <i class="fas fa-inbox" />
      <span>暂无未处理订单</span>
    </div>

    <!-- Table -->
    <template v-else>
      <div class="pc-section-body">
        <div class="pc-table-wrap">
          <table>
          <thead>
            <tr>
              <th style="width:60px">
                <div class="pc-th-check">
                  <UiCheckbox :checked="allSelected" @update:checked="$emit('toggleAll', $event)" />
                  <span>全选</span>
                </div>
              </th>
              <th>下单时间</th>
              <th>订单号</th>
              <th style="text-align:left">客户名称</th>
              <th style="text-align:left">产品名称</th>
              <th style="text-align:right">订单数量</th>
              <th style="text-align:center">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="o in orders"
              :key="o.id"
              :class="{ 'pc-row-selected': selectedIds.includes(o.id) }"
              @click="$emit('toggleSelection', o.id)"
            >
              <td class="pc-td-center" @click.stop>
                <UiCheckbox :checked="selectedIds.includes(o.id)" @update:checked="$emit('toggleSelection', o.id)" />
              </td>
              <td class="pc-td-nowrap">{{ o.create_time || o.order_date || '-' }}</td>
              <td class="pc-td-nowrap">{{ o.order_no }}</td>
              <td class="pc-td-truncate" style="max-width:120px">{{ o.customer || '-' }}</td>
              <td class="pc-td-truncate" style="max-width:300px">{{ o.product_name || '-' }}</td>
              <td class="pc-td-right pc-td-nowrap">{{ o.quantity?.toLocaleString() || '-' }}</td>
              <td class="pc-td-center" @click.stop>
                <button
                  v-if="o.has_bom"
                  class="pc-btn pc-btn-success pc-btn-sm"
                  :disabled="submitting"
                  @click="$emit('quickGenerate', o.id)"
                >
                  <i :class="submitting ? 'fas fa-spinner fa-spin' : 'fas fa-magic'" /> 审核订单
                </button>
                <button
                  v-else
                  class="pc-btn pc-btn-danger pc-btn-sm"
                  @click="$emit('noBomError', o)"
                >
                  <i class="fas fa-exclamation-circle" /> 未配置BOM
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import UiCheckbox from '@/components/ui/UiCheckbox.vue'

defineProps<{
  orders: any[]
  loading: boolean
  selectedIds: number[]
  selectedCount: number
  validSelectedCount: number
  allSelected: boolean
  submitting: boolean
}>()

defineEmits<{
  toggleAll: [checked: boolean]
  toggleSelection: [id: number]
  oneClickGenerate: []
  quickGenerate: [id: number]
  noBomError: [order: any]
}>()
</script>

<style scoped>
.pc-section {
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.pc-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px 10px;
}

.pc-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.pc-section-title i {
  font-size: 13px;
  color: var(--color-primary-500);
}

.pc-section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.pc-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  background: white;
}

.pc-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pc-btn-sm {
  padding: 5px 10px;
  font-size: 11px;
}

.pc-btn-success {
  color: var(--color-success-600);
  border-color: var(--color-success-200);
  background: var(--color-success-50);
}

.pc-btn-success:hover:not(:disabled) {
  background: var(--color-success-500);
  color: white;
  border-color: transparent;
}

.pc-btn-danger {
  color: var(--color-danger-600, #dc2626);
  border-color: var(--color-danger-200, #fecaca);
  background: var(--color-danger-50, #fef2f2);
}

.pc-btn-danger:hover {
  background: var(--color-danger-500, #ef4444);
  color: white;
  border-color: transparent;
}

.pc-btn-disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Section body - consistent padding with header */
.pc-section-body {
  padding: 0 24px;
}

/* Table */
.pc-table-wrap {
  padding: 0 0 16px;
  overflow-x: auto;
}

.pc-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pc-table-wrap thead th {
  padding: 10px 14px;
  background: var(--color-surface, #f8fafc);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
  text-align: left;
}

.pc-th-check {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.pc-th-check span {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pc-table-wrap tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
  cursor: pointer;
  transition: background 0.15s ease;
}

.pc-table-wrap tbody tr:hover td {
  background: var(--color-primary-50);
}

.pc-table-wrap tbody tr:last-child td {
  border-bottom: none;
}

.pc-row-selected td {
  background: rgba(0, 148, 191, 0.06);
}

.pc-td-center { text-align: center; }
.pc-td-right { text-align: right; }
.pc-td-nowrap { white-space: nowrap; }
.pc-td-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Empty & Loading */
.pc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}

.pc-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}

.pc-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

.pc-loading-state i {
  font-size: 20px;
}
</style>
