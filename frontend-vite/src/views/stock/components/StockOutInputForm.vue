<template>
  <div class="so-col-title">
    <span>出货信息录入</span>
    <UiBadge v-if="stagedCount" variant="cancelled">已暂存: {{ stagedCount }}</UiBadge>
  </div>
  <div class="so-col-scroll">
    <form @submit.prevent>
      <div class="form-grid">
        <div class="form-field">
          <label class="form-label">出货时间</label>
          <UiDatePicker v-model="form.date" style="width: 100%" />
        </div>
        <div class="form-field">
          <label class="form-label">客户名称</label>
          <UiSelect v-model="form.customer" placeholder="请选择客户" :options="customerOptions" />
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">产品名称</label>
        <UiAutocomplete
          ref="productAcRef"
          v-model="form.search"
          :search-fn="searchFn"
          :list-fn="listFn"
          :empty-text="emptyText"
          placeholder="输入产品名称或69码搜索，或点击查看全部"
          @select="onSelect"
          @update:model-value="onSearchInput"
        >
          <template #option="{ item }">
            {{ item.name }}
          </template>
        </UiAutocomplete>
      </div>

      <!-- 成品库存批次：选定 SKU 后带出，供按批次扣减（无批次时不显示） -->
      <div v-if="batchOptions.length" class="form-field">
        <label class="form-label">批次号</label>
        <UiSelect
          v-model="form.batchNo"
          placeholder="不指定批次（整产品扣减）"
          :options="batchSelectOptions"
        />
        <small v-if="selectedBatch" class="shipment-info">
          <FontAwesomeIcon icon="info-circle" style="margin-right: 4px" aria-hidden="true" />
          该批次可用: <strong style="color: var(--color-primary-500)">{{ selectedBatch.available_quantity }}</strong>
        </small>
      </div>

      <div class="form-field">
        <label class="form-label">出货数量</label>
        <input v-model.number="form.quantity" type="number" class="form-input" min="1" step="1" name="quantity" autocomplete="off" />
        <small v-if="shipmentInfo" class="shipment-info">
          <FontAwesomeIcon icon="info-circle" style="margin-right: 4px" aria-hidden="true" />
          订单量: {{ shipmentInfo.order_quantity }} | 已出货: {{ shipmentInfo.shipped_quantity }} | 可出货:
          <strong style="color: var(--color-primary-500)">{{ shipmentInfo.available_quantity }}</strong>
        </small>
      </div>

      <div class="form-field">
        <label class="form-label">备注</label>
        <textarea
          v-model="form.note"
          class="form-input"
          rows="2"
          placeholder="例如：物流发货"
        />
      </div>

      <StockOutImportSection
        :customer="form.customer"
        :date="form.date"
        :search-products="searchFn"
        @ocr-staged="emit('ocr-staged', $event)"
        @go-manual="focusProductInput"
        @imported="emit('imported')"
      />

      <UiButton
        :variant="canAdd ? 'danger' : 'outline'"
        :disabled="!canAdd"
        style="margin-top: 15px"
        @click="emit('add-staged')"
      >
        <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />新增出货
      </UiButton>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ShipmentInfo, Product, StagedStockout, BatchAvailable } from '@/types'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import StockOutImportSection from './StockOutImportSection.vue'

interface StockOutForm {
  customer: string
  date: string
  search: string
  productId: string
  quantity: number
  note: string
  /** 成品库存批次号（选填；选定后按该批次扣减） */
  batchNo: string
}

const props = defineProps<{
  customerOptions: { value: string; label: string }[]
  shipmentInfo: ShipmentInfo | null
  /** 成品库存批次可用量列表（选定 SKU 后由父级带出） */
  batchOptions: BatchAvailable[]
  canAdd: boolean
  stagedCount: number
  searchFn: (q: string) => Promise<Product[]>
  /** 点击输入框列全量：当前客户可见的 SKU 浏览列表（与客户订单页同款能力） */
  listFn: () => Promise<Product[]>
  /** 下拉无结果时的文案；区分「请先选客户 / 搜索失败 / 该客户暂无产品」 */
  emptyText: string
}>()

const form = defineModel<StockOutForm>('form', { required: true })

/** 批次下拉选项：首项为空值（可改回「不指定批次」），其余显示批次号 + 该批次可用量 */
const batchSelectOptions = computed(() => [
  { value: '', label: '不指定批次（整产品扣减）' },
  ...props.batchOptions.map((b) => ({ value: b.batch_no, label: `${b.batch_no}（可用 ${b.available_quantity}）` })),
])
/** 当前选中批次（用于显示可用量提示） */
const selectedBatch = computed(() => props.batchOptions.find((b) => b.batch_no === form.value.batchNo) ?? null)

const emit = defineEmits<{
  'add-staged': []
  'product-select': [product: Product]
  'clear-shipment': []
  imported: []
  /** OCR 粘贴识别确认后的暂存出货条目，转发给上层并入暂存列表 */
  'ocr-staged': [items: StagedStockout[]]
  'go-manual': []
}>()

/** 产品输入框引用：指引态「去录入」时把焦点交回这里（按暴露的接口结构声明） */
const productAcRef = ref<{ focusInput: () => void } | null>(null)

function focusProductInput() {
  productAcRef.value?.focusInput()
}

function onSelect(product: Product) {
  emit('product-select', product)
}

function onSearchInput() {
  form.value.productId = ''
  emit('clear-shipment')
}
</script>

<style scoped>
:deep(input.bg-slate-50) {
  background-color: #ffffff !important;
}

.so-col-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.so-col-title i {
  color: var(--color-danger-500);
  margin-right: 6px;
  font-size: 13px;
}
.so-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.form-field { margin-bottom: 10px; }
.form-label {
  display: block;
  font-weight: 500;
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.label-icon {
  color: var(--color-danger-500);
  margin-right: 4px;
  font-size: 11px;
}
.form-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: var(--radius-input, 12px);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  min-height: 40px;
  box-sizing: border-box;
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-input::-webkit-inner-spin-button,
.form-input::-webkit-outer-spin-button { opacity: 1; }
.form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
textarea.form-input { resize: vertical; }
textarea.form-input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}
.shipment-info {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.shipment-detail {
  margin-left: 4px;
  color: var(--color-text-tertiary);
  font-size: 11px;
}

@media (max-width: 767.98px) {
  .form-grid { grid-template-columns: 1fr; }
}
</style>
