<template>
  <!--
    汇总下单弹窗内会录入损耗率、逐行改数量，属于「有未保存内容」的编辑型弹窗，
    误触遮罩/空白处关闭会直接丢失输入，故显式关闭遮罩点击关闭行为。
    （UiDialog 默认允许遮罩点击关闭；此处仅对本弹窗覆盖，不影响其它弹窗。）
  -->
  <UiDialog
    :open="open"
    max-width-class="max-w-[1400px]"
    :close-on-overlay-click="false"
    @update:open="$emit('close')"
  >
    <template #title>
      <div class="flex items-center gap-2"><FontAwesomeIcon icon="clipboard-list" class="text-primary-500" aria-hidden="true" /> 汇总下单</div>
    </template>

    <!-- Tab headers -->
    <div class="sm-tab-group" role="tablist">
      <div
        role="tab"
        :aria-selected="activeTab === 'factory'"
        :class="['sm-tab-btn', { active: activeTab === 'factory' }]"
        @click="activeTab = 'factory'"
      >
        <FontAwesomeIcon icon="industry" aria-hidden="true" /> 工厂内部订单
      </div>
      <div
        role="tab"
        :aria-selected="activeTab === 'supplier'"
        :class="['sm-tab-btn', { active: activeTab === 'supplier', 'out-mode': activeTab === 'supplier' }]"
        @click="activeTab = 'supplier'"
      >
        <FontAwesomeIcon icon="truck" aria-hidden="true" /> 供应商采购订单
      </div>
    </div>

    <div class="py-4">
      <!-- Factory Tab -->
      <SummaryFactoryTab
        v-if="activeTab === 'factory' && factoryData"
        :factory-data="factoryData"
        :edit-mode="editMode"
        :loss-rate="lossRate"
        :order-count="orderCount"
        :loss-rate-save-state="lossRateSaveState"
        :loss-rate-mixed="lossRateMixed"
        @close="$emit('close')"
        @toggle-edit-mode="$emit('toggleEditMode', $event)"
        @save-edits="$emit('saveEdits')"
        @update-qty="(gi, si, fi, value) => $emit('updateQty', gi, si, fi, value)"
        @loss-rate-input="applyLossRateDebounced"
        @export-factory="$emit('exportFactory')"
        @print-factory="$emit('printFactory')"
      />

      <!-- Supplier Tab -->
      <SummarySupplierTab
        v-if="activeTab === 'supplier' && supplierData"
        :supplier-data="supplierData"
        :order-count="orderCount"
        :supplier-groups="supplierGroups"
        @close="$emit('close')"
        @export-supplier="$emit('exportSupplier')"
        @print-supplier="$emit('printSupplier')"
      />
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * SummaryModal.vue — 汇总下单弹窗外壳（页签切换 + 事件转发）。
 *
 * 两个页签各自独立成组件（与 SummarySupplierTab.vue 对称）：
 * - `SummaryFactoryTab.vue` — 工厂内部订单（含损耗率输入、逐 SKU 分行、编辑态数量输入）
 * - `SummarySupplierTab.vue` — 供应商采购订单
 *
 * 拆分为的是把本文件压回质量门禁的「单 SFC ≤400 行」阈值。**对外契约零改动**：
 * props / emits 与拆分前逐字一致，PurchaseView.vue 无需任何改动；子组件事件在此
 * 原样转发，行为与视觉不变（表格外观由子组件各自的 `summary-tables.scss` 提供）。
 *
 * ⚠️ 损耗率防抖（300ms）**留在本组件**，不下放到 SummaryFactoryTab：工厂页签位于
 * `v-if` 之下，用户在防抖窗口内切页签会让该子组件卸载，若定时器在子组件内则
 * `emit` 无监听者、刚输入的损耗率被静默丢弃。本组件不随页签切换卸载，行为与拆分前一致。
 */
import { ref } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import UiDialog from '@/components/ui/UiDialog.vue'
import SummaryFactoryTab from './SummaryFactoryTab.vue'
import SummarySupplierTab from './SummarySupplierTab.vue'
import type { FactorySummaryData, SupplierSummaryData, MaterialItem } from '../composables/useSummaryModal'

defineProps<{
  open: boolean
  factoryData: FactorySummaryData | null
  supplierData: SupplierSummaryData | null
  editMode: boolean
  lossRate: number
  orderCount: number
  supplierGroups: { supplierName: string; materials: MaterialItem[] }[]
  /** 损耗率自动落库的可见反馈状态（缺省视为 idle；由 useSummaryModal 提供） */
  lossRateSaveState?: 'idle' | 'saving' | 'saved' | 'error'
  /** 各单损耗率不一致（缺省视为 false；由 useSummaryModal 提供）→ 输入框旁提示 */
  lossRateMixed?: boolean
}>()

const emit = defineEmits<{
  close: []
  toggleEditMode: [enable: boolean]
  saveEdits: []
  updateQty: [gi: number | string, si: number | string, fi: number | string, value: string]
  applyLossRate: [rate: number]
  exportFactory: []
  exportSupplier: []
  printFactory: []
  printSupplier: []
}>()

const activeTab = ref<'factory' | 'supplier'>('factory')

/**
 * P1-4: 损耗率输入防抖 300ms，避免每次按键触发全量 groups×suppliers×fabrics×materials 重算。
 * 定时器归属本组件（弹窗外壳）而非页签子组件，确保防抖窗口内切换页签不丢输入。
 */
const applyLossRateDebounced = useDebounceFn((v: number) => emit('applyLossRate', v), 300)
</script>

<style scoped>
.sm-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  margin-bottom: 12px;
}
.sm-tab-btn {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: color 0.3s ease, background 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sm-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.sm-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.sm-tab-btn.active.out-mode {
  background: linear-gradient(135deg, var(--color-danger-50), var(--color-danger-100));
  color: var(--color-danger-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(234, 84, 85, 0.2);
}
</style>
