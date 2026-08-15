<template>
  <UiDialog v-model:open="openModel" title="编辑订单" max-width-class="max-w-[580px]">
    <div v-if="detailData" class="oe-dialog">
      <div class="oe-header">
        <div class="oe-header-left">
          <span class="oe-order-no">{{ detailData.order_no }}</span>
          <span :class="['oe-status-dot', getStatusClass(detailData.status)]"></span>
          <span class="oe-status-text">{{ detailData.status }}</span>
        </div>
        <span class="oe-date">{{ detailData.order_date }}</span>
      </div>

      <div class="oe-section">
        <div class="oe-section-title"><FontAwesomeIcon icon="info-circle" aria-hidden="true" /> 订单信息</div>
        <div class="oe-info-grid">
          <div class="oe-info-cell">
            <span class="oe-info-label">客户</span>
            <span class="oe-info-value">{{ detailData.customer }}</span>
          </div>
          <div class="oe-info-cell">
            <span class="oe-info-label">订单类型</span>
            <span class="oe-info-value">{{ detailData.order_type === 'custom' ? '定制' : '常规' }}</span>
          </div>
          <div class="oe-info-cell">
            <span class="oe-info-label">产品</span>
            <span class="oe-info-value oe-info-product">
              <img v-if="detailData.product?.image" :src="detailData.product.image" class="oe-product-thumb" />
              <span>{{ detailData.product?.name || '-' }}</span>
            </span>
          </div>
          <div class="oe-info-cell">
            <span class="oe-info-label">69码</span>
            <span class="oe-info-value oe-mono">{{ detailData.product?.barcode || '-' }}</span>
          </div>
          <div class="oe-info-cell" v-if="detailData.country">
            <span class="oe-info-label">国家</span>
            <span class="oe-info-value">{{ detailData.country }}</span>
          </div>
          <div class="oe-info-cell" v-if="detailData.batch_no">
            <span class="oe-info-label">批次号</span>
            <span class="oe-info-value oe-mono">{{ detailData.batch_no }}</span>
          </div>
        </div>
      </div>

      <div v-if="(detailData.items?.length ?? 0) > 1" class="oe-section">
        <div class="oe-section-title">
          <FontAwesomeIcon icon="list-ul" aria-hidden="true" /> 订单明细（{{ detailData.items?.length ?? 0 }} 个 SKU）
        </div>
        <table class="oe-sku-table">
          <thead>
            <tr>
              <th>产品名</th>
              <th>数量</th>
              <th>类型</th>
              <th>国家</th>
              <th>抵扣数量</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(sku, idx) in detailData.items" :key="sku.id ?? idx">
              <td class="oe-sku-product">
                {{ sku.product_name || '-' }}
                <span v-if="sku.product_barcode" class="oe-sku-barcode">{{ sku.product_barcode }}</span>
              </td>
              <td><strong>{{ sku.quantity }}</strong></td>
              <td>{{ sku.order_type === 'custom' ? '定制' : '常规' }}</td>
              <td>{{ sku.country || '-' }}</td>
              <td>{{ sku.deduct_quantity || 0 }}</td>
              <td class="oe-sku-note">{{ sku.note || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="oe-section oe-editable">
        <div class="oe-section-title"><FontAwesomeIcon icon="pen" aria-hidden="true" /> 编辑内容</div>
        <div class="oe-edit-grid">
          <div class="oe-edit-cell">
            <label class="oe-edit-label">数量</label>
            <div class="oe-edit-control">
              <button class="oe-stepper-btn" @click="editForm.quantity = Math.max(1, editForm.quantity - 1)" aria-label="减少">
                <FontAwesomeIcon icon="minus" aria-hidden="true" />
              </button>
              <input type="number" class="oe-stepper-input" v-model.number="editForm.quantity" min="1" step="1" autocomplete="off" />
              <button class="oe-stepper-btn" @click="editForm.quantity = editForm.quantity + 1" aria-label="增加">
                <FontAwesomeIcon icon="plus" aria-hidden="true" />
              </button>
            </div>
          </div>
          <div class="oe-edit-cell">
            <label class="oe-edit-label">抵扣备货</label>
            <div class="oe-edit-control">
              <button class="oe-stepper-btn" @click="editForm.deductQuantity = Math.max(0, editForm.deductQuantity - 1)" aria-label="减少抵扣">
                <FontAwesomeIcon icon="minus" aria-hidden="true" />
              </button>
              <input type="number" class="oe-stepper-input" v-model.number="editForm.deductQuantity" min="0" step="1" autocomplete="off" />
              <button class="oe-stepper-btn" @click="editForm.deductQuantity = editForm.deductQuantity + 1" aria-label="增加抵扣">
                <FontAwesomeIcon icon="plus" aria-hidden="true" />
              </button>
              <span v-if="availableStockin > 0" class="oe-available-hint">可用: {{ availableStockin }}</span>
            </div>
          </div>
        </div>
        <div class="oe-edit-full">
          <label class="oe-edit-label">备注</label>
          <textarea class="oe-textarea" v-model="editForm.note" rows="2" placeholder="输入备注信息…" />
        </div>
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" :disabled="saving" @click="openModel = false">取消</UiButton>
      <UiButton v-if="deductRetryPending" variant="warning" :disabled="saving" @click="retryDeductUpdate">
        <FontAwesomeIcon icon="redo" style="margin-right: 4px" aria-hidden="true" />重试抵扣更新
      </UiButton>
      <UiButton variant="primary" :disabled="saving" @click="saveEditOrder">
        <FontAwesomeIcon icon="check" style="margin-right: 4px" aria-hidden="true" />{{ saving ? '保存中…' : '保存' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import type { OrderDetailData } from '../composables/types'

interface EditFormState {
  quantity: number
  deductQuantity: number
  note: string
}

const props = defineProps<{
  open: boolean
  // 详情数据由 useOrderActions 返回，API 实际包含 batch_no / items 等扩展字段，
  // 类型见 composables/types.ts 的 OrderDetailData。
  detailData: OrderDetailData | null
  editForm: EditFormState
  availableStockin: number
  saving: boolean
  deductRetryPending: boolean
  getStatusClass: (status: string) => string
  saveEditOrder: () => void
  retryDeductUpdate: () => void
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const openModel = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})
</script>

<style scoped>
.oe-dialog { display: flex; flex-direction: column; gap: 16px; }
.oe-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px;
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), var(--color-primary-100, #dbeafe));
  border-radius: 12px; border: 1px solid var(--color-primary-200, #bfdbfe);
}
.oe-header-left { display: flex; align-items: center; gap: 8px; }
.oe-order-no { font-size: 15px; font-weight: 700; color: var(--color-primary-700, #1d4ed8); letter-spacing: 0.02em; }
.oe-status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.oe-status-dot.co-status-pending { background: #f59e0b; }
.oe-status-dot.co-status-stocked { background: #22c55e; }
.oe-status-dot.co-status-partial { background: #3b82f6; }
.oe-status-dot.co-status-shipping { background: #6366f1; }
.oe-status-dot.co-status-shipped { background: #10b981; }
.oe-status-dot.co-status-cancelled { background: #ef4444; }
.oe-status-dot.co-status-completed { background: #8b5cf6; }
.oe-status-text { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); }
.oe-date { font-size: 13px; color: var(--color-text-muted); font-weight: 500; }
.oe-section { border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 12px; overflow: hidden; }
.oe-section-title {
  display: flex; align-items: center; gap: 6px; padding: 10px 16px;
  font-size: 12px; font-weight: 700; color: var(--color-text-secondary);
  text-transform: uppercase; letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.oe-section-title i { color: var(--color-primary-500); font-size: 11px; }
.oe-info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.oe-info-cell {
  padding: 10px 16px; display: flex; flex-direction: column; gap: 2px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.oe-info-cell:nth-child(odd) { border-right: 1px solid var(--color-border-light, #e2e8f0); }
.oe-info-cell:nth-last-child(-n+2) { border-bottom: none; }
.oe-info-label { font-size: 11px; font-weight: 600; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.oe-info-value { font-size: 14px; font-weight: 500; color: var(--color-text); }
.oe-info-product { display: flex; align-items: center; gap: 8px; }
.oe-product-thumb { width: 28px; height: 28px; border-radius: 6px; object-fit: cover; flex-shrink: 0; }
.oe-mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 13px; letter-spacing: 0.02em; }
.oe-sku-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.oe-sku-table thead th {
  padding: 8px 12px; text-align: left; font-weight: 600; font-size: 11px;
  color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.04em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0); white-space: nowrap;
}
.oe-sku-table tbody td { padding: 8px 12px; border-bottom: 1px solid var(--color-border-light, #e2e8f0); color: var(--color-text); vertical-align: middle; }
.oe-sku-table tbody tr:last-child td { border-bottom: none; }
.oe-sku-table tbody tr:hover { background: var(--color-primary-50); }
.oe-sku-product { display: flex; flex-direction: column; gap: 2px; font-weight: 500; }
.oe-sku-barcode { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 10px; color: var(--color-text-muted); letter-spacing: 0.02em; }
.oe-sku-note { color: var(--color-text-secondary); font-size: 11px; max-width: 160px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.oe-editable { border-color: var(--color-primary-200, #bfdbfe); background: linear-gradient(135deg, rgba(255,255,255,0.9), rgba(239,246,255,0.5)); }
.oe-editable .oe-section-title {
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), rgba(219,234,254,0.5));
  color: var(--color-primary-600, #2563eb); border-bottom-color: var(--color-primary-200, #bfdbfe);
}
.oe-edit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px; }
.oe-edit-cell { display: flex; flex-direction: column; gap: 6px; }
.oe-edit-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); }
.oe-edit-control { display: flex; align-items: center; gap: 0; height: 40px; }
.oe-stepper-btn {
  width: 40px; height: 40px; display: flex; align-items: center; justify-content: center;
  border: 2px solid var(--color-border, #cbd5e1); background: var(--color-surface, #f8fafc);
  color: var(--color-text-secondary); cursor: pointer; transition: all 0.2s ease; font-size: 12px;
}
.oe-stepper-btn:first-child { border-radius: 10px 0 0 10px; border-right: none; }
.oe-stepper-btn:last-child { border-radius: 0 10px 10px 0; border-left: none; }
.oe-stepper-btn:hover { background: var(--color-primary-50); color: var(--color-primary-600); border-color: var(--color-primary-300); }
.oe-stepper-input {
  width: 72px; height: 40px; text-align: center; font-size: 15px; font-weight: 600;
  color: var(--color-text); border: 2px solid var(--color-border, #cbd5e1); border-radius: 0;
  outline: none; background: white; -moz-appearance: textfield; box-sizing: border-box;
}
.oe-stepper-input::-webkit-inner-spin-button, .oe-stepper-input::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.oe-stepper-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); z-index: 1; position: relative; }
.oe-available-hint { font-size: 11px; color: var(--color-success-600, #16a34a); margin-left: 10px; font-weight: 600; white-space: nowrap; }
.oe-edit-full { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 6px; }
.oe-textarea {
  width: 100%; padding: 10px 14px; font-size: 14px; line-height: 1.5; color: var(--color-text);
  background: white; border: 2px solid var(--color-border, #cbd5e1); border-radius: 10px;
  outline: none; resize: vertical; font-family: inherit; box-sizing: border-box;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.oe-textarea::placeholder { color: var(--color-text-muted); }
.oe-textarea:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); }
@media (max-width: 480px) {
  .oe-info-grid { grid-template-columns: 1fr; }
  .oe-info-cell:nth-child(odd) { border-right: none; }
  .oe-edit-grid { grid-template-columns: 1fr; }
  .oe-header { flex-direction: column; align-items: flex-start; gap: 4px; }
}
</style>
