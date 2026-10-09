<template>
  <div v-if="row.status !== 'cancelled'" class="sr-action-group">
    <button
      v-if="canEdit"
      class="sr-row-btn sr-row-btn-edit"
      aria-label="修改退货"
      title="修改退货（取消原单后按同一出货明细重建，生成新单号）"
      @click="emit('edit', row)"
    >
      <FontAwesomeIcon icon="pen-to-square" aria-hidden="true" />
    </button>
    <button
      v-if="canDelete"
      class="sr-row-btn sr-row-btn-danger"
      :disabled="disabled"
      aria-label="删除退货"
      title="删除退货（硬删除：记录移除，库存对称扣回）"
      @click="emit('delete', row)"
    >
      <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
    </button>
  </div>
  <span v-else class="sr-cancelled-mark">—</span>
</template>

<script setup lang="ts">
/**
 * StockReturnRowActions.vue — /stock-return 行内「修改」「删除」单元格。
 *
 * 权限由父级算好传入（父级镜像后端 require_any_permission：stock_return_manage
 * 或对应子码 return_edit / return_delete）。已取消的退货不显示任何按钮——后端也不允许编辑。
 */
import type { StockReturnRecord } from '@/api/stockReturn'

defineProps<{
  row: StockReturnRecord
  canEdit: boolean
  canDelete: boolean
  /** 该行删除进行中（禁用按钮） */
  disabled: boolean
}>()

const emit = defineEmits<{
  edit: [row: StockReturnRecord]
  delete: [row: StockReturnRecord]
}>()
</script>

<style scoped>
/* 方形（本页方正基准）；修改=琥珀、删除=危险红（与报表行内按钮同语义） */
.sr-action-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sr-row-btn {
  width: 34px;
  height: 34px;
  border-radius: 0;
  border: 2px solid transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  cursor: pointer;
  padding: 0;
  transition: background 0.2s ease, color 0.2s ease;
}
.sr-row-btn-edit {
  background: var(--color-warning-50, #fff3e6);
  color: var(--color-warning-700, #c47820);
  border-color: var(--color-warning-200, #ffd199);
}
.sr-row-btn-edit:hover {
  background: var(--color-warning-500, #ff9f43);
  color: white;
  border-color: transparent;
}
.sr-row-btn-danger {
  background: var(--color-danger-50, #fde8e8);
  color: var(--color-danger-700, #b33335);
  border-color: var(--color-danger-200, #f7a5a5);
}
.sr-row-btn-danger:hover {
  background: var(--color-danger-500, #ea5455);
  color: white;
  border-color: transparent;
}
.sr-row-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.sr-cancelled-mark {
  color: var(--color-text-muted);
}
</style>
