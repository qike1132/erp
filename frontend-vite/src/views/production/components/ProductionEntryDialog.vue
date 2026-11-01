<template>
  <Transition name="pr-qe">
    <!-- 遮罩不绑点击关闭：误触空白会丢掉已输一半的录入内容，只能用右上角 ✕ 或 Esc 关（关闭时自动留草稿） -->
    <div v-if="openModel" class="pr-qe-overlay">
      <div class="pr-qe-modal" role="dialog" aria-labelledby="pr-qe-title" @keydown="onModalKeydown">
        <header class="pr-qe-header">
          <div class="pr-qe-head-left">
            <span class="pr-qe-icon"><FontAwesomeIcon icon="pen-to-square" aria-hidden="true" /></span>
            <div>
              <h3 id="pr-qe-title">录入生产数据</h3>
              <span class="pr-qe-sub">{{ currentDept.label }} · {{ selectedDate }} · 今天已录 {{ todayCount }} 条</span>
            </div>
          </div>
          <div class="pr-qe-head-right">
            <span class="pr-qe-head-pill">一次可提交多个 SKU</span>
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
            <label class="pr-qe-switch" title="包装部自动开启；其它部门按客户记住，下次选这个客户会自动带上">
              <input type="checkbox" :checked="batchColumnOn" data-test="qe-batch-switch" @change="onBatchSwitch" />
              <i /><span>批次号列</span>
            </label>
          </div>

          <div v-if="batchColumnOn" class="pr-qe-banner" data-test="qe-banner">
            <FontAwesomeIcon icon="info-circle" aria-hidden="true" />
            <div class="pr-qe-banner-text">
              <b>{{ bannerTitle }}</b>
              <span>{{ rows.length }} 条中 {{ batchFilledCount }} 条已填批次{{ batchRequired ? '，该客户要求每条必填' : '，可按需填写' }}</span>
            </div>
            <button type="button" class="pr-qe-banner-fill" data-test="qe-banner-fill" @click="fillBatchColumn">铺满空行</button>
          </div>

          <div class="pr-qe-body">
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
                  @select="selectProduct"
                />
              </div>
              <button type="button" class="pr-qe-paste" data-test="qe-paste-open" @click="pasteOpen = true">
                <FontAwesomeIcon icon="paste" aria-hidden="true" /> 粘贴 Excel
              </button>
            </div>

            <div v-if="recentProducts.length" class="pr-qe-recents">
              <span class="pr-qe-recents-label">最近使用</span>
              <button
                v-for="p in recentProducts"
                :key="p.id"
                type="button"
                class="pr-qe-recent-chip"
                data-test="qe-recent"
                :title="p.barcode || ''"
                @click="selectProduct(p)"
              >
                {{ p.name }}
              </button>
              <button type="button" class="pr-qe-recents-clear" @click="clearRecent">清空</button>
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
  undoConfirmOpen, undoText, pasteOpen, recentProducts, clearRecent, rows, totals, canSubmit,
  customerId, customerOptions, selectCustomer, batchColumnOn, batchRequired, batchFilledCount,
  toggleBatchColumn, fillBatchColumn, adjustRowQty, onRowQtyArrow, onRowQtyEnter,
  selectProduct, removeRow, clearRows, searchQuery, searchResults, showDropdown, searchLoading,
  searchError, searchActiveIndex, productSearchRef, onSearchInput, onSearchFocus, onSearchBlur,
  moveSearchIndex, confirmSearchSelection, submitBatch, requestUndo, confirmUndo, saveDraft,
  importPaste, startNewBatch, todayCount, closeEntryDrawer, pickDept, onModalKeydown,
} = useProductionEntry(openModel, selectedDateModel)

const bannerTitle = computed(() => {
  if (batchRequired.value) return '该客户要求录入批次号'
  return isPackaging.value ? '包装部成品库存批次' : '本单启用批次号'
})

function onBatchSwitch(event: Event) {
  toggleBatchColumn((event.target as HTMLInputElement).checked)
}

defineExpose({ handleSubmit: submitBatch, closeEntryDrawer })
</script>

<style scoped>
.pr-qe-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(6px); z-index: var(--z-modal); display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }
.pr-qe-modal { position: relative; width: 1200px; min-height: 480px; max-width: 100%; max-height: 100%; background: white; border-radius: 18px; display: flex; flex-direction: column; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22), 0 4px 12px rgba(15, 23, 42, 0.08); overflow: hidden; }
.pr-qe-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 26px; background: linear-gradient(135deg, var(--color-primary-700) 0%, var(--color-primary-500) 100%); color: white; flex-shrink: 0; }
.pr-qe-head-left { display: flex; align-items: center; gap: 14px; min-width: 0; }
.pr-qe-icon { width: 42px; height: 42px; border-radius: 12px; background: rgba(255, 255, 255, 0.18); display: flex; align-items: center; justify-content: center; font-size: 19px; flex-shrink: 0; }
.pr-qe-header h3 { margin: 0; font-size: 19px; font-weight: 700; color: white; }
.pr-qe-sub { display: block; font-size: 13px; font-weight: 500; color: rgba(255, 255, 255, 0.85); margin-top: 3px; }
.pr-qe-head-right { display: flex; align-items: center; gap: 10px; }
.pr-qe-head-pill { font-size: 12px; font-weight: 600; padding: 4px 11px; border-radius: 99px; background: rgba(255, 255, 255, 0.16); border: 1px solid rgba(255, 255, 255, 0.22); }
.pr-qe-close { width: 36px; height: 36px; border: none; background: rgba(255, 255, 255, 0.15); color: white; border-radius: 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 16px; }
.pr-qe-close:hover { background: rgba(255, 255, 255, 0.28); }

.pr-qe-ctx { display: flex; align-items: center; gap: 14px; padding: 12px 26px; border-bottom: 1px solid var(--color-border-light); background: #fcfdff; flex-shrink: 0; flex-wrap: wrap; }
.pr-qe-seg { display: inline-flex; align-items: center; padding: 3px; gap: 2px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; }
.pr-qe-seg-btn { height: 32px; padding: 0 13px; border: none; border-radius: 7px; background: transparent; color: var(--color-text-muted); font-size: 13px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-family: inherit; white-space: nowrap; }
.pr-qe-seg-btn.on { background: #fff; color: var(--color-primary-700); box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14); }
.pr-qe-seg-btn.on[data-dept='packaging'] { color: var(--color-warning-600); }
.pr-qe-seg-btn.on[data-dept='handcraft'] { color: var(--color-success-700); }
.pr-qe-date { display: flex; align-items: center; gap: 7px; }
.pr-qe-date span { font-size: 12px; font-weight: 700; color: var(--color-text-muted); }
.pr-qe-date input { height: 34px; padding: 0 9px; border: 1px solid var(--color-border); border-radius: 8px; font-size: 13px; font-family: inherit; color: var(--color-text); background: #fff; }
.pr-qe-sp { flex: 1; min-width: 8px; }
.pr-qe-switch { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; user-select: none; }
.pr-qe-switch input { position: absolute; opacity: 0; pointer-events: none; }
.pr-qe-switch i { width: 34px; height: 19px; border-radius: 99px; background: var(--color-border-strong); position: relative; transition: 0.18s; flex: 0 0 34px; }
.pr-qe-switch i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 15px; height: 15px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.25); transition: 0.18s; }
.pr-qe-switch input:checked + i { background: var(--color-primary-500); }
.pr-qe-switch input:checked + i::after { transform: translateX(15px); }

.pr-qe-banner { display: flex; align-items: center; gap: 10px; margin: 12px 26px 0; padding: 9px 13px; border-radius: 10px; background: var(--color-warning-50); border: 1px solid var(--color-warning-300); color: var(--color-warning-700); font-size: 13px; flex-shrink: 0; }
.pr-qe-banner-text { flex: 1; min-width: 0; display: flex; gap: 8px; flex-wrap: wrap; }
.pr-qe-banner-fill { border: 1px solid var(--color-warning-300); background: #fff; color: var(--color-warning-700); font-size: 12px; font-weight: 700; border-radius: 7px; padding: 4px 10px; cursor: pointer; font-family: inherit; white-space: nowrap; }

.pr-qe-body { flex: 1; min-height: 0; overflow: hidden; padding: 12px 26px 0; display: flex; flex-direction: column; gap: 10px; }
.pr-qe-add { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
.pr-qe-search { position: relative; flex: 1; min-width: 0; }
.pr-qe-input { width: 100%; padding: 10px 14px; font-size: 15px; line-height: 1.5; color: var(--color-text); background: #fff; border: 1px solid var(--color-border); border-radius: 10px; outline: none; min-height: 42px; box-sizing: border-box; font-family: inherit; }
.pr-qe-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.13); }
.pr-qe-search-input { padding-left: 38px !important; }
.pr-qe-search-icon { position: absolute; left: 13px; top: 50%; transform: translateY(-50%); color: var(--color-text-placeholder); font-size: 15px; pointer-events: none; }
.pr-qe-paste { display: inline-flex; align-items: center; gap: 7px; height: 42px; padding: 0 14px; border: 1px solid var(--color-border); border-radius: 10px; background: #fff; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; cursor: pointer; font-family: inherit; white-space: nowrap; }
.pr-qe-paste:hover { border-color: var(--color-primary-400); color: var(--color-primary-700); background: var(--color-primary-50); }
.pr-qe-recents { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; flex-shrink: 0; }
.pr-qe-recents-label { font-size: 11px; font-weight: 800; color: var(--color-text-placeholder); letter-spacing: 0.04em; }
.pr-qe-recent-chip { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 5px 12px; border: 1px solid var(--color-border); border-radius: 999px; background: white; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; font-family: inherit; }
.pr-qe-recent-chip:hover { border-color: var(--color-primary-500); color: var(--color-primary-700); background: var(--color-primary-50); }
.pr-qe-recents-clear { border: none; background: transparent; font-size: 12px; color: var(--color-text-placeholder); cursor: pointer; font-family: inherit; }
.pr-qe-recents-clear:hover { color: var(--color-danger-600); }

.pr-qe-foot { display: flex; align-items: center; gap: 10px; padding: 12px 26px; border-top: 1px solid var(--color-border-light); flex-shrink: 0; margin-top: 12px; }
.pr-qe-totals { flex: 1; min-width: 0; display: flex; align-items: center; gap: 16px; font-size: 13px; color: var(--color-text-muted); }
.pr-qe-totals b { font-size: 15px; color: var(--color-text); font-variant-numeric: tabular-nums; }
.pr-qe-totals b.val { color: var(--color-primary-700); }
.pr-qe-btn { height: 38px; padding: 0 14px; border-radius: 9px; border: 1px solid var(--color-border); background: #fff; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; cursor: pointer; font-family: inherit; }
.pr-qe-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pr-qe-submit { display: inline-flex; align-items: center; gap: 9px; height: 40px; padding: 0 22px; border: none; border-radius: 10px; background: linear-gradient(135deg, var(--color-primary-500) 0%, var(--color-primary-700) 100%); color: white; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; box-shadow: 0 4px 12px rgba(30, 64, 175, 0.25); white-space: nowrap; }
.pr-qe-submit:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
.pr-qe-submit-hint { padding: 2px 7px; background: rgba(255, 255, 255, 0.22); border-radius: 4px; font-size: 11px; font-weight: 700; font-family: 'SF Mono', Consolas, monospace; }

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
  .pr-qe-body, .pr-qe-ctx, .pr-qe-foot { padding-left: 14px; padding-right: 14px; }
}
</style>
