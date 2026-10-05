<template>
  <UiDialog :open="open" title="新增退货" :close-on-overlay-click="false" @update:open="emit('update:open', $event)">
    <div class="sr-dialog-body">
      <div class="sr-hint">
        <FontAwesomeIcon icon="info-circle" aria-hidden="true" />
        选择客户与产品、填写数量后确认：库存按退货数量回补并写入退货流水（不关联具体出货单）
      </div>

      <div class="sr-grid">
        <div class="sr-field">
          <label>客户 <span class="req">*</span></label>
          <select
            v-model="form.customer"
            class="sr-select"
            :disabled="loadingCatalog"
          >
            <option value="" disabled>{{ loadingCatalog ? '客户加载中…' : '请选择客户' }}</option>
            <option v-for="c in customers" :key="c.id" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        <div class="sr-field">
          <label>产品 <span class="req">*</span></label>
          <select
            v-model.number="form.product_id"
            class="sr-select"
            :disabled="loadingCatalog"
          >
            <option :value="null" disabled>{{ loadingCatalog ? '产品加载中…' : '请选择产品' }}</option>
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
      </div>

      <div class="sr-grid">
        <div class="sr-field">
          <label>退货数量（件）<span class="req">*</span></label>
          <input
            v-model.number="form.quantity"
            type="number"
            min="1"
            placeholder="请输入"
            class="sr-input"
          />
        </div>
        <div class="sr-field">
          <label>退货原因 <span class="req">*</span></label>
          <select v-model="form.reason" class="sr-select">
            <option value="" disabled>请选择</option>
            <option v-for="r in RETURN_REASON_OPTIONS" :key="r" :value="r">{{ r }}</option>
          </select>
        </div>
      </div>

      <div class="sr-field">
        <label>备注</label>
        <textarea v-model="form.note" class="sr-textarea" rows="3" placeholder="运输破损、责任说明等可补充在此…" />
      </div>
    </div>

    <template #footer>
      <button class="sr-btn" :disabled="submitting" @click="emit('update:open', false)">取消</button>
      <button class="sr-btn sr-btn-primary" :disabled="submitting" @click="emit('submit')">
        {{ submitting ? '提交中…' : '确认退货' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * StockReturnCreateDialog.vue — 新增退货弹窗（P1 按产品制）
 *
 * 客户（下拉，来自客户目录）与产品（下拉，来自产品目录）为硬性必填。
 * 产品下拉来自 catalog store（懒加载 + 跨页缓存）。
 * 可退数量无上限概念，以实物为准（服务层仅校验正整数）。
 */
import UiDialog from '@/components/ui/UiDialog.vue'
import type { Customer, Product } from '@/types'
import { RETURN_REASON_OPTIONS, type StockReturnFormData } from '../composables/useStockReturn'

defineProps<{
  open: boolean
  submitting: boolean
  products: Product[]
  customers: Customer[]
  loadingCatalog: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  submit: []
}>()

/** 表单对象由 composable 持有（reactive）；经 v-model:form 传入，避免直接改 prop */
const form = defineModel<StockReturnFormData>('form', { required: true })
</script>

<style scoped>
.sr-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 2px;
}
.sr-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-ocean-light, #d4f1f4);
  border: 1px solid var(--color-ocean, #b0e0e6);
  color: var(--color-ocean-text, #02669e);
  font-size: 12px;
  font-weight: 600;
}
.sr-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.sr-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sr-field label {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
}
.sr-field .req {
  color: var(--color-danger-500);
}
.sr-input,
.sr-select,
.sr-textarea {
  min-height: 34px;
  padding: 4px 10px;
  border: 1px solid var(--color-border, #e4e7ed);
  font-size: 13px;
  color: var(--color-text);
  background: white;
  box-sizing: border-box;
}
.sr-textarea {
  resize: vertical;
}
.sr-input:focus,
.sr-select:focus,
.sr-textarea:focus {
  outline: none;
  border-color: var(--color-primary-300);
}
.sr-btn {
  min-height: 34px;
  padding: 0 16px;
  border: 1px solid var(--color-border, #e4e7ed);
  background: white;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.sr-btn-primary {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}
.sr-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
