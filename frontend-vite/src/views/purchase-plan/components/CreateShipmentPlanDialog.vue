<template>
  <UiDialog
    :open="open"
    title=""
    max-width-class="max-w-[1200px]"
    @update:open="$emit('update:open', $event)"
  >
    <template #title>
      <div class="csd-header-tabs" role="tablist">
        <span
          role="tab"
          :aria-selected="mode === 'manual'"
          :class="['csd-htab', { 'csd-htab-active': mode === 'manual' }]"
          @click="mode = 'manual'"
        >填写数据</span>
        <span
          role="tab"
          :aria-selected="mode === 'import'"
          :class="['csd-htab', { 'csd-htab-active': mode === 'import' }]"
          @click="mode = 'import'"
        >批量导入</span>
      </div>
    </template>

    <div class="csd-form">
      <!-- 填写数据 -->
      <ManualPlanForm
        v-if="mode === 'manual'"
        :details="form.details"
        :customer-options="customerOptions"
        :product-suggestions="productSuggestions"
        :error-msg="errorMsg"
        @remove="removeDetail"
        @product-input="onProductInput"
        @product-focus="onProductFocus"
        @product-blur="onProductBlur"
        @select-product="selectProduct"
      />

      <!-- 批量导入（v-show 保持切换 Tab 时文件选中状态不丢失，与原单文件状态一致） -->
      <ImportPanel
        v-show="mode === 'import'"
        :open="open"
        @created="$emit('created')"
      />
    </div>

    <template #footer>
      <button v-if="mode === 'manual'" class="csd-btn csd-btn-add" @click="addDetail" aria-label="添加明细">
        <FontAwesomeIcon icon="plus" aria-hidden="true" /> 添加明细
      </button>
      <span style="flex:1"></span>
      <button class="csd-btn csd-btn-cancel" @click="$emit('update:open', false)" aria-label="取消">
        取消
      </button>
      <button v-if="mode === 'manual'" class="csd-btn csd-btn-submit" :disabled="submitting" @click="handleSubmit" :aria-label="submitting ? '保存中…' : '确认创建'">
        <FontAwesomeIcon v-if="submitting" icon="spinner" spin />
        <FontAwesomeIcon v-else icon="check" />
        {{ submitting ? '保存中…' : '确认创建' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, watch, toRef } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import ManualPlanForm from './ManualPlanForm.vue'
import ImportPanel from './ImportPanel.vue'
import { useCreateShipmentPlan } from '../composables/useCreateShipmentPlan'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  created: []
}>()

const mode = ref<'manual' | 'import'>('manual')

// 表单状态 / 产品建议 / 校验 / 提交逻辑抽至 composables/useCreateShipmentPlan.ts
const {
  form, productSuggestions, submitting, errorMsg, customerOptions,
  addDetail, removeDetail, onProductInput, onProductFocus, onProductBlur, selectProduct, handleSubmit,
} = useCreateShipmentPlan(toRef(props, 'open'), () => emit('created'))

// 打开对话框时切回「填写数据」页签（表单重置在 composable 内、文件清空在 ImportPanel 内完成）
watch(() => props.open, (val) => {
  if (val) {
    mode.value = 'manual'
  }
})
</script>

<style scoped>
.csd-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 70vh;
}

.csd-header-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  margin: 0 auto;
}

.csd-htab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  user-select: none;
  white-space: nowrap;
}

.csd-htab:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.csd-htab-active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91,141,239,0.2);
  transform: translateY(-1px);
}

.csd-btn {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.csd-btn-add {
  border: 1.5px dashed var(--color-primary-300);
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.csd-btn-add:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-100);
  color: var(--color-primary-700);
}

.csd-btn-cancel {
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
}
.csd-btn-cancel:hover {
  border-color: var(--color-border-dark);
  color: var(--color-text);
}

.csd-btn-submit {
  border: none;
  background: var(--gradient-primary);
  color: white;
}
.csd-btn-submit:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3);
}
.csd-btn-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
