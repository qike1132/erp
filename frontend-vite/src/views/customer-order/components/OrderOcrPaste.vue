<template>
  <!--
    粘贴图片识别：与 Excel 投放区并列成两条独立导入路径。
    整块是 button 语义——可 Tab 到、Enter 触发，与 Excel 投放区一致。
  -->
  <div
    ref="pasteZoneRef"
    class="op-paste"
    :class="{ 'op-paste-busy': recognizing }"
    role="button"
    tabindex="0"
    :aria-label="recognizing ? '正在识别图片，请稍候' : '粘贴截图识别订单：截图后按 Ctrl+V，或按回车选择图片'"
    :aria-busy="recognizing ? 'true' : undefined"
    @click="openImageDialog"
    @keydown.enter.prevent="openImageDialog"
    @keydown.space.prevent="openImageDialog"
  >
    <span class="op-paste-icon" aria-hidden="true">
      <FontAwesomeIcon :icon="recognizing ? 'spinner' : 'paste'" :spin="recognizing" />
    </span>
    <span class="op-paste-text">
      <span class="op-paste-title">
        <template v-if="recognizing">正在识别…</template>
        <template v-else>粘贴截图识别 <kbd>Ctrl</kbd><kbd>V</kbd></template>
      </span>
      <span class="op-paste-sub">聊天截图、表格、拍照均可</span>
    </span>
    <span class="op-paste-go">或点此选图</span>
    <input
      ref="imageInputRef"
      type="file"
      accept="image/*,.pdf"
      class="op-paste-input"
      @change="handleImageSelect"
    />
  </div>

  <OcrPreviewModal
    v-model:open="dialogOpen"
    v-model:draft-items="draftItems"
    :show-guide="emptyResult"
    :unmatched-count="unmatchedCount"
    :invalid-quantity-count="invalidQuantityCount"
    :missing-customer-count="missingCustomerCount"
    :warnings="warnings"
    :raw-text="rawText"
    :source-name="sourceName"
    :default-customer="defaultCustomer"
    :search-products="searchProducts"
    @confirm="confirmImport"
    @retry="retryFromGuide"
    @download-template="downloadTemplate"
    @go-manual="goManual"
    @paste-image="recognize"
  />
</template>

<script setup lang="ts">
/**
 * OrderOcrPaste — 粘贴图片识别（热区 + 确认弹窗 + 状态）整体封装
 *
 * 封装成一个组件的原因：录入面板与主视图都逼近单文件 400 行门禁，
 * 把这条链路内聚到这里，两边只需各加一行接线。
 */
import { ref } from 'vue'
import OcrPreviewModal from './OcrPreviewModal.vue'
import { useImagePaste } from '@/composables/useImagePaste'
import { useOrderOcr } from '../composables/useOrderOcr'
import type { ProductSuggestion, StagedItem } from '../composables/types'

const props = defineProps<{
  /** 确认后把条目交给暂存区 */
  addItems: (items: StagedItem[]) => void
  /** 表单当前选中的客户：图上没有客户信息时兜底 */
  defaultCustomer: string
  /** 表单当前选中的时间 */
  defaultDate: string
  searchProducts: (query: string) => Promise<ProductSuggestion[]>
  downloadTemplate: () => void
}>()

const emit = defineEmits<{
  /** 指引态「去录入」：由录入面板把焦点交给产品输入框 */
  'go-manual': []
}>()

const {
  recognizing,
  dialogOpen,
  draftItems,
  rawText,
  warnings,
  sourceName,
  emptyResult,
  unmatchedCount,
  invalidQuantityCount,
  missingCustomerCount,
  recognize,
  confirmImport,
  closeDialog,
} = useOrderOcr({
  addItems: (items) => props.addItems(items),
  getDefaultCustomer: () => props.defaultCustomer,
  getDefaultDate: () => props.defaultDate,
})

const pasteZoneRef = ref<HTMLElement | null>(null)
const imageInputRef = ref<HTMLInputElement | null>(null)

/**
 * 复用 useImagePaste：监听挂在 document 上，用户填表时不必先聚焦热区；
 * 被弹窗遮挡时不响应（预览弹窗自己用更高优先级接管弹窗内的粘贴）。
 */
useImagePaste({
  target: pasteZoneRef,
  onFile: (file) => void recognize(file),
})

function openImageDialog() {
  // 识别中再点：recognize() 会直接 return，选中的文件被静默丢弃——干脆不开选择器
  if (recognizing.value) return
  imageInputRef.value?.click()
}

/**
 * 指引态的两个出路都必须**先关弹窗**：
 * UiDialog 是模态的（焦点被锁在弹窗内），不关的话文件选择器会被盖住、
 * 「去录入」交出去的焦点也落在看不见的输入框上，按钮看起来毫无反应。
 */
function retryFromGuide() {
  closeDialog()
  openImageDialog()
}

function goManual() {
  closeDialog()
  emit('go-manual')
}

function handleImageSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  input.value = '' // 复位，允许连续选同一个文件
  if (file) void recognize(file)
}
</script>

<style scoped>
.op-paste {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  padding: 11px 12px;
  border: 2px dashed var(--color-ocean-deep);
  border-radius: var(--radius-input, 12px);
  background: linear-gradient(180deg, var(--color-ocean-light) 0%, white 100%);
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.op-paste:hover {
  border-color: var(--color-primary-500);
  box-shadow: var(--shadow-sm);
}
.op-paste:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}
.op-paste-busy {
  cursor: progress;
  border-color: var(--color-primary-400);
}
.op-paste-icon {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: var(--color-ocean-deep);
  color: white;
  font-size: 13px;
}
.op-paste-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.op-paste-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-ocean-text);
}
.op-paste-sub {
  font-size: 11.5px;
  color: var(--color-text-muted);
  margin-top: 1px;
}
.op-paste-go {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--color-primary-600);
}
.op-paste kbd {
  font-family: inherit;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 5px;
  border: 1px solid var(--color-slate-300, #cbd5e1);
  border-bottom-width: 2px;
  border-radius: 5px;
  background: white;
  color: var(--color-slate-600, #334155);
}
.op-paste-input {
  display: none;
}
</style>
