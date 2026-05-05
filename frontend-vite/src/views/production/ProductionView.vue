<template>
  <div class="pr-container">
    <div class="pr-card pr-card-main">

      <!-- 顶部工具栏：HeaderTabs + 日期 + Tab切换 + 操作按钮 -->
      <div class="pr-toolbar">
        <HeaderTabs />
        <div class="pr-toolbar-row">
          <div class="pr-toolbar-left">
            <!-- 日期导航（看板 & 日报共享） -->
            <div v-if="viewTab !== 'monthly'" class="pr-date-nav">
              <button class="pr-date-btn" @click="dateRef = prevDay(dateRef)"><i class="fas fa-chevron-left" /></button>
              <input v-model="dateRef" type="date" class="pr-date-input" />
              <button class="pr-date-btn" @click="dateRef = nextDay(dateRef)"><i class="fas fa-chevron-right" /></button>
              <button class="pr-today-btn" @click="dateRef = todayLocal()">今天</button>
            </div>
            <!-- 月报日期导航 -->
            <div v-else class="pr-date-nav">
              <button class="pr-date-btn" @click="prevMonth"><i class="fas fa-chevron-left" /></button>
              <span class="pr-month-label">{{ monthlyYear }}年{{ monthlyMonth }}月</span>
              <button class="pr-date-btn" @click="nextMonth"><i class="fas fa-chevron-right" /></button>
            </div>
          </div>
          <div class="pr-toolbar-center">
            <div class="pr-tab-group">
              <button :class="['pr-tab', { 'pr-tab-active': viewTab === 'overview' }]" @click="viewTab = 'overview'">看板</button>
              <button :class="['pr-tab', { 'pr-tab-active': viewTab === 'daily' }]" @click="viewTab = 'daily'">日报</button>
              <button :class="['pr-tab', { 'pr-tab-active': viewTab === 'monthly' }]" @click="viewTab = 'monthly'">月报</button>
            </div>
          </div>
          <div class="pr-toolbar-right">
            <button class="pr-action-btn pr-action-primary" @click="openEntryDrawer">
              <i class="fas fa-plus" /> 录入
            </button>
            <button class="pr-action-btn" @click="handleExport">
              <i class="fas fa-download" /> 导出
            </button>
          </div>
        </div>
      </div>

      <!-- ============ 看板 TAB ============ -->
      <div v-show="viewTab === 'overview'" class="pr-main">

        <!-- KPI 英雄区 -->
        <div class="pr-kpi-row">
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-blue"><i class="fas fa-cubes" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">总产量</span>
              <span class="pr-kpi-value">{{ overviewTotalQty }}<small class="pr-kpi-unit">件</small></span>
            </div>
          </div>
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-green"><i class="fas fa-yen-sign" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">总产值</span>
              <span class="pr-kpi-value">¥{{ formatMoney(overviewTotalValue) }}</span>
            </div>
          </div>
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-amber"><i class="fas fa-barcode" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">SKU 数</span>
              <span class="pr-kpi-value">{{ overviewTotalSku }}<small class="pr-kpi-unit">种</small></span>
            </div>
          </div>
        </div>

        <!-- 部门面板 -->
        <div class="pr-dept-row">
          <div v-for="dept in departments" :key="dept.value" :class="['pr-dept-card', `pr-dept-${dept.value}`]">
            <div class="pr-dept-accent" />
            <div class="pr-dept-content">
              <div class="pr-dept-head">
                <div :class="['pr-dept-icon-sm', `pr-dept-icon-${dept.value}`]"><i :class="dept.icon" /></div>
                <span class="pr-dept-name">{{ dept.label }}</span>
              </div>
              <div class="pr-dept-qty">
                <span class="pr-dept-qty-num">{{ getDeptQty(dept.value) }}</span>
                <span class="pr-dept-qty-unit">件</span>
              </div>
              <div class="pr-dept-stats">
                <div class="pr-dept-stat">
                  <span class="pr-dept-stat-label">产值</span>
                  <span class="pr-dept-stat-val">¥{{ formatMoney(getDeptValue(dept.value)) }}</span>
                </div>
                <div class="pr-dept-stat">
                  <span class="pr-dept-stat-label">SKU</span>
                  <span class="pr-dept-stat-val">{{ getDeptSku(dept.value) }}</span>
                </div>
                <div class="pr-dept-stat">
                  <span class="pr-dept-stat-label">记录</span>
                  <span class="pr-dept-stat-val">{{ getDeptRecordCount(dept.value) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 图表 + 明细表格 并排 -->
        <div class="pr-content-row">
          <div class="pr-chart-section">
            <div class="pr-section-header">
              <span class="pr-section-title"><i class="fas fa-chart-bar" /> 各部门产量与产值</span>
              <div class="pr-chart-filter">
                <span :class="['pr-chip', { active: chartMode === 'qty' }]" @click="chartMode = 'qty'">产量</span>
                <span :class="['pr-chip', { active: chartMode === 'value' }]" @click="chartMode = 'value'">产值</span>
              </div>
            </div>
            <div ref="overviewChartRef" class="pr-chart-body" />
          </div>

          <div class="pr-table-section">
            <div class="pr-section-header">
              <span class="pr-section-title"><i class="fas fa-list-ul" /> 今日明细</span>
              <div class="pr-table-filter">
                <span :class="['pr-chip', { active: !tableDeptFilter }]" @click="tableDeptFilter = ''">全部</span>
                <span
                  v-for="dept in departments" :key="dept.value"
                  :class="['pr-chip', { active: tableDeptFilter === dept.value }]"
                  @click="tableDeptFilter = dept.value"
                >{{ dept.label }}</span>
              </div>
            </div>
            <div class="pr-table-scroll">
              <div v-if="!filteredRecords.length" class="pr-empty">
                <i class="fas fa-clipboard-list" />
                <span>暂无记录，点击「录入」添加</span>
              </div>
              <table v-else class="pr-table">
                <thead>
                  <tr>
                    <th>部门</th>
                    <th>产品</th>
                    <th>69码</th>
                    <th>数量</th>
                    <th>产值</th>
                    <th>时间</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="rec in filteredRecords" :key="rec.id">
                    <td><span :class="['pr-dept-tag', `pr-dept-tag-${rec.department}`]">{{ deptLabel(rec.department) }}</span></td>
                    <td class="pr-td-product"><strong>{{ rec.product_name }}</strong></td>
                    <td class="pr-td-mono">{{ rec.barcode || '—' }}</td>
                    <td><strong>{{ rec.quantity }}</strong></td>
                    <td class="pr-td-value">¥{{ formatMoney(rec.production_value) }}</td>
                    <td class="pr-td-time">{{ formatTime(rec.create_time) }}</td>
                    <td><button class="pr-row-del" @click="handleDelete(rec.id)"><i class="fas fa-trash-alt" /></button></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="recordsPages > 1" class="pr-pagination">
              <button class="pr-page-btn" :disabled="recordsPage <= 1" @click="recordsPage--"><i class="fas fa-chevron-left" /></button>
              <span class="pr-page-info">{{ recordsPage }} / {{ recordsPages }}</span>
              <button class="pr-page-btn" :disabled="recordsPage >= recordsPages" @click="recordsPage++"><i class="fas fa-chevron-right" /></button>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ 日报 TAB ============ -->
      <div v-show="viewTab === 'daily'" class="pr-main">

        <!-- KPI -->
        <div v-if="reportSummary" class="pr-kpi-row">
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-blue"><i class="fas fa-cubes" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">总产量</span>
              <span class="pr-kpi-value">{{ reportSummary.overall_quantity }}<small class="pr-kpi-unit">件</small></span>
            </div>
          </div>
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-green"><i class="fas fa-yen-sign" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">总产值</span>
              <span class="pr-kpi-value">¥{{ formatMoney(reportSummary.overall_value) }}</span>
            </div>
          </div>
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-amber"><i class="fas fa-barcode" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">SKU 数</span>
              <span class="pr-kpi-value">{{ reportSummary.overall_sku_count }}<small class="pr-kpi-unit">种</small></span>
            </div>
          </div>
        </div>

        <!-- 部门面板 -->
        <div v-if="reportSummary?.departments?.length" class="pr-dept-row">
          <div v-for="d in reportSummary.departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
            <div class="pr-dept-accent" />
            <div class="pr-dept-content">
              <div class="pr-dept-head">
                <div :class="['pr-dept-icon-sm', `pr-dept-icon-${d.department}`]"><i :class="deptIcon(d.department)" /></div>
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

        <!-- 图表 + 汇总表 并排 -->
        <div class="pr-content-row">
          <div class="pr-chart-section">
            <div class="pr-section-header">
              <span class="pr-section-title"><i class="fas fa-chart-bar" /> {{ reportDate }} 生产概况</span>
            </div>
            <div ref="dailyChartRef" class="pr-chart-body" />
          </div>

          <div v-if="reportSummary?.departments?.length" class="pr-table-section">
            <div class="pr-section-header">
              <span class="pr-section-title"><i class="fas fa-table" /> 部门汇总</span>
            </div>
            <div class="pr-table-scroll">
              <table class="pr-table">
                <thead><tr><th>部门</th><th>产量</th><th>产值</th><th>SKU</th></tr></thead>
                <tbody>
                  <tr v-for="d in reportSummary.departments" :key="d.department">
                    <td><span :class="['pr-dept-tag', `pr-dept-tag-${d.department}`]">{{ d.department_label }}</span></td>
                    <td><strong>{{ d.total_quantity }}</strong></td>
                    <td>¥{{ formatMoney(d.total_value) }}</td>
                    <td>{{ d.sku_count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ 月报 TAB ============ -->
      <div v-show="viewTab === 'monthly'" class="pr-main">

        <!-- KPI -->
        <div v-if="monthlySummary" class="pr-kpi-row">
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-blue"><i class="fas fa-cubes" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">月总产量</span>
              <span class="pr-kpi-value">{{ monthlySummary.overall_quantity ?? 0 }}<small class="pr-kpi-unit">件</small></span>
            </div>
          </div>
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-green"><i class="fas fa-yen-sign" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">月总产值</span>
              <span class="pr-kpi-value">¥{{ formatMoney(monthlySummary.overall_value ?? 0) }}</span>
            </div>
          </div>
          <div class="pr-kpi-card">
            <div class="pr-kpi-icon pr-kpi-icon-amber"><i class="fas fa-calendar-check" /></div>
            <div class="pr-kpi-body">
              <span class="pr-kpi-label">生产天数</span>
              <span class="pr-kpi-value">{{ monthlySummary.daily_data?.filter((d: any) => d.total.quantity > 0).length || 0 }}<small class="pr-kpi-unit">天</small></span>
            </div>
          </div>
        </div>

        <!-- 部门面板 -->
        <div v-if="monthlySummary?.monthly_departments?.length" class="pr-dept-row">
          <div v-for="d in monthlySummary.monthly_departments" :key="d.department" :class="['pr-dept-card', `pr-dept-${d.department}`]">
            <div class="pr-dept-accent" />
            <div class="pr-dept-content">
              <div class="pr-dept-head">
                <div :class="['pr-dept-icon-sm', `pr-dept-icon-${d.department}`]"><i :class="deptIcon(d.department)" /></div>
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

        <!-- 图表 + 日明细表 并排 -->
        <div class="pr-content-row">
          <div class="pr-chart-section">
            <div class="pr-section-header">
              <span class="pr-section-title"><i class="fas fa-chart-area" /> 月度趋势</span>
            </div>
            <div ref="monthlyChartRef" class="pr-chart-body" />
          </div>

          <div v-if="monthlySummary?.daily_data?.length" class="pr-table-section">
            <div class="pr-section-header">
              <span class="pr-section-title"><i class="fas fa-table" /> 每日明细</span>
            </div>
            <div class="pr-table-scroll">
              <table class="pr-table">
                <thead><tr><th>日期</th><th>充棉</th><th>手工</th><th>包装</th><th>合计</th><th>总产值</th></tr></thead>
                <tbody>
                  <tr v-for="d in monthlySummary.daily_data" :key="d.date">
                    <td><strong>{{ d.day }}日</strong></td>
                    <td>{{ d.filling.quantity }}</td>
                    <td>{{ d.handcraft.quantity }}</td>
                    <td>{{ d.packaging.quantity }}</td>
                    <td><strong>{{ d.total.quantity }}</strong></td>
                    <td>¥{{ formatMoney(d.total.value) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ 录入抽屉 ============ -->
      <Transition name="pr-drawer">
        <div v-if="showEntryDrawer" class="pr-drawer-overlay" @click.self="closeEntryDrawer">
          <div class="pr-drawer">
            <div class="pr-drawer-header">
              <h3><i class="fas fa-pen-alt" /> 生产数据录入</h3>
              <button class="pr-drawer-close" @click="closeEntryDrawer"><i class="fas fa-times" /></button>
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
                    <i :class="dept.icon" /> {{ dept.label }}
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
                  <i class="fas fa-search pr-form-search-icon" />
                  <div v-if="showDropdown" class="pr-form-dropdown">
                    <div v-if="searchLoading" class="pr-form-dropdown-loading">
                      <i class="fas fa-spinner fa-spin" /> 搜索中...
                    </div>
                    <div v-else-if="searchError" class="pr-form-dropdown-error">
                      <i class="fas fa-exclamation-circle" /> {{ searchError }}
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
                  <i class="fas fa-check-circle" />
                  <span>{{ form.product_name }}</span>
                  <span v-if="form.barcode" class="pr-form-selected-barcode">{{ form.barcode }}</span>
                  <button class="pr-form-selected-clear" @click="clearProduct"><i class="fas fa-times" /></button>
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
                <div class="pr-form-value">¥{{ formatMoney(computedValue) }}</div>
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
              <i class="fas fa-question-circle" />
              <h4>确认录入</h4>
            </div>
            <div class="pr-modal-body">
              <p>请确认以下生产数据：</p>
              <div class="pr-confirm-data">
                <div class="pr-confirm-row"><span>部门：</span><strong>{{ deptLabel(formDept) }}</strong></div>
                <div class="pr-confirm-row"><span>产品：</span><strong>{{ form.product_name }}</strong></div>
                <div class="pr-confirm-row"><span>数量：</span><strong>{{ form.quantity }} 件</strong></div>
                <div class="pr-confirm-row"><span>产值：</span><strong>¥{{ formatMoney(computedValue) }}</strong></div>
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
          <i :class="exportStatus.icon" />
          <span>{{ exportStatus.message }}</span>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { dailyProductionApi, productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { DailyProductionRecord, Product } from '@/types'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import * as echarts from 'echarts'

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
function formatMoney(v: number | string): string {
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (isNaN(n)) return '0.00'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ===== 核心状态 =====
const viewTab = ref('overview')
const selectedDate = ref(todayLocal())
const reportDate = ref(todayLocal())
const tableDeptFilter = ref('')
const chartMode = ref<'qty' | 'value'>('qty')
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
  // 自动获取产品单价
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
const recordsPage = ref(1)
const { data: recordsData } = useQuery({
  queryKey: ['daily-production-records', selectedDate, recordsPage],
  queryFn: () => dailyProductionApi.records({ year: parseInt(selectedDate.value.slice(0, 4)), month: parseInt(selectedDate.value.slice(5, 7)), production_date: selectedDate.value, page: recordsPage.value, per_page: 50 }) as Promise<any>,
  staleTime: 30_000,
  gcTime: 60_000,
})
const records = computed(() => {
  const d = recordsData.value
  return (d?.records ?? d?.data ?? (Array.isArray(d) ? d : [])) as DailyProductionRecord[]
})
const recordsTotal = computed(() => recordsData.value?.total ?? 0)
const recordsPages = computed(() => recordsData.value?.pages ?? 0)
const recordsStats = computed(() => recordsData.value?.stats ?? null)

const filteredRecords = computed(() => {
  if (!tableDeptFilter.value) return records.value
  return records.value.filter((r: DailyProductionRecord) => r.department === tableDeptFilter.value)
})

const overviewTotalQty = computed(() => recordsStats.value?.total_quantity ?? records.value.reduce((s: number, r: DailyProductionRecord) => s + (Number(r.quantity) || 0), 0))
const overviewTotalValue = computed(() => recordsStats.value?.total_value ?? records.value.reduce((s: number, r: DailyProductionRecord) => s + (Number(r.production_value) || 0), 0))
const overviewTotalSku = computed(() => recordsStats.value?.total_sku ?? new Set(records.value.map((r: DailyProductionRecord) => r.product_name)).size)

function getDeptQty(dept: string) {
  return records.value.filter((r: DailyProductionRecord) => r.department === dept).reduce((s: number, r: DailyProductionRecord) => s + (Number(r.quantity) || 0), 0)
}
function getDeptValue(dept: string) {
  return records.value.filter((r: DailyProductionRecord) => r.department === dept).reduce((s: number, r: DailyProductionRecord) => s + (Number(r.production_value) || 0), 0)
}
function getDeptSku(dept: string) {
  return new Set(records.value.filter((r: DailyProductionRecord) => r.department === dept).map((r: DailyProductionRecord) => r.product_name)).size
}
function getDeptRecordCount(dept: string) {
  return records.value.filter((r: DailyProductionRecord) => r.department === dept).length
}

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
  // 二次确认
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
  if (!confirm('确认删除该生产记录？')) return
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
  if (e.ctrlKey && ['1', '2', '3'].includes(e.key)) {
    e.preventDefault()
    const tabs = ['overview', 'daily', 'monthly']
    viewTab.value = tabs[parseInt(e.key) - 1]
  }
}

// ===== ECharts =====
const overviewChartRef = ref<HTMLElement>()
const dailyChartRef = ref<HTMLElement>()
const monthlyChartRef = ref<HTMLElement>()
let overviewChart: echarts.ECharts | null = null
let dailyChart: echarts.ECharts | null = null
let monthlyChart: echarts.ECharts | null = null

function getChart(el: HTMLElement, existing: echarts.ECharts | null) {
  return (existing && !existing.isDisposed()) ? existing : echarts.init(el)
}

function renderOverviewChart() {
  if (!overviewChartRef.value) return
  overviewChart = getChart(overviewChartRef.value, overviewChart)
  const depts = departments.map(d => ({
    name: d.label, key: d.value, color: deptColors[d.value].main,
  }))
  const isQty = chartMode.value === 'qty'
  overviewChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: depts.map(d => d.name), axisLabel: { fontSize: 13, fontWeight: 600 } },
    yAxis: { type: 'value', name: isQty ? '产量（件）' : '产值（元）', axisLabel: { fontSize: 11 } },
    series: [{
      type: 'bar',
      barWidth: '50%',
      data: depts.map(d => ({
        value: isQty ? getDeptQty(d.key) : getDeptValue(d.key),
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: deptColors[d.key].gradient[0] },
            { offset: 1, color: deptColors[d.key].gradient[1] },
          ]),
          borderRadius: [6, 6, 0, 0],
        },
      })),
      label: {
        show: true, position: 'top', fontSize: 14, fontWeight: 700,
        formatter: (p: any) => isQty ? `${p.value}件` : `¥${p.value}`,
      },
    }],
  }, true)
}

function renderDailyChart() {
  if (!dailyChartRef.value || !reportSummary.value?.departments?.length) return
  dailyChart = getChart(dailyChartRef.value, dailyChart)
  const depts = reportSummary.value.departments
  dailyChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: depts.map((d: any) => d.department_label), axisLabel: { fontSize: 13, fontWeight: 600 } },
    yAxis: [
      { type: 'value', name: '产量', axisLabel: { fontSize: 11 } },
      { type: 'value', name: '产值', axisLabel: { fontSize: 11 } },
    ],
    series: [
      {
        name: '产量', type: 'bar', barWidth: '30%',
        data: depts.map((d: any) => ({
          value: d.total_quantity,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: deptColors[d.department]?.gradient[0] ?? '#3b82f6' },
              { offset: 1, color: deptColors[d.department]?.gradient[1] ?? '#1d4ed8' },
            ]),
            borderRadius: [6, 6, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 12, fontWeight: 600 },
      },
      {
        name: '产值', type: 'bar', barWidth: '30%', yAxisIndex: 1,
        data: depts.map((d: any) => ({
          value: d.total_value,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#fbbf24' },
              { offset: 1, color: '#f59e0b' },
            ]),
            borderRadius: [6, 6, 0, 0],
          },
        })),
        label: { show: true, position: 'top', fontSize: 11, formatter: (p: any) => `¥${p.value}` },
      },
    ],
  }, true)
}

function renderMonthlyChart() {
  if (!monthlyChartRef.value || !monthlySummary.value?.daily_data?.length) return
  monthlyChart = getChart(monthlyChartRef.value, monthlyChart)
  const days = monthlySummary.value.daily_data.filter((d: any) => d.total.quantity > 0)
  monthlyChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['充棉', '手工', '包装', '合计'], bottom: 0, itemWidth: 12, itemHeight: 12, textStyle: { fontSize: 12 } },
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: days.map((d: any) => d.day + '日'), axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', name: '产量', axisLabel: { fontSize: 11 } },
    series: [
      {
        name: '充棉', type: 'bar', stack: 'dept',
        data: days.map((d: any) => d.filling.quantity),
        itemStyle: { color: deptColors.filling.main, borderRadius: [0, 0, 0, 0] },
      },
      {
        name: '手工', type: 'bar', stack: 'dept',
        data: days.map((d: any) => d.handcraft.quantity),
        itemStyle: { color: deptColors.handcraft.main },
      },
      {
        name: '包装', type: 'bar', stack: 'dept',
        data: days.map((d: any) => d.packaging.quantity),
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
  if (viewTab.value === 'overview') overviewChart?.resize()
  else if (viewTab.value === 'daily') dailyChart?.resize()
  else if (viewTab.value === 'monthly') monthlyChart?.resize()
}

// 图表渲染 watcher
watch([records, selectedDate, chartMode], () => { if (viewTab.value === 'overview') nextTick(() => requestAnimationFrame(renderOverviewChart)) })
watch([reportSummary], () => { if (viewTab.value === 'daily') nextTick(() => requestAnimationFrame(renderDailyChart)) })
watch([monthlySummary], () => { if (viewTab.value === 'monthly') nextTick(() => requestAnimationFrame(renderMonthlyChart)) })
watch(viewTab, (tab) => {
  nextTick(() => requestAnimationFrame(() => {
    if (tab === 'overview') { renderOverviewChart(); overviewChart?.resize() }
    else if (tab === 'daily') { renderDailyChart(); dailyChart?.resize() }
    else if (tab === 'monthly') { renderMonthlyChart(); monthlyChart?.resize() }
  }))
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleKeydown)
  nextTick(() => requestAnimationFrame(renderOverviewChart))
})
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleKeydown)
  overviewChart?.dispose(); dailyChart?.dispose(); monthlyChart?.dispose()
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<style scoped>
/* ========================================
   生产报表 — 重构布局
   信息层级：KPI 英雄区 → 部门面板 → 图表+表格并排
   ======================================== */

.pr-container { padding: 8px; margin: 0 auto; height: 100%; display: flex; flex-direction: column; box-sizing: border-box; }
.pr-card { background: var(--color-surface-card, white); border-radius: 18px; border: 1px solid var(--color-border-light, #e2e8f0); box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06); transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
.pr-card:hover { box-shadow: 0 8px 24px rgba(0,0,0,0.06), 0 24px 80px rgba(0,0,0,0.08); }
.pr-card-main { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }

/* === 顶部工具栏 === */
.pr-toolbar { border-bottom: 1px solid var(--color-border-light, #f1f5f9); }
.pr-toolbar-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 24px 10px; gap: 12px; flex-wrap: wrap; }
.pr-toolbar-left { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.pr-toolbar-center { display: flex; align-items: center; }
.pr-toolbar-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

/* === 日期导航 === */
.pr-date-nav { display: flex; align-items: center; gap: 6px; }
.pr-date-btn { width: 30px; height: 30px; border: 1px solid var(--color-border, #e4e7ed); border-radius: 8px; background: white; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--color-text-secondary); transition: all 0.2s ease; }
.pr-date-btn:hover { border-color: var(--color-primary-400); color: var(--color-primary-600); background: var(--color-primary-50); }
.pr-date-input { padding: 5px 10px; border: 1px solid var(--color-border, #e4e7ed); border-radius: 8px; font-size: 13px; font-weight: 600; outline: none; background: white; color: var(--color-text); font-family: inherit; transition: all 0.2s ease; }
.pr-date-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.pr-today-btn { padding: 5px 10px; border: 1px solid var(--color-primary-200); border-radius: 8px; background: var(--color-primary-50); font-size: 12px; font-weight: 600; color: var(--color-primary-600); cursor: pointer; transition: all 0.2s ease; }
.pr-today-btn:hover { background: var(--color-primary-100); }
.pr-month-label { font-size: 15px; font-weight: 700; color: var(--color-text); min-width: 100px; text-align: center; }

/* === Tab 切换 === */
.pr-tab-group { display: inline-flex; gap: 2px; padding: 3px; border-radius: 10px; background: var(--color-surface, #f4f6fc); border: 1px solid var(--color-border-light); }
.pr-tab { padding: 6px 16px; border: none; border-radius: 8px; background: transparent; font-size: 13px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; transition: all 0.3s ease; }
.pr-tab:hover { background: white; color: var(--color-primary-600); }
.pr-tab-active { background: white; color: var(--color-primary-700); box-shadow: 0 1px 3px rgba(0,0,0,0.08); transform: translateY(-1px); }

/* === 操作按钮 === */
.pr-action-btn { padding: 6px 14px; border: 1px solid var(--color-border, #e4e7ed); border-radius: 9px; background: white; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; color: var(--color-text-secondary); display: inline-flex; align-items: center; gap: 5px; }
.pr-action-btn:hover { border-color: var(--color-primary-300); transform: translateY(-1px); }
.pr-action-primary { color: var(--color-primary-600); border-color: var(--color-primary-200); }
.pr-action-primary:hover { background: var(--color-primary-50); border-color: var(--color-primary-400); }

/* === 内容主体 === */
.pr-main { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 0; }

/* === KPI 英雄区 === */
.pr-kpi-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 16px 24px 0; }
.pr-kpi-card { display: flex; align-items: center; gap: 14px; padding: 16px 20px; background: var(--color-surface, #f4f6fc); border-radius: 14px; border: 1px solid var(--color-border-light, #f0f2f5); transition: all 0.3s ease; }
.pr-kpi-card:hover { border-color: var(--color-primary-200); box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
.pr-kpi-icon { width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.pr-kpi-icon-blue { background: var(--color-primary-50); color: var(--color-primary-600); }
.pr-kpi-icon-green { background: var(--color-success-50); color: var(--color-success-600); }
.pr-kpi-icon-amber { background: var(--color-warning-50); color: var(--color-warning-600); }
.pr-kpi-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pr-kpi-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); letter-spacing: 0.02em; }
.pr-kpi-value { font-size: 22px; font-weight: 800; color: var(--color-text); font-variant-numeric: tabular-nums; line-height: 1.2; }
.pr-kpi-unit { font-size: 13px; font-weight: 600; color: var(--color-text-secondary); margin-left: 3px; }

/* === 部门面板 === */
.pr-dept-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 12px 24px 0; }
.pr-dept-card { display: flex; border-radius: 12px; border: 1px solid var(--color-border-light, #f0f2f5); background: white; overflow: hidden; transition: all 0.3s ease; }
.pr-dept-card:hover { border-color: var(--color-border, #e4e7ed); box-shadow: 0 2px 12px rgba(0,0,0,0.04); }
.pr-dept-accent { width: 4px; flex-shrink: 0; }
.pr-dept-content { flex: 1; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.pr-dept-head { display: flex; align-items: center; gap: 8px; }
.pr-dept-icon-sm { width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 12px; }
.pr-dept-icon-filling { background: var(--color-primary-50); color: var(--color-primary-600); }
.pr-dept-icon-handcraft { background: var(--color-success-50); color: var(--color-success-600); }
.pr-dept-icon-packaging { background: var(--color-warning-50); color: var(--color-warning-600); }
.pr-dept-name { font-size: 13px; font-weight: 700; color: var(--color-text); }
.pr-dept-qty { display: flex; align-items: baseline; gap: 4px; }
.pr-dept-qty-num { font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums; line-height: 1.1; }
.pr-dept-qty-unit { font-size: 13px; font-weight: 600; color: var(--color-text-secondary); }
.pr-dept-stats { display: flex; gap: 14px; }
.pr-dept-stat { display: flex; flex-direction: column; gap: 1px; }
.pr-dept-stat-label { font-size: 11px; font-weight: 500; color: var(--color-text-muted); }
.pr-dept-stat-val { font-size: 12px; font-weight: 700; color: var(--color-text-secondary); font-variant-numeric: tabular-nums; }

/* 部门色系 */
.pr-dept-filling .pr-dept-accent { background: var(--color-primary-500, #5b8def); }
.pr-dept-filling .pr-dept-qty-num { color: var(--color-primary-700, #1e3d7a); }
.pr-dept-handcraft .pr-dept-accent { background: var(--color-success-500, #28c76f); }
.pr-dept-handcraft .pr-dept-qty-num { color: var(--color-success-700, #115d33); }
.pr-dept-packaging .pr-dept-accent { background: var(--color-warning-500, #ff9f43); }
.pr-dept-packaging .pr-dept-qty-num { color: var(--color-warning-700, #7d4d12); }

/* === 图表 + 表格 并排区 === */
.pr-content-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px 24px 16px; flex: 1; min-height: 0; }
.pr-chart-section { display: flex; flex-direction: column; min-height: 0; }
.pr-table-section { display: flex; flex-direction: column; min-height: 0; }

/* 区块标题 */
.pr-section-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; flex-shrink: 0; }
.pr-section-title { font-size: 13px; font-weight: 700; color: var(--color-text); display: flex; align-items: center; gap: 6px; }
.pr-section-title i { color: var(--color-primary-500); font-size: 12px; }

/* 筛选芯片 */
.pr-chip { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; border: 1px solid var(--color-border-light, #e4e7ed); background: white; color: var(--color-text-secondary); transition: all 0.2s ease; user-select: none; }
.pr-chip:hover { border-color: var(--color-primary-300); color: var(--color-primary-600); }
.pr-chip.active { background: var(--color-primary-600, #5b8def); color: white; border-color: transparent; }
.pr-chart-filter, .pr-table-filter { display: flex; gap: 4px; }

/* 图表 */
.pr-chart-body { width: 100%; height: 280px; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 12px; overflow: hidden; flex-shrink: 0; }

/* 表格 */
.pr-table-scroll { overflow-y: auto; overflow-x: auto; border-radius: 10px; border: 1px solid var(--color-border-light); flex: 1; min-height: 0; }
.pr-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pr-table thead th { padding: 8px 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; background: var(--color-surface, #f8fafc); border-bottom: 2px solid var(--color-border-light, #e2e8f0); color: var(--color-text-secondary); text-align: center; white-space: nowrap; position: sticky; top: 0; z-index: 1; }
.pr-table tbody td { padding: 8px 12px; font-size: 13px; border-bottom: 1px solid var(--color-border-light, #f1f5f9); text-align: center; vertical-align: middle; transition: background 0.2s ease; color: var(--color-text); }
.pr-table tbody tr:hover { background: var(--color-primary-50); }
.pr-td-product { display: flex; align-items: center; gap: 6px; text-align: left !important; }
.pr-td-mono { font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; color: var(--color-text-secondary); }
.pr-td-value { font-weight: 700; color: var(--color-success-600); }
.pr-td-time { font-size: 12px; color: var(--color-text-muted); }
.pr-row-del { border: none; background: transparent; color: var(--color-text-muted); cursor: pointer; font-size: 12px; padding: 4px 6px; border-radius: 6px; transition: all 0.2s ease; }
.pr-row-del:hover { color: var(--color-danger-500); background: var(--color-danger-50); }

/* 部门标签 */
.pr-dept-tag { display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px; border-radius: 8px; font-size: 11px; font-weight: 700; white-space: nowrap; }
.pr-dept-tag-filling { background: var(--color-primary-50, #eff6ff); color: var(--color-primary-700, #1d4ed8); }
.pr-dept-tag-handcraft { background: var(--color-success-50, #f0fdf4); color: var(--color-success-700, #15803d); }
.pr-dept-tag-packaging { background: var(--color-warning-50, #fffbeb); color: var(--color-warning-700, #b45309); }

/* === 空状态 === */
.pr-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px 20px; color: var(--color-text-muted); }
.pr-empty i { font-size: 24px; opacity: 0.4; }
.pr-empty span { font-size: 13px; }

/* === 分页 === */
.pr-pagination { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 8px 0; border-top: 1px solid var(--color-border-light, #f1f5f9); }
.pr-page-btn { width: 28px; height: 28px; border: 1px solid var(--color-border, #e4e7ed); border-radius: 6px; background: white; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 11px; color: var(--color-text-secondary); transition: all 0.2s ease; }
.pr-page-btn:hover:not(:disabled) { border-color: var(--color-primary-400); color: var(--color-primary-600); background: var(--color-primary-50); }
.pr-page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pr-page-info { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); }

/* ===== 录入抽屉 ===== */
.pr-drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.3); backdrop-filter: blur(4px); z-index: 100; display: flex; justify-content: flex-end; }
.pr-drawer { width: 440px; max-width: 100%; background: white; display: flex; flex-direction: column; box-shadow: -8px 0 30px rgba(0,0,0,0.15); }
.pr-drawer-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 24px; border-bottom: 1px solid var(--color-border-light, #f1f5f9); }
.pr-drawer-header h3 { font-size: 15px; font-weight: 700; color: var(--color-text); margin: 0; display: flex; align-items: center; gap: 8px; }
.pr-drawer-header h3 i { color: var(--color-primary-500); }
.pr-drawer-close { border: none; background: transparent; color: var(--color-text-muted); font-size: 16px; cursor: pointer; padding: 4px; }
.pr-drawer-close:hover { color: var(--color-text); }
.pr-drawer-body { flex: 1; overflow-y: auto; padding: 18px 24px; display: flex; flex-direction: column; gap: 14px; }
.pr-drawer-footer { display: flex; gap: 10px; padding: 14px 24px; border-top: 1px solid var(--color-border-light, #f1f5f9); }
.pr-drawer-cancel { flex: 1; padding: 10px; border: 1px solid var(--color-border, #e4e7ed); border-radius: 10px; background: white; font-size: 14px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; transition: all 0.3s ease; }
.pr-drawer-cancel:hover { border-color: var(--color-primary-300); }
.pr-drawer-submit { flex: 1; padding: 10px; border: none; border-radius: 10px; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: white; font-size: 14px; font-weight: 700; cursor: pointer; transition: all 0.3s ease; display: flex; align-items: center; justify-content: center; gap: 6px; }
.pr-drawer-submit:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(91, 141, 239, 0.4); transform: translateY(-1px); }
.pr-drawer-submit:disabled { opacity: 0.5; cursor: not-allowed; }

/* 抽屉动画 */
.pr-drawer-enter-active, .pr-drawer-leave-active { transition: all 0.3s ease; }
.pr-drawer-enter-active .pr-drawer, .pr-drawer-leave-active .pr-drawer { transition: transform 0.3s ease; }
.pr-drawer-enter-from, .pr-drawer-leave-to { opacity: 0; }
.pr-drawer-enter-from .pr-drawer, .pr-drawer-leave-to .pr-drawer { transform: translateX(100%); }

/* 表单 */
.pr-form-group { display: flex; flex-direction: column; gap: 5px; }
.pr-form-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-text-secondary); }
.pr-required { color: var(--color-danger-500); }
.pr-form-input { width: 100%; padding: 0.5rem 0.875rem; font-size: 0.875rem; color: var(--color-heading); background: white; border: 1px solid var(--color-border, #e4e7ed); border-radius: 10px; transition: all 0.2s ease; outline: none; min-height: 40px; box-sizing: border-box; font-family: inherit; }
.pr-form-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.pr-form-input::placeholder { color: var(--color-text-muted); font-size: 13px; font-weight: 400; opacity: 1; }
.pr-form-textarea { min-height: 56px; resize: vertical; }
.pr-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pr-form-value { padding: 0.5rem 0.875rem; background: var(--color-primary-50); border-radius: 10px; border: 1px solid var(--color-primary-200); font-size: 18px; font-weight: 800; color: var(--color-primary-600); min-height: 40px; display: flex; align-items: center; font-variant-numeric: tabular-nums; }
.pr-form-error { font-size: 12px; color: var(--color-danger-500); margin-top: 1px; }

/* 部门选择按钮 */
.pr-dept-select { display: flex; gap: 8px; }
.pr-dept-btn { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px; padding: 8px; border: 1px solid var(--color-border, #e4e7ed); border-radius: 10px; background: white; font-size: 13px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; transition: all 0.2s ease; }
.pr-dept-btn:hover { border-color: var(--color-primary-300); }
.pr-dept-btn-active { border-color: var(--color-primary-500); background: var(--color-primary-50); color: var(--color-primary-700); }
.pr-dept-btn-filling.pr-dept-btn-active { border-color: var(--color-primary-500); color: var(--color-primary-700); }
.pr-dept-btn-handcraft.pr-dept-btn-active { border-color: var(--color-success-500); background: var(--color-success-50); color: var(--color-success-700); }
.pr-dept-btn-packaging.pr-dept-btn-active { border-color: var(--color-warning-500); background: var(--color-warning-50); color: var(--color-warning-700); }

/* 搜索 */
.pr-form-search { position: relative; }
.pr-form-search-input { padding-left: 34px !important; padding-right: 32px !important; }
.pr-form-search-icon { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--color-text-muted); font-size: 12px; pointer-events: none; }
.pr-form-dropdown { position: absolute; top: 100%; left: 0; right: 0; margin-top: 4px; background: white; border: 1px solid var(--color-primary-200); border-radius: 10px; box-shadow: 0 10px 40px rgba(0,0,0,0.12); max-height: 200px; overflow-y: auto; z-index: 20; }
.pr-form-dropdown-item { padding: 9px 12px; cursor: pointer; transition: background 0.2s ease; border-bottom: 1px solid var(--color-border-light, #f1f5f9); }
.pr-form-dropdown-item:last-child { border-bottom: none; }
.pr-form-dropdown-item:hover, .pr-form-dropdown-item-active { background: var(--color-primary-50); }
.pr-form-dropdown-name { font-size: 13px; font-weight: 600; color: var(--color-text); }
.pr-form-dropdown-barcode { font-size: 11px; color: var(--color-text-secondary); margin-top: 1px; }
.pr-form-dropdown-loading, .pr-form-dropdown-empty, .pr-form-dropdown-error { padding: 10px 12px; font-size: 13px; color: var(--color-text-secondary); text-align: center; }
.pr-form-dropdown-error { color: var(--color-danger-500); }
.pr-form-selected { display: flex; align-items: center; gap: 6px; padding: 6px 10px; background: var(--color-primary-50); border: 1px solid var(--color-primary-200); border-radius: 8px; font-size: 13px; font-weight: 600; color: var(--color-primary-700); margin-top: 4px; }
.pr-form-selected i { color: var(--color-primary-500); }
.pr-form-selected-barcode { font-size: 11px; color: var(--color-text-secondary); font-weight: 500; }
.pr-form-selected-clear { border: none; background: transparent; color: var(--color-text-muted); cursor: pointer; font-size: 12px; margin-left: auto; padding: 2px; }

/* ===== 二次确认弹窗 ===== */
.pr-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); backdrop-filter: blur(4px); z-index: 110; display: flex; align-items: center; justify-content: center; }
.pr-modal { background: white; border-radius: 18px; width: 380px; max-width: 90%; box-shadow: 0 20px 60px rgba(0,0,0,0.2); overflow: hidden; }
.pr-modal-header { display: flex; align-items: center; gap: 10px; padding: 18px 24px 10px; }
.pr-modal-header i { font-size: 22px; color: var(--color-primary-500); }
.pr-modal-header h4 { margin: 0; font-size: 15px; font-weight: 700; color: var(--color-text); }
.pr-modal-body { padding: 0 24px 14px; }
.pr-modal-body p { margin: 0 0 10px; font-size: 13px; color: var(--color-text-secondary); }
.pr-confirm-data { background: var(--color-surface, #f8fafc); border-radius: 10px; padding: 10px 14px; display: flex; flex-direction: column; gap: 6px; }
.pr-confirm-row { display: flex; justify-content: space-between; font-size: 13px; }
.pr-confirm-row span { color: var(--color-text-secondary); }
.pr-confirm-row strong { color: var(--color-text); }
.pr-modal-footer { display: flex; gap: 10px; padding: 10px 24px 18px; }

/* 弹窗动画 */
.pr-modal-enter-active, .pr-modal-leave-active { transition: all 0.25s ease; }
.pr-modal-enter-from, .pr-modal-leave-to { opacity: 0; transform: scale(0.95); }

/* ===== 导出提示 ===== */
.pr-export-toast { position: fixed; top: 20px; right: 20px; z-index: 120; padding: 10px 18px; border-radius: 10px; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); }
.pr-export-toast.info { background: var(--color-primary-50); color: var(--color-primary-700); border: 1px solid var(--color-primary-200); }
.pr-export-toast.success { background: var(--color-success-50); color: var(--color-success-700); border: 1px solid var(--color-success-200); }
.pr-export-toast.error { background: var(--color-danger-50); color: var(--color-danger-700); border: 1px solid var(--color-danger-200); }

/* Toast动画 */
.pr-toast-enter-active, .pr-toast-leave-active { transition: all 0.3s ease; }
.pr-toast-enter-from, .pr-toast-leave-to { opacity: 0; transform: translateX(20px); }

/* === 响应式 === */
@media (max-width: 1200px) {
  .pr-dept-row { grid-template-columns: 1fr; }
  .pr-content-row { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .pr-kpi-row { grid-template-columns: 1fr; }
  .pr-dept-row { grid-template-columns: 1fr; }
  .pr-content-row { grid-template-columns: 1fr; }
  .pr-drawer { width: 100%; }
  .pr-toolbar-row { flex-direction: column; align-items: flex-start; }
  .pr-toolbar-center { align-self: stretch; justify-content: center; }
  .pr-toolbar-right { align-self: stretch; justify-content: flex-end; }
}
</style>
