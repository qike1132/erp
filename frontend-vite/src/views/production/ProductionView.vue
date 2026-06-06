<template>
  <div class="pr-container">
    <div class="pr-card-main">

      <!-- ====== 顶部工具栏 ====== -->
      <header class="pr-toolbar">
        <div class="pr-toolbar-tabs-wrap">
          <HeaderTabs />
        </div>
        <div class="pr-toolbar-row">
          <div class="pr-toolbar-left">
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
          </div>
          <div class="pr-toolbar-center">
            <div class="pr-tab-group" role="tablist">
              <button role="tab" :aria-selected="viewTab === 'daily'" :class="['pr-tab', { 'pr-tab-active': viewTab === 'daily' }]" @click="viewTab = 'daily'">日报</button>
              <button role="tab" :aria-selected="viewTab === 'monthly'" :class="['pr-tab', { 'pr-tab-active': viewTab === 'monthly' }]" @click="viewTab = 'monthly'">月报</button>
            </div>
          </div>
          <div class="pr-toolbar-right">
            <button class="pr-action-btn pr-action-primary" @click="openEntryDrawer">
              <i class="fas fa-plus" aria-hidden="true" /> 录入
            </button>
            <button class="pr-action-btn" @click="handleExport">
              <i class="fas fa-download" aria-hidden="true" /> 导出
            </button>
          </div>
        </div>
      </header>

      <!-- ============ 日报 TAB ============ -->
      <div v-show="viewTab === 'daily'" class="pr-main">

        <section class="pr-kpi-section">
          <div v-if="reportSummary" class="pr-kpi-row">
            <div class="pr-kpi-card pr-kpi-blue">
              <div class="pr-kpi-icon-wrap"><i class="fas fa-cubes" aria-hidden="true" /></div>
              <div class="pr-kpi-body">
                <span class="pr-kpi-label">总产量</span>
                <span class="pr-kpi-value">{{ reportSummary.overall_quantity }}<small class="pr-kpi-unit">件</small></span>
              </div>
            </div>
            <div class="pr-kpi-card pr-kpi-green">
              <div class="pr-kpi-icon-wrap"><i class="fas fa-yen-sign" aria-hidden="true" /></div>
              <div class="pr-kpi-body">
                <span class="pr-kpi-label">总产值</span>
                <span class="pr-kpi-value">{{ formatCurrency(reportSummary.overall_value) }}</span>
              </div>
            </div>
            <div class="pr-kpi-card pr-kpi-amber">
              <div class="pr-kpi-icon-wrap"><i class="fas fa-barcode" aria-hidden="true" /></div>
              <div class="pr-kpi-body">
                <span class="pr-kpi-label">SKU 数</span>
                <span class="pr-kpi-value">{{ reportSummary.overall_sku_count }}<small class="pr-kpi-unit">种</small></span>
              </div>
            </div>
          </div>
        </section>

        <section class="pr-dept-section">
          <div class="pr-section-label">部门概览</div>
          <div v-if="reportSummary?.departments?.length" class="pr-dept-row">
            <div v-for="d in reportSummary.departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
              <div class="pr-dept-accent" />
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
            <div class="pr-kpi-card pr-kpi-blue">
              <div class="pr-kpi-icon-wrap"><i class="fas fa-cubes" aria-hidden="true" /></div>
              <div class="pr-kpi-body">
                <span class="pr-kpi-label">月总产量</span>
                <span class="pr-kpi-value">{{ monthlySummary.overall_quantity ?? 0 }}<small class="pr-kpi-unit">件</small></span>
              </div>
            </div>
            <div class="pr-kpi-card pr-kpi-green">
              <div class="pr-kpi-icon-wrap"><i class="fas fa-yen-sign" aria-hidden="true" /></div>
              <div class="pr-kpi-body">
                <span class="pr-kpi-label">月总产值</span>
                <span class="pr-kpi-value">{{ formatCurrency(monthlySummary.overall_value ?? 0) }}</span>
              </div>
            </div>
            <div class="pr-kpi-card pr-kpi-amber">
              <div class="pr-kpi-icon-wrap"><i class="fas fa-calendar-check" aria-hidden="true" /></div>
              <div class="pr-kpi-body">
                <span class="pr-kpi-label">生产天数</span>
                <span class="pr-kpi-value">{{ monthlySummary.daily_data?.filter((d: any) => d.total.quantity > 0).length || 0 }}<small class="pr-kpi-unit">天</small></span>
              </div>
            </div>
          </div>
        </section>

        <section class="pr-dept-section">
          <div class="pr-section-label">部门概览</div>
          <div v-if="monthlySummary?.monthly_departments?.length" class="pr-dept-row">
            <div v-for="d in monthlySummary.monthly_departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
              <div class="pr-dept-accent" />
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

      <!-- ============ 录入抽屉 ============ -->
      <Transition name="pr-drawer">
        <div v-if="showEntryDrawer" class="pr-drawer-overlay" @click.self="closeEntryDrawer">
          <div class="pr-drawer">
            <div class="pr-drawer-header">
              <h3><i class="fas fa-pen-alt" aria-hidden="true" /> 生产数据录入</h3>
              <button class="pr-drawer-close" @click="closeEntryDrawer" aria-label="关闭"><i class="fas fa-times" aria-hidden="true" /></button>
            </div>
            <div class="pr-drawer-body">
              <div class="pr-form-group">
                <label class="pr-form-label">生产日期</label>
                <input v-model="selectedDate" type="date" class="pr-form-input" />
              </div>
              <div class="pr-form-group">
                <label class="pr-form-label">生产部门 <span class="pr-required">*</span></label>
                <div class="pr-dept-select">
                  <button
                    v-for="dept in departments"
                    :key="dept.value"
                    :class="[
                      'pr-dept-btn',
                      `pr-dept-btn-${dept.value}`,
                      { 'pr-dept-btn-active': formDept === dept.value }
                    ]"
                    @click="formDept = dept.value"
                  >
                    <i :class="dept.icon" aria-hidden="true" /> {{ dept.label }}
                  </button>
                </div>
              </div>
              <div class="pr-form-group">
                <label class="pr-form-label">产品 <span class="pr-required">*</span></label>
                <div class="pr-form-search">
                  <input
                    ref="productSearchRef"
                    v-model="searchQuery"
                    class="pr-form-input pr-form-search-input"
                    placeholder="搜索产品名称/69码（支持键盘上下选择）"
                    @input="onSearchInput"
                    @focus="onSearchFocus"
                    @blur="onSearchBlur"
                    @keydown.down.prevent="moveSearchIndex(1)"
                    @keydown.up.prevent="moveSearchIndex(-1)"
                    @keydown.enter.prevent="confirmSearchSelection"
                    @keydown.esc="showDropdown = false"
                  />
                  <i class="fas fa-search pr-form-search-icon" aria-hidden="true" />
                  <div v-if="showDropdown" class="pr-form-dropdown">
                    <div v-if="searchLoading" class="pr-form-dropdown-loading">
                      <i class="fas fa-spinner fa-spin" aria-hidden="true" /> 搜索中...
                    </div>
                    <div v-else-if="searchError" class="pr-form-dropdown-error">
                      <i class="fas fa-exclamation-circle" aria-hidden="true" /> {{ searchError }}
                    </div>
                    <div v-else-if="!searchResults.length" class="pr-form-dropdown-empty">
                      无匹配产品
                    </div>
                    <div
                      v-for="(p, idx) in searchResults"
                      :key="p.id"
                      :class="['pr-form-dropdown-item', { 'pr-form-dropdown-item-active': idx === searchActiveIndex }]"
                      @mousedown.prevent="selectProduct(p)"
                    >
                      <div class="pr-form-dropdown-name">{{ p.name }}</div>
                      <div class="pr-form-dropdown-barcode">{{ p.barcode || '无69码' }}</div>
                    </div>
                  </div>
                </div>
                <div v-if="form.product_name" class="pr-form-selected">
                  <i class="fas fa-check-circle" aria-hidden="true" />
                  <span>{{ form.product_name }}</span>
                  <span v-if="form.barcode" class="pr-form-selected-barcode">{{ form.barcode }}</span>
                  <button class="pr-form-selected-clear" @click="clearProduct" aria-label="关闭"><i class="fas fa-times" aria-hidden="true" /></button>
                </div>
                <div v-if="formErrors.product_name" class="pr-form-error">{{ formErrors.product_name }}</div>
              </div>
              <div class="pr-form-row">
                <div class="pr-form-group">
                  <label class="pr-form-label">数量 <span class="pr-required">*</span></label>
                  <input
                    v-model.number="form.quantity"
                    type="number"
                    min="1"
                    class="pr-form-input"
                    placeholder="0"
                    @blur="validateField('quantity')"
                  />
                  <div v-if="formErrors.quantity" class="pr-form-error">{{ formErrors.quantity }}</div>
                </div>
                <div class="pr-form-group">
                  <label class="pr-form-label">单价</label>
                  <input
                    v-model.number="form.unit_price"
                    type="number"
                    min="0"
                    step="0.01"
                    class="pr-form-input"
                    placeholder="0.00"
                  />
                </div>
              </div>
              <div class="pr-form-group">
                <label class="pr-form-label">产值</label>
                <div class="pr-form-value">{{ formatCurrency(computedValue) }}</div>
              </div>
              <div class="pr-form-group">
                <label class="pr-form-label">备注</label>
                <textarea v-model="form.remark" class="pr-form-input pr-form-textarea" placeholder="选填" rows="2" />
              </div>
            </div>
            <div class="pr-drawer-footer">
              <button class="pr-drawer-cancel" @click="closeEntryDrawer">取消 (Esc)</button>
              <button class="pr-drawer-submit" :disabled="isSubmitting" @click="handleSubmit">
                <i v-if="isSubmitting" class="fas fa-spinner fa-spin" /> 确认录入
              </button>
            </div>
          </div>
        </div>
      </Transition>

      <!-- ============ 二次确认弹窗 ============ -->
      <Transition name="pr-modal">
        <div v-if="showConfirmModal" class="pr-modal-overlay" @click.self="showConfirmModal = false">
          <div class="pr-modal">
            <div class="pr-modal-header">
              <i class="fas fa-question-circle" aria-hidden="true" />
              <h4>确认录入</h4>
            </div>
            <div class="pr-modal-body">
              <p>请确认以下生产数据：</p>
              <div class="pr-confirm-data">
                <div class="pr-confirm-row"><span>部门：</span><strong>{{ deptLabel(formDept) }}</strong></div>
                <div class="pr-confirm-row"><span>产品：</span><strong>{{ form.product_name }}</strong></div>
                <div class="pr-confirm-row"><span>数量：</span><strong>{{ form.quantity }} 件</strong></div>
                <div class="pr-confirm-row"><span>产值：</span><strong>{{ formatCurrency(computedValue) }}</strong></div>
                <div class="pr-confirm-row"><span>日期：</span><strong>{{ selectedDate }}</strong></div>
              </div>
            </div>
            <div class="pr-modal-footer">
              <button class="pr-drawer-cancel" @click="showConfirmModal = false">取消</button>
              <button class="pr-drawer-submit" @click="confirmSubmit">确认提交</button>
            </div>
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
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { dailyProductionApi, productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import type { DailyProductionRecord, Product } from '@/types'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
type EChartsCore = typeof import('echarts/core')

let echarts: EChartsCore | null = null
let echartsLoaded = false
const confirmDialog = useConfirmDialog()

async function loadEcharts(): Promise<EChartsCore> {
  if (echartsLoaded && echarts) return echarts
  const [
    ec,
    { BarChart, LineChart },
    { GridComponent, TooltipComponent, TitleComponent, LegendComponent, DatasetComponent },
    { CanvasRenderer },
  ] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  ec.use([
    BarChart,
    LineChart,
    GridComponent,
    TooltipComponent,
    TitleComponent,
    LegendComponent,
    DatasetComponent,
    CanvasRenderer,
  ])
  echarts = ec
  echartsLoaded = true
  return ec
}
import { formatCurrency, formatNumber } from '@/utils/format'
const formatMoney = formatNumber

const queryClient = useQueryClient()

const departments = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]

const deptColors: Record<string, { main: string; light: string; gradient: string[] }> = {
  filling: { main: '#3b82f6', light: '#eff6ff', gradient: ['#3b82f6', '#1d4ed8'] },
  handcraft: { main: '#22c55e', light: '#f0fdf4', gradient: ['#22c55e', '#15803d'] },
  packaging: { main: '#f59e0b', light: '#fffbeb', gradient: ['#f59e0b', '#d97706'] },
}

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
const showConfirmModal = ref(false)

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
    } catch (e: any) {
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
  setTimeout(() => { showDropdown.value = false; searchActiveIndex.value = -1 }, 150)
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
async function selectProduct(p: Product) {
  form.product_id = p.id
  form.product_name = p.name
  form.barcode = p.barcode || ''
  searchQuery.value = p.name
  searchResults.value = []
  showDropdown.value = false
  searchActiveIndex.value = -1
  try {
    const infoRes = await dailyProductionApi.productInfo(p.id) as any
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
  showConfirmModal.value = true
}

async function confirmSubmit() {
  showConfirmModal.value = false
  isSubmitting.value = true
  try {
    await dailyProductionApi.createRecord({
      department: formDept.value, product_id: form.product_id, product_name: form.product_name,
      barcode: form.barcode, unit_price: form.unit_price || 0, quantity: form.quantity,
      production_value: Number(computedValue.value), production_date: selectedDate.value, remark: form.remark,
    } as any)
    showToast('录入成功', 'success')
    resetForm(); showEntryDrawer.value = false
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
  } catch (e: any) {
    showToast(e?.response?.data?.detail ?? '录入失败', 'error')
  }
  finally { isSubmitting.value = false }
}

function resetForm() {
  form.product_id = null; form.product_name = ''; form.barcode = ''
  form.unit_price = 0; form.quantity = 0; form.remark = ''; searchQuery.value = ''
  formDept.value = 'filling'
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
      setTimeout(() => { exportStatus.show = false }, 3000)
      return
    } catch (e: any) {
      retries++
      if (retries <= maxRetries) {
        exportStatus.message = `导出失败，正在重试 (${retries}/${maxRetries})...`
        await new Promise(r => setTimeout(r, 1000 * retries))
      } else {
        exportStatus.type = 'error'
        exportStatus.icon = 'fas fa-times-circle'
        exportStatus.message = '导出失败，请稍后重试'
        setTimeout(() => { exportStatus.show = false }, 5000)
      }
    }
  }
}

function formatTime(t?: string | null) { return t ? t.slice(11, 16) : '' }

// ===== 键盘快捷键 =====
function handleKeydown(e: KeyboardEvent) {
  if (e.ctrlKey && (e.key === 'n' || e.key === 'N')) {
    e.preventDefault()
    if (!showEntryDrawer.value) openEntryDrawer()
  }
  if (e.ctrlKey && e.key === 'Enter' && showEntryDrawer.value && !showConfirmModal.value) {
    e.preventDefault()
    handleSubmit()
  }
  if (e.key === 'Escape' && showEntryDrawer.value && !showConfirmModal.value) {
    closeEntryDrawer()
  }
  if (e.key === 'Escape' && showConfirmModal.value) {
    showConfirmModal.value = false
  }
  if (e.ctrlKey && ['1', '2'].includes(e.key)) {
    e.preventDefault()
    const tabs = ['daily', 'monthly']
    viewTab.value = tabs[parseInt(e.key) - 1]
  }
}

// ===== ECharts =====
const dailyChartRef = ref<HTMLElement>()
const monthlyChartRef = ref<HTMLElement>()
let dailyChart: any = null
let monthlyChart: any = null

function getChart(el: HTMLElement, existing: any) {
  if (!echarts) return null
  return (existing && !existing.isDisposed()) ? existing : echarts!.init(el)
}

function renderDailyChart() {
  if (!echarts || !dailyChartRef.value || !reportSummary.value?.departments?.length) return
  dailyChart = getChart(dailyChartRef.value, dailyChart)
  if (!dailyChart) return
  const depts = reportSummary.value.departments
  dailyChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: 'rgba(255,255,255,0.96)', borderColor: '#e2e8f0', textStyle: { color: '#1e293b', fontSize: 13 } },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: depts.map((d: any) => d.department_label), axisLabel: { fontSize: 13, fontWeight: 600, color: '#475569' }, axisLine: { lineStyle: { color: '#e2e8f0' } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', name: '产量', axisLabel: { fontSize: 11, color: '#94a3b8' }, splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } } },
      { type: 'value', name: '产值', axisLabel: { fontSize: 11, color: '#94a3b8' }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '产量', type: 'bar', barWidth: '30%',
        data: depts.map((d: any) => ({
          value: d.total_quantity,
          itemStyle: {
            color: new echarts!.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: deptColors[d.department]?.gradient[0] ?? '#3b82f6' },
              { offset: 1, color: deptColors[d.department]?.gradient[1] ?? '#1d4ed8' },
            ]),
            borderRadius: [6, 6, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 12, fontWeight: 600, color: '#1e293b' },
      },
      {
        name: '产值', type: 'bar', barWidth: '30%', yAxisIndex: 1,
        data: depts.map((d: any) => ({
          value: d.total_value,
          itemStyle: {
            color: new echarts!.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#fbbf24' },
              { offset: 1, color: '#f59e0b' },
            ]),
            borderRadius: [6, 6, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 11, color: '#1e293b', formatter: (p: any) => `¥${p.value}` },
      },
    ],
  }, true)
}

function renderMonthlyChart() {
  if (!echarts || !monthlyChartRef.value || !monthlySummary.value?.daily_data?.length) return
  monthlyChart = getChart(monthlyChartRef.value, monthlyChart)
  if (!monthlyChart) return
  const days = monthlySummary.value.daily_data.filter((d: any) => d.total.quantity > 0)
  monthlyChart.setOption({
    tooltip: { trigger: 'axis', backgroundColor: 'rgba(255,255,255,0.96)', borderColor: '#e2e8f0', textStyle: { color: '#1e293b', fontSize: 13 } },
    legend: { data: ['充棉', '手工', '包装', '合计'], bottom: 0, itemWidth: 12, itemHeight: 12, textStyle: { fontSize: 12, color: '#475569' } },
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: days.map((d: any) => d.day + '日'), axisLabel: { fontSize: 11, color: '#94a3b8' }, axisLine: { lineStyle: { color: '#e2e8f0' } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '产量', axisLabel: { fontSize: 11, color: '#94a3b8' }, splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } } },
    series: [
      {
        name: '充棉', type: 'bar', stack: 'dept',
        data: days.map((d: any) => d.filling?.quantity ?? 0),
        itemStyle: { color: deptColors.filling.main, borderRadius: [0, 0, 0, 0] },
      },
      {
        name: '手工', type: 'bar', stack: 'dept',
        data: days.map((d: any) => d.handcraft?.quantity ?? 0),
        itemStyle: { color: deptColors.handcraft.main },
      },
      {
        name: '包装', type: 'bar', stack: 'dept',
        data: days.map((d: any) => d.packaging?.quantity ?? 0),
        itemStyle: { color: deptColors.packaging.main, borderRadius: [4, 4, 0, 0] },
      },
      {
        name: '合计', type: 'line',
        data: days.map((d: any) => d.total.quantity),
        lineStyle: { width: 2, color: '#64748b' },
        itemStyle: { color: '#64748b' },
        symbol: 'circle', symbolSize: 6,
      },
    ],
  }, true)
}

function handleResize() {
  if (viewTab.value === 'daily') dailyChart?.resize()
  else if (viewTab.value === 'monthly') monthlyChart?.resize()
}

// 图表渲染 watcher
watch([reportSummary], () => { if (viewTab.value === 'daily') nextTick(() => requestAnimationFrame(renderDailyChart)) })
watch([monthlySummary], () => { if (viewTab.value === 'monthly') nextTick(() => requestAnimationFrame(renderMonthlyChart)) })
watch(viewTab, (tab) => {
  nextTick(() => requestAnimationFrame(() => {
    if (tab === 'daily') { renderDailyChart(); dailyChart?.resize() }
    else if (tab === 'monthly') { renderMonthlyChart(); monthlyChart?.resize() }
  }))
})

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleKeydown)
  await loadEcharts()
  nextTick(() => requestAnimationFrame(renderDailyChart))
})
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleKeydown)
  dailyChart?.dispose(); monthlyChart?.dispose()
  if (searchTimer) clearTimeout(searchTimer)
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
  padding: 12px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  background: #f1f5f9;
}

.pr-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: white;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 14px rgba(0, 0, 0, 0.06);
}

/* === 顶部工具栏 === */
.pr-toolbar {
  padding: 14px 24px 10px;
  background: white;
  border-bottom: 1px solid #f1f5f9;
  flex-shrink: 0;
}
.pr-toolbar-tabs-wrap { display: flex; width: 100%; }
.pr-toolbar-tabs-wrap :deep(.ht-bar) { width: 100%; margin: 0; }
.pr-toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  width: 100%;
}
.pr-toolbar-left { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.pr-toolbar-center { display: flex; align-items: center; }
.pr-toolbar-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

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
.pr-kpi-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
}
.pr-kpi-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}
.pr-kpi-blue::before { background: linear-gradient(90deg, #3b82f6, #1d4ed8); }
.pr-kpi-blue:hover { border-color: #bfdbfe; }
.pr-kpi-green::before { background: linear-gradient(90deg, #22c55e, #15803d); }
.pr-kpi-green:hover { border-color: #bbf7d0; }
.pr-kpi-amber::before { background: linear-gradient(90deg, #f59e0b, #d97706); }
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
.pr-dept-accent { width: 4px; flex-shrink: 0; border-radius: 12px 0 0 12px; }
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
.pr-dept-filling .pr-dept-accent { background: #3b82f6; }
.pr-dept-filling .pr-dept-qty-num { color: #1e3a8a; }
.pr-dept-filling .pr-dept-icon-sm { background: #eff6ff; color: #1e40af; }
.pr-dept-filling:hover { border-color: #bfdbfe; }

.pr-dept-handcraft .pr-dept-accent { background: #22c55e; }
.pr-dept-handcraft .pr-dept-qty-num { color: #14532d; }
.pr-dept-handcraft .pr-dept-icon-sm { background: #f0fdf4; color: #15803d; }
.pr-dept-handcraft:hover { border-color: #bbf7d0; }

.pr-dept-packaging .pr-dept-accent { background: #f59e0b; }
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

/* ===== 录入抽屉 ===== */
.pr-drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(4px);
  z-index: 100; display: flex; justify-content: flex-end;
}
.pr-drawer {
  width: 440px; max-width: 100%; background: white;
  display: flex; flex-direction: column;
  box-shadow: -8px 0 30px rgba(0, 0, 0, 0.15);
}
.pr-drawer-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px; border-bottom: 1px solid #f1f5f9;
}
.pr-drawer-header h3 {
  font-size: 15px; font-weight: 700; color: #1e293b; margin: 0;
  display: flex; align-items: center; gap: 8px;
}
.pr-drawer-header h3 i { color: #3b82f6; }
.pr-drawer-close {
  border: none; background: transparent; color: #94a3b8;
  font-size: 16px; cursor: pointer; padding: 4px;
  transition: color 0.2s ease;
}
.pr-drawer-close:hover { color: #1e293b; }
.pr-drawer-body {
  flex: 1; overflow-y: auto; padding: 20px 24px;
  display: flex; flex-direction: column; gap: 16px;
}
.pr-drawer-footer {
  display: flex; gap: 10px; padding: 14px 24px;
  border-top: 1px solid #f1f5f9;
}
.pr-drawer-cancel {
  flex: 1; padding: 10px; border: 1px solid #e2e8f0; border-radius: 10px;
  background: white; font-size: 14px; font-weight: 600; color: #475569;
  cursor: pointer; transition: all 0.2s ease;
}
.pr-drawer-cancel:hover { border-color: #3b82f6; color: #1e40af; }
.pr-drawer-submit {
  flex: 1; padding: 10px; border: none; border-radius: 10px;
  background: linear-gradient(135deg, #3b82f6, #1e40af);
  color: white; font-size: 14px; font-weight: 700;
  cursor: pointer; transition: all 0.2s ease;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.pr-drawer-submit:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4); }
.pr-drawer-submit:disabled { opacity: 0.5; cursor: not-allowed; }

/* 抽屉动画 */
.pr-drawer-enter-active, .pr-drawer-leave-active { transition: opacity 0.3s ease; }
.pr-drawer-enter-active .pr-drawer, .pr-drawer-leave-active .pr-drawer { transition: transform 0.3s ease; }
.pr-drawer-enter-from, .pr-drawer-leave-to { opacity: 0; }
.pr-drawer-enter-from .pr-drawer, .pr-drawer-leave-to .pr-drawer { transform: translateX(100%); }

/* 表单 */
.pr-form-group { display: flex; flex-direction: column; gap: 5px; }
.pr-form-label {
  font-size: 12px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; color: #64748b;
}
.pr-required { color: #dc2626; }
.pr-form-input {
  width: 100%; padding: 10px 14px; font-size: 14px; line-height: 1.5;
  color: #1e293b; background: white;
  border: 1px solid #e2e8f0; border-radius: 10px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  outline: none; min-height: 44px; box-sizing: border-box; font-family: inherit;
}
.pr-form-input:focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; }
.pr-form-input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1); }
.pr-form-input:hover:not(:disabled) { border-color: #94a3b8; }
.pr-form-input::placeholder { color: #94a3b8; font-size: 14px; font-weight: 400; }
.pr-form-textarea { min-height: 56px; resize: vertical; }
.pr-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.pr-form-value {
  padding: 10px 14px; background: #eff6ff; border-radius: 10px;
  border: 1px solid #bfdbfe;
  font-size: 18px; font-weight: 800; color: #1e40af;
  min-height: 44px; display: flex; align-items: center;
  font-variant-numeric: tabular-nums;
}
.pr-form-error { font-size: 12px; color: #dc2626; margin-top: 1px; }

/* 部门选择按钮 */
.pr-dept-select { display: flex; gap: 8px; }
.pr-dept-btn {
  flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
  padding: 9px 14px; border: 1px solid #e2e8f0; border-radius: 8px;
  background: white; font-size: 13px; font-weight: 600; color: #475569;
  cursor: pointer; transition: all 0.2s ease;
}
.pr-dept-btn:hover { border-color: #3b82f6; color: #1e40af; }
.pr-dept-btn-active { border-color: #3b82f6; background: #eff6ff; color: #1e40af; }
.pr-dept-btn-filling.pr-dept-btn-active { border-color: #3b82f6; color: #1e40af; background: #eff6ff; }
.pr-dept-btn-handcraft.pr-dept-btn-active { border-color: #22c55e; color: #15803d; background: #f0fdf4; }
.pr-dept-btn-packaging.pr-dept-btn-active { border-color: #f59e0b; color: #d97706; background: #fffbeb; }

/* 搜索 */
.pr-form-search { position: relative; }
.pr-form-search-input { padding-left: 38px !important; padding-right: 40px !important; }
.pr-form-search-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  color: #94a3b8; font-size: 14px; pointer-events: none;
}
.pr-form-dropdown {
  position: absolute; top: 100%; left: 0; right: 0; margin-top: 4px;
  background: white; border: 1px solid #e2e8f0; border-radius: 10px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  max-height: 200px; overflow-y: auto; z-index: 20;
}
.pr-form-dropdown-item {
  padding: 9px 12px; cursor: pointer; transition: background 0.15s ease;
  border-bottom: 1px solid #f1f5f9;
}
.pr-form-dropdown-item:last-child { border-bottom: none; }
.pr-form-dropdown-item:hover, .pr-form-dropdown-item-active { background: #eff6ff; }
.pr-form-dropdown-name { font-size: 13px; font-weight: 600; color: #1e293b; }
.pr-form-dropdown-barcode { font-size: 11px; color: #64748b; margin-top: 1px; }
.pr-form-dropdown-loading, .pr-form-dropdown-empty, .pr-form-dropdown-error {
  padding: 12px; font-size: 13px; color: #64748b; text-align: center;
}
.pr-form-dropdown-error { color: #dc2626; }
.pr-form-selected {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px; background: #eff6ff; border: 1px solid #bfdbfe;
  border-radius: 8px; font-size: 13px; font-weight: 600; color: #1e40af;
  margin-top: 4px;
}
.pr-form-selected i { color: #3b82f6; }
.pr-form-selected-barcode { font-size: 11px; color: #64748b; font-weight: 500; }
.pr-form-selected-clear {
  border: none; background: transparent; color: #94a3b8;
  cursor: pointer; font-size: 12px; margin-left: auto; padding: 2px;
  transition: color 0.15s ease;
}
.pr-form-selected-clear:hover { color: #1e293b; }

/* ===== 二次确认弹窗 ===== */
.pr-modal-overlay {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.5); backdrop-filter: blur(4px);
  z-index: 110; display: flex; align-items: center; justify-content: center;
}
.pr-modal {
  background: white; border-radius: 16px; width: 380px; max-width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2); overflow: hidden;
}
.pr-modal-header {
  display: flex; align-items: center; gap: 10px;
  padding: 18px 24px 10px;
}
.pr-modal-header i { font-size: 22px; color: #3b82f6; }
.pr-modal-header h4 { margin: 0; font-size: 15px; font-weight: 700; color: #1e293b; }
.pr-modal-body { padding: 0 24px 14px; }
.pr-modal-body p { margin: 0 0 10px; font-size: 13px; color: #64748b; }
.pr-confirm-data {
  background: #f8fafc; border-radius: 10px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 6px;
  border: 1px solid #f1f5f9;
}
.pr-confirm-row { display: flex; justify-content: space-between; font-size: 13px; }
.pr-confirm-row span { color: #64748b; }
.pr-confirm-row strong { color: #1e293b; }
.pr-modal-footer { display: flex; gap: 10px; padding: 10px 24px 18px; }

/* 弹窗动画 */
.pr-modal-enter-active, .pr-modal-leave-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.pr-modal-enter-from, .pr-modal-leave-to { opacity: 0; transform: scale(0.95); }

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
  .pr-container { padding: 8px; }
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
  .pr-container { padding: 4px; background: #f8fafc; }
  .pr-card-main { border-radius: 12px; }
  .pr-toolbar { padding: 10px 12px 8px; }
  .pr-toolbar-row { flex-direction: column; align-items: stretch; gap: 8px; }
  .pr-toolbar-left { justify-content: center; }
  .pr-toolbar-center { justify-content: center; }
  .pr-toolbar-right { justify-content: center; }

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

  .pr-drawer { width: 100%; }
  .pr-form-row { grid-template-columns: 1fr; }

  .pr-panel-header { flex-wrap: wrap; gap: 6px; }
  .pr-table-filter { flex-wrap: wrap; }
}

/* 大屏优化 */
@media (min-width: 1440px) {
  .pr-container { max-width: 1600px; }
  .pr-kpi-value { font-size: 28px; }
  .pr-chart-body { height: 320px; }
}
</style>
