<template>
  <Transition name="pr-qe">
    <!-- 遮罩不绑点击关闭：误触空白会丢掉已输一半的录入内容，只能用右上角 ✕ 或 Esc 关 -->
    <div v-if="openModel" class="pr-qe-overlay">
      <div class="pr-qe-modal" role="dialog" aria-labelledby="pr-qe-title" @keydown="onModalKeydown">
        <header class="pr-qe-header">
          <div class="pr-qe-head-left">
            <span class="pr-qe-icon"><FontAwesomeIcon icon="pen-to-square" aria-hidden="true" /></span>
            <div>
              <h3 id="pr-qe-title">录入生产数据</h3>
              <span class="pr-qe-sub">{{ selectedDate }} · 今天已录 {{ todayCount }} 条</span>
            </div>
          </div>
          <button class="pr-qe-close" aria-label="关闭" @click="closeEntryDrawer"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </header>

        <div class="pr-qe-body">
          <!-- 快捷行：部门 · 产品 · 数量 · 录入（鼠标只需点一次） -->
          <div class="pr-qe-row">
            <div ref="deptMenuRef" class="pr-qe-dept">
              <button
                type="button"
                data-test="qe-dept"
                :class="['pr-qe-dept-chip', `is-${formDept}`]"
                aria-haspopup="listbox"
                :aria-expanded="deptMenuOpen"
                @click="deptMenuOpen = !deptMenuOpen"
              >
                <FontAwesomeIcon :icon="currentDept.icon" aria-hidden="true" />
                <span>{{ currentDept.label }}</span>
                <FontAwesomeIcon icon="chevron-down" class="pr-qe-caret" aria-hidden="true" />
              </button>
              <div v-if="deptMenuOpen" class="pr-qe-dept-menu" role="listbox" aria-label="生产部门">
                <button
                  v-for="(dept, i) in departments"
                  :key="dept.value"
                  type="button"
                  role="option"
                  :aria-selected="formDept === dept.value"
                  :class="['pr-qe-dept-option', { active: formDept === dept.value }]"
                  @click="pickDept(dept.value)"
                >
                  <FontAwesomeIcon :icon="dept.icon" aria-hidden="true" />
                  <span>{{ dept.label }}</span>
                  <kbd>Alt+{{ i + 1 }}</kbd>
                </button>
              </div>
            </div>

            <CustomerSelect
              data-test="qe-customer"
              :model-value="form.customer_id"
              :options="customerOptions"
              placeholder="客户（选填）"
              @update:model-value="selectCustomer"
            />

            <div class="pr-qe-search">
              <FontAwesomeIcon icon="search" class="pr-qe-search-icon" aria-hidden="true" />
              <input
                ref="productSearchRef"
                v-model="searchQuery"
                type="text"
                data-test="qe-search"
                class="pr-qe-input pr-qe-search-input"
                placeholder="搜索产品名称或 69 码（↑↓ 选择，Enter 确认）"
                autocomplete="off"
                @input="onSearchInput"
                @focus="onSearchFocus"
                @blur="onSearchBlur"
                @keydown.down.prevent="moveSearchIndex(1)"
                @keydown.up.prevent="moveSearchIndex(-1)"
                @keydown.enter.prevent="confirmSearchSelection"
              />
              <button v-if="searchQuery" type="button" class="pr-qe-search-clear" aria-label="清除" @click="clearProduct">
                <FontAwesomeIcon icon="times" aria-hidden="true" />
              </button>
              <ProductSearchDropdown
                v-if="showDropdown"
                :search-loading="searchLoading"
                :search-error="searchError"
                :search-results="searchResults"
                :search-active-index="searchActiveIndex"
                @select="selectProduct"
              />
            </div>

            <div class="pr-qe-qty">
              <button type="button" class="pr-qe-step" aria-label="减1" @click="adjustQty(-1)">−</button>
              <input
                ref="quantityRef"
                v-model.number="form.quantity"
                type="number"
                min="0"
                inputmode="numeric"
                data-test="qe-quantity"
                class="pr-qe-input pr-qe-qty-input"
                placeholder="0"
                aria-label="生产数量"
                @keydown.up.prevent="onQtyArrow(1, $event)"
                @keydown.down.prevent="onQtyArrow(-1, $event)"
                @keydown.enter.prevent="handleSubmit"
                @blur="validateField('quantity')"
              />
              <button type="button" class="pr-qe-step" aria-label="加1" @click="adjustQty(1)">＋</button>
              <span class="pr-qe-qty-unit">件</span>
            </div>

            <button
              type="button"
              data-test="qe-submit"
              class="pr-qe-submit"
              aria-label="录入 Enter"
              :disabled="!canSubmit || isSubmitting"
              @click="handleSubmit"
            >
              <UiLoadingIcon :loading="isSubmitting" icon="check" />
              <span>录入</span>
              <span class="pr-qe-submit-hint">⏎</span>
            </button>
          </div>

          <!-- 慢路径收进「详细」：单价自动带出、日期默认选中日、备注选填 -->
          <div class="pr-qe-hint" data-test="qe-hint">
            <span>单价 {{ form.unit_price > 0 ? formatCurrency(form.unit_price) : '—' }}（自动）</span>
            <span class="pr-qe-dot">·</span>
            <span>客户 {{ form.customer_name || '空' }}</span>
            <span class="pr-qe-dot">·</span>
            <span>备注（{{ form.remark || '空' }}）</span>
            <span class="pr-qe-dot">·</span>
            <span>日期 {{ selectedDate }}</span>
            <button
              type="button"
              class="pr-qe-detail-toggle"
              data-test="qe-detail-toggle"
              :aria-expanded="detailOpen"
              @click="detailOpen = !detailOpen"
            >
              详细 <FontAwesomeIcon icon="chevron-down" :class="{ 'is-open': detailOpen }" aria-hidden="true" />
            </button>
          </div>

          <EntryDetailFields
            v-if="detailOpen"
            v-model:date="selectedDateModel"
            v-model:unit-price="form.unit_price"
            v-model:remark="form.remark"
            :value="computedValue"
          />

          <div v-if="duplicateHint" class="pr-qe-dup" data-test="qe-dup">
            <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />
            <span>{{ duplicateHint }}</span>
          </div>
          <div v-if="formErrors.product_name || formErrors.quantity" class="pr-qe-error">
            {{ formErrors.product_name || formErrors.quantity }}
          </div>

          <div v-if="recentProducts.length" class="pr-qe-recents">
            <span class="pr-qe-recents-label">最近使用</span>
            <div class="pr-qe-recents-row">
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
          </div>

          <div v-if="lastCreated" class="pr-qe-just" data-test="qe-just">
            <FontAwesomeIcon icon="circle-check" aria-hidden="true" />
            <span class="pr-qe-just-text">
              刚录入 {{ lastCreated.product_name }} · {{ deptLabel(lastCreated.department) }} · {{ lastCreated.quantity }} 件
            </span>
            <button type="button" class="pr-qe-undo" data-test="qe-undo" @click="requestUndo">撤销</button>
          </div>
        </div>

        <!-- 撤销确认：物理删除不可恢复，必须写明「删的是哪一条」。
             确认框被传送出遮罩的层叠上下文，遮罩与弹窗卡都是 z-[var(--z-modal)]（40），
             若确认框沿用默认层级（30/40），谁盖谁取决于传送顺序 —— 实测会渲染在弹窗之下、
             点不到，撤销护栏等于不存在。故显式抬到嵌套层级（--z-overlay/modal-nested，2200/2210）。 -->
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
import EntryDetailFields from './EntryDetailFields.vue'
import ProductSearchDropdown from './ProductSearchDropdown.vue'
import CustomerSelect from './CustomerSelect.vue'
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
  departments,
  formDept,
  currentDept,
  deptLabel,
  isSubmitting,
  detailOpen,
  deptMenuOpen,
  deptMenuRef,
  recentProducts,
  clearRecent,
  form,
  formErrors,
  computedValue,
  canSubmit,
  adjustQty,
  onQtyArrow,
  searchQuery,
  searchResults,
  showDropdown,
  searchLoading,
  searchError,
  searchActiveIndex,
  productSearchRef,
  quantityRef,
  onSearchInput,
  onSearchFocus,
  onSearchBlur,
  moveSearchIndex,
  confirmSearchSelection,
  selectProduct,
  clearProduct,
  selectCustomer,
  customerOptions,
  validateField,
  closeEntryDrawer,
  handleSubmit,
  todayCount,
  duplicateHint,
  lastCreated,
  undoConfirmOpen,
  undoText,
  requestUndo,
  confirmUndo,
  pickDept,
  onModalKeydown,
} = useProductionEntry(openModel, selectedDateModel)

defineExpose({ handleSubmit, closeEntryDrawer })
</script>

<style scoped>
/* 遮罩必须留在 token 尺度上（--z-modal = 40）：撤销确认框是嵌套层级 60/70，
   而它是被传送出本层叠上下文的，两者在根上下文里直接比大小。
   这里写魔法数 100 会把 30/40 的确认框压到弹窗下面，点不到。 */
.pr-qe-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(6px); z-index: var(--z-modal); display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }
.pr-qe-modal { width: 1200px; min-height: 480px; max-width: 100%; max-height: 100%; background: white; border-radius: 18px; display: flex; flex-direction: column; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22), 0 4px 12px rgba(15, 23, 42, 0.08); overflow: hidden; }
.pr-qe-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 24px 32px; background: linear-gradient(135deg, var(--color-primary-700) 0%, var(--color-primary-500) 100%); color: white; flex-shrink: 0; }
.pr-qe-head-left { display: flex; align-items: center; gap: 16px; min-width: 0; }
.pr-qe-icon { width: 52px; height: 52px; border-radius: 14px; background: rgba(255, 255, 255, 0.18); display: flex; align-items: center; justify-content: center; font-size: 23px; flex-shrink: 0; }
.pr-qe-header h3 { margin: 0; font-size: 22px; font-weight: 700; color: white; }
.pr-qe-sub { display: block; font-size: 15px; font-weight: 500; color: rgba(255, 255, 255, 0.85); margin-top: 4px; }
.pr-qe-close { width: 44px; height: 44px; border: none; background: rgba(255, 255, 255, 0.15); color: white; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 18px; transition: background 0.2s ease; }
.pr-qe-close:hover { background: rgba(255, 255, 255, 0.28); }

.pr-qe-body { flex: 1; min-height: 0; overflow-y: auto; padding: 28px 32px 30px; display: flex; flex-direction: column; gap: 16px; }
.pr-qe-input { width: 100%; padding: 14px 18px; font-size: 17px; line-height: 1.5; color: var(--color-text); background: white; border: 1px solid var(--color-border); border-radius: 14px; transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none; min-height: 64px; box-sizing: border-box; font-family: inherit; }
.pr-qe-input:hover:not(:disabled) { border-color: var(--color-border-strong); }
.pr-qe-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.pr-qe-input::placeholder { color: var(--color-text-placeholder); }

/* 快捷行 */
.pr-qe-row { display: grid; grid-template-columns: auto 220px minmax(0, 1fr) auto auto; align-items: center; gap: 14px; }
.pr-qe-dept { position: relative; }
.pr-qe-dept-chip { display: inline-flex; align-items: center; gap: 10px; height: 64px; padding: 0 22px; border: 2px solid var(--color-border); border-radius: 16px; background: white; font-size: 16px; font-weight: 700; color: var(--color-text-secondary); cursor: pointer; font-family: inherit; white-space: nowrap; transition: all 0.2s ease; }
.pr-qe-dept-chip:hover { border-color: var(--color-border-strong); }
.pr-qe-dept-chip.is-filling { border-color: var(--color-primary-300); background: var(--color-primary-50); color: var(--color-primary-700); }
.pr-qe-dept-chip.is-handcraft { border-color: var(--color-success-300); background: var(--color-success-50); color: var(--color-success-700); }
.pr-qe-dept-chip.is-packaging { border-color: var(--color-warning-300); background: var(--color-warning-50); color: var(--color-warning-600); }
.pr-qe-caret { font-size: 12px; opacity: 0.7; }
.pr-qe-dept-menu { position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; min-width: 280px; padding: 6px; background: white; border: 1px solid var(--color-border); border-radius: 14px; box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16); display: flex; flex-direction: column; }
.pr-qe-dept-option { display: flex; align-items: center; gap: 10px; width: 100%; padding: 14px; border: none; border-radius: 10px; background: transparent; font-family: inherit; font-size: 16px; font-weight: 600; color: var(--color-text-secondary); text-align: left; cursor: pointer; transition: background 0.15s ease; }
.pr-qe-dept-option:hover { background: var(--color-primary-50); }
.pr-qe-dept-option.active { background: var(--color-primary-50); color: var(--color-primary-700); }
.pr-qe-dept-option kbd { margin-left: auto; padding: 2px 7px; border-radius: 4px; background: var(--color-border-light); border: 1px solid var(--color-border); font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; font-weight: 700; color: var(--color-text-muted); }

.pr-qe-search { position: relative; }
.pr-qe-search-input { padding-left: 54px !important; padding-right: 54px !important; font-size: 18px !important; }
.pr-qe-search-icon { position: absolute; left: 20px; top: 50%; transform: translateY(-50%); color: var(--color-text-placeholder); font-size: 18px; pointer-events: none; }
.pr-qe-search-clear { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); width: 34px; height: 34px; border: none; background: var(--color-border-light); border-radius: 50%; cursor: pointer; color: var(--color-text-muted); font-size: 13px; display: flex; align-items: center; justify-content: center; }
.pr-qe-search-clear:hover { background: var(--color-border); color: var(--color-text); }

.pr-qe-qty { display: flex; align-items: stretch; background: white; border: 1px solid var(--color-border); border-radius: 16px; overflow: hidden; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.pr-qe-qty:focus-within { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.pr-qe-step { border: none; background: var(--color-surface); padding: 0 20px; font-size: 20px; font-weight: 700; color: var(--color-text-secondary); cursor: pointer; font-family: inherit; transition: background 0.15s ease, color 0.15s ease; }
.pr-qe-step:first-child { border-right: 1px solid var(--color-border); }
.pr-qe-step:last-child { border-left: 1px solid var(--color-border); }
.pr-qe-step:hover { background: var(--color-primary-700); color: white; }
.pr-qe-qty-input { width: 150px; border: none !important; background: transparent !important; text-align: center; font-size: 30px !important; font-weight: 800 !important; padding: 10px 6px !important; min-height: 64px !important; font-variant-numeric: tabular-nums; }
.pr-qe-qty-input:focus { box-shadow: none !important; }
.pr-qe-qty-input::-webkit-outer-spin-button, .pr-qe-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.pr-qe-qty-input { -moz-appearance: textfield; }
.pr-qe-qty-unit { display: flex; align-items: center; padding: 0 18px; font-size: 15px; font-weight: 600; color: var(--color-text-muted); background: var(--color-surface); border-left: 1px solid var(--color-border); }

.pr-qe-submit { display: inline-flex; align-items: center; gap: 10px; height: 64px; padding: 0 34px; border: none; border-radius: 16px; background: linear-gradient(135deg, var(--color-primary-500) 0%, var(--color-primary-700) 100%); color: white; font-size: 17px; font-weight: 700; cursor: pointer; font-family: inherit; transition: all 0.2s ease; box-shadow: 0 4px 12px rgba(30, 64, 175, 0.25); white-space: nowrap; }
.pr-qe-submit:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(30, 64, 175, 0.4); }
.pr-qe-submit:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
.pr-qe-submit-hint { padding: 2px 7px; background: rgba(255, 255, 255, 0.22); border-radius: 4px; font-size: 12px; font-weight: 700; font-family: 'SF Mono', 'Consolas', monospace; }

/* 提示行 + 详细 */
.pr-qe-hint { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 15px; color: var(--color-text-muted); }
.pr-qe-dot { color: var(--color-border-strong); }
.pr-qe-detail-toggle { display: inline-flex; align-items: center; gap: 5px; margin-left: auto; padding: 8px 16px; border: 1px solid var(--color-border); border-radius: 10px; background: white; font-size: 15px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; font-family: inherit; }
.pr-qe-detail-toggle:hover { border-color: var(--color-primary-500); color: var(--color-primary-700); }
.pr-qe-detail-toggle i { font-size: 12px; transition: transform 0.2s ease; }
.pr-qe-detail-toggle i.is-open { transform: rotate(180deg); }

.pr-qe-dup { display: flex; align-items: center; gap: 10px; padding: 14px 18px; border-radius: 12px; background: var(--color-warning-50); border: 1px solid var(--color-warning-300); font-size: 15px; font-weight: 600; color: var(--color-warning-600); }
.pr-qe-error { font-size: 15px; font-weight: 600; color: var(--color-danger-600); }

/* 最近使用 */
.pr-qe-recents { display: flex; align-items: center; gap: 12px; min-width: 0; }
.pr-qe-recents-label { flex-shrink: 0; font-size: 14px; font-weight: 700; color: var(--color-text-secondary); letter-spacing: 0.03em; }
.pr-qe-recents-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.pr-qe-recent-chip { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 10px 18px; border: 1px solid var(--color-border); border-radius: 999px; background: white; font-size: 15px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; font-family: inherit; transition: all 0.15s ease; }
.pr-qe-recent-chip:hover { border-color: var(--color-primary-500); color: var(--color-primary-700); background: var(--color-primary-50); }
.pr-qe-recents-clear { border: none; background: transparent; font-size: 14px; font-weight: 600; color: var(--color-text-placeholder); cursor: pointer; font-family: inherit; padding: 4px; }
.pr-qe-recents-clear:hover { color: var(--color-danger-600); }

/* 刚才录的 */
.pr-qe-just { display: flex; align-items: center; gap: 12px; padding: 14px 20px; border-radius: 12px; background: var(--color-success-50); border: 1px solid var(--color-success-300); font-size: 16px; font-weight: 600; color: var(--color-success-700); }
.pr-qe-just-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-qe-undo { flex-shrink: 0; padding: 8px 20px; border: 1px solid var(--color-danger-600); border-radius: 10px; background: white; font-size: 15px; font-weight: 700; color: var(--color-danger-600); cursor: pointer; font-family: inherit; }
.pr-qe-undo:hover { background: var(--color-danger-600); color: white; }

.pr-qe-enter-active, .pr-qe-leave-active { transition: opacity 0.25s ease; }
.pr-qe-enter-active .pr-qe-modal, .pr-qe-leave-active .pr-qe-modal { transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease; }
.pr-qe-enter-from, .pr-qe-leave-to { opacity: 0; }
.pr-qe-enter-from .pr-qe-modal, .pr-qe-leave-to .pr-qe-modal { transform: scale(0.96) translateY(8px); opacity: 0; }

@media (max-width: 1100px) {
  .pr-qe-row { grid-template-columns: 1fr; }
  .pr-qe-dept-chip, .pr-qe-qty, .pr-qe-submit { width: 100%; justify-content: center; }
}
@media (max-width: 600px) {
  .pr-qe-overlay { padding: 0; }
  .pr-qe-modal { width: 100%; height: 100%; max-height: 100%; border-radius: 0; }
}
</style>
