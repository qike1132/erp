<template>
  <div class="rp-filter-bar">
    <UiSelect
      v-model="filters.customer"
      placeholder="全部客户"
      style="width: 180px; flex-shrink: 0"
      :options="customerOptions"
    />

    <div class="rp-field">
      <UiInput
        v-model="filters.product"
        placeholder="产品名称 / SKU / 订单号"
        @keyup.enter="emit('search')"
      />
    </div>

    <UiButton variant="primary" class="rp-query" aria-label="查询" @click="emit('search')">查询</UiButton>
    <UiButton variant="outline" aria-label="重置" @click="emit('reset')">重置</UiButton>
    <UiButton
      v-if="searched"
      variant="success"
      aria-label="导出"
      @click="emit('export')"
    >
      <FontAwesomeIcon icon="download" aria-hidden="true" />导出 Excel
    </UiButton>
  </div>
</template>

<script setup lang="ts">
/**
 * ReportFilterBar.vue — 报表筛选与动作（嵌在单行工具条里）
 *
 * 控件一律用系统组件（UiSelect / UiInput / UiButton），不再自绘样式 ——
 * 自绘的输入框与系统下拉在高度、边框、底色上都不一致（2026-09-29 反馈）。
 * 日期区间筛选已按反馈移除；若之后要按日期过滤，系统里有现成的 UiDateRangePicker。
 */
import UiSelect from '@/components/ui/UiSelect.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiButton from '@/components/ui/UiButton.vue'

defineProps<{
  customerOptions: { value: string; label: string }[]
  searched: boolean
}>()

// 显式双向绑定：父组件 v-model:filters 传入，筛选条件就地编辑
const filters = defineModel<{ customer: string; product: string }>('filters', { required: true })

const emit = defineEmits<{
  'search': []
  'reset': []
  'export': []
}>()
</script>

<style scoped>
.rp-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

/* UiInput 自身是 w-full（表单里占满一行的写法），放进工具条需给定宽度 */
.rp-field {
  width: 220px;
  flex-shrink: 0;
}

/* 系统里 UiSelect(44px/白底/15px 字) 与 UiInput(42px/浅灰底/14px 字) 本身就有差异，
   同排并列时看得出参差。浅灰底这套是系统内三处输入控件（UiInput / UiSearchInput /
   PrimeVue inputtext）的共同口径，故把下拉对齐到输入框一侧。仅本页作用域内生效。 */
.rp-filter-bar :deep(.ui-select-input) {
  min-height: 42px;
  padding: 0.625rem 2.5rem 0.625rem 1rem;
  font-size: 0.875rem;
  background: #f8fafc;
}

/* 查询/重置/导出靠右成一排：筛选条件在左，动作按钮在右 */
.rp-query {
  margin-left: auto;
}
</style>
