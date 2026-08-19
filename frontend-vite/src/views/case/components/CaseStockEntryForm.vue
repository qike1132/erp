<template>
  <div class="cs-form-section">
    <div class="cs-section-header">
      <div class="cs-section-title">
        <FontAwesomeIcon :icon="mode === 'stockin' ? 'truck-loading' : 'shipping-fast'" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" aria-hidden="true" />
        {{ mode === 'stockin' ? '入库信息录入' : '出库信息录入' }}
      </div>
      <span v-if="staged.length" :class="['cs-badge', mode === 'stockin' ? 'cs-badge-info' : 'cs-badge-danger']">
        已暂存: {{ staged.length }}
      </span>
    </div>

    <form @submit.prevent class="cs-form">
      <div class="cs-form-row">
        <div class="cs-form-field">
          <label class="cs-form-label">客户名称</label>
          <UiSelect v-model="form.customer" placeholder="请选择客户" :options="customerOptions" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">{{ mode === 'stockin' ? '入库时间' : '出库时间' }}</label>
          <UiDatePicker v-model="form.date" style="width: 100%" />
        </div>
      </div>

      <div class="cs-form-row" style="grid-template-columns: 2fr 1fr">
        <div class="cs-form-field">
          <label class="cs-form-label">产品名称</label>
          <UiAutocomplete
            v-model="form.search"
            :searchFn="searchFn"
            placeholder="输入产品名称或69码搜索"
            @select="onProductSelect"
          >
            <template #option="{ item }">
              {{ item.name }}
              <span v-if="item.barcode" class="cs-barcode-hint">{{ item.barcode }}</span>
            </template>
          </UiAutocomplete>
          <small v-if="mode === 'stockout' && form.productId" class="cs-current-stock">当前库存: {{ currentStock }}</small>
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">{{ mode === 'stockin' ? '入库数量' : '出库数量' }}</label>
          <input type="number" class="cs-input" v-model.number="form.quantity" min="1" step="1" />
        </div>
      </div>

      <div class="cs-form-field">
        <label class="cs-form-label">备注</label>
        <textarea v-model="form.note" class="cs-textarea" rows="2" :placeholder="mode === 'stockin' ? '例如：批量入库' : '例如：批量出库'" />
      </div>

      <button
        type="button"
        :class="['cs-submit-btn', canAdd ? (mode === 'stockin' ? 'cs-submit-primary' : 'cs-submit-danger') : 'cs-submit-disabled']"
        :disabled="!canAdd"
        @click="emit('add-staged')"
      >
        <FontAwesomeIcon icon="plus-circle" style="margin-right: 4px" />{{ mode === 'stockin' ? '新增入库' : '新增出库' }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import type {
  CaseProductOption,
  CaseStockFormState,
  CustomerOption,
  StagedStockItem,
} from '../composables/useCaseStockEntry'

defineProps<{
  mode: 'stockin' | 'stockout'
  staged: StagedStockItem[]
  currentStock: number
  customerOptions: CustomerOption[]
  canAdd: boolean
  searchFn: (query: string) => Promise<CaseProductOption[]>
}>()

const form = defineModel<CaseStockFormState>('form', { required: true })

const emit = defineEmits<{
  'product-select': [product: CaseProductOption]
  'add-staged': []
}>()

function onProductSelect(product: CaseProductOption) {
  emit('product-select', product)
}
</script>

<style scoped>
.cs-form-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}

.cs-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cs-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.cs-section-title i {
  font-size: 14px;
}

.cs-form {
  padding: 16px;
}
.cs-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.cs-form-field {
  margin-bottom: 12px;
}
.cs-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.cs-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  resize: vertical;
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-current-stock {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.cs-submit-btn {
  width: 100%;
  padding: 9px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cs-submit-primary { background: var(--color-primary-50); color: var(--color-primary-600); border: 2px solid var(--color-primary-300); }
.cs-submit-primary:hover { background: var(--color-primary-100); transform: translateY(-1px); }
.cs-submit-danger { background: var(--color-danger-50); color: var(--color-danger-600); border: 2px solid var(--color-danger-300); }
.cs-submit-danger:hover { background: var(--color-danger-100); transform: translateY(-1px); }
.cs-submit-disabled { background: var(--color-surface, #f8fafc); color: var(--color-text-muted); border: 2px solid var(--color-border-light); cursor: not-allowed; opacity: 0.4; }

.cs-badge {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.cs-badge-info { background: var(--color-primary-50); color: var(--color-primary-600); }
.cs-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }

.cs-barcode-hint { color: var(--color-text-muted); font-size: 11px; }
</style>