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
                <button type="button" :class="['pr-date-chip', { active: selectedDate === todayLocal() }]" @click="selectedDateModel = todayLocal()">今日</button>
                <button type="button" :class="['pr-date-chip', { active: selectedDate === prevDay(todayLocal()) }]" @click="selectedDateModel = prevDay(todayLocal())">昨日</button>
                <input v-model="selectedDateModel" type="date" class="pr-entry-input pr-entry-date-input" />
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
                <div v-if="showDropdown" class="pr-entry-dropdown">
                  <div v-if="searchLoading" class="pr-entry-dropdown-state">
                    <UiSpinner /></div>
                  <div v-else-if="searchError" class="pr-entry-dropdown-state pr-entry-dropdown-error">
                    <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> {{ searchError }}
                  </div>
                  <div v-else-if="!searchResults.length" class="pr-entry-dropdown-state">
                    <FontAwesomeIcon icon="inbox" aria-hidden="true" /> 无匹配产品
                  </div>
                  <button
                    v-for="(p, idx) in searchResults"
                    :key="p.id"
                    type="button"
                    :class="['pr-entry-dropdown-item', { active: idx === searchActiveIndex }]"
                    @mousedown.prevent="selectProduct(p)"
                  >
                    <span class="pr-entry-dropdown-icon"><FontAwesomeIcon icon="box" aria-hidden="true" /></span>
                    <span class="pr-entry-dropdown-content">
                      <span class="pr-entry-dropdown-name">{{ p.name }}</span>
                      <span class="pr-entry-dropdown-meta">
                        <span v-if="p.barcode" class="pr-entry-dropdown-barcode"><FontAwesomeIcon icon="barcode" aria-hidden="true" /> {{ p.barcode }}</span>
                        <span v-if="p.specification" class="pr-entry-dropdown-spec">{{ p.specification }}</span>
                      </span>
                    </span>
                    <FontAwesomeIcon v-if="idx === searchActiveIndex" icon="arrow-right" class="pr-entry-dropdown-enter" aria-hidden="true" />
                  </button>
                </div>
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
                  <button type="button" class="pr-entry-qty-pill" @click="adjustQty(-1)">−1</button>
                  <button type="button" class="pr-entry-qty-pill" @click="adjustQty(1)">+1</button>
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

          <aside class="pr-entry-sidebar">
            <div class="pr-entry-side-card">
              <div class="pr-entry-side-head">
                <span><FontAwesomeIcon icon="clock-rotate-left" aria-hidden="true" /> 最近使用</span>
                <button v-if="recentProducts.length" type="button" class="pr-entry-side-clear" @click="clearRecent">清空</button>
              </div>
              <div v-if="recentProducts.length" class="pr-entry-recent-list">
                <button
                  v-for="p in recentProducts"
                  :key="p.id"
                  type="button"
                  class="pr-entry-recent-item"
                  :title="p.barcode || ''"
                  @click="selectProduct(p)"
                >
                  <span class="pr-entry-recent-bullet" />
                  <span class="pr-entry-recent-content">
                    <span class="pr-entry-recent-name">{{ p.name }}</span>
                    <span v-if="p.barcode" class="pr-entry-recent-barcode">{{ p.barcode }}</span>
                  </span>
                  <FontAwesomeIcon icon="chevron-right" class="pr-entry-recent-arrow" aria-hidden="true" />
                </button>
              </div>
              <div v-else class="pr-entry-empty-small">
                <FontAwesomeIcon icon="inbox" aria-hidden="true" />
                <span>暂无最近使用</span>
                <small>录入后会自动记录</small>
              </div>
            </div>

            <div class="pr-entry-side-card">
              <div class="pr-entry-side-head">
                <span><FontAwesomeIcon icon="keyboard" aria-hidden="true" /> 快捷键</span>
              </div>
              <div class="pr-entry-shortcuts">
                <div class="pr-entry-shortcut"><kbd>↑</kbd><kbd>↓</kbd><span>选择产品</span></div>
                <div class="pr-entry-shortcut"><kbd>Enter</kbd><span>确认选择 / 提交</span></div>
                <div class="pr-entry-shortcut"><kbd>Ctrl</kbd>+<kbd>Enter</kbd><span>直接提交</span></div>
                <div class="pr-entry-shortcut"><kbd>Esc</kbd><span>关闭</span></div>
              </div>
            </div>
          </aside>
        </div>

        <footer class="pr-entry-footer">
          <label class="pr-entry-continue" :class="{ active: keepAdding }">
            <input v-model="keepAdding" type="checkbox" />
            <span class="pr-entry-continue-box" aria-hidden="true">
              <FontAwesomeIcon icon="check" />
            </span>
            <span>保存后继续录入下一条</span>
          </label>
          <div class="pr-entry-footer-btns">
            <button type="button" class="pr-entry-btn-cancel" @click="closeEntryDrawer">取消</button>
            <button type="button" class="pr-entry-btn-submit" :disabled="isSubmitting" @click="handleSubmit">
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
import { ref, reactive, computed, watch, nextTick, onUnmounted } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { dailyProductionApi, productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { formatCurrency } from '@/utils/format'
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

const queryClient = useQueryClient()
const _timers: ReturnType<typeof setTimeout>[] = []

const departments = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]

const formDept = ref('filling')
const isSubmitting = ref(false)
const keepAdding = ref(false)

const RECENT_PRODUCTS_KEY = 'production.recentProducts'
const MAX_RECENT = 6
const recentProducts = ref<Product[]>(loadRecent())

function loadRecent(): Product[] {
  try {
    const raw = localStorage.getItem(RECENT_PRODUCTS_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.slice(0, MAX_RECENT) : []
  } catch { return [] }
}
function saveRecent() {
  try {
    localStorage.setItem(RECENT_PRODUCTS_KEY, JSON.stringify(recentProducts.value.slice(0, MAX_RECENT)))
  } catch { /* localStorage 不可用时静默忽略 */ }
}
function pushRecent(product: Product) {
  if (!product || product.id == null) return
  const filtered = recentProducts.value.filter(x => x.id !== product.id)
  filtered.unshift(product)
  recentProducts.value = filtered.slice(0, MAX_RECENT)
  saveRecent()
}
function clearRecent() {
  recentProducts.value = []
  saveRecent()
}

function adjustQty(delta: number) {
  const cur = Number(form.quantity) || 0
  form.quantity = Math.max(0, cur + delta)
}

const form = reactive({
  product_id: null as number | null,
  product_name: '',
  barcode: '',
  unit_price: 0,
  quantity: 0,
  remark: '',
})
const formErrors = reactive<Record<string, string>>({})
const computedValue = computed(() => (form.quantity || 0) * (form.unit_price || 0))

const searchQuery = ref('')
const searchResults = ref<Product[]>([])
const showDropdown = ref(false)
const searchLoading = ref(false)
const searchError = ref('')
const searchActiveIndex = ref(-1)
const productSearchRef = ref<HTMLInputElement>()
let searchTimer: ReturnType<typeof setTimeout> | null = null

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchError.value = ''
  if (form.product_name && searchQuery.value !== form.product_name) {
    form.product_id = null; form.product_name = ''; form.barcode = ''; form.unit_price = 0
  }
  if (!searchQuery.value.trim()) { searchResults.value = []; showDropdown.value = false; return }
  searchLoading.value = true
  showDropdown.value = true
  searchActiveIndex.value = -1
  searchTimer = setTimeout(async () => {
    try {
      const res = (await productApi.search(searchQuery.value.trim())) as unknown as Product[] & { products?: Product[] }
      searchResults.value = res.products ?? res ?? []
      searchError.value = ''
    } catch {
      searchError.value = '产品搜索失败，请重试'
      searchResults.value = []
    } finally {
      searchLoading.value = false
    }
  }, 300)
}
function onSearchFocus() {
  if (searchQuery.value.trim() && (searchResults.value.length || searchError.value)) {
    showDropdown.value = true
  }
}
function onSearchBlur() {
  const _t = setTimeout(() => { showDropdown.value = false; searchActiveIndex.value = -1 }, 150)
  _timers.push(_t)
}
function moveSearchIndex(delta: number) {
  if (!searchResults.value.length) return
  searchActiveIndex.value += delta
  if (searchActiveIndex.value < 0) searchActiveIndex.value = searchResults.value.length - 1
  if (searchActiveIndex.value >= searchResults.value.length) searchActiveIndex.value = 0
}
function confirmSearchSelection() {
  const product = searchActiveIndex.value >= 0 ? searchResults.value[searchActiveIndex.value] : undefined
  if (product) selectProduct(product)
}
async function selectProduct(product: Product) {
  form.product_id = product.id
  form.product_name = product.name
  form.barcode = product.barcode || ''
  searchQuery.value = product.name
  searchResults.value = []
  showDropdown.value = false
  searchActiveIndex.value = -1
  pushRecent(product)
  try {
    const infoRes = await dailyProductionApi.productInfo(product.id)
    if (infoRes?.data?.price) {
      form.unit_price = infoRes.data.price
    }
  } catch {
    // 获取单价失败不影响主流程
  }
}
function clearProduct() {
  form.product_id = null; form.product_name = ''; form.barcode = ''; searchQuery.value = ''; form.unit_price = 0
}

function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function todayLocal(): string { return toLocalDate(new Date()) }
function prevDay(d: string) { const dt = new Date(d + 'T00:00:00'); dt.setDate(dt.getDate() - 1); return toLocalDate(dt) }

function validateField(field: string): boolean {
  formErrors[field] = ''
  if (field === 'quantity') {
    if (!form.quantity || form.quantity <= 0) {
      formErrors.quantity = '生产数量必须大于0'
      return false
    }
    if (form.quantity > 999999) {
      formErrors.quantity = '生产数量不能超过999999'
      return false
    }
  }
  if (field === 'product_name' && !form.product_name) {
    formErrors.product_name = '请选择产品'
    return false
  }
  return true
}

function validateForm(): boolean {
  let valid = true
  if (!validateField('product_name')) valid = false
  if (!validateField('quantity')) valid = false
  if (!formDept.value) {
    showToast('请选择生产部门', 'warning')
    valid = false
  }
  return valid
}

function closeEntryDrawer() {
  openModel.value = false
  resetForm()
}

async function handleSubmit() {
  if (!validateForm()) return
  if (keepAdding.value) {
    await confirmSubmit({ keepOpen: true })
  } else {
    await confirmSubmit({ keepOpen: false })
  }
}

async function confirmSubmit(opts: { keepOpen: boolean } = { keepOpen: false }) {
  isSubmitting.value = true
  try {
    await dailyProductionApi.createRecord({
      department: formDept.value, product_id: form.product_id, product_name: form.product_name,
      barcode: form.barcode, unit_price: form.unit_price || 0, quantity: form.quantity,
      production_value: Number(computedValue.value), production_date: props.selectedDate, remark: form.remark,
    } as Record<string, unknown>)
    showToast('录入成功', 'success')
    if (opts.keepOpen) {
      resetFormForContinue()
      nextTick(() => productSearchRef.value?.focus())
    } else {
      resetForm()
      openModel.value = false
    }
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail
    showToast(detail ?? '录入失败', 'error')
  } finally { isSubmitting.value = false }
}

function resetForm() {
  form.product_id = null; form.product_name = ''; form.barcode = ''
  form.unit_price = 0; form.quantity = 0; form.remark = ''; searchQuery.value = ''
  formDept.value = 'filling'
  keepAdding.value = false
  Object.keys(formErrors).forEach(k => formErrors[k] = '')
}

function resetFormForContinue() {
  form.product_id = null; form.product_name = ''; form.barcode = ''
  form.quantity = 0; searchQuery.value = ''
  Object.keys(formErrors).forEach(k => formErrors[k] = '')
}

watch(() => props.open, (v) => {
  if (v) {
    nextTick(() => productSearchRef.value?.focus())
  }
})

onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
  _timers.forEach(clearTimeout)
})

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
.pr-entry-dropdown { position: absolute; top: 100%; left: 0; right: 0; margin-top: 6px; background: white; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 12px 40px rgba(15, 23, 42, 0.15); max-height: 260px; overflow-y: auto; z-index: 20; padding: 4px; }
.pr-entry-dropdown-state { padding: 16px; font-size: 13px; color: #64748b; text-align: center; display: flex; align-items: center; justify-content: center; gap: 6px; }
.pr-entry-dropdown-state i { font-size: 14px; }
.pr-entry-dropdown-error { color: #dc2626; }
.pr-entry-dropdown-item { display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px 12px; border: none; background: transparent; text-align: left; cursor: pointer; border-radius: 8px; font-family: inherit; color: inherit; transition: background 0.15s ease; }
.pr-entry-dropdown-item:hover, .pr-entry-dropdown-item.active { background: #eff6ff; }
.pr-entry-dropdown-icon { width: 32px; height: 32px; border-radius: 8px; background: #f1f5f9; color: #64748b; display: flex; align-items: center; justify-content: center; font-size: 13px; flex-shrink: 0; }
.pr-entry-dropdown-item.active .pr-entry-dropdown-icon { background: #dbeafe; color: #1e40af; }
.pr-entry-dropdown-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.pr-entry-dropdown-name { font-size: 13px; font-weight: 700; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-entry-dropdown-meta { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #64748b; }
.pr-entry-dropdown-barcode { display: inline-flex; align-items: center; gap: 3px; }
.pr-entry-dropdown-barcode i { font-size: 10px; }
.pr-entry-dropdown-enter { color: #1e40af; font-size: 12px; }
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

.pr-entry-sidebar { padding: 22px 20px; background: #f8fafc; display: flex; flex-direction: column; gap: 14px; overflow-y: auto; }
.pr-entry-side-card { background: white; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }
.pr-entry-side-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; background: #f8fafc; border-bottom: 1px solid #f1f5f9; font-size: 12px; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.04em; }
.pr-entry-side-head span { display: inline-flex; align-items: center; gap: 6px; }
.pr-entry-side-head i { color: #1e40af; font-size: 11px; }
.pr-entry-side-clear { border: none; background: transparent; color: #94a3b8; font-size: 11px; font-weight: 600; cursor: pointer; padding: 2px 4px; font-family: inherit; text-transform: none; letter-spacing: 0; transition: color 0.15s ease; }
.pr-entry-side-clear:hover { color: #dc2626; }
.pr-entry-recent-list { display: flex; flex-direction: column; padding: 6px; }
.pr-entry-recent-item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 9px 10px; border: none; background: transparent; text-align: left; cursor: pointer; border-radius: 8px; font-family: inherit; color: inherit; transition: all 0.15s ease; }
.pr-entry-recent-item:hover { background: #eff6ff; transform: translateX(2px); }
.pr-entry-recent-bullet { width: 6px; height: 6px; border-radius: 50%; background: #cbd5e1; flex-shrink: 0; transition: background 0.15s ease, transform 0.15s ease; }
.pr-entry-recent-item:hover .pr-entry-recent-bullet { background: #3b82f6; transform: scale(1.4); }
.pr-entry-recent-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.pr-entry-recent-name { font-size: 13px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-entry-recent-barcode { font-size: 11px; color: #64748b; font-family: 'SF Mono', 'Consolas', monospace; }
.pr-entry-recent-arrow { font-size: 10px; color: #cbd5e1; transition: all 0.15s ease; }
.pr-entry-recent-item:hover .pr-entry-recent-arrow { color: #1e40af; transform: translateX(2px); }
.pr-entry-empty-small { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; padding: 24px 12px; color: #94a3b8; text-align: center; }
.pr-entry-empty-small i { font-size: 22px; opacity: 0.5; }
.pr-entry-empty-small span { font-size: 12px; font-weight: 600; }
.pr-entry-empty-small small { font-size: 11px; color: #cbd5e1; }
.pr-entry-shortcuts { padding: 10px 14px 12px; display: flex; flex-direction: column; gap: 8px; }
.pr-entry-shortcut { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #475569; }
.pr-entry-shortcut span { margin-left: auto; font-weight: 500; }
.pr-entry-shortcut kbd { display: inline-block; min-width: 22px; padding: 2px 6px; background: #f1f5f9; border: 1px solid #e2e8f0; border-bottom-width: 2px; border-radius: 5px; font-size: 10px; font-weight: 700; color: #475569; font-family: 'SF Mono', 'Consolas', monospace; text-align: center; }

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
  .pr-entry-sidebar { padding: 16px; max-height: 40vh; }
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
  .pr-entry-sidebar { padding: 14px; }
  .pr-entry-footer { padding: 12px 16px; flex-direction: column; align-items: stretch; }
  .pr-entry-footer-btns { width: 100%; }
  .pr-entry-btn-cancel, .pr-entry-btn-submit { flex: 1; }
}
</style>
