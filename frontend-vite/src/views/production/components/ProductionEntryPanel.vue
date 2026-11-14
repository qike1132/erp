<template>
  <!-- 录入生产数据整页视图（由弹窗改为铺满内容区，参照 /purchase 汇总下单的做法）：
       结构：上下文条（部门/客户/日期/批次设置/返回）→ 表体（左表格 + 右最近客户）→ 底部合计与提交。
       数据层 useProductionEntry 不变；ProductionView 在 entryOpen 时用本组件替换整个日报卡片，
       侧边栏保留。关闭（返回/Esc）时自动留草稿，下次打开恢复。 -->
  <div class="pr-qe-page" role="dialog" aria-label="录入生产数据" @keydown="onModalKeydown">
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
            :disabled="isSubmitting"
            @click="pickDept(d.value)"
          >
            <FontAwesomeIcon :icon="d.icon" aria-hidden="true" />{{ d.label }}
          </button>
        </div>
        <CustomerSelect
          data-test="qe-customer"
          :model-value="customerId"
          :options="customerOptions"
          :disabled="isSubmitting"
          placeholder="客户（必选）"
          @update:model-value="selectCustomer"
        />
        <label class="pr-qe-date">
          <span>日期</span>
          <input v-model="selectedDateModel" type="date" data-test="qe-date" aria-label="生产日期" :disabled="isSubmitting" />
        </label>
        <div class="pr-qe-sp" />
        <span
          v-if="batchColumnOn && rows.length && batchFilledCount < rows.length"
          class="pr-qe-batchstat"
          data-test="qe-banner"
          title="包装部成品库存批次，选填；留空按未分批次入库"
        >
          批次 {{ batchFilledCount }}/{{ rows.length }}
        </span>
        <button class="pr-qe-back" data-test="qe-close" title="返回生产日报（Esc）" :disabled="isSubmitting" @click="closeEntryDrawer">
          <FontAwesomeIcon icon="arrow-left" aria-hidden="true" /> 返回生产日报
        </button>
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
                @click="onSearchClick"
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
                @select="onPickFromDropdown"
              />
            </div>
            <div class="pr-qe-actions" role="group" aria-label="草稿操作">
              <button type="button" class="pr-qe-icon-btn" data-test="qe-draft" title="存草稿" :disabled="!rows.length" @click="saveDraft()">
                <FontAwesomeIcon icon="floppy-disk" aria-hidden="true" />
              </button>
              <span class="pr-qe-actions-div" aria-hidden="true" />
              <button type="button" class="pr-qe-icon-btn" data-test="qe-clear" title="清空" :disabled="!rows.length || isSubmitting" @click="clearRows">
                <FontAwesomeIcon icon="eraser" aria-hidden="true" />
              </button>
            </div>
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
            <button type="button" class="pr-qe-paste" data-test="qe-paste-open" @click="pasteOpen = true">
              <FontAwesomeIcon icon="paste" aria-hidden="true" /> 粘贴 Excel
            </button>
          </div>

          <ProductionEntryTable
            :rows="rows"
            :batch-column-on="batchColumnOn"
            :is-packaging="isPackaging"
            :disabled="isSubmitting"
            @remove="removeRow"
            @qty-arrow="onRowQtyArrow"
            @qty-enter="onRowQtyEnter"
          />
        </div>

        <!-- 右侧固定区域：该客户最近录入过的 SKU，点一条直接加一行 -->
        <ProductionEntryRecent
          :customer-id="customerId"
          :items="customerRecent"
          :loading="recentLoading"
          :customer-name="customerName"
          @add="addRecentSku"
          @browse="browseProducts"
        />
      </div>

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
      @confirm="confirmUndo"
      @cancel="undoConfirmOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ProductSearchDropdown from './ProductSearchDropdown.vue'
import CustomerSelect from './CustomerSelect.vue'
import ProductionEntryTable from './ProductionEntryTable.vue'
import ProductionEntryPaste from './ProductionEntryPaste.vue'
import ProductionEntryDone from './ProductionEntryDone.vue'
import ProductionEntryRecent from './ProductionEntryRecent.vue'
import { useProductionEntry } from '@/views/production/composables/useProductionEntry'
import type { Product } from '@/types'

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
  rows, canSubmit,
  customerId, customerName, customerOptions, selectCustomer, batchColumnOn, batchFilledCount,
  onRowQtyArrow, onRowQtyEnter,
  selectProduct, removeRow, clearRows, searchQuery, searchResults, showDropdown, searchLoading,
  searchError, searchActiveIndex, searchHint, productSearchRef, onSearchInput, onSearchClick, onSearchFocus, onSearchBlur,
  moveSearchIndex, confirmSearchSelection, submitBatch, requestUndo, confirmUndo, saveDraft,
  importPaste, startNewBatch, closeEntryDrawer, pickDept, onModalKeydown,
} = useProductionEntry(openModel, selectedDateModel)

/** 点下拉条目：加一行但**不收起下拉**，支持连续点多个 SKU */
function onPickFromDropdown(product: Product) {
  void selectProduct(product, true)
}

defineExpose({ handleSubmit: submitBatch, closeEntryDrawer })
</script>

<style scoped>
.pr-qe-page { position: relative; height: 100%; min-height: 0; background: #fff; display: flex; flex-direction: column; overflow: hidden; }
.pr-qe-back { display: inline-flex; align-items: center; gap: 7px; height: 40px; padding: 0 14px; border: 1px solid var(--color-border); border-radius: 8px; background: #fff; color: var(--color-text-secondary); font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; white-space: nowrap; flex: 0 0 auto; }
.pr-qe-back:hover { border-color: var(--color-primary-400); color: var(--color-primary-700); background: var(--color-primary-50); }

.pr-qe-ctx { display: flex; align-items: center; gap: 12px; padding: 12px 24px; border-bottom: 1px solid var(--color-border-light); background: #fcfdff; flex-shrink: 0; flex-wrap: wrap; }
.pr-qe-ctx :deep(.pr-customer-select) { width: 230px; }
.pr-qe-seg { display: inline-flex; align-items: center; padding: 4px; gap: 2px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; }
.pr-qe-seg-btn { height: 40px; padding: 0 15px; border: none; border-radius: 8px; background: transparent; color: var(--color-text-muted); font-size: 14px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-family: inherit; white-space: nowrap; }
.pr-qe-seg-btn.on { background: #fff; color: var(--color-primary-700); box-shadow: 0 1px 3px rgba(15, 23, 42, 0.14); }
.pr-qe-seg-btn.on[data-dept='packaging'] { color: var(--color-warning-600); }
.pr-qe-seg-btn.on[data-dept='handcraft'] { color: var(--color-success-700); }
.pr-qe-date { display: flex; align-items: center; gap: 7px; }
.pr-qe-date span { font-size: 12px; font-weight: 700; color: var(--color-text-muted); }
.pr-qe-date input { height: 40px; padding: 0 11px; border: 1px solid var(--color-border); border-radius: 8px; font-size: 14px; font-family: inherit; color: var(--color-text); background: #fff; }
.pr-qe-sp { flex: 1; min-width: 8px; }
.pr-qe-switch { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; user-select: none; }
.pr-qe-switch input:disabled { cursor: not-allowed; }
.pr-qe-switch input:disabled + i { opacity: 0.45; }
.pr-qe-switch input { position: absolute; opacity: 0; pointer-events: none; }
.pr-qe-switch i { width: 40px; height: 22px; border-radius: 99px; background: var(--color-border-strong); position: relative; transition: 0.18s; flex: 0 0 40px; }
.pr-qe-switch i::after { content: ''; position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.25); transition: 0.18s; }
.pr-qe-switch input:checked + i { background: var(--color-primary-500); }
.pr-qe-switch input:checked + i::after { transform: translateX(18px); }

.pr-qe-batchstat { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px; border-radius: 99px; background: var(--color-warning-50); border: 1px solid var(--color-warning-300); color: var(--color-warning-700); font-size: 12px; font-weight: 700; white-space: nowrap; font-variant-numeric: tabular-nums; }
.pr-qe-batchstat b { font-size: 12px; font-weight: 800; color: #fff; background: var(--color-warning-500); border-radius: 4px; padding: 1px 5px; }

.pr-qe-body { flex: 1; min-height: 0; overflow: hidden; padding: 12px 24px 0; display: flex; gap: 10px; }
.pr-qe-main { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
.pr-qe-add { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
.pr-qe-search { position: relative; flex: 1; min-width: 0; }
.pr-qe-input { width: 100%; padding: 12px 16px; font-size: 16px; line-height: 1.5; color: var(--color-text); background: #fff; border: 1px solid var(--color-border); border-radius: 10px; outline: none; min-height: 48px; box-sizing: border-box; font-family: inherit; }
.pr-qe-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.13); }
.pr-qe-search-input { padding-left: 42px !important; }
.pr-qe-search-icon { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: var(--color-text-placeholder); font-size: 16px; pointer-events: none; }
.pr-qe-paste { display: inline-flex; align-items: center; gap: 8px; height: 48px; padding: 0 18px; border: 1px solid var(--color-border); border-radius: 10px; background: #fff; color: var(--color-text-secondary); font-size: 14px; font-weight: 600; cursor: pointer; font-family: inherit; white-space: nowrap; }
.pr-qe-paste:hover:not(:disabled) { border-color: var(--color-primary-400); color: var(--color-primary-700); background: var(--color-primary-50); }

.pr-qe-actions { display: inline-flex; align-items: stretch; height: 48px; border: 1px solid var(--color-border); border-radius: 10px; background: #fff; overflow: hidden; flex: 0 0 auto; }
.pr-qe-icon-btn { width: 48px; border: none; background: transparent; color: var(--color-text-secondary); font-size: 16px; cursor: pointer; display: grid; place-items: center; }
.pr-qe-icon-btn:hover:not(:disabled) { background: var(--color-primary-50); color: var(--color-primary-700); }
.pr-qe-icon-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.pr-qe-actions-div { width: 1px; background: var(--color-border-light); }
.pr-qe-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pr-qe-submit { display: inline-flex; align-items: center; gap: 9px; height: 48px; padding: 0 22px; border: 1px solid transparent; border-radius: 10px; background: var(--color-primary-600); color: #fff; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; white-space: nowrap; }
.pr-qe-submit:hover:not(:disabled) { background: var(--color-primary-700); }
.pr-qe-submit:disabled { opacity: 0.55; cursor: not-allowed; }
.pr-qe-submit-hint { padding: 2px 6px; background: rgba(255, 255, 255, 0.22); border-radius: 4px; font-size: 12px; font-weight: 700; font-family: var(--font-mono); }

@media (max-width: 1100px) {
  .pr-qe-ctx { gap: 10px; }
  .pr-qe-add { flex-direction: column; align-items: stretch; }
  .pr-qe-body, .pr-qe-ctx, .pr-qe-foot { padding-left: 16px; padding-right: 16px; }
}
</style>
