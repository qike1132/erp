<template>
  <Transition name="pr-qe">
    <!-- 遮罩不绑点击关闭：误触空白会丢掉已输一半的录入内容，只能用右上角 ✕ 或 Esc 关（关闭时自动留草稿） -->
    <div v-if="openModel" class="pr-qe-overlay">
      <div class="pr-qe-modal" role="dialog" aria-labelledby="pr-qe-title" @keydown="onModalKeydown">
        <header class="pr-qe-header">
          <div class="pr-qe-head-left">
            <h3 id="pr-qe-title">录入生产数据</h3>
            <span class="pr-qe-sub">{{ currentDept.label }} · {{ selectedDate }} · 今日已录 {{ todayCount }} 条</span>
          </div>
          <div class="pr-qe-head-right">
            <span class="pr-qe-head-meta">可一次提交多个 SKU</span>
            <button class="pr-qe-close" aria-label="关闭" @click="closeEntryDrawer"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
          </div>
        </header>

        <template v-if="submitState === 'editing'">
          <!-- 整单共用的上下文：部门 / 客户 / 日期，只选一次 -->
          <div class="pr-qe-ctx">
            <div class="pr-qe-seg" data-test="qe-dept" role="group" aria-label="生产部门">
              <button
                v-for="d in departments"
                :key="d.value"
                type="button"
                :class="['pr-qe-seg-btn', { on: formDept === d.value }]"
                :data-dept="d.value"
                :aria-pressed="formDept === d.value"
                @click="pickDept(d.value)"
              >
                <FontAwesomeIcon :icon="d.icon" aria-hidden="true" />{{ d.label }}
              </button>
            </div>
            <CustomerSelect
              data-test="qe-customer"
              :model-value="customerId"
              :options="customerOptions"
              placeholder="客户（选填）"
              @update:model-value="selectCustomer"
            />
            <label class="pr-qe-date">
              <span>日期</span>
              <input v-model="selectedDateModel" type="date" data-test="qe-date" aria-label="生产日期" />
            </label>
            <div class="pr-qe-sp" />
            <span
              v-if="batchColumnOn && rows.length && batchFilledCount < rows.length"
              class="pr-qe-batchstat"
              data-test="qe-banner"
              :title="batchRequired ? '该客户要求每条都填批次号' : '包装部成品库存批次，可按需填写'"
            >
              批次 {{ batchFilledCount }}/{{ rows.length }}
              <b v-if="batchRequired">必填</b>
            </span>
            <label class="pr-qe-switch" title="包装部自动开启；其它部门按客户记住，下次选这个客户会自动带上">
              <input type="checkbox" :checked="batchColumnOn" data-test="qe-batch-switch" @change="onBatchSwitch" />
              <i /><span>批次号列</span>
            </label>
          </div>

          <div class="pr-qe-body">
            <div class="pr-qe-main">
              <!-- 连续加 SKU：搜索回车即追加一行，焦点落到该行数量 -->
              <div class="pr-qe-add">
                <div class="pr-qe-search">
                  <FontAwesomeIcon icon="search" class="pr-qe-search-icon" aria-hidden="true" />
                  <input
                    ref="productSearchRef"
                    v-model="searchQuery"
                    type="text"
                    data-test="qe-search"
                    class="pr-qe-input pr-qe-search-input"
                    placeholder="输入产品名称或 69 码，回车加入一行（可连续加）"
                    autocomplete="off"
                    @input="onSearchInput"
                    @focus="onSearchFocus"
                    @blur="onSearchBlur"
                    @keydown.down.prevent="moveSearchIndex(1)"
                    @keydown.up.prevent="moveSearchIndex(-1)"
                    @keydown.enter.prevent="confirmSearchSelection"
                  />
                  <ProductSearchDropdown
                    v-if="showDropdown"
                    :search-loading="searchLoading"
                    :search-error="searchError"
                    :search-results="searchResults"
                    :search-active-index="searchActiveIndex"
                    :hint="searchHint"
                    @select="selectProduct"
                  />
                </div>
                <button type="button" class="pr-qe-paste" data-test="qe-paste-open" @click="pasteOpen = true">
                  <FontAwesomeIcon icon="paste" aria-hidden="true" /> 粘贴 Excel
                </button>
              </div>

              <ProductionEntryTable
                :rows="rows"
                :batch-column-on="batchColumnOn"
                :batch-required="batchRequired"
                :is-packaging="isPackaging"
                :disabled="isSubmitting"
                @remove="removeRow"
                @adjust="adjustRowQty"
                @qty-arrow="onRowQtyArrow"
                @qty-enter="onRowQtyEnter"
                @fill-batch="fillBatchColumn"
              />
            </div>

            <!-- 右侧：该客户最近录入过的 SKU，点一条直接加一行 -->
            <ProductionEntryRecent
              v-if="customerId != null"
              :items="customerRecent"
              :loading="recentLoading"
              :customer-name="customerName"
              @add="addRecentSku"
              @browse="browseProducts"
            />
          </div>

          <footer class="pr-qe-foot">
            <div class="pr-qe-totals">
              <span>共 <b data-test="qe-total-sku">{{ totals.sku }}</b> 个 SKU</span>
              <span>合计 <b data-test="qe-total-qty">{{ totals.qty }}</b> 件</span>
              <span>货值 <b class="val" data-test="qe-total-value">{{ formatCurrency(totals.value) }}</b></span>
            </div>
            <button type="button" class="pr-qe-btn" data-test="qe-draft" :disabled="!rows.length" @click="saveDraft()">存草稿</button>
            <button type="button" class="pr-qe-btn" data-test="qe-clear" :disabled="!rows.length || isSubmitting" @click="clearRows">清空</button>
            <button
              type="button"
              data-test="qe-submit"
              class="pr-qe-submit"
              aria-label="批量提交 Ctrl+Enter"
              :disabled="!canSubmit"
              @click="submitBatch"
            >
              <UiLoadingIcon :loading="isSubmitting" icon="check" />
              <span>批量提交</span>
              <span class="pr-qe-submit-hint">Ctrl ⏎</span>
            </button>
          </footer>
        </template>

        <ProductionEntryDone
          v-else
          :created="createdBatch"
          :dept-label="currentDept.label"
          :date="selectedDate"
          @again="startNewBatch"
          @close="closeEntryDrawer"
          @undo="requestUndo"
        />

        <ProductionEntryPaste v-model:open="pasteOpen" @import="importPaste" />

        <!-- 撤销确认：物理删除不可恢复，层级必须抬到嵌套层（--z-overlay/modal-nested），
             否则会被同为 var(--z-modal) 的弹窗卡盖住而点不到。 -->
        <UiConfirmDialog
          :open="undoConfirmOpen"
          type="danger"
          :text="undoText"
          sub="物理删除，不可恢复"
          overlay-z-class="z-[var(--z-overlay-nested)]"
          content-z-class="z-[var(--z-modal-nested)]"
          @confirm="confirmUndo"
          @cancel="undoConfirmOpen = false"
        />
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatCurrency } from '@/utils/format'
import ProductSearchDropdown from './ProductSearchDropdown.vue'
import CustomerSelect from './CustomerSelect.vue'
import ProductionEntryTable from './ProductionEntryTable.vue'
import ProductionEntryPaste from './ProductionEntryPaste.vue'
import ProductionEntryDone from './ProductionEntryDone.vue'
import ProductionEntryRecent from './ProductionEntryRecent.vue'
import { useProductionEntry } from '@/views/production/composables/useProductionEntry'

const props = defineProps<{
  open: boolean
  selectedDate: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:selectedDate': [value: string]
}>()

const openModel = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})
const selectedDateModel = computed({
  get: () => props.selectedDate,
  set: (v: string) => emit('update:selectedDate', v),
})

const {
  departments, formDept, currentDept, isPackaging, isSubmitting, submitState, createdBatch,
  undoConfirmOpen, undoText, pasteOpen, customerRecent, recentLoading, addRecentSku, browseProducts,
  rows, totals, canSubmit,
  customerId, customerName, customerOptions, selectCustomer, batchColumnOn, batchRequired, batchFilledCount,
  toggleBatchColumn, fillBatchColumn, adjustRowQty, onRowQtyArrow, onRowQtyEnter,
  selectProduct, removeRow, clearRows, searchQuery, searchResults, showDropdown, searchLoading,
  searchError, searchActiveIndex, searchHint, productSearchRef, onSearchInput, onSearchFocus, onSearchBlur,
  moveSearchIndex, confirmSearchSelection, submitBatch, requestUndo, confirmUndo, saveDraft,
  importPaste, startNewBatch, todayCount, closeEntryDrawer, pickDept, onModalKeydown,
} = useProductionEntry(openModel, selectedDateModel)

function onBatchSwitch(event: Event) {
  toggleBatchColumn((event.target as HTMLInputElement).checked)
}

defineExpose({ handleSubmit: submitBatch, closeEntryDrawer })
</script>

<style scoped>
.pr-qe-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(6px); z-index: var(--z-modal); display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }
.pr-qe-modal { position: relative; width: 1360px; min-height: 600px; max-width: 100%; max-height: 100%; background: white; border-radius: 14px; display: flex; flex-direction: column; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16), 0 2px 6px rgba(15, 23, 42, 0.06); overflow: hidden; }
.pr-qe-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px 30px; background: #fff; border-bottom: 1px solid var(--color-border); flex-shrink: 0; }
.pr-qe-head-left { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.pr-qe-header h3 { margin: 0; font-size: 19px; font-weight: 700; color: var(--color-text); letter-spacing: 0.01em; }
.pr-qe-sub { font-size: 13px; color: var(--color-text-muted); }
.pr-qe-head-right { display: flex; align-items: center; gap: 14px; }
.pr-qe-head-meta { font-size: 12.5px; color: var(--color-text-placeholder); white-space: nowrap; }
.pr-qe-close { width: 32px; height: 32px; border: none; background: transparent; color: var(--color-text-muted); border-radius: 8px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 16px; }
.pr-qe-close:hover { background: var(--color-surface); color: var(--color-text); }

.pr-qe-ctx { display: flex; align-items: center; gap: 16px; padding: 14px 30px; border-bottom: 1px solid var(--color-border-light); background: #fcfdff; flex-shrink: 0; flex-wrap: wrap; }
.pr-qe-ctx :deep(.pr-customer-select) { width: 250px; }
.pr-qe-seg { display: inline-flex; align-items: center; padding: 4px; gap: 2px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; }
.pr-qe-seg-btn { height: 44px; padding: 0 18px; border: none; border-radius: 8px; background: transparent; color: var(--color-text-muted); font-size: 15px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-family: inherit; white-space: nowrap; }
.pr-qe-seg-btn.on { background: #fff; color: var(--color-primary-700); box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14); }
.pr-qe-seg-btn.on[data-dept='packaging'] { color: var(--color-warning-600); }
.pr-qe-seg-btn.on[data-dept='handcraft'] { color: var(--color-success-700); }
.pr-qe-date { display: flex; align-items: center; gap: 7px; }
.pr-qe-date span { font-size: 13px; font-weight: 700; color: var(--color-text-muted); }
.pr-qe-date input { height: 44px; padding: 0 12px; border: 1px solid var(--color-border); border-radius: 10px; font-size: 15px; font-family: inherit; color: var(--color-text); background: #fff; }
.pr-qe-sp { flex: 1; min-width: 8px; }
.pr-qe-switch { display: inline-flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; user-select: none; }
.pr-qe-switch input { position: absolute; opacity: 0; pointer-events: none; }
.pr-qe-switch i { width: 44px; height: 24px; border-radius: 99px; background: var(--color-border-strong); position: relative; transition: 0.18s; flex: 0 0 44px; }
.pr-qe-switch i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.25); transition: 0.18s; }
.pr-qe-switch input:checked + i { background: var(--color-primary-500); }
.pr-qe-switch input:checked + i::after { transform: translateX(20px); }

.pr-qe-batchstat { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 11px; border-radius: 99px; background: var(--color-warning-50); border: 1px solid var(--color-warning-300); color: var(--color-warning-700); font-size: 13px; font-weight: 700; white-space: nowrap; font-variant-numeric: tabular-nums; }
.pr-qe-batchstat b { font-size: 11px; font-weight: 800; color: #fff; background: var(--color-warning-500); border-radius: 4px; padding: 1px 5px; }

.pr-qe-body { flex: 1; min-height: 0; overflow: hidden; padding: 14px 30px 0; display: flex; gap: 12px; }
.pr-qe-main { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.pr-qe-add { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
.pr-qe-search { position: relative; flex: 1; min-width: 0; }
.pr-qe-input { width: 100%; padding: 14px 18px; font-size: 17px; line-height: 1.5; color: var(--color-text); background: #fff; border: 1px solid var(--color-border); border-radius: 12px; outline: none; min-height: 56px; box-sizing: border-box; font-family: inherit; }
.pr-qe-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.13); }
.pr-qe-search-input { padding-left: 48px !important; }
.pr-qe-search-icon { position: absolute; left: 17px; top: 50%; transform: translateY(-50%); color: var(--color-text-placeholder); font-size: 18px; pointer-events: none; }
.pr-qe-paste { display: inline-flex; align-items: center; gap: 9px; height: 56px; padding: 0 20px; border: 1px solid var(--color-border); border-radius: 12px; background: #fff; color: var(--color-text-secondary); font-size: 15px; font-weight: 700; cursor: pointer; font-family: inherit; white-space: nowrap; }
.pr-qe-paste:hover { border-color: var(--color-primary-400); color: var(--color-primary-700); background: var(--color-primary-50); }

.pr-qe-foot { display: flex; align-items: center; gap: 12px; padding: 14px 30px; border-top: 1px solid var(--color-border-light); flex-shrink: 0; margin-top: 16px; }
.pr-qe-totals { flex: 1; min-width: 0; display: flex; align-items: center; gap: 18px; font-size: 15px; color: var(--color-text-muted); }
.pr-qe-totals b { font-size: 18px; color: var(--color-text); font-variant-numeric: tabular-nums; }
.pr-qe-totals b.val { color: var(--color-primary-700); }
.pr-qe-btn { height: 46px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--color-border); background: #fff; color: var(--color-text-secondary); font-size: 15px; font-weight: 700; cursor: pointer; font-family: inherit; }
.pr-qe-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pr-qe-submit { display: inline-flex; align-items: center; gap: 10px; height: 52px; padding: 0 28px; border: none; border-radius: 12px; background: linear-gradient(135deg, var(--color-primary-500) 0%, var(--color-primary-700) 100%); color: white; font-size: 16px; font-weight: 700; cursor: pointer; font-family: inherit; box-shadow: 0 4px 12px rgba(30, 64, 175, 0.25); white-space: nowrap; }
.pr-qe-submit:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
.pr-qe-submit-hint { padding: 3px 8px; background: rgba(255, 255, 255, 0.22); border-radius: 4px; font-size: 12px; font-weight: 700; font-family: 'SF Mono', Consolas, monospace; }

.pr-qe-enter-active, .pr-qe-leave-active { transition: opacity 0.25s ease; }
.pr-qe-enter-active .pr-qe-modal, .pr-qe-leave-active .pr-qe-modal { transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease; }
.pr-qe-enter-from, .pr-qe-leave-to { opacity: 0; }
.pr-qe-enter-from .pr-qe-modal, .pr-qe-leave-to .pr-qe-modal { transform: scale(0.96) translateY(8px); opacity: 0; }

@media (max-width: 1100px) {
  .pr-qe-ctx { gap: 10px; }
  .pr-qe-add { flex-direction: column; align-items: stretch; }
}
@media (max-width: 600px) {
  .pr-qe-overlay { padding: 0; }
  .pr-qe-modal { width: 100%; height: 100%; max-height: 100%; border-radius: 0; }
  .pr-qe-body, .pr-qe-ctx, .pr-qe-foot { padding-left: 16px; padding-right: 16px; }
}
</style>
