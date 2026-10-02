<template>
  <div class="sec-card">
    <div class="sec-header">
      <div class="sec-title">
        <FontAwesomeIcon :icon="mode === 'stockin' ? 'truck-loading' : 'shipping-fast'" :style="{ color: accent }" aria-hidden="true" />
        {{ mode === 'stockin' ? '入库信息' : '出库信息' }}
      </div>
      <span :class="['sec-badge', mode === 'stockin' ? 'sec-badge-in' : 'sec-badge-out']">
        暂存 {{ stagedCount }} 条
      </span>
    </div>

    <form class="sec-form" @submit.prevent>
      <div class="sec-row">
        <div class="sec-field">
          <label class="sec-label">客户（选填）</label>
          <UiSelect v-model="form.customer" placeholder="可不选" :options="customerOptions" />
        </div>
        <div class="sec-field">
          <label class="sec-label">{{ mode === 'stockin' ? '入库日期' : '出库日期' }}</label>
          <UiDatePicker v-model="form.date" style="width: 100%" />
        </div>
      </div>

      <div class="sec-row" style="grid-template-columns: 2fr 1fr">
        <div class="sec-field">
          <label class="sec-label">皮套 / 产品</label>
          <UiAutocomplete
            v-model="form.search"
            :search-fn="searchFn"
            placeholder="输入皮套名称或69码搜索"
            suppress-after-select
            @select="(p: CaseSearchItem) => emit('select', p)"
          >
            <template #option="{ item }">
              <span class="sec-option-name">{{ item.name }}</span>
              <span v-if="item.parent_id" class="sec-option-part">配件</span>
              <span v-if="item.barcode" class="sec-option-barcode">{{ item.barcode }}</span>
              <span :class="['sec-option-stock', item.current_stock <= 0 && 'sec-option-stock-zero']">库存 {{ item.current_stock ?? 0 }}</span>
            </template>
          </UiAutocomplete>
          <small v-if="mode === 'stockout' && form.caseId" class="sec-stock-hint">
            当前库存 <strong>{{ availableStock ?? '-' }}</strong>
            <template v-if="stagedQtySelected">（本单已暂存 {{ stagedQtySelected }}）</template>
          </small>
        </div>
        <div class="sec-field">
          <label class="sec-label">{{ mode === 'stockin' ? '入库数量' : '出库数量' }}</label>
          <div class="sec-qty-group">
            <button type="button" class="sec-qty-btn" aria-label="减少数量" :disabled="form.quantity <= 1" @click="form.quantity = Math.max(1, form.quantity - 1)">
              <FontAwesomeIcon icon="minus" />
            </button>
            <input
              v-model.number="form.quantity"
              type="number"
              class="sec-qty-input"
              min="1"
              step="1"
              :aria-label="mode === 'stockin' ? '入库数量' : '出库数量'"
              @keydown.enter.prevent="emit('add')"
            />
            <button type="button" class="sec-qty-btn" aria-label="增加数量" @click="form.quantity = form.quantity + 1">
              <FontAwesomeIcon icon="plus" />
            </button>
          </div>
        </div>
      </div>

      <div v-if="quantityWarning" class="sec-warning" role="alert">
        <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
        {{ quantityWarning }}
      </div>

      <div class="sec-field">
        <label class="sec-label">备注（选填）</label>
        <textarea v-model="form.note" class="sec-textarea" rows="2" :placeholder="mode === 'stockin' ? '例如：首批入库' : '例如：客户提货'" @keydown.enter.exact.prevent="emit('add')" />
      </div>

      <button
        type="button"
        :class="['sec-add-btn', canAdd ? (mode === 'stockin' ? 'sec-add-in' : 'sec-add-out') : 'sec-add-disabled']"
        :disabled="!canAdd"
        @click="emit('add')"
      >
        <FontAwesomeIcon icon="plus-circle" style="margin-right: 4px" aria-hidden="true" />
        加入暂存单
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
/**
 * StockEntryCard — 入库/出库录入表单卡。
 * 纯展示 + 表单绑定：状态由 useCaseStockWorkbench 持有，经 defineModel 双向绑定。
 */
import { computed } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import type { CaseSearchItem, CustomerOption } from '@/api/case'
import type { CaseStockFormState, StockMode } from '../composables/useCaseStockWorkbench'

const props = defineProps<{
  mode: StockMode
  stagedCount: number
  customerOptions: CustomerOption[]
  canAdd: boolean
  quantityWarning: string
  /** 出库时选 SKU 的可用库存（已扣本单暂存）；入库为 null */
  availableStock: number | null
  /** 选中的 SKU 在本单已暂存的数量（提示用） */
  stagedQtySelected: number
  searchFn: (query: string) => Promise<CaseSearchItem[]>
}>()

const form = defineModel<CaseStockFormState>('form', { required: true })

const emit = defineEmits<{
  select: [item: CaseSearchItem]
  add: []
}>()

const accent = computed(() => (props.mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)'))
</script>

<style scoped>
.sec-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.sec-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.sec-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.sec-badge {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.sec-badge-in { background: var(--color-primary-50); color: var(--color-primary-600); }
.sec-badge-out { background: var(--color-danger-50); color: var(--color-danger-600); }

.sec-form { padding: 16px; }
.sec-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.sec-field { margin-bottom: 12px; }
.sec-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.sec-option-name { margin-right: 6px; }
.sec-option-part { color: var(--color-primary-700); font-size: 11px; margin-right: 6px; }
.sec-option-barcode { color: var(--color-text-muted); font-size: 11px; margin-right: 6px; }
.sec-option-stock { color: var(--color-primary-600); font-size: 11px; }
.sec-option-stock-zero { color: var(--color-danger-500); }
.sec-stock-hint {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.sec-qty-group {
  display: flex;
  align-items: stretch;
}
.sec-qty-btn {
  width: 34px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: var(--color-surface, #f8fafc);
  color: var(--color-text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease;
}
.sec-qty-btn:first-child { border-radius: 10px 0 0 10px; }
.sec-qty-btn:last-child { border-radius: 0 10px 10px 0; }
.sec-qty-btn:hover:not(:disabled) { background: var(--color-primary-50); color: var(--color-primary-600); }
.sec-qty-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.sec-qty-input {
  width: 100%;
  min-width: 0;
  text-align: center;
  padding: 8px 4px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-left: none;
  border-right: none;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
}
.sec-qty-input:focus { background: var(--color-primary-50, #f0f7ff); }
.sec-qty-input::-webkit-outer-spin-button,
.sec-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.sec-qty-input { appearance: textfield; -moz-appearance: textfield; }

.sec-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin-bottom: 12px;
  border-radius: 9px;
  background: var(--color-warning-50, #fff7e6);
  color: var(--color-warning-600, #d48806);
  font-size: 12px;
  font-weight: 600;
}
.sec-textarea {
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
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
.sec-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.sec-textarea:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

.sec-add-btn {
  width: 100%;
  padding: 10px 14px;
  border: none;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  color: white;
  transition: box-shadow 0.3s ease, transform 0.3s ease, opacity 0.2s ease;
}
.sec-add-in { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); }
.sec-add-out { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); }
.sec-add-in:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
.sec-add-out:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(234, 84, 85, 0.3); }
.sec-add-disabled { opacity: 0.45; cursor: not-allowed; }
</style>
