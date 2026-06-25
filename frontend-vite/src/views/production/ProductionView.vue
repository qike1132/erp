<template>
  <div class="pr-container">
    <div class="page-card page-card-main">

      <!-- ====== 顶部工具栏 ====== -->
      <header class="pr-toolbar">
        <div class="pr-toolbar-row pr-toolbar-row-right">
          <div class="pr-toolbar-tabs-wrap">
            <HeaderTabs />
          </div>
          <div class="pr-toolbar-controls">
            <div v-if="viewTab !== 'monthly'" class="pr-date-nav">
              <button class="pr-date-btn" @click="dateRef = prevDay(dateRef)" aria-label="上一页"><i class="fas fa-chevron-left" aria-hidden="true" /></button>
              <input v-model="dateRef" type="date" class="pr-date-input" />
              <button class="pr-date-btn" @click="dateRef = nextDay(dateRef)" aria-label="下一页"><i class="fas fa-chevron-right" aria-hidden="true" /></button>
              <button class="pr-today-btn" @click="dateRef = todayLocal()">今天</button>
            </div>
            <div v-else class="pr-date-nav">
              <button class="pr-date-btn" @click="prevMonth" aria-label="上一月"><i class="fas fa-chevron-left" aria-hidden="true" /></button>
              <span class="pr-month-label">{{ monthlyYear }}年{{ monthlyMonth }}月</span>
              <button class="pr-date-btn" @click="nextMonth" aria-label="下一月"><i class="fas fa-chevron-right" aria-hidden="true" /></button>
            </div>
            <div class="pr-divider" />
            <div class="pr-actions-group">
              <div class="pr-tab-group" role="tablist">
                <button role="tab" :aria-selected="viewTab === 'daily'" :class="['pr-tab', { 'pr-tab-active': viewTab === 'daily' }]" @click="viewTab = 'daily'">日报</button>
                <button role="tab" :aria-selected="viewTab === 'monthly'" :class="['pr-tab', { 'pr-tab-active': viewTab === 'monthly' }]" @click="viewTab = 'monthly'">月报</button>
              </div>
              <button class="pr-action-btn pr-action-primary" @click="openEntryDrawer">
                <i class="fas fa-plus" aria-hidden="true" /> 录入
              </button>
              <button class="pr-action-btn" @click="handleExport">
                <i class="fas fa-download" aria-hidden="true" /> 导出
              </button>
            </div>
          </div>
        </div>
      </header>

      <!-- ============ 日报 TAB ============ -->
      <div v-show="viewTab === 'daily'" class="pr-main">

        <section class="pr-kpi-section">
          <div v-if="reportSummary" class="pr-kpi-row">
            <KpiCard icon-class="fas fa-cubes" color-class="pr-kpi-blue" label="总产量" :value="reportSummary.overall_quantity" unit="件" />
            <KpiCard icon-class="fas fa-yen-sign" color-class="pr-kpi-green" label="总产值" :value="formatCurrency(reportSummary.overall_value)" />
            <KpiCard icon-class="fas fa-barcode" color-class="pr-kpi-amber" label="SKU 数" :value="reportSummary.overall_sku_count" unit="种" />
          </div>
        </section>

        <section class="pr-dept-section">
          <div class="pr-section-label">部门概览</div>
          <div v-if="reportSummary?.departments?.length" class="pr-dept-row">
            <div v-for="d in reportSummary.departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
              <div class="pr-dept-content">
                <div class="pr-dept-head">
                  <div :class="['pr-dept-icon-sm', `pr-dept-icon-${d.department}`]"><i :class="deptIcon(d.department)" aria-hidden="true" /></div>
                  <span class="pr-dept-name">{{ d.department_label }}</span>
                </div>
                <div class="pr-dept-qty">
                  <span class="pr-dept-qty-num">{{ d.total_quantity }}</span>
                  <span class="pr-dept-qty-unit">件</span>
                </div>
                <div class="pr-dept-stats">
                  <div class="pr-dept-stat">
                    <span class="pr-dept-stat-label">产值</span>
                    <span class="pr-dept-stat-val">¥{{ formatMoney(d.total_value) }}</span>
                  </div>
                  <div class="pr-dept-stat">
                    <span class="pr-dept-stat-label">SKU</span>
                    <span class="pr-dept-stat-val">{{ d.sku_count }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="pr-content-section">
          <div class="pr-content-row">
            <div class="pr-chart-panel">
              <div class="pr-panel-header">
                <span class="pr-panel-title"><i class="fas fa-chart-bar" aria-hidden="true" /> {{ reportDate }} 生产概况</span>
              </div>
              <div ref="dailyChartRef" class="pr-chart-body" />
            </div>
            <div v-if="reportSummary?.departments?.length" class="pr-table-panel">
              <div class="pr-panel-header">
                <span class="pr-panel-title"><i class="fas fa-table" aria-hidden="true" /> 部门汇总</span>
              </div>
              <div class="pr-table-scroll">
                <table class="pr-table">
                  <thead><tr><th>部门</th><th>产量</th><th>产值</th><th>SKU</th></tr></thead>
                  <tbody>
                    <tr v-for="d in reportSummary.departments" :key="d.department">
                      <td><span :class="['pr-dept-tag', `pr-dept-tag-${d.department}`]">{{ d.department_label }}</span></td>
                      <td><strong>{{ d.total_quantity }}</strong></td>
                      <td>{{ formatCurrency(d.total_value) }}</td>
                      <td>{{ d.sku_count }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- ============ 月报 TAB ============ -->
      <div v-show="viewTab === 'monthly'" class="pr-main">

        <section class="pr-kpi-section">
          <div v-if="monthlySummary" class="pr-kpi-row">
            <KpiCard icon-class="fas fa-cubes" color-class="pr-kpi-blue" label="月总产量" :value="monthlySummary.overall_quantity ?? 0" unit="件" />
            <KpiCard icon-class="fas fa-yen-sign" color-class="pr-kpi-green" label="月总产值" :value="formatCurrency(monthlySummary.overall_value ?? 0)" />
            <KpiCard icon-class="fas fa-calendar-check" color-class="pr-kpi-amber" label="生产天数" :value="monthlySummary.daily_data?.filter((d: any) => d.total.quantity > 0).length || 0" unit="天" />
          </div>
        </section>

        <section class="pr-dept-section">
          <div class="pr-section-label">部门概览</div>
          <div v-if="monthlySummary?.monthly_departments?.length" class="pr-dept-row">
            <div v-for="d in monthlySummary.monthly_departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
              <div class="pr-dept-content">
                <div class="pr-dept-head">
                  <div :class="['pr-dept-icon-sm', `pr-dept-icon-${d.department}`]"><i :class="deptIcon(d.department)" aria-hidden="true" /></div>
                  <span class="pr-dept-name">{{ d.department_label }}</span>
                </div>
                <div class="pr-dept-qty">
                  <span class="pr-dept-qty-num">{{ d.total_quantity }}</span>
                  <span class="pr-dept-qty-unit">件</span>
                </div>
                <div class="pr-dept-stats">
                  <div class="pr-dept-stat">
                    <span class="pr-dept-stat-label">产值</span>
                    <span class="pr-dept-stat-val">¥{{ formatMoney(d.total_value) }}</span>
                  </div>
                  <div class="pr-dept-stat">
                    <span class="pr-dept-stat-label">SKU</span>
                    <span class="pr-dept-stat-val">{{ d.sku_count }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="pr-content-section">
          <div class="pr-content-row">
            <div class="pr-chart-panel">
              <div class="pr-panel-header">
                <span class="pr-panel-title"><i class="fas fa-chart-area" aria-hidden="true" /> 月度趋势</span>
              </div>
              <div ref="monthlyChartRef" class="pr-chart-body" />
            </div>
            <div v-if="monthlySummary?.daily_data?.length" class="pr-table-panel">
              <div class="pr-panel-header">
                <span class="pr-panel-title"><i class="fas fa-table" aria-hidden="true" /> 每日明细</span>
              </div>
              <div class="pr-table-scroll">
                <table class="pr-table">
                  <thead><tr><th>日期</th><th>充棉</th><th>手工</th><th>包装</th><th>合计</th><th>总产值</th></tr></thead>
                  <tbody>
                    <tr v-for="d in monthlySummary.daily_data" :key="d.date">
                      <td><strong>{{ d.day }}日</strong></td>
                      <td>{{ d.filling?.quantity ?? 0 }}</td>
                      <td>{{ d.handcraft?.quantity ?? 0 }}</td>
                      <td>{{ d.packaging?.quantity ?? 0 }}</td>
                      <td><strong>{{ d.total?.quantity ?? 0 }}</strong></td>
                      <td>¥{{ formatMoney(d.total?.value ?? 0) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- ============ 录入弹窗 (Data Entry Center) ============ -->
      <Transition name="pr-entry">
        <div v-if="showEntryDrawer" class="pr-entry-overlay" @click.self="closeEntryDrawer">
          <div class="pr-entry-modal" role="dialog" aria-labelledby="pr-entry-title">
            <header class="pr-entry-header">
              <div class="pr-entry-header-left">
                <span class="pr-entry-icon"><i class="fas fa-pen-to-square" aria-hidden="true" /></span>
                <div>
                  <h3 id="pr-entry-title">录入生产数据</h3>
                  <span class="pr-entry-sub">{{ selectedDate }} · 快捷键 <kbd>Ctrl</kbd>+<kbd>N</kbd></span>
                </div>
              </div>
              <button class="pr-entry-close" @click="closeEntryDrawer" aria-label="关闭"><i class="fas fa-times" aria-hidden="true" /></button>
            </header>

            <div class="pr-entry-body">
              <!-- 左侧：表单 -->
              <div class="pr-entry-form">
                <!-- 1. 日期 -->
                <div class="pr-entry-group">
                  <label class="pr-entry-label">生产日期</label>
                  <div class="pr-entry-date-row">
                    <button type="button" :class="['pr-date-chip', { active: selectedDate === todayLocal() }]" @click="selectedDate = todayLocal()">今日</button>
                    <button type="button" :class="['pr-date-chip', { active: selectedDate === prevDay(todayLocal()) }]" @click="selectedDate = prevDay(todayLocal())">昨日</button>
                    <input v-model="selectedDate" type="date" class="pr-entry-input pr-entry-date-input" />
                  </div>
                </div>

                <!-- 2. 部门 -->
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
                      <span class="pr-entry-dept-mark"><i class="fas fa-circle-check" aria-hidden="true" /></span>
                    </button>
                  </div>
                </div>

                <!-- 3. 产品 -->
                <div class="pr-entry-group">
                  <label class="pr-entry-label">产品 <span class="pr-req">*</span></label>
                  <div class="pr-entry-search">
                    <i class="fas fa-search pr-entry-search-icon" aria-hidden="true" />
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
                      <i class="fas fa-times" aria-hidden="true" />
                    </button>
                    <div v-if="showDropdown" class="pr-entry-dropdown">
                      <div v-if="searchLoading" class="pr-entry-dropdown-state">
                        <i class="fas fa-spinner fa-spin" aria-hidden="true" /> 搜索中…
                      </div>
                      <div v-else-if="searchError" class="pr-entry-dropdown-state pr-entry-dropdown-error">
                        <i class="fas fa-exclamation-circle" aria-hidden="true" /> {{ searchError }}
                      </div>
                      <div v-else-if="!searchResults.length" class="pr-entry-dropdown-state">
                        <i class="fas fa-inbox" aria-hidden="true" /> 无匹配产品
                      </div>
                      <button
                        v-for="(p, idx) in searchResults"
                        :key="p.id"
                        type="button"
                        :class="['pr-entry-dropdown-item', { active: idx === searchActiveIndex }]"
                        @mousedown.prevent="selectProduct(p)"
                      >
                        <span class="pr-entry-dropdown-icon"><i class="fas fa-box" aria-hidden="true" /></span>
                        <span class="pr-entry-dropdown-content">
                          <span class="pr-entry-dropdown-name">{{ p.name }}</span>
                          <span class="pr-entry-dropdown-meta">
                            <span v-if="p.barcode" class="pr-entry-dropdown-barcode"><i class="fas fa-barcode" aria-hidden="true" /> {{ p.barcode }}</span>
                            <span v-if="p.specification" class="pr-entry-dropdown-spec">{{ p.specification }}</span>
                          </span>
                        </span>
                        <i v-if="idx === searchActiveIndex" class="fas fa-arrow-right pr-entry-dropdown-enter" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                  <div v-if="form.product_name" class="pr-entry-selected">
                    <span class="pr-entry-selected-icon"><i class="fas fa-check-circle" aria-hidden="true" /></span>
                    <span class="pr-entry-selected-name">{{ form.product_name }}</span>
                    <span v-if="form.barcode" class="pr-entry-selected-barcode">{{ form.barcode }}</span>
                  </div>
                  <div v-if="formErrors.product_name" class="pr-entry-error">{{ formErrors.product_name }}</div>
                </div>

                <!-- 4. 数量 -->
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

                <!-- 5. 单价 + 产值 -->
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
                      <i class="fas fa-yen-sign" aria-hidden="true" />
                      <span>{{ formatCurrency(computedValue) }}</span>
                    </div>
                  </div>
                </div>

                <!-- 6. 备注 -->
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

              <!-- 右侧：侧栏 -->
              <aside class="pr-entry-sidebar">
                <div class="pr-entry-side-card">
                  <div class="pr-entry-side-head">
                    <span><i class="fas fa-clock-rotate-left" aria-hidden="true" /> 最近使用</span>
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
                      <i class="fas fa-chevron-right pr-entry-recent-arrow" aria-hidden="true" />
                    </button>
                  </div>
                  <div v-else class="pr-entry-empty-small">
                    <i class="fas fa-inbox" aria-hidden="true" />
                    <span>暂无最近使用</span>
                    <small>录入后会自动记录</small>
                  </div>
                </div>

                <div class="pr-entry-side-card">
                  <div class="pr-entry-side-head">
                    <span><i class="fas fa-keyboard" aria-hidden="true" /> 快捷键</span>
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
                  <i class="fas fa-check" />
                </span>
                <span>保存后继续录入下一条</span>
              </label>
              <div class="pr-entry-footer-btns">
                <button type="button" class="pr-entry-btn-cancel" @click="closeEntryDrawer">取消</button>
                <button type="button" class="pr-entry-btn-submit" :disabled="isSubmitting" @click="handleSubmit">
                  <i v-if="isSubmitting" class="fas fa-spinner fa-spin" aria-hidden="true" />
                  <i v-else class="fas fa-check" aria-hidden="true" />
                  <span>确认录入</span>
                  <span class="pr-entry-btn-hint">Ctrl+Enter</span>
                </button>
              </div>
            </footer>
          </div>
        </div>
      </Transition>

      <!-- ============ 导出进度提示 ============ -->
      <Transition name="pr-toast">
        <div v-if="exportStatus.show" :class="['pr-export-toast', exportStatus.type]">
          <i :class="exportStatus.icon" aria-hidden="true" />
          <span>{{ exportStatus.message }}</span>
        </div>
      </Transition>
    </div>
  </div>
  <UiConfirmDialog
    :open="confirmDialog.open"
    :text="confirmDialog.text"
    :sub="confirmDialog.sub"
    :type="confirmDialog.type"
    @confirm="confirmDialog.onConfirm"
    @cancel="confirmDialog.onCancel"
  />
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { dailyProductionApi, productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import type { DailyProductionRecord, Product } from '@/types'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import KpiCard from './components/KpiCard.vue'
import { useProductionCharts } from './composables/useProductionCharts'

const _timers: ReturnType<typeof setTimeout>[] = []

const confirmDialog = useConfirmDialog()
import { formatCurrency, formatNumber } from '@/utils/format'
const formatMoney = formatNumber

const queryClient = useQueryClient()

const departments = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]

function deptLabel(d: string) { return departments.find(x => x.value === d)?.label ?? d }
function deptIcon(d: string) { return departments.find(x => x.value === d)?.icon ?? 'fas fa-building' }


// ===== 核心状态 =====
const viewTab = ref('daily')
const selectedDate = ref(todayLocal())
const reportDate = ref(todayLocal())
const showEntryDrawer = ref(false)
const formDept = ref('filling')
const isSubmitting = ref(false)
const monthlyYear = ref(new Date().getFullYear())
const monthlyMonth = ref(new Date().getMonth() + 1)
const keepAdding = ref(false)

// ===== 最近使用产品 (localStorage 持久化) =====
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

// 统一日期引用：看板用 selectedDate，日报用 reportDate
const dateRef = computed({
  get: () => viewTab.value === 'daily' ? reportDate.value : selectedDate.value,
  set: (v: string) => { if (viewTab.value === 'daily') reportDate.value = v; else selectedDate.value = v }
})

// ===== 表单 =====
const form = reactive({
  product_id: null as number | null,
  product_name: '',
  barcode: '',
  unit_price: 0,
  quantity: 0,
  remark: '',
})
const formErrors = reactive<Record<string, string>>({})
const computedValue = computed(() => {
  const v = (form.quantity || 0) * (form.unit_price || 0)
  return v
})

// ===== 产品搜索 =====
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
      const res = (await productApi.search(searchQuery.value.trim())) as any
      searchResults.value = res.products ?? res ?? []
      searchError.value = ''
    } catch (error: any) {
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
  if (searchActiveIndex.value >= 0 && searchResults.value[searchActiveIndex.value]) {
    selectProduct(searchResults.value[searchActiveIndex.value])
  }
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
    const infoRes = await dailyProductionApi.productInfo(product.id) as any
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

// ===== 数据查询 =====
// 日报
const { data: reportSummaryData } = useQuery({
  queryKey: ['daily-production-daily-summary', reportDate],
  queryFn: () => dailyProductionApi.dailySummary(reportDate.value) as Promise<any>,
  staleTime: 30_000,
})
const reportSummary = computed(() => reportSummaryData.value?.data ?? reportSummaryData.value ?? null)

// 月报
const { data: monthlySummaryData } = useQuery({
  queryKey: ['daily-production-monthly-summary', monthlyYear, monthlyMonth],
  queryFn: () => dailyProductionApi.monthlySummary({ year: monthlyYear.value, month: monthlyMonth.value }) as Promise<any>,
  staleTime: 60_000,
})
const monthlySummary = computed(() => monthlySummaryData.value?.data ?? monthlySummaryData.value ?? null)

function prevMonth() { if (monthlyMonth.value === 1) { monthlyMonth.value = 12; monthlyYear.value-- } else { monthlyMonth.value-- } }
function nextMonth() { if (monthlyMonth.value === 12) { monthlyMonth.value = 1; monthlyYear.value++ } else { monthlyMonth.value++ } }
function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function todayLocal(): string { return toLocalDate(new Date()) }

function prevDay(d: string) { const dt = new Date(d + 'T00:00:00'); dt.setDate(dt.getDate() - 1); return toLocalDate(dt) }
function nextDay(d: string) { const dt = new Date(d + 'T00:00:00'); dt.setDate(dt.getDate() + 1); return toLocalDate(dt) }

// ===== 表单校验 =====
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

// ===== 表单提交 =====
function openEntryDrawer() {
  showEntryDrawer.value = true
  nextTick(() => {
    productSearchRef.value?.focus()
  })
}

function closeEntryDrawer() {
  showEntryDrawer.value = false
  resetForm()
}

async function handleSubmit() {
  if (!validateForm()) return
  // 内联直接提交：保留 keepAdding 以支持快速连续录入
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
      production_value: Number(computedValue.value), production_date: selectedDate.value, remark: form.remark,
    } as any)
    showToast('录入成功', 'success')
    if (opts.keepOpen) {
      // 连续录入：保留部门/日期，仅重置产品和数量；焦点回到搜索框
      resetFormForContinue()
      nextTick(() => productSearchRef.value?.focus())
    } else {
      resetForm()
      showEntryDrawer.value = false
    }
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
  } catch (error: any) {
    showToast(error?.response?.data?.detail ?? '录入失败', 'error')
  }
  finally { isSubmitting.value = false }
}

function resetForm() {
  form.product_id = null; form.product_name = ''; form.barcode = ''
  form.unit_price = 0; form.quantity = 0; form.remark = ''; searchQuery.value = ''
  formDept.value = 'filling'
  keepAdding.value = false
  Object.keys(formErrors).forEach(k => formErrors[k] = '')
}

function resetFormForContinue() {
  // 连续录入模式：保留部门、日期、备注、单价；重置产品和数量
  form.product_id = null; form.product_name = ''; form.barcode = ''
  form.quantity = 0; searchQuery.value = ''
  Object.keys(formErrors).forEach(k => formErrors[k] = '')
}

async function handleDelete(id: number) {
  if (!(await confirmDialog.confirm('确认删除该生产记录？'))) return
  try {
    await dailyProductionApi.deleteRecord(id)
    showToast('已删除', 'success')
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
  } catch { showToast('删除失败', 'error') }
}

// ===== 导出（带进度提示和重试） =====
const exportStatus = reactive({ show: false, message: '', type: 'info', icon: 'fas fa-spinner fa-spin' })

async function handleExport() {
  exportStatus.show = true
  exportStatus.type = 'info'
  exportStatus.icon = 'fas fa-spinner fa-spin'
  exportStatus.message = '正在导出报表...'

  let retries = 0
  const maxRetries = 2

  while (retries <= maxRetries) {
    try {
      await dailyProductionApi.export({ start_date: selectedDate.value, end_date: selectedDate.value })
      exportStatus.type = 'success'
      exportStatus.icon = 'fas fa-check-circle'
      exportStatus.message = '导出成功'
      const _t = setTimeout(() => { exportStatus.show = false }, 3000)
      _timers.push(_t)
      return
    } catch (error: any) {
      retries++
      if (retries <= maxRetries) {
        exportStatus.message = `导出失败，正在重试 (${retries}/${maxRetries})...`
        await new Promise(r => setTimeout(r, 1000 * retries))
      } else {
        exportStatus.type = 'error'
        exportStatus.icon = 'fas fa-times-circle'
        exportStatus.message = '导出失败，请稍后重试'
        const _t = setTimeout(() => { exportStatus.show = false }, 5000)
        _timers.push(_t)
      }
    }
  }
}

function formatTime(timestamp?: string | null) { return timestamp ? timestamp.slice(11, 16) : '' }

// ===== 键盘快捷键 =====
function handleKeydown(event: KeyboardEvent) {
  if (event.ctrlKey && (event.key === 'n' || event.key === 'N')) {
    event.preventDefault()
    if (!showEntryDrawer.value) openEntryDrawer()
  }
  if (event.ctrlKey && event.key === 'Enter' && showEntryDrawer.value) {
    event.preventDefault()
    handleSubmit()
  }
  if (event.key === 'Escape' && showEntryDrawer.value) {
    closeEntryDrawer()
  }
  if (event.ctrlKey && ['1', '2'].includes(event.key)) {
    event.preventDefault()
    const tabs = ['daily', 'monthly']
    viewTab.value = tabs[parseInt(event.key) - 1]
  }
}

// ===== ECharts =====
const dailyChartRef = ref<HTMLElement>()
const monthlyChartRef = ref<HTMLElement>()

useProductionCharts(
  reportSummary,
  monthlySummary,
  viewTab,
  dailyChartRef,
  monthlyChartRef,
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (searchTimer) clearTimeout(searchTimer)
  _timers.forEach(clearTimeout)
})
</script>

<style scoped>
/* ========================================
   生产报表 — UI/UX 全面重构
   设计系统：Data-Dense Dashboard
   色彩：Primary #1E40AF / Secondary #3B82F6 / CTA #F59E0B
   信息层级：KPI英雄区 → 部门面板 → 图表+表格
   ======================================== */

/* === 全局容器 === */
.pr-container {
  width: 100%;
  padding: 0;
  margin: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === 顶部工具栏 === */
.pr-toolbar {
  padding: 14px 24px 10px;
  background: white;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.pr-toolbar-tabs-wrap { display: flex; align-items: center; flex: 0 0 auto; min-width: 0; }
.pr-toolbar-tabs-wrap :deep(.ht-bar) { width: fit-content; margin: 0; }
.pr-toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  width: 100%;
}
.pr-toolbar-row-right {
  justify-content: space-between;
  flex-wrap: nowrap;
}
.pr-toolbar-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.pr-actions-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 3px;
  border-radius: 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}
.pr-actions-group .pr-tab-group {
  background: transparent;
  border: none;
  padding: 0;
  border-radius: 8px;
  gap: 2px;
}
.pr-actions-group .pr-action-btn {
  background: transparent;
  border: 1px solid transparent;
  box-shadow: none;
}
.pr-actions-group .pr-action-primary {
  background: transparent;
  border-color: transparent;
  color: #1e40af;
}
.pr-toolbar-left { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.pr-toolbar-center { display: flex; align-items: center; }
.pr-toolbar-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.pr-divider {
  width: 1px; height: 20px; background: #e2e8f0; flex-shrink: 0;
}

/* === 日期导航 === */
.pr-date-nav { display: flex; align-items: center; gap: 6px; }
.pr-date-btn {
  width: 32px; height: 32px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: #64748b;
  transition: all 0.2s ease;
}
.pr-date-btn:hover {
  border-color: #3b82f6; color: #1e40af;
  background: #eff6ff;
}
.pr-date-input {
  padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 8px;
  font-size: 13px; font-weight: 600; color: #1e293b;
  background: white; cursor: pointer;
  transition: border-color 0.2s ease;
}
.pr-date-input:hover { border-color: #3b82f6; }
.pr-today-btn {
  padding: 6px 12px; border: 1px solid #bfdbfe; border-radius: 8px;
  background: #eff6ff; font-size: 12px; font-weight: 600; color: #1e40af;
  cursor: pointer; transition: all 0.2s ease;
}
.pr-today-btn:hover { background: #dbeafe; }
.pr-month-label { font-size: 15px; font-weight: 700; color: #1e293b; min-width: 100px; text-align: center; }

/* === Tab 切换 === */
.pr-tab-group {
  display: inline-flex; gap: 2px; padding: 3px;
  border-radius: 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}
.pr-tab {
  padding: 7px 16px; border: none; border-radius: 8px;
  background: transparent; font-size: 13px; font-weight: 600;
  color: #64748b; cursor: pointer;
  transition: all 0.2s ease;
}
.pr-tab:hover { color: #1e40af; background: white; }
.pr-tab-active {
  background: white; color: #1e40af;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06);
}

/* === 操作按钮 === */
.pr-action-btn {
  padding: 7px 14px; border: 1px solid #e2e8f0; border-radius: 8px;
  background: white; font-size: 12px; font-weight: 600; cursor: pointer;
  color: #475569; display: inline-flex; align-items: center; gap: 5px;
  transition: all 0.2s ease;
}
.pr-action-btn:hover { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-action-primary { color: #1e40af; border-color: #bfdbfe; background: #eff6ff; }
.pr-action-primary:hover { background: #dbeafe; border-color: #3b82f6; }

/* === 内容主体 === */
.pr-main {
  flex: 1; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: 0;
}

/* === KPI 英雄区 === */
.pr-kpi-section {
  padding: 16px 24px 0;
  flex-shrink: 0;
}
.pr-kpi-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.pr-kpi-card {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: white;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
  position: relative;
  overflow: hidden;
}
.pr-kpi-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.pr-kpi-blue:hover { border-color: #bfdbfe; }
.pr-kpi-green:hover { border-color: #bbf7d0; }
.pr-kpi-amber:hover { border-color: #fde68a; }

.pr-kpi-icon-wrap {
  width: 48px; height: 48px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; flex-shrink: 0;
}
.pr-kpi-blue .pr-kpi-icon-wrap { background: #eff6ff; color: #1e40af; }
.pr-kpi-green .pr-kpi-icon-wrap { background: #f0fdf4; color: #15803d; }
.pr-kpi-amber .pr-kpi-icon-wrap { background: #fffbeb; color: #d97706; }

.pr-kpi-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pr-kpi-label { font-size: 12px; font-weight: 600; color: #64748b; letter-spacing: 0.03em; text-transform: uppercase; }
.pr-kpi-value { font-size: 24px; font-weight: 800; color: #1e293b; font-variant-numeric: tabular-nums; line-height: 1.2; }
.pr-kpi-unit { font-size: 13px; font-weight: 600; color: #64748b; margin-left: 3px; }

/* === 部门面板 === */
.pr-dept-section {
  padding: 12px 24px 0;
  flex-shrink: 0;
}
.pr-section-label {
  font-size: 11px; font-weight: 700; color: #94a3b8;
  text-transform: uppercase; letter-spacing: 0.08em;
  margin-bottom: 8px;
}
.pr-dept-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.pr-dept-card {
  display: flex;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: white;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.pr-dept-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.pr-dept-content { flex: 1; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.pr-dept-head { display: flex; align-items: center; gap: 8px; }
.pr-dept-icon-sm {
  width: 28px; height: 28px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
}
.pr-dept-name { font-size: 13px; font-weight: 700; color: #1e293b; }
.pr-dept-qty { display: flex; align-items: baseline; gap: 4px; }
.pr-dept-qty-num { font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums; line-height: 1.1; }
.pr-dept-qty-unit { font-size: 13px; font-weight: 600; color: #64748b; }
.pr-dept-stats { display: flex; gap: 16px; }
.pr-dept-stat { display: flex; flex-direction: column; gap: 1px; }
.pr-dept-stat-label { font-size: 11px; font-weight: 500; color: #94a3b8; }
.pr-dept-stat-val { font-size: 12px; font-weight: 700; color: #475569; font-variant-numeric: tabular-nums; }

/* 部门色系 */
.pr-dept-filling .pr-dept-qty-num { color: #1e3a8a; }
.pr-dept-filling .pr-dept-icon-sm { background: #eff6ff; color: #1e40af; }
.pr-dept-filling:hover { border-color: #bfdbfe; }

.pr-dept-handcraft .pr-dept-qty-num { color: #14532d; }
.pr-dept-handcraft .pr-dept-icon-sm { background: #f0fdf4; color: #15803d; }
.pr-dept-handcraft:hover { border-color: #bbf7d0; }

.pr-dept-packaging .pr-dept-qty-num { color: #78350f; }
.pr-dept-packaging .pr-dept-icon-sm { background: #fffbeb; color: #d97706; }
.pr-dept-packaging:hover { border-color: #fde68a; }

/* === 图表 + 表格 并排区 === */
.pr-content-section {
  padding: 12px 24px 16px;
  flex: 1; min-height: 0;
}
.pr-content-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  height: 100%;
  min-height: 320px;
}
.pr-chart-panel, .pr-table-panel {
  display: flex; flex-direction: column; min-height: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}

/* 面板标题 */
.pr-panel-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
  background: #fafbfc;
}
.pr-panel-title {
  font-size: 13px; font-weight: 700; color: #1e293b;
  display: flex; align-items: center; gap: 6px;
}
.pr-panel-title i { color: #3b82f6; font-size: 12px; }

/* 图表切换按钮 */
.pr-chart-toggle {
  display: flex; gap: 2px; padding: 2px;
  border-radius: 8px; background: #f1f5f9;
}
.pr-toggle-btn {
  padding: 5px 12px; border: none; border-radius: 6px;
  background: transparent; font-size: 12px; font-weight: 600;
  color: #64748b; cursor: pointer; transition: all 0.2s ease;
}
.pr-toggle-btn:hover { color: #1e40af; }
.pr-toggle-btn.active {
  background: white; color: #1e40af;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

/* 表格筛选按钮 */
.pr-table-filter { display: flex; gap: 4px; }
.pr-filter-btn {
  padding: 4px 10px; border: 1px solid #e2e8f0; border-radius: 6px;
  background: white; font-size: 11px; font-weight: 600;
  color: #64748b; cursor: pointer; transition: all 0.2s ease;
}
.pr-filter-btn:hover { border-color: #3b82f6; color: #1e40af; }
.pr-filter-btn.active {
  background: #eff6ff; border-color: #3b82f6; color: #1e40af;
}

/* 图表 */
.pr-chart-body {
  width: 100%; height: 280px;
  flex-shrink: 0;
}

/* 表格 */
.pr-table-scroll {
  overflow-y: auto; overflow-x: auto;
  flex: 1; min-height: 0;
}
.pr-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pr-table thead th {
  padding: 8px 12px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em;
  background: #f8fafc; border-bottom: 2px solid #e2e8f0;
  color: #64748b; text-align: center; white-space: nowrap;
  position: sticky; top: 0; z-index: 1;
}
.pr-table tbody td {
  padding: 8px 12px; font-size: 13px;
  border-bottom: 1px solid #f1f5f9;
  text-align: center; vertical-align: middle;
  transition: background 0.15s ease; color: #1e293b;
}
.pr-table tbody tr:hover { background: #f8fafc; }
.pr-td-product { text-align: left !important; }
.pr-td-mono { font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; color: #64748b; }
.pr-td-value { font-weight: 700; color: #15803d; }
.pr-td-time { font-size: 12px; color: #94a3b8; }
.pr-row-del {
  border: none; background: transparent; color: #94a3b8;
  cursor: pointer; font-size: 12px; padding: 4px 6px; border-radius: 6px;
  transition: all 0.15s ease;
}
.pr-row-del:hover { color: #dc2626; background: #fef2f2; }

/* 部门标签 */
.pr-dept-tag {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 8px; border-radius: 6px;
  font-size: 11px; font-weight: 700; white-space: nowrap;
}
.pr-dept-tag-filling { background: #eff6ff; color: #1e40af; }
.pr-dept-tag-handcraft { background: #f0fdf4; color: #15803d; }
.pr-dept-tag-packaging { background: #fffbeb; color: #d97706; }

/* === 空状态 === */
.pr-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 40px 20px; color: #94a3b8;
}
.pr-empty i { font-size: 28px; opacity: 0.4; }
.pr-empty span { font-size: 13px; }

/* 分页 */
.pr-pagination {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 8px 0; border-top: 1px solid #f1f5f9;
}
.pr-page-btn {
  width: 28px; height: 28px; border: 1px solid #e2e8f0; border-radius: 6px;
  background: white; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: #64748b; transition: all 0.2s ease;
}
.pr-page-btn:hover:not(:disabled) { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pr-page-info { font-size: 12px; font-weight: 600; color: #64748b; }

/* ========================================
   录入弹窗 — Data Entry Center
   设计系统：Data-Dense Dashboard
   信息层级：表头 → 表单 (60%) + 侧栏 (40%) → 操作栏
   ======================================== */

/* === 遮罩 === */
.pr-entry-overlay {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(6px);
  z-index: 100; display: flex; align-items: center; justify-content: center;
  padding: 24px;
  box-sizing: border-box;
}

/* === 弹窗主体 === */
.pr-entry-modal {
  width: 800px; max-width: 100%; max-height: 100%;
  background: white; border-radius: 18px;
  display: flex; flex-direction: column;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22), 0 4px 12px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

/* === Header === */
.pr-entry-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px;
  padding: 18px 24px;
  background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
  color: white;
  flex-shrink: 0;
}
.pr-entry-header-left { display: flex; align-items: center; gap: 14px; min-width: 0; }
.pr-entry-icon {
  width: 42px; height: 42px; border-radius: 12px;
  background: rgba(255, 255, 255, 0.18); backdrop-filter: blur(10px);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
}
.pr-entry-header h3 {
  margin: 0; font-size: 16px; font-weight: 700; color: white;
  letter-spacing: 0.01em;
}
.pr-entry-sub {
  display: block; font-size: 12px; font-weight: 500;
  color: rgba(255, 255, 255, 0.85); margin-top: 2px;
}
.pr-entry-sub kbd {
  display: inline-block; padding: 1px 5px;
  background: rgba(255, 255, 255, 0.2); border-radius: 4px;
  font-size: 10px; font-family: 'SF Mono', 'Consolas', monospace;
  margin: 0 1px;
}
.pr-entry-close {
  width: 36px; height: 36px; border: none;
  background: rgba(255, 255, 255, 0.15); color: white;
  border-radius: 10px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
  transition: all 0.2s ease;
}
.pr-entry-close:hover { background: rgba(255, 255, 255, 0.28); }

/* === Body 双列布局 === */
.pr-entry-body {
  flex: 1; min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
  gap: 0;
  overflow: hidden;
}

/* === 左侧表单 === */
.pr-entry-form {
  padding: 22px 24px;
  overflow-y: auto;
  display: flex; flex-direction: column; gap: 18px;
  border-right: 1px solid #f1f5f9;
}

/* 表单分组 */
.pr-entry-group { display: flex; flex-direction: column; gap: 7px; }
.pr-entry-label {
  font-size: 12px; font-weight: 700; color: #475569;
  letter-spacing: 0.03em; text-transform: uppercase;
}
.pr-req { color: #dc2626; font-weight: 800; }

.pr-entry-input {
  width: 100%; padding: 10px 14px; font-size: 14px; line-height: 1.5;
  color: #1e293b; background: white;
  border: 1px solid #e2e8f0; border-radius: 10px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  outline: none; min-height: 44px; box-sizing: border-box; font-family: inherit;
}
.pr-entry-input:hover:not(:disabled) { border-color: #cbd5e1; }
.pr-entry-input:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }
.pr-entry-input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.pr-entry-input::placeholder { color: #94a3b8; }

.pr-entry-error {
  font-size: 12px; color: #dc2626; font-weight: 600;
  display: flex; align-items: center; gap: 4px;
}
.pr-entry-error::before {
  content: '\f06a'; font-family: 'Font Awesome 5 Free'; font-weight: 900;
  font-size: 11px;
}

/* === 日期行 === */
.pr-entry-date-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pr-date-chip {
  padding: 7px 14px; border: 1px solid #e2e8f0; border-radius: 8px;
  background: white; font-size: 12px; font-weight: 600; color: #475569;
  cursor: pointer; transition: all 0.2s ease;
}
.pr-date-chip:hover { border-color: #3b82f6; color: #1e40af; }
.pr-date-chip.active {
  background: #1e40af; border-color: #1e40af; color: white;
  box-shadow: 0 1px 3px rgba(30, 64, 175, 0.3);
}
.pr-entry-date-input { flex: 1; min-width: 140px; }

/* === 部门卡片网格 === */
.pr-entry-dept-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
}
.pr-entry-dept-card {
  position: relative;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; padding: 14px 10px;
  border: 2px solid #e2e8f0; border-radius: 12px;
  background: white; cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
}
.pr-entry-dept-card:hover {
  border-color: #cbd5e1; transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.pr-entry-dept-icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  transition: all 0.2s ease;
}
.pr-entry-dept-name {
  font-size: 13px; font-weight: 700; color: #475569;
  letter-spacing: 0.01em;
}
.pr-entry-dept-mark {
  position: absolute; top: 6px; right: 6px;
  font-size: 14px; color: transparent;
  transition: all 0.2s ease;
}
.pr-entry-dept-card.active { transform: translateY(-1px); }
.pr-entry-dept-card.active .pr-entry-dept-mark { color: white; }

/* 充棉 - 蓝 */
.pr-entry-dept-filling .pr-entry-dept-icon { background: #eff6ff; color: #1e40af; }
.pr-entry-dept-filling:hover { border-color: #93c5fd; }
.pr-entry-dept-filling.active {
  background: linear-gradient(135deg, #3b82f6, #1e40af);
  border-color: #1e40af;
  box-shadow: 0 6px 16px rgba(59, 130, 246, 0.35);
}
.pr-entry-dept-filling.active .pr-entry-dept-icon { background: rgba(255, 255, 255, 0.2); color: white; }
.pr-entry-dept-filling.active .pr-entry-dept-name { color: white; }

/* 手工 - 绿 */
.pr-entry-dept-handcraft .pr-entry-dept-icon { background: #f0fdf4; color: #15803d; }
.pr-entry-dept-handcraft:hover { border-color: #86efac; }
.pr-entry-dept-handcraft.active {
  background: linear-gradient(135deg, #22c55e, #15803d);
  border-color: #15803d;
  box-shadow: 0 6px 16px rgba(34, 197, 94, 0.35);
}
.pr-entry-dept-handcraft.active .pr-entry-dept-icon { background: rgba(255, 255, 255, 0.2); color: white; }
.pr-entry-dept-handcraft.active .pr-entry-dept-name { color: white; }

/* 包装 - 琥珀 */
.pr-entry-dept-packaging .pr-entry-dept-icon { background: #fffbeb; color: #d97706; }
.pr-entry-dept-packaging:hover { border-color: #fcd34d; }
.pr-entry-dept-packaging.active {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  border-color: #d97706;
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.35);
}
.pr-entry-dept-packaging.active .pr-entry-dept-icon { background: rgba(255, 255, 255, 0.2); color: white; }
.pr-entry-dept-packaging.active .pr-entry-dept-name { color: white; }

/* === 产品搜索 === */
.pr-entry-search { position: relative; }
.pr-entry-search-input {
  padding-left: 40px !important; padding-right: 40px !important;
  font-size: 15px !important; min-height: 48px !important;
}
.pr-entry-search-icon {
  position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
  color: #94a3b8; font-size: 15px; pointer-events: none;
}
.pr-entry-search-clear {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  width: 28px; height: 28px; border: none; background: #f1f5f9;
  border-radius: 50%; cursor: pointer;
  color: #64748b; font-size: 11px;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s ease;
}
.pr-entry-search-clear:hover { background: #e2e8f0; color: #1e293b; }

.pr-entry-dropdown {
  position: absolute; top: 100%; left: 0; right: 0; margin-top: 6px;
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.15);
  max-height: 260px; overflow-y: auto; z-index: 20;
  padding: 4px;
}
.pr-entry-dropdown-state {
  padding: 16px; font-size: 13px; color: #64748b; text-align: center;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.pr-entry-dropdown-state i { font-size: 14px; }
.pr-entry-dropdown-error { color: #dc2626; }
.pr-entry-dropdown-item {
  display: flex; align-items: center; gap: 12px;
  width: 100%; padding: 10px 12px; border: none;
  background: transparent; text-align: left; cursor: pointer;
  border-radius: 8px;
  font-family: inherit; color: inherit;
  transition: background 0.15s ease;
}
.pr-entry-dropdown-item:hover, .pr-entry-dropdown-item.active {
  background: #eff6ff;
}
.pr-entry-dropdown-icon {
  width: 32px; height: 32px; border-radius: 8px;
  background: #f1f5f9; color: #64748b;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; flex-shrink: 0;
}
.pr-entry-dropdown-item.active .pr-entry-dropdown-icon {
  background: #dbeafe; color: #1e40af;
}
.pr-entry-dropdown-content {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column; gap: 2px;
}
.pr-entry-dropdown-name {
  font-size: 13px; font-weight: 700; color: #1e293b;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pr-entry-dropdown-meta {
  display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: #64748b;
}
.pr-entry-dropdown-barcode { display: inline-flex; align-items: center; gap: 3px; }
.pr-entry-dropdown-barcode i { font-size: 10px; }
.pr-entry-dropdown-enter { color: #1e40af; font-size: 12px; }

.pr-entry-selected {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: #eff6ff; border: 1px solid #bfdbfe;
  border-radius: 10px; font-size: 13px; font-weight: 600; color: #1e40af;
}
.pr-entry-selected-icon { color: #1e40af; font-size: 15px; flex-shrink: 0; }
.pr-entry-selected-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-entry-selected-barcode {
  font-size: 11px; color: #64748b; font-weight: 500;
  font-family: 'SF Mono', 'Consolas', monospace;
  background: white; padding: 2px 6px; border-radius: 4px;
  border: 1px solid #bfdbfe;
}

/* === 数量输入 === */
.pr-entry-qty-row {
  display: flex; align-items: center; gap: 10px;
}
.pr-entry-qty-input-wrap {
  flex: 1; min-width: 0;
  display: flex; align-items: stretch;
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.pr-entry-qty-input-wrap:focus-within {
  border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.pr-entry-qty-step {
  border: none; background: #f8fafc;
  padding: 0 14px; font-size: 13px; font-weight: 700;
  color: #475569; cursor: pointer; font-family: inherit;
  transition: background 0.15s ease, color 0.15s ease;
  min-width: 52px;
}
.pr-entry-qty-step:first-child { border-right: 1px solid #e2e8f0; }
.pr-entry-qty-step:last-child { border-left: 1px solid #e2e8f0; }
.pr-entry-qty-step:hover { background: #1e40af; color: white; }
.pr-entry-qty-input {
  flex: 1; min-width: 0; border: none !important;
  background: transparent !important;
  text-align: center; font-size: 22px !important; font-weight: 800 !important;
  color: #1e293b; padding: 8px 4px !important; min-height: 48px !important;
  font-variant-numeric: tabular-nums;
}
.pr-entry-qty-input:focus { box-shadow: none !important; }
.pr-entry-qty-input::-webkit-outer-spin-button,
.pr-entry-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.pr-entry-qty-input { -moz-appearance: textfield; }
.pr-entry-qty-unit {
  display: flex; align-items: center;
  padding: 0 12px; font-size: 12px; font-weight: 600; color: #64748b;
  background: #f8fafc; border-left: 1px solid #e2e8f0;
}
.pr-entry-qty-btns { display: flex; gap: 6px; }
.pr-entry-qty-pill {
  padding: 0 14px; height: 48px; border: 1px solid #e2e8f0; border-radius: 12px;
  background: white; font-size: 14px; font-weight: 700; color: #475569;
  cursor: pointer; font-family: inherit;
  transition: all 0.15s ease;
}
.pr-entry-qty-pill:hover {
  background: #1e40af; border-color: #1e40af; color: white;
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(30, 64, 175, 0.25);
}

/* === 单价 / 产值 网格 === */
.pr-entry-form-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
}
.pr-entry-price-wrap {
  position: relative;
  display: flex; align-items: center;
}
.pr-entry-price-prefix {
  position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
  font-size: 14px; font-weight: 700; color: #64748b; pointer-events: none;
}
.pr-entry-price-input { padding-left: 28px !important; }
.pr-entry-value-display {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; min-height: 44px;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  border: 1px solid #bfdbfe; border-radius: 10px;
  font-size: 18px; font-weight: 800; color: #1e40af;
  font-variant-numeric: tabular-nums;
}
.pr-entry-value-display i { font-size: 14px; opacity: 0.7; }

/* === 右侧栏 === */
.pr-entry-sidebar {
  padding: 22px 20px;
  background: #f8fafc;
  display: flex; flex-direction: column; gap: 14px;
  overflow-y: auto;
}
.pr-entry-side-card {
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  overflow: hidden;
  display: flex; flex-direction: column;
}
.pr-entry-side-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px;
  background: #f8fafc; border-bottom: 1px solid #f1f5f9;
  font-size: 12px; font-weight: 700; color: #475569;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.pr-entry-side-head span {
  display: inline-flex; align-items: center; gap: 6px;
}
.pr-entry-side-head i { color: #1e40af; font-size: 11px; }
.pr-entry-side-clear {
  border: none; background: transparent; color: #94a3b8;
  font-size: 11px; font-weight: 600; cursor: pointer; padding: 2px 4px;
  font-family: inherit; text-transform: none; letter-spacing: 0;
  transition: color 0.15s ease;
}
.pr-entry-side-clear:hover { color: #dc2626; }

.pr-entry-recent-list { display: flex; flex-direction: column; padding: 6px; }
.pr-entry-recent-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 9px 10px; border: none;
  background: transparent; text-align: left; cursor: pointer;
  border-radius: 8px;
  font-family: inherit; color: inherit;
  transition: all 0.15s ease;
}
.pr-entry-recent-item:hover {
  background: #eff6ff;
  transform: translateX(2px);
}
.pr-entry-recent-bullet {
  width: 6px; height: 6px; border-radius: 50%;
  background: #cbd5e1; flex-shrink: 0;
  transition: background 0.15s ease, transform 0.15s ease;
}
.pr-entry-recent-item:hover .pr-entry-recent-bullet {
  background: #3b82f6; transform: scale(1.4);
}
.pr-entry-recent-content {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column; gap: 1px;
}
.pr-entry-recent-name {
  font-size: 13px; font-weight: 600; color: #1e293b;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pr-entry-recent-barcode {
  font-size: 11px; color: #64748b;
  font-family: 'SF Mono', 'Consolas', monospace;
}
.pr-entry-recent-arrow {
  font-size: 10px; color: #cbd5e1;
  transition: all 0.15s ease;
}
.pr-entry-recent-item:hover .pr-entry-recent-arrow {
  color: #1e40af; transform: translateX(2px);
}

.pr-entry-empty-small {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px; padding: 24px 12px;
  color: #94a3b8; text-align: center;
}
.pr-entry-empty-small i { font-size: 22px; opacity: 0.5; }
.pr-entry-empty-small span { font-size: 12px; font-weight: 600; }
.pr-entry-empty-small small { font-size: 11px; color: #cbd5e1; }

.pr-entry-shortcuts {
  padding: 10px 14px 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.pr-entry-shortcut {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: #475569;
}
.pr-entry-shortcut span { margin-left: auto; font-weight: 500; }
.pr-entry-shortcut kbd {
  display: inline-block; min-width: 22px; padding: 2px 6px;
  background: #f1f5f9; border: 1px solid #e2e8f0; border-bottom-width: 2px;
  border-radius: 5px;
  font-size: 10px; font-weight: 700; color: #475569;
  font-family: 'SF Mono', 'Consolas', monospace;
  text-align: center;
}

/* === Footer === */
.pr-entry-footer {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 14px 24px;
  background: #f8fafc; border-top: 1px solid #f1f5f9;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.pr-entry-continue {
  display: inline-flex; align-items: center; gap: 8px;
  cursor: pointer; font-size: 13px; font-weight: 600; color: #475569;
  user-select: none;
  padding: 4px 0;
}
.pr-entry-continue input { position: absolute; opacity: 0; pointer-events: none; }
.pr-entry-continue-box {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 5px;
  background: white; border: 2px solid #cbd5e1;
  color: transparent; font-size: 10px;
  transition: all 0.15s ease;
}
.pr-entry-continue.active .pr-entry-continue-box {
  background: #1e40af; border-color: #1e40af; color: white;
}
.pr-entry-continue:hover .pr-entry-continue-box { border-color: #1e40af; }
.pr-entry-continue.active { color: #1e40af; }

.pr-entry-footer-btns { display: flex; gap: 10px; }
.pr-entry-btn-cancel {
  padding: 0 18px; height: 44px; border: 1px solid #e2e8f0; border-radius: 10px;
  background: white; font-size: 14px; font-weight: 600; color: #475569;
  cursor: pointer; font-family: inherit;
  transition: all 0.2s ease;
}
.pr-entry-btn-cancel:hover { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-entry-btn-submit {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 0 22px; height: 44px; border: none; border-radius: 10px;
  background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%);
  color: white; font-size: 14px; font-weight: 700;
  cursor: pointer; font-family: inherit;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(30, 64, 175, 0.25);
}
.pr-entry-btn-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(30, 64, 175, 0.4);
}
.pr-entry-btn-submit:disabled { opacity: 0.6; cursor: not-allowed; }
.pr-entry-btn-hint {
  display: inline-block; padding: 1px 5px;
  background: rgba(255, 255, 255, 0.2); border-radius: 4px;
  font-size: 10px; font-weight: 600;
  font-family: 'SF Mono', 'Consolas', monospace;
  letter-spacing: 0;
}

/* === 弹窗动画 === */
.pr-entry-enter-active, .pr-entry-leave-active { transition: opacity 0.25s ease; }
.pr-entry-enter-active .pr-entry-modal, .pr-entry-leave-active .pr-entry-modal {
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease;
}
.pr-entry-enter-from, .pr-entry-leave-to { opacity: 0; }
.pr-entry-enter-from .pr-entry-modal, .pr-entry-leave-to .pr-entry-modal {
  transform: scale(0.96) translateY(8px);
  opacity: 0;
}

/* === 响应式 === */
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
  .pr-entry-modal {
    width: 100%; height: 100%; max-height: 100%;
    border-radius: 0;
  }
  .pr-entry-header { padding: 14px 16px; }
  .pr-entry-form { padding: 16px; gap: 14px; }
  .pr-entry-sidebar { padding: 14px; }
  .pr-entry-footer { padding: 12px 16px; }
  .pr-entry-footer { flex-direction: column; align-items: stretch; }
  .pr-entry-footer-btns { width: 100%; }
  .pr-entry-btn-cancel, .pr-entry-btn-submit { flex: 1; }
}

/* ===== 导出提示 ===== */
.pr-export-toast {
  position: fixed; top: 20px; right: 20px; z-index: 120;
  padding: 10px 18px; border-radius: 10px;
  font-size: 13px; font-weight: 600;
  display: flex; align-items: center; gap: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}
.pr-export-toast.info { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
.pr-export-toast.success { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
.pr-export-toast.error { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }

/* Toast动画 */
.pr-toast-enter-active, .pr-toast-leave-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.pr-toast-enter-from, .pr-toast-leave-to { opacity: 0; transform: translateX(20px); }

/* ===== 响应式设计 ===== */

/* 平板竖屏 / 小桌面 */
@media (max-width: 1200px) {
  .pr-dept-row { grid-template-columns: repeat(3, 1fr); }
  .pr-content-row { grid-template-columns: 1fr; }
  .pr-chart-body { height: 240px; }
}

/* 平板横屏 */
@media (max-width: 1024px) {
  .pr-container { padding: 0; }
  .pr-toolbar { padding: 12px 16px 8px; }
  .pr-kpi-section { padding: 12px 16px 0; }
  .pr-dept-section { padding: 10px 16px 0; }
  .pr-content-section { padding: 10px 16px 12px; }
  .pr-kpi-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .pr-kpi-card { padding: 14px 16px; }
  .pr-kpi-value { font-size: 20px; }
  .pr-dept-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .pr-dept-qty-num { font-size: 22px; }
}

/* 移动端 / 小平板 */
@media (max-width: 768px) {
  .pr-container { padding: 0; }
  .page-card-main { border-radius: 12px; }
  .pr-toolbar { padding: 10px 12px 8px; }
  .pr-toolbar-row { gap: 8px; }
  .pr-toolbar-row-right {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .pr-toolbar-controls {
    flex-wrap: wrap;
    overflow-x: auto;
  }
  .pr-divider { display: none; }

  .pr-kpi-section { padding: 8px 12px 0; }
  .pr-kpi-row { grid-template-columns: 1fr; gap: 8px; }
  .pr-kpi-card { padding: 12px 14px; }
  .pr-kpi-value { font-size: 20px; }
  .pr-kpi-icon-wrap { width: 40px; height: 40px; font-size: 16px; }

  .pr-dept-section { padding: 8px 12px 0; }
  .pr-dept-row { grid-template-columns: 1fr; gap: 8px; }

  .pr-content-section { padding: 8px 12px 12px; }
  .pr-content-row { grid-template-columns: 1fr; gap: 12px; min-height: auto; }
  .pr-chart-body { height: 220px; }

  .pr-panel-header { flex-wrap: wrap; gap: 6px; }
  .pr-table-filter { flex-wrap: wrap; }
}

/* 大屏优化 */
@media (min-width: 1440px) {
  .pr-kpi-value { font-size: 28px; }
  .pr-chart-body { height: 320px; }
}
</style>
