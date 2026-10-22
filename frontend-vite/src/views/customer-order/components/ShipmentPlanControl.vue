<template>
  <div :class="['plan-row', hasPlans && 'plan-row-active', invalid && 'plan-row-invalid']">
    <div class="plan-check-group">
      <UiCheckbox
        :checked="hasPlans"
        aria-label="是否有出货计划"
        name="has-shipment-plan"
        @update:checked="onToggle"
      />
      <label class="plan-label" @click="onToggle">有出货计划</label>
      <span class="plan-hint">提交时按批次同步至采购计划系统</span>
    </div>
    <div :class="['plan-date-wrap', hasPlans && 'plan-date-open']">
      <div class="plan-date-inner">
        <div v-for="(plan, idx) in model.shipmentPlans" :key="rowIds[idx]" class="plan-split-row">
          <span class="plan-batch-no">第{{ idx + 1 }}批</span>
          <UiDatePicker
            :model-value="plan.date"
            label=""
            style="width: 150px; flex-shrink: 0"
            @update:model-value="(v: string) => updateSplit(idx, 'date', v)"
          />
          <input
            :value="plan.quantity"
            type="number"
            class="plan-qty-input"
            :min="1"
            :max="QUANTITY_MAX"
            step="1"
            aria-label="批次数量"
            @input="updateSplit(idx, 'quantity', Number(($event.target as HTMLInputElement).value) || 0)"
          />
          <input
            :value="plan.note"
            type="text"
            class="plan-note-input"
            placeholder="批次备注（如：首批急发）"
            aria-label="批次备注"
            @input="updateSplit(idx, 'note', ($event.target as HTMLInputElement).value)"
          />
          <button
            type="button"
            class="plan-remove-btn"
            :aria-label="`删除第${idx + 1}批`"
            :disabled="model.shipmentPlans.length <= 1"
            @click="removeSplit(idx)"
          >
            <FontAwesomeIcon icon="trash" aria-hidden="true" />
          </button>
        </div>
        <div class="plan-split-footer">
          <button type="button" class="plan-add-btn" @click="addSplit">
            <FontAwesomeIcon icon="plus" aria-hidden="true" />添加一批
          </button>
          <span :class="['plan-total', invalid && 'plan-total-bad']">
            已分配 {{ allocated }} / 订单量 {{ model.quantity }}
            <template v-if="invalid">（{{ invalid }}）</template>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import { QUANTITY_MAX } from '../composables/quantityRange'
import { planSplitsMessage, sumSplitQuantity } from '../composables/shipmentPlanRules'
import type { FormState, ShipmentPlanSplit } from '../composables/types'

/**
 * 分批出货计划控件（2026-10-06 v2）：
 * 复选框「有出货计划」+ 多行批次编辑器（日期/数量/备注，增删行）。
 * 口径：各批数量之和必须排满订单数量（planSplitsMessage 给出原因）。
 * 仅订单模式挂载（v-if 在父组件）；未勾选时界面与原流程零差异。
 */
const model = defineModel<FormState>('form', { required: true })

// 稳定行 key：批次对象没有 id，用并行 id 数组避免删中间行后焦点/日期面板状态错位
const rowIds = ref<string[]>([])
let seq = 0
function newRowId() {
  return `sp-${++seq}`
}
watch(
  () => model.value.shipmentPlans.length,
  (n) => {
    while (rowIds.value.length < n) rowIds.value.push(newRowId())
    if (rowIds.value.length > n) rowIds.value.splice(n)
  },
  { immediate: true },
)

const hasPlans = computed(() => model.value.shipmentPlans.length > 0)
const allocated = computed(() => sumSplitQuantity(model.value.shipmentPlans))
const invalid = computed(() => planSplitsMessage(model.value.shipmentPlans, model.value.quantity))

/** 勾选时自动生成首行（数量=订单全量），单批用户改个日期即可提交 */
function onToggle() {
  if (hasPlans.value) {
    model.value.shipmentPlans = []
    return
  }
  model.value.shipmentPlans = [{ date: '', quantity: Math.max(1, model.value.quantity), note: '' }]
}

function updateSplit(idx: number, key: keyof ShipmentPlanSplit, value: string | number) {
  const row = model.value.shipmentPlans[idx]
  if (!row) return
  row[key] = value as never
}

/** 追加一批：数量默认填当前剩余（剩余为 0 时空着让用户自己调整） */
function addSplit() {
  const remain = Math.max(0, model.value.quantity - allocated.value)
  model.value.shipmentPlans.push({ date: '', quantity: remain, note: '' })
}

function removeSplit(idx: number) {
  if (model.value.shipmentPlans.length <= 1) return
  rowIds.value.splice(idx, 1)
  model.value.shipmentPlans.splice(idx, 1)
}
</script>

<style scoped>
.plan-row {
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 14px;
  transition: border-color 0.2s ease, background 0.2s ease;
}
/* 勾选态 = 视觉锚点：primary-50 底 + primary-200 描边（与 co-tab-btn.active 同语言） */
.plan-row-active {
  background: var(--color-primary-50);
  border-color: var(--color-primary-200, var(--color-primary-100));
}
/* 排满口径违规：danger 描边（底色保持 primary 锚点语义不变） */
.plan-row-invalid {
  border-color: var(--color-danger-500);
}
.plan-check-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.plan-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  cursor: pointer;
  user-select: none;
}
.plan-hint {
  font-size: 12px;
  color: var(--color-text-muted);
}
.plan-date-wrap {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
}
.plan-date-open {
  grid-template-rows: 1fr;
  opacity: 1;
  margin-top: 8px;
}
.plan-date-inner {
  overflow: hidden;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.plan-split-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.plan-batch-no {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-700, var(--color-primary-600));
  flex-shrink: 0;
  width: 38px;
}
.plan-qty-input,
.plan-note-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
  outline: none;
  background: white;
  font-family: inherit;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.plan-qty-input {
  width: 90px;
  flex-shrink: 0;
  -moz-appearance: textfield;
}
.plan-qty-input::-webkit-inner-spin-button,
.plan-qty-input::-webkit-outer-spin-button {
  opacity: 1;
}
.plan-note-input {
  flex: 1;
  min-width: 0;
}
.plan-qty-input:focus-visible,
.plan-note-input:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
  border-color: var(--color-primary-400);
}
.plan-remove-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: var(--color-danger-50);
  color: var(--color-danger-500);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 12px;
  transition: background 0.2s ease;
}
.plan-remove-btn:hover:not(:disabled) {
  background: var(--color-danger-100);
}
.plan-remove-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.plan-split-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 2px;
}
.plan-add-btn {
  border: 1px dashed var(--color-primary-300, var(--color-border, #cbd5e1));
  background: transparent;
  color: var(--color-primary-600);
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: background 0.2s ease;
}
.plan-add-btn:hover {
  background: var(--color-primary-50);
}
.plan-total {
  font-size: 12px;
  color: var(--color-success-700, var(--color-text-secondary));
  font-weight: 500;
}
.plan-total-bad {
  color: var(--color-danger-600);
}
@media (prefers-reduced-motion: no-preference) {
  .plan-date-wrap {
    transition: grid-template-rows 0.16s ease, opacity 0.16s ease;
  }
}
</style>
