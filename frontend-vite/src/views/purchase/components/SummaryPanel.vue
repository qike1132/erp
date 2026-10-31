<template>
  <!--
    汇总下单整页视图（2026-10-31 由弹窗改为铺满内容区，需求：用户嫌弹窗局促）。
    结构：头部（标题+页签+返回）→ 表体（唯一滚动区，flex 撑满）→ 底部操作条。
    侧边栏保留；「编辑态离开需确认」由 PurchaseView 的 useSummaryLeaveGuard 把守。
  -->
  <div class="sm-panel">
    <!-- 头部：标题 + 页签（左） / 返回订单列表（右） -->
    <div class="sm-header">
      <div class="sm-title-block">
        <div class="sm-title">
          <FontAwesomeIcon icon="clipboard-list" class="text-primary-500" aria-hidden="true" /> 汇总下单
        </div>
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
      </div>
      <button
        class="sm-back-btn"
        :title="editMode ? '编辑态返回需确认' : '返回订单列表'"
        @click="$emit('close')"
      >
        <FontAwesomeIcon icon="arrow-left" aria-hidden="true" /> 返回订单列表
      </button>
    </div>

    <!-- 表体：唯一滚动区。页签切换用 v-if（不换页签不卸载子组件的表格 DOM 无益，
         但换页签卸载可减轻长表格的常驻 DOM——与拆分前的弹窗行为一致） -->
    <div class="sm-body">
      <!-- Factory Tab -->
      <SummaryFactoryTab
        v-if="activeTab === 'factory' && factoryData"
        :factory-data="factoryData"
        :edit-mode="editMode"
        :loss-rate="lossRate"
        :order-count="orderCount"
        :loss-rate-save-state="lossRateSaveState"
        :loss-rate-mixed="lossRateMixed"
        :fabric-loss-rates="fabricLossRates"
        :fabric-loss-rate-mixed="fabricLossRateMixed"
        :group-spare-rates="groupSpareRates"
        @close="$emit('close')"
        @toggle-edit-mode="onToggleEditMode"
        @save-edits="$emit('saveEdits')"
        @update-qty="(gi, si, fi, value) => $emit('updateQty', gi, si, fi, value)"
        @loss-rate-input="applyLossRateDebounced"
        @fabric-loss-rate-input="applyFabricLossRateDebounced"
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
  </div>
</template>

<script setup lang="ts">
/**
 * SummaryPanel.vue — 汇总下单整页视图外壳（页签切换 + 事件转发）。
 *
 * 2026-10-31 由 SummaryModal.vue（UiDialog 弹窗）整页化而来：保留侧边栏、
 * 占满内容区；props/emits 契约除删去 open 外与弹窗版逐字一致，
 * 两个页签子组件（SummaryFactoryTab / SummarySupplierTab）零改动可复用。
 *
 * ⚠️ 损耗率防抖（300ms）**留在本组件**，不下放到 SummaryFactoryTab：工厂页签位于
 * `v-if` 之下，用户在防抖窗口内切页签会让该子组件卸载，若定时器在子组件内则
 * `emit` 无监听者、刚输入的损耗率被静默丢弃。本组件不随页签切换卸载，行为与
 * 弹窗版一致。
 */
import { ref, onUnmounted } from 'vue'
import SummaryFactoryTab from './SummaryFactoryTab.vue'
import SummarySupplierTab from './SummarySupplierTab.vue'
import type { FactorySummaryData, SupplierSummaryData, MaterialItem } from '../composables/useSummaryModal'

defineProps<{
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
  /** 每个布料行当前的损耗率（由 useSummaryModal 提供） */
  fabricLossRates?: number[][][]
  /** 每个布料行内各明细损耗率是否不一致（由 useSummaryModal 提供） */
  fabricLossRateMixed?: boolean[][][]
  /** 每个分组的订单级损耗率（「备品数量」列唯一口径，由 useSummaryModal 提供） */
  groupSpareRates?: number[]
}>()

const emit = defineEmits<{
  close: []
  toggleEditMode: [enable: boolean]
  saveEdits: []
  updateQty: [gi: number | string, si: number | string, fi: number | string, value: string]
  applyLossRate: [rate: number]
  applyFabricLossRate: [gi: number, si: number, fi: number, rate: number]
  exportFactory: []
  exportSupplier: []
  printFactory: []
  printSupplier: []
}>()

const activeTab = ref<'factory' | 'supplier'>('factory')

/**
 * P1-4: 损耗率输入防抖 300ms，避免每次按键触发全量 groups×suppliers×fabrics×materials 重算。
 * 定时器归属本组件（整页外壳）而非页签子组件，确保防抖窗口内切换页签不丢输入。
 * 不用 useDebounceFn：当前 @vueuse 版本的返回值没有 cancel，取消编辑时无法作废挂起值。
 */
let lossRateTimer: ReturnType<typeof setTimeout> | null = null
function applyLossRateDebounced(v: number) {
  if (lossRateTimer) clearTimeout(lossRateTimer)
  lossRateTimer = setTimeout(() => {
    lossRateTimer = null
    emit('applyLossRate', v)
  }, 300)
}

/** 单个布料行损耗率输入防抖：按行独立计时，快速连续改多行时不能互相取消。 */
const fabricLossRateTimers = new Map<string, ReturnType<typeof setTimeout>>()
function applyFabricLossRateDebounced(gi: number, si: number, fi: number, v: number) {
  const key = `${gi}-${si}-${fi}`
  const timer = fabricLossRateTimers.get(key)
  if (timer) clearTimeout(timer)
  fabricLossRateTimers.set(key, setTimeout(() => {
    fabricLossRateTimers.delete(key)
    emit('applyFabricLossRate', gi, si, fi, v)
  }, 300))
}

function cancelPendingRateEdits() {
  if (lossRateTimer) { clearTimeout(lossRateTimer); lossRateTimer = null }
  fabricLossRateTimers.forEach((timer) => clearTimeout(timer))
  fabricLossRateTimers.clear()
}

/**
 * 只有点击「取消编辑」才作废挂起的防抖。
 * 不能 watch editMode→false：保存修改/播种同样会置 false，会把用户刚输入、
 * 尚未到点落库的损耗率静默丢掉（且 saveFactoryEdits 不会代为提交）。
 */
function onToggleEditMode(enable: boolean) {
  if (!enable) cancelPendingRateEdits()
  emit('toggleEditMode', enable)
}
onUnmounted(cancelPendingRateEdits)
</script>

<style scoped>
/* 整页外壳：占满父容器（PurchaseView 的 .pc-container → page-card-body 链路），
   唯一滚动区是表体。与 /stock 的 .sk-card-main 同一套 flex 约束。 */
.sm-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.sm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}
.sm-title-block {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.sm-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
}
.sm-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: color 0.3s ease, background 0.3s ease;
  white-space: nowrap;
  flex-shrink: 0;
}
.sm-back-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-500);
}
.sm-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sm-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
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
