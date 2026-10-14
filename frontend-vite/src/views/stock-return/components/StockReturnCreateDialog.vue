<template>
  <UiDialog
    :open="open"
    title="新增退货"
    max-width-class="max-w-[1320px]"
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

      <!-- 左选明细、右录退货信息：数量输入紧挨所选行，不再沉到弹窗最底部 -->
      <div class="sr-layout">
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

        <aside class="sr-pane sr-pane-form">
          <header class="sr-pane-head">
            <FontAwesomeIcon icon="list-check" aria-hidden="true" />
            <span>退货信息</span>
          </header>

          <template v-if="picked">
            <div class="sr-picked">
              <div class="sr-picked-row">
                <span class="k">出货单号</span>
                <span class="v mono">{{ form.stockout_no }}</span>
              </div>
              <div class="sr-picked-row">
                <span class="k">客户</span>
                <span class="v">{{ form.customer || '-' }}</span>
              </div>
              <div class="sr-picked-row">
                <span class="k">产品</span>
                <span class="v">{{ form.product_name }}</span>
              </div>
              <div class="sr-picked-row">
                <span class="k">可退数量</span>
                <span class="v hl">{{ form.available }} 件</span>
              </div>
            </div>

            <div class="sr-field">
              <label>退货数量（件）<span class="req">*</span></label>
              <div class="sr-qty">
                <input
                  v-model.number="form.quantity"
                  type="number"
                  min="1"
                  :max="form.available ?? undefined"
                  :placeholder="'不超过 ' + (form.available ?? '') + ' 件'"
                  class="sr-input"
                />
                <button
                  type="button"
                  class="sr-btn sr-btn-ghost"
                  :disabled="form.available == null"
                  @click="fillMax"
                >
                  全部退回
                </button>
              </div>
            </div>

            <div class="sr-field">
              <label>退货原因 <span class="req">*</span></label>
              <select v-model="form.reason" class="sr-select">
                <option value="" disabled>请选择</option>
                <option v-for="r in RETURN_REASON_OPTIONS" :key="r" :value="r">{{ r }}</option>
              </select>
            </div>

            <div class="sr-field">
              <label>备注</label>
              <textarea v-model="form.note" class="sr-textarea" rows="3" placeholder="运输破损、责任说明等可补充在此…" />
            </div>
          </template>

          <div v-else class="sr-pane-empty">
            <FontAwesomeIcon icon="hand-pointer" aria-hidden="true" />
            <p>请从左侧选择要退的出货明细</p>
          </div>
        </aside>
      </div>
    </div>

    <template #footer>
      <button class="sr-btn" :disabled="submitting" @click="emit('update:open', false)">取消</button>
      <button class="sr-btn sr-btn-primary" :disabled="submitting || !form.stockout_id" @click="emit('submit')">
        {{ submitting ? '提交中…' : '确认退货' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * StockReturnCreateDialog.vue - 新增退货弹窗（搜产品 -> 选出货明细 -> 录数量）
 *
 * 布局为两栏：左侧列出可退的出货明细（单号/客户/产品/可退/日期），右侧在选中行后就地
 * 录入退货数量/原因/备注——数量输入紧跟所选行，不再排在长表格下方需要滚动才能看到。
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
  gap: 16px;
  padding: 2px;
}

.sr-search-row {
  display: flex;
  gap: 8px;
}
.sr-search-row .sr-input.grow {
  flex: 1;
}

/* 两栏：左列出货明细，右录退货信息 */
.sr-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(320px, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .sr-layout {
    grid-template-columns: 1fr;
  }
}

.sr-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
}
.sr-pane-head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 50px;
  padding: 0 16px;
  flex-shrink: 0;
  background: #f8fafc;
  border-bottom: 1px solid var(--color-border, #e4e7ed);
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}
.sr-pane-head svg {
  width: 16px;
  height: 16px;
  color: var(--color-primary-500);
}
.sr-count {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-muted, #64748b);
}

.mono {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--color-primary-700);
}

.sr-pane-form {
  padding-bottom: 18px;
}
.sr-picked {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 16px 16px 0;
  padding: 14px 16px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 10px;
  background: var(--color-slate-50, #f8fafc);
}
.sr-picked-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 15px;
}
.sr-picked-row .k {
  width: 78px;
  flex-shrink: 0;
  color: var(--color-text-muted, #64748b);
}
.sr-picked-row .v {
  min-width: 0;
  color: var(--color-text);
  font-weight: 600;
  word-break: break-all;
}
.sr-picked-row .v.hl {
  color: var(--color-success-700, #2e7d32);
}

.sr-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 16px 16px 0;
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
.sr-select,
.sr-textarea {
  width: 100%;
  min-height: 46px;
  padding: 6px 12px;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 8px;
  font-size: 16px;
  font-family: inherit;
  color: var(--color-text);
  background: white;
  box-sizing: border-box;
}
.sr-textarea {
  resize: vertical;
}
.sr-input:focus,
.sr-select:focus,
.sr-textarea:focus {
  outline: none;
  border-color: var(--color-primary-300);
}

.sr-btn {
  min-height: 46px;
  padding: 0 22px;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 8px;
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

.sr-pane-empty {
  display: flex;
  flex: 1;
  min-height: 300px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  text-align: center;
  font-size: 15px;
  color: var(--color-text-muted, #94a3b8);
}
.sr-pane-empty svg {
  width: 30px;
  height: 30px;
  color: var(--color-primary-300, #9db8ff);
}
</style>
