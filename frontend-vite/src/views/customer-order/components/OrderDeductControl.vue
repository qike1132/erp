<template>
  <div class="co-form-group">
    <label class="co-label">抵扣备货数量</label>
    <div class="co-deduct-row">
      <button
        type="button"
        :class="['co-btn-deduct', form.deductStock && 'active']"
        :aria-pressed="form.deductStock"
        @click="handleDeductPreview"
      >
        <FontAwesomeIcon icon="boxes" aria-hidden="true" />抵扣备货
      </button>
      <button
        type="button"
        class="co-deduct-display"
        :style="{ borderColor: form.deductQuantity > 0 ? 'var(--color-ocean-deep)' : 'var(--color-text-muted)' }"
        :aria-label="`抵扣数量 ${form.deductQuantity}，点击修改`"
        @click="openDeductEdit"
      >
        <FontAwesomeIcon icon="edit" style="font-size: 11px" aria-hidden="true" />抵扣: <strong>{{ form.deductQuantity }}</strong>
      </button>
    </div>
    <div v-if="deductInfoVisible" class="co-deduct-info" aria-live="polite">
      <small v-if="stockError" style="color: var(--color-danger-500)">
        <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> {{ stockError }}
      </small>
      <small v-else-if="availableStock > 0" style="color: var(--color-success-700)">
        <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 可用备货: <strong>{{ availableStock }}</strong> 件
        <span v-if="form.deductQuantity > 0" style="margin-left: 8px; color: var(--color-ocean-text)">
          <FontAwesomeIcon icon="arrow-right" aria-hidden="true" /> 抵扣后剩余:
          <strong>{{ availableStock - form.deductQuantity }}</strong> 件
        </span>
      </small>
      <small v-else style="color: var(--color-warning-500)"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> 暂无可用备货</small>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { FormState } from '../composables/types'

defineProps<{
  availableStock: number
  deductInfoVisible: boolean
  /** 可用备货查询失败的原因；非空时优先展示，避免把故障说成「暂无可用备货」 */
  stockError: string
  handleDeductPreview: () => void
  openDeductEdit: () => void
}>()

const form = defineModel<FormState>('form', { required: true })
</script>

<style scoped>
.co-form-group {
  margin-bottom: 14px;
}
.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
.co-deduct-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}
.co-btn-deduct {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.3s ease, color 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-btn-deduct:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.co-btn-deduct.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-color: var(--color-primary-400);
}
.co-deduct-display {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 10px;
  border: 2px dashed var(--color-border-light);
  background: var(--color-surface, #f8fafc);
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
  color: var(--color-text-secondary);
  font-family: inherit;
  line-height: inherit;
}
.co-deduct-display:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}
.co-deduct-display strong {
  color: var(--color-primary-600);
}
.co-deduct-info {
  margin-top: 6px;
  padding: 6px 0;
}
.co-deduct-info small {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>