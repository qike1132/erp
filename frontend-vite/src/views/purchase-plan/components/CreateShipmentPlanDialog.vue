<template>
  <UiDialog
    :open="open"
    title="新建出货计划"
    max-width-class="max-w-[1200px]"
    @update:open="$emit('update:open', $event)"
  >
    <div class="csd-form">
      <!-- 批量导入：不再单独占一个页签，直接并进填写界面——
           要整批录就走导入，要逐行核对就往下填，同一屏里选，不用来回切。 -->
      <section class="csd-import-block">
        <div class="csd-import-head">
          <span class="csd-import-title">
            <FontAwesomeIcon icon="file-excel" aria-hidden="true" /> 批量导入 Excel
          </span>
          <span class="csd-import-hint">选文件后点「导入」直接落库；没有表格也可以跳过，直接在下面逐行填写</span>
        </div>
        <ImportPanel :open="open" @imported="$emit('imported', $event)" />
      </section>

      <div class="csd-divider" role="separator"><span>或手工填写</span></div>

      <ManualPlanForm
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
    </div>

    <template #footer>
      <button class="csd-btn csd-btn-add" aria-label="添加明细" @click="addDetail">
        <FontAwesomeIcon icon="plus" aria-hidden="true" /> 添加明细
      </button>
      <span style="flex:1" />
      <button class="csd-btn csd-btn-cancel" aria-label="取消" @click="$emit('update:open', false)">
        取消
      </button>
      <button class="csd-btn csd-btn-submit" :disabled="submitting || !hasDetail" :aria-label="submitting ? '保存中…' : '确认创建'" @click="handleSubmit">
        <FontAwesomeIcon v-if="submitting" icon="spinner" spin />
        <FontAwesomeIcon v-else icon="check" />
        {{ submitting ? '保存中…' : '确认创建' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import ManualPlanForm from './ManualPlanForm.vue'
import ImportPanel from './ImportPanel.vue'
import { useCreateShipmentPlan } from '../composables/useCreateShipmentPlan'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  /** 手动创建**全部成功**（调用方据此关闭对话框） */
  created: []
  /** 有分组创建成功（部分成功时只刷新数据，对话框保持打开以保留失败草稿） */
  succeeded: []
  /** 批量导入完成，参数为数据所属月份 YYYY-MM（对话框保持打开以展示结果） */
  imported: [month?: string]
}>()

// 表单状态 / 产品建议 / 校验 / 提交逻辑抽至 composables/useCreateShipmentPlan.ts
/** 明细区一行都没填时禁用「确认创建」：导入成功后按钮常显，空表单点它会报「第 1 行…」 */
const hasDetail = computed(() =>
  form.details.some((d) => d.customer_id != null || d.product_name.trim() !== ''),
)

const {
  form, productSuggestions, submitting, errorMsg, customerOptions,
  addDetail, removeDetail, onProductInput, onProductFocus, onProductBlur, selectProduct, handleSubmit,
} = useCreateShipmentPlan(toRef(props, 'open'), () => emit('created'), {
  // H6：部分成功只刷新数据，不关闭对话框（失败草稿必须留在表单里可重试）
  onSucceeded: () => emit('succeeded'),
})

</script>

<style scoped>
.csd-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 70vh;
}

.csd-import-block {
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: 12px;
  padding: 12px 14px;
  background: #fbfcfe;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.csd-import-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.csd-import-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.csd-import-hint {
  font-size: 12px;
  color: var(--color-text-muted);
}

.csd-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-placeholder);
}

.csd-divider::before,
.csd-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border-light, #e2e8f0);
}

.csd-btn {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 14px;
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
