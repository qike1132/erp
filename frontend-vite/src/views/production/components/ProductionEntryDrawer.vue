<template>
  <Transition name="pr-entry">
    <div v-if="openModel" class="pr-entry-overlay" @click.self="closeEntryDrawer">
      <div class="pr-entry-modal" role="dialog" aria-labelledby="pr-entry-title">
        <header class="pr-entry-header">
          <div class="pr-entry-header-left">
            <span class="pr-entry-icon"><FontAwesomeIcon icon="pen-to-square" aria-hidden="true" /></span>
            <div>
              <h3 id="pr-entry-title">录入生产数据</h3>
              <span class="pr-entry-sub">{{ selectedDate }} · 快捷键 <kbd>Ctrl</kbd>+<kbd>N</kbd></span>
            </div>
          </div>
          <button class="pr-entry-close" @click="closeEntryDrawer" aria-label="关闭"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </header>

        <div class="pr-entry-body">
          <div class="pr-entry-form">
            <div class="pr-entry-group">
              <label class="pr-entry-label">生产日期</label>
              <div class="pr-entry-date-row">
                <button type="button" :class="['pr-date-chip', { active: selectedDate === todayLocal() }]" @click="selectedDateModel = todayLocal()" aria-label="今日">今日</button>
                <button type="button" :class="['pr-date-chip', { active: selectedDate === prevDay(todayLocal()) }]" @click="selectedDateModel = prevDay(todayLocal())" aria-label="昨日">昨日</button>
                <input v-model="selectedDateModel" type="date" class="pr-entry-input pr-entry-date-input" aria-label="生产日期" />
              </div>
            </div>

            <div class="pr-entry-group">
              <label class="pr-entry-label">生产部门 <span class="pr-req">*</span></label>
              <div class="pr-entry-dept-grid">
                <button
                  v-for="dept in departments"
                  :key="dept.value"
                  type="button"
                  :class="['pr-entry-dept-card', `pr-entry-dept-${dept.value}`, { active: formDept === dept.value }]"
                  @click="formDept = dept.value"
                >
                  <span :class="['pr-entry-dept-icon', `pr-entry-dept-icon-${dept.value}`]"><i :class="dept.icon" aria-hidden="true" /></span>
                  <span class="pr-entry-dept-name">{{ dept.label }}</span>
                  <span class="pr-entry-dept-mark"><FontAwesomeIcon icon="circle-check" aria-hidden="true" /></span>
                </button>
              </div>
            </div>

            <div class="pr-entry-group">
              <label class="pr-entry-label">产品 <span class="pr-req">*</span></label>
              <div class="pr-entry-search">
                <FontAwesomeIcon icon="search" class="pr-entry-search-icon" aria-hidden="true" />
                <input
                  ref="productSearchRef"
                  v-model="searchQuery"
                  type="text"
                  class="pr-entry-input pr-entry-search-input"
                  placeholder="搜索产品名称或69码 (↑↓ 选择, Enter 确认)"
                  autocomplete="off"
                  @input="onSearchInput"
                  @focus="onSearchFocus"
                  @blur="onSearchBlur"
                  @keydown.down.prevent="moveSearchIndex(1)"
                  @keydown.up.prevent="moveSearchIndex(-1)"
                  @keydown.enter.prevent="confirmSearchSelection"
                  @keydown.esc="showDropdown = false"
                />
                <button v-if="searchQuery" type="button" class="pr-entry-search-clear" @click="clearProduct" aria-label="清除">
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
              <div v-if="form.product_name" class="pr-entry-selected">
                <span class="pr-entry-selected-icon"><FontAwesomeIcon icon="check-circle" aria-hidden="true" /></span>
                <span class="pr-entry-selected-name">{{ form.product_name }}</span>
                <span v-if="form.barcode" class="pr-entry-selected-barcode">{{ form.barcode }}</span>
              </div>
              <div v-if="formErrors.product_name" class="pr-entry-error">{{ formErrors.product_name }}</div>
            </div>

            <div class="pr-entry-group">
              <label class="pr-entry-label">数量 <span class="pr-req">*</span></label>
              <div class="pr-entry-qty-row">
                <div class="pr-entry-qty-input-wrap">
                  <button type="button" class="pr-entry-qty-step" aria-label="减少10" @click="adjustQty(-10)">
                    <span>−10</span>
                  </button>
                  <input
                    v-model.number="form.quantity"
                    type="number"
                    min="0"
                    inputmode="numeric"
                    class="pr-entry-input pr-entry-qty-input"
                    placeholder="0"
                    @blur="validateField('quantity')"
                  />
                  <span class="pr-entry-qty-unit">件</span>
                  <button type="button" class="pr-entry-qty-step" aria-label="增加10" @click="adjustQty(10)">
                    <span>+10</span>
                  </button>
                </div>
                <div class="pr-entry-qty-btns">
                  <button type="button" class="pr-entry-qty-pill" @click="adjustQty(-1)" aria-label="减1">−1</button>
                  <button type="button" class="pr-entry-qty-pill" @click="adjustQty(1)" aria-label="+1">+1</button>
                </div>
              </div>
              <div v-if="formErrors.quantity" class="pr-entry-error">{{ formErrors.quantity }}</div>
            </div>

            <div class="pr-entry-form-grid">
              <div class="pr-entry-group">
                <label class="pr-entry-label">单价</label>
                <div class="pr-entry-price-wrap">
                  <span class="pr-entry-price-prefix">¥</span>
                  <input
                    v-model.number="form.unit_price"
                    type="number"
                    min="0"
                    step="0.01"
                    inputmode="decimal"
                    class="pr-entry-input pr-entry-price-input"
                    placeholder="0.00"
                  />
                </div>
              </div>
              <div class="pr-entry-group">
                <label class="pr-entry-label">产值</label>
                <div class="pr-entry-value-display">
                  <FontAwesomeIcon icon="yen-sign" aria-hidden="true" />
                  <span>{{ formatCurrency(computedValue) }}</span>
                </div>
              </div>
            </div>

            <div class="pr-entry-group">
              <label class="pr-entry-label">备注</label>
              <input
                v-model="form.remark"
                type="text"
                class="pr-entry-input"
                placeholder="选填，例如批次号或特殊说明"
              />
            </div>
          </div>

          <EntrySidebar :recent-products="recentProducts" @select="selectProduct" @clear="clearRecent" />
        </div>

        <footer class="pr-entry-footer">
          <label class="pr-entry-continue" :class="{ active: keepAdding }">
            <input v-model="keepAdding" type="checkbox" aria-label="勾选项" />
            <span class="pr-entry-continue-box" aria-hidden="true">
              <FontAwesomeIcon icon="check" />
            </span>
            <span>保存后继续录入下一条</span>
          </label>
          <div class="pr-entry-footer-btns">
            <button type="button" class="pr-entry-btn-cancel" @click="closeEntryDrawer" aria-label="取消">取消</button>
            <button type="button" class="pr-entry-btn-submit" :disabled="isSubmitting" @click="handleSubmit" aria-label="确认录入 Ctrl+Enter">
              <UiLoadingIcon :loading="isSubmitting" icon="check" />
              <span>确认录入</span>
              <span class="pr-entry-btn-hint">Ctrl+Enter</span>
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatCurrency } from '@/utils/format'
import EntrySidebar from './EntrySidebar.vue'
import ProductSearchDropdown from './ProductSearchDropdown.vue'
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
  isSubmitting,
  keepAdding,
  recentProducts,
  clearRecent,
  form,
  formErrors,
  computedValue,
  adjustQty,
  searchQuery,
  searchResults,
  showDropdown,
  searchLoading,
  searchError,
  searchActiveIndex,
  productSearchRef,
  onSearchInput,
  onSearchFocus,
  onSearchBlur,
  moveSearchIndex,
  confirmSearchSelection,
  selectProduct,
  clearProduct,
  validateField,
  closeEntryDrawer,
  handleSubmit,
  todayLocal,
  prevDay,
} = useProductionEntry(openModel, selectedDateModel)

defineExpose({ handleSubmit, closeEntryDrawer })
</script>

<style scoped>
.pr-entry-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(6px); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; }
.pr-entry-modal { width: 800px; max-width: 100%; max-height: 100%; background: white; border-radius: 18px; display: flex; flex-direction: column; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22), 0 4px 12px rgba(15, 23, 42, 0.08); overflow: hidden; }
.pr-entry-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 24px; background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); color: white; flex-shrink: 0; }
.pr-entry-header-left { display: flex; align-items: center; gap: 14px; min-width: 0; }
.pr-entry-icon { width: 42px; height: 42px; border-radius: 12px; background: rgba(255, 255, 255, 0.18); backdrop-filter: blur(10px); display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.pr-entry-header h3 { margin: 0; font-size: 16px; font-weight: 700; color: white; letter-spacing: 0.01em; }
.pr-entry-sub { display: block; font-size: 12px; font-weight: 500; color: rgba(255, 255, 255, 0.85); margin-top: 2px; }
.pr-entry-sub kbd { display: inline-block; padding: 1px 5px; background: rgba(255, 255, 255, 0.2); border-radius: 4px; font-size: 10px; font-family: 'SF Mono', 'Consolas', monospace; margin: 0 1px; }
.pr-entry-close { width: 36px; height: 36px; border: none; background: rgba(255, 255, 255, 0.15); color: white; border-radius: 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 14px; transition: all 0.2s ease; }
.pr-entry-close:hover { background: rgba(255, 255, 255, 0.28); }

.pr-entry-body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 0; overflow: hidden; }
.pr-entry-form { padding: 22px 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 18px; border-right: 1px solid #f1f5f9; }
.pr-entry-group { display: flex; flex-direction: column; gap: 7px; }
.pr-entry-label { font-size: 12px; font-weight: 700; color: #475569; letter-spacing: 0.03em; text-transform: uppercase; }
.pr-req { color: #dc2626; font-weight: 800; }
.pr-entry-input { width: 100%; padding: 10px 14px; font-size: 14px; line-height: 1.5; color: #1e293b; background: white; border: 1px solid #e2e8f0; border-radius: 10px; transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none; min-height: 44px; box-sizing: border-box; font-family: inherit; }
.pr-entry-input:hover:not(:disabled) { border-color: #cbd5e1; }
.pr-entry-input:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }
.pr-entry-input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.pr-entry-input::placeholder { color: #94a3b8; }
.pr-entry-error { font-size: 12px; color: #dc2626; font-weight: 600; display: flex; align-items: center; gap: 4px; }
.pr-entry-error::before { content: '\f06a'; font-family: 'Font Awesome 5 Free'; font-weight: 900; font-size: 11px; }

.pr-entry-date-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pr-date-chip { padding: 7px 14px; border: 1px solid #e2e8f0; border-radius: 8px; background: white; font-size: 12px; font-weight: 600; color: #475569; cursor: pointer; transition: all 0.2s ease; }
.pr-date-chip:hover { border-color: #3b82f6; color: #1e40af; }
.pr-date-chip.active { background: #1e40af; border-color: #1e40af; color: white; box-shadow: 0 1px 3px rgba(30, 64, 175, 0.3); }
.pr-entry-date-input { flex: 1; min-width: 140px; }

.pr-entry-dept-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.pr-entry-dept-card { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; padding: 14px 10px; border: 2px solid #e2e8f0; border-radius: 12px; background: white; cursor: pointer; transition: all 0.2s ease; font-family: inherit; }
.pr-entry-dept-card:hover { border-color: #cbd5e1; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05); }
.pr-entry-dept-icon { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; transition: all 0.2s ease; }
.pr-entry-dept-name { font-size: 13px; font-weight: 700; color: #475569; letter-spacing: 0.01em; }
.pr-entry-dept-mark { position: absolute; top: 6px; right: 6px; font-size: 14px; color: transparent; transition: all 0.2s ease; }
.pr-entry-dept-card.active { transform: translateY(-1px); }
.pr-entry-dept-card.active .pr-entry-dept-mark { color: white; }
.pr-entry-dept-filling .pr-entry-dept-icon { background: #eff6ff; color: #1e40af; }
.pr-entry-dept-filling:hover { border-color: #93c5fd; }
.pr-entry-dept-filling.active { background: linear-gradient(135deg, #3b82f6, #1e40af); border-color: #1e40af; box-shadow: 0 6px 16px rgba(59, 130, 246, 0.35); }
.pr-entry-dept-filling.active .pr-entry-dept-icon { background: rgba(255, 255, 255, 0.2); color: white; }
.pr-entry-dept-filling.active .pr-entry-dept-name { color: white; }
.pr-entry-dept-handcraft .pr-entry-dept-icon { background: #f0fdf4; color: #15803d; }
.pr-entry-dept-handcraft:hover { border-color: #86efac; }
.pr-entry-dept-handcraft.active { background: linear-gradient(135deg, #22c55e, #15803d); border-color: #15803d; box-shadow: 0 6px 16px rgba(34, 197, 94, 0.35); }
.pr-entry-dept-handcraft.active .pr-entry-dept-icon { background: rgba(255, 255, 255, 0.2); color: white; }
.pr-entry-dept-handcraft.active .pr-entry-dept-name { color: white; }
.pr-entry-dept-packaging .pr-entry-dept-icon { background: #fffbeb; color: #d97706; }
.pr-entry-dept-packaging:hover { border-color: #fcd34d; }
.pr-entry-dept-packaging.active { background: linear-gradient(135deg, #f59e0b, #d97706); border-color: #d97706; box-shadow: 0 6px 16px rgba(245, 158, 11, 0.35); }
.pr-entry-dept-packaging.active .pr-entry-dept-icon { background: rgba(255, 255, 255, 0.2); color: white; }
.pr-entry-dept-packaging.active .pr-entry-dept-name { color: white; }

.pr-entry-search { position: relative; }
.pr-entry-search-input { padding-left: 40px !important; padding-right: 40px !important; font-size: 15px !important; min-height: 48px !important; }
.pr-entry-search-icon { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: #94a3b8; font-size: 15px; pointer-events: none; }
.pr-entry-search-clear { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); width: 28px; height: 28px; border: none; background: #f1f5f9; border-radius: 50%; cursor: pointer; color: #64748b; font-size: 11px; display: flex; align-items: center; justify-content: center; transition: all 0.15s ease; }
.pr-entry-search-clear:hover { background: #e2e8f0; color: #1e293b; }
.pr-entry-selected { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; font-size: 13px; font-weight: 600; color: #1e40af; }
.pr-entry-selected-icon { color: #1e40af; font-size: 15px; flex-shrink: 0; }
.pr-entry-selected-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-entry-selected-barcode { font-size: 11px; color: #64748b; font-weight: 500; font-family: 'SF Mono', 'Consolas', monospace; background: white; padding: 2px 6px; border-radius: 4px; border: 1px solid #bfdbfe; }

.pr-entry-qty-row { display: flex; align-items: center; gap: 10px; }
.pr-entry-qty-input-wrap { flex: 1; min-width: 0; display: flex; align-items: stretch; background: white; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
.pr-entry-qty-input-wrap:focus-within { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.pr-entry-qty-step { border: none; background: #f8fafc; padding: 0 14px; font-size: 13px; font-weight: 700; color: #475569; cursor: pointer; font-family: inherit; transition: background 0.15s ease, color 0.15s ease; min-width: 52px; }
.pr-entry-qty-step:first-child { border-right: 1px solid #e2e8f0; }
.pr-entry-qty-step:last-child { border-left: 1px solid #e2e8f0; }
.pr-entry-qty-step:hover { background: #1e40af; color: white; }
.pr-entry-qty-input { flex: 1; min-width: 0; border: none !important; background: transparent !important; text-align: center; font-size: 22px !important; font-weight: 800 !important; color: #1e293b; padding: 8px 4px !important; min-height: 48px !important; font-variant-numeric: tabular-nums; }
.pr-entry-qty-input:focus { box-shadow: none !important; }
.pr-entry-qty-input::-webkit-outer-spin-button, .pr-entry-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.pr-entry-qty-input { -moz-appearance: textfield; }
.pr-entry-qty-unit { display: flex; align-items: center; padding: 0 12px; font-size: 12px; font-weight: 600; color: #64748b; background: #f8fafc; border-left: 1px solid #e2e8f0; }
.pr-entry-qty-btns { display: flex; gap: 6px; }
.pr-entry-qty-pill { padding: 0 14px; height: 48px; border: 1px solid #e2e8f0; border-radius: 12px; background: white; font-size: 14px; font-weight: 700; color: #475569; cursor: pointer; font-family: inherit; transition: all 0.15s ease; }
.pr-entry-qty-pill:hover { background: #1e40af; border-color: #1e40af; color: white; transform: translateY(-1px); box-shadow: 0 4px 10px rgba(30, 64, 175, 0.25); }

.pr-entry-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.pr-entry-price-wrap { position: relative; display: flex; align-items: center; }
.pr-entry-price-prefix { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); font-size: 14px; font-weight: 700; color: #64748b; pointer-events: none; }
.pr-entry-price-input { padding-left: 28px !important; }
.pr-entry-value-display { display: flex; align-items: center; gap: 8px; padding: 10px 14px; min-height: 44px; background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); border: 1px solid #bfdbfe; border-radius: 10px; font-size: 18px; font-weight: 800; color: #1e40af; font-variant-numeric: tabular-nums; }
.pr-entry-value-display i { font-size: 14px; opacity: 0.7; }

.pr-entry-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 24px; background: #f8fafc; border-top: 1px solid #f1f5f9; flex-shrink: 0; flex-wrap: wrap; }
.pr-entry-continue { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; font-weight: 600; color: #475569; user-select: none; padding: 4px 0; }
.pr-entry-continue input { position: absolute; opacity: 0; pointer-events: none; }
.pr-entry-continue-box { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 5px; background: white; border: 2px solid #cbd5e1; color: transparent; font-size: 10px; transition: all 0.15s ease; }
.pr-entry-continue.active .pr-entry-continue-box { background: #1e40af; border-color: #1e40af; color: white; }
.pr-entry-continue:hover .pr-entry-continue-box { border-color: #1e40af; }
.pr-entry-continue.active { color: #1e40af; }
.pr-entry-footer-btns { display: flex; gap: 10px; }
.pr-entry-btn-cancel { padding: 0 18px; height: 44px; border: 1px solid #e2e8f0; border-radius: 10px; background: white; font-size: 14px; font-weight: 600; color: #475569; cursor: pointer; font-family: inherit; transition: all 0.2s ease; }
.pr-entry-btn-cancel:hover { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-entry-btn-submit { display: inline-flex; align-items: center; gap: 8px; padding: 0 22px; height: 44px; border: none; border-radius: 10px; background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%); color: white; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; transition: all 0.2s ease; box-shadow: 0 4px 12px rgba(30, 64, 175, 0.25); }
.pr-entry-btn-submit:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(30, 64, 175, 0.4); }
.pr-entry-btn-submit:disabled { opacity: 0.6; cursor: not-allowed; }
.pr-entry-btn-hint { display: inline-block; padding: 1px 5px; background: rgba(255, 255, 255, 0.2); border-radius: 4px; font-size: 10px; font-weight: 600; font-family: 'SF Mono', 'Consolas', monospace; letter-spacing: 0; }

.pr-entry-enter-active, .pr-entry-leave-active { transition: opacity 0.25s ease; }
.pr-entry-enter-active .pr-entry-modal, .pr-entry-leave-active .pr-entry-modal { transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease; }
.pr-entry-enter-from, .pr-entry-leave-to { opacity: 0; }
.pr-entry-enter-from .pr-entry-modal, .pr-entry-leave-to .pr-entry-modal { transform: scale(0.96) translateY(8px); opacity: 0; }

@media (max-width: 900px) {
  .pr-entry-overlay { padding: 12px; }
  .pr-entry-modal { border-radius: 16px; }
  .pr-entry-body { grid-template-columns: 1fr; }
  .pr-entry-form { border-right: none; border-bottom: 1px solid #f1f5f9; max-height: 55vh; }
  .pr-entry-dept-grid { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .pr-entry-dept-card { padding: 10px 6px; }
  .pr-entry-dept-icon { width: 36px; height: 36px; font-size: 16px; }
  .pr-entry-dept-name { font-size: 12px; }
  .pr-entry-form-grid { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
  .pr-entry-overlay { padding: 0; }
  .pr-entry-modal { width: 100%; height: 100%; max-height: 100%; border-radius: 0; }
  .pr-entry-header { padding: 14px 16px; }
  .pr-entry-form { padding: 16px; gap: 14px; }
  .pr-entry-footer { padding: 12px 16px; flex-direction: column; align-items: stretch; }
  .pr-entry-footer-btns { width: 100%; }
  .pr-entry-btn-cancel, .pr-entry-btn-submit { flex: 1; }
}
</style>
