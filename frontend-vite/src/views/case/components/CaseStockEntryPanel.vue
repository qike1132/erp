<template>
  <div class="cs-top-row">
    <CaseStockEntryForm
      v-model:form="form"
      :mode="mode"
      :staged="staged"
      :current-stock="currentStock"
      :customer-options="customerOptions"
      :can-add="canAdd"
      :search-fn="searchFn"
      @product-select="(p) => emit('product-select', p)"
      @add-staged="() => emit('add-staged')"
    />
    <CaseStagedAndBatch
      v-model:show-batch-upload="showBatchUpload"
      :mode="mode"
      :staged="staged"
      :excel-file="excelFile"
      :importing="importing"
      :template-downloading="templateDownloading"
      @remove-staged="(idx) => emit('remove-staged', idx)"
      @excel-change="(files) => emit('excel-change', files)"
      @download-template="() => emit('download-template')"
      @import-excel="() => emit('import-excel')"
    />
  </div>
</template>

<script setup lang="ts">
import CaseStockEntryForm from './CaseStockEntryForm.vue'
import CaseStagedAndBatch from './CaseStagedAndBatch.vue'
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
  excelFile: File | null
  importing: boolean
  templateDownloading: boolean
}>()

const showBatchUpload = defineModel<boolean>('showBatchUpload', { default: false })
const form = defineModel<CaseStockFormState>('form', { required: true })

const emit = defineEmits<{
  'product-select': [product: CaseProductOption]
  'add-staged': []
  'remove-staged': [idx: number]
  'excel-change': [files: FileList]
  'download-template': []
  'import-excel': []
}>()
</script>

<style scoped>
.cs-top-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 992px) {
  .cs-top-row { grid-template-columns: 1fr; }
}
</style>
