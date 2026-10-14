<template>
  <UiDialog
    :open="open"
    title="新增退货"
    max-width-class="max-w-[1600px]"
    :close-on-overlay-click="false"
    @update:open="emit('update:open', $event)"
  >
    <div class="sr-dialog-body">
      <div class="sr-search-row">
        <input
          v-model="searchKeyword"
          class="sr-input grow"
          placeholder="输入产品名称搜索出货明细，如：鲨鱼"
          @keyup.enter="emit('search')"
        />
        <button class="sr-btn sr-btn-primary" :disabled="loadingShipments" @click="emit('search')">
          {{ loadingShipments ? '搜索中…' : '搜索' }}
        </button>
      </div>

      <!-- 单列：明细表在上；录入区放在弹窗 footer（固定不滚动），见下方 #footer 插槽 -->
      <section class="sr-pane">
        <header class="sr-pane-head">
          <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />
          <span>可退出货明细</span>
          <span class="sr-count">{{ shipments.length }} 条</span>
        </header>
        <StockReturnShipmentList
          :shipments="shipments"
          :loading="loadingShipments"
          :picked-id="pickedId"
          @pick="onPick"
        />
      </section>
    </div>

    <!-- 固定在弹窗底部：列表再长也一直看得见，不用滚到底 -->
    <template #footer>
      <div class="sr-entry">
        <div class="sr-entry-head">
          <template v-if="picked">
            已选 <b class="mono">{{ form.stockout_no }}</b>
            <span class="sr-dot" />
            {{ form.customer || '-' }}
            <span class="sr-dot" />
            可退 <b class="hl">{{ form.available }}</b> 件
          </template>
          <span v-else class="sr-entry-hint">
            <FontAwesomeIcon icon="hand-pointer" aria-hidden="true" />
            请先在上方选择要退的出货明细
          </span>
        </div>

        <div class="sr-entry-grid">
          <div class="sr-field">
            <label>退货数量（件）<span class="req">*</span></label>
            <div class="sr-qty">
              <input
                v-model.number="form.quantity"
                type="number"
                min="1"
                :max="form.available ?? undefined"
                :disabled="!picked"
                :placeholder="'不超过 ' + (form.available ?? '') + ' 件'"
                class="sr-input"
              />
              <button
                type="button"
                class="sr-btn sr-btn-ghost"
                :disabled="!picked || form.available == null"
                @click="fillMax"
              >
                全部退回
              </button>
            </div>
          </div>
          <div class="sr-field">
            <label>退货原因 <span class="req">*</span></label>
            <select v-model="form.reason" class="sr-select" :disabled="!picked">
              <option value="" disabled>请选择</option>
              <option v-for="r in RETURN_REASON_OPTIONS" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>
          <div class="sr-field">
            <label>备注</label>
            <input
              v-model="form.note"
              type="text"
              :disabled="!picked"
              placeholder="运输破损、责任说明等可补充在此…"
              class="sr-input"
            />
          </div>
        </div>

        <div class="sr-entry-actions">
          <button class="sr-btn" :disabled="submitting" @click="emit('update:open', false)">取消</button>
          <button class="sr-btn sr-btn-primary" :disabled="submitting || !picked" @click="emit('submit')">
            {{ submitting ? '提交中…' : '确认退货' }}
          </button>
        </div>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * StockReturnCreateDialog.vue - 新增退货弹窗（搜产品 -> 选出货明细 -> 录数量）
 *
 * 布局（2026-10-14 定稿，方案 C）：单列，明细表在上；退货数量/原因/备注放在弹窗
 * footer 里做成**固定录入条**，不随列表滚动。既没有左右分栏，输入框也不会沉到
 * 长表格底部 —— 列表再长，录入条一直在眼前。
 * 可退量 = 明细出货量 - 已退量；客户/产品由明细带出，无需单独录入。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import StockReturnShipmentList from './StockReturnShipmentList.vue'
import type { ShipmentOption } from '@/api/stockReturn'
import { RETURN_REASON_OPTIONS, type StockReturnFormData } from '../composables/useStockReturn'

defineProps<{
  open: boolean
  submitting: boolean
  shipments: ShipmentOption[]
  loadingShipments: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  submit: []
  search: []
  pick: [row: ShipmentOption]
}>()

/** 表单对象由 composable 持有（reactive）；经 v-model:form 传入，避免直接改 prop */
const form = defineModel<StockReturnFormData>('form', { required: true })

const searchKeyword = defineModel<string>('searchKeyword', { required: true })

const pickedId = computed(() => form.value.stockout_id)
const picked = computed(() => !!form.value.stockout_id)

function onPick(s: ShipmentOption) {
  emit('pick', s)
}

/** 「全部退回」：把退货数量一键填成当前可退上限 */
function fillMax() {
  if (form.value.available != null) form.value.quantity = form.value.available
}
</script>

<style scoped>
.sr-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 2px;
}

.sr-search-row {
  display: flex;
  gap: 8px;
}
.sr-search-row .sr-input.grow {
  flex: 1;
}

/* 不再 overflow:hidden —— 否则表头 position:sticky 会失效（弹窗 body 才是滚动容器） */
.sr-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 12px;
  background: #fff;
}
.sr-pane-head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 54px;
  padding: 0 18px;
  flex-shrink: 0;
  background: #f8fafc;
  border-bottom: 1px solid var(--color-border, #e4e7ed);
  border-radius: 12px 12px 0 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}
.sr-pane-head svg {
  width: 17px;
  height: 17px;
  color: var(--color-primary-500);
}
.sr-count {
  margin-left: auto;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-muted, #64748b);
}

/* ===== 底部固定录入条（由 UiDialog 的 #footer 插槽承载，本身不滚动） ===== */
.sr-entry {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sr-entry-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--color-text-secondary);
}
.sr-entry-head .mono {
  font-family: var(--font-mono);
  color: var(--color-primary-700);
}
.sr-entry-head .hl {
  color: var(--color-success-700, #2e7d32);
}
.sr-entry-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-muted, #94a3b8);
}
.sr-entry-hint svg {
  width: 15px;
  height: 15px;
  color: var(--color-primary-300, #9db8ff);
}
.sr-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--color-border, #cbd5e1);
}
.sr-entry-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1.3fr;
  gap: 14px 18px;
}
.sr-entry-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.sr-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}
.sr-field label {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text-secondary);
}
.sr-field .req {
  color: var(--color-danger-500);
}
.sr-qty {
  display: flex;
  gap: 8px;
}
.sr-qty .sr-input {
  flex: 1;
}

.sr-input,
.sr-select {
  width: 100%;
  min-height: 46px;
  padding: 8px 14px;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 10px;
  font-size: 16px;
  font-family: inherit;
  color: var(--color-text);
  background: white;
  box-sizing: border-box;
}
.sr-input:focus,
.sr-select:focus {
  outline: none;
  border-color: var(--color-primary-300);
}
.sr-input:disabled,
.sr-select:disabled {
  background: var(--color-slate-50, #f8fafc);
  color: var(--color-text-muted, #94a3b8);
  cursor: not-allowed;
}

.sr-btn {
  min-height: 46px;
  padding: 0 22px;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 10px;
  background: white;
  font-size: 16px;
  font-weight: 700;
  white-space: nowrap;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.sr-btn-primary {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}
.sr-btn-ghost {
  background: var(--color-primary-50, #eff5ff);
  border-color: var(--color-primary-200, #cfe0ff);
  color: var(--color-primary-600);
}
.sr-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 搜索行是整块内容区里唯一的“大”输入，比录入条略高 */
.sr-search-row .sr-input,
.sr-search-row .sr-btn {
  min-height: 52px;
  font-size: 17px;
}

@media (max-width: 1100px) {
  .sr-entry-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
