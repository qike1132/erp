<template>
  <div class="rp-container">
    <div class="page-card page-card-main">
      <!-- 单行工具条：标题 · 维度 tab · 筛选与动作（原先是 tab 独占一个卡片头、筛选独占一行） -->
      <div class="rp-toolbar">
        <div class="rp-title">
          <FontAwesomeIcon icon="chart-line" aria-hidden="true" />
          <h1>报表流水</h1>
        </div>

        <ReportTabGroup :model-value="activeTab" @change="onTabChange" />

        <ReportFilterBar
          v-model:filters="filters"
          :customer-options="customerOptions"
          :searched="searched"
          @search="doSearch"
          @reset="doReset"
          @export="exportReport"
        />
      </div>

      <ReportTable
        :logs="sortedLogs"
        :columns="reportColumns"
        :is-loading="isLoading"
        :is-fetching="isFetching"
        :searched="searched"
        :per-page="perPage"
        :pagination="pagination"
        :current-cfg="currentCfg"
        :active-tab="activeTab"
        :can-edit="canEditRowActions"
        :can-delete="canDeleteRowActions"
        @sort="onSort"
        @page="onPageChange"
        @row-edit="onRowEdit"
        @row-delete="onRowDelete"
      />
    </div>

    <!-- 编辑订单明细弹窗（订单流水行内编辑单个 SKU，2026-10-13） -->
    <EditOrderItemModal
      v-model:open="rowActions.orderItemEditVisible.value"
      v-model:form="rowActions.orderItemEditForm.value"
      :saving="rowActions.savingOrderItem.value"
      :save-order-item-edit="rowActions.saveOrderItemEdit"
    />

    <!-- 编辑备货弹窗（备货流水里的备货行） -->
    <EditStockinModal
      v-model:open="rowActions.stockinEditVisible.value"
      v-model:form="rowActions.stockinEditForm.value"
      :customer-options="customerOptions"
      :saving="rowActions.savingStockin.value"
      :save-stockin-edit="rowActions.saveStockinEdit"
    />

    <!-- 编辑出货/备货抵扣弹窗（出货流水 / 备货抵扣流水；抵扣行客户不可改） -->
    <EditStockoutModal
      v-model:open="rowActions.stockoutEditVisible.value"
      v-model:form="rowActions.stockoutEditForm.value"
      :customer-options="customerOptions"
      :saving="rowActions.savingStockout.value"
      :save-stockout-edit="rowActions.saveStockoutEdit"
      :is-deduction="rowActions.stockoutEditIsDeduction.value"
    />

    <!-- 编辑退货弹窗（退货流水；后端单事务内取消+重建） -->
    <EditReturnModal
      v-model:open="rowActions.returnEditVisible.value"
      v-model:form="rowActions.returnEditForm.value"
      :saving="rowActions.savingReturn.value"
      :save-return-edit="rowActions.saveReturnEdit"
    />

    <!-- 删除确认对话框 -->
    <UiConfirmDialog
      :open="rowActions.confirmDialog.open"
      :text="rowActions.confirmDialog.text"
      :sub="rowActions.confirmDialog.sub"
      :type="rowActions.confirmDialog.type"
      @confirm="rowActions.confirmDialog.onConfirm"
      @cancel="rowActions.confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { useDebounceFn } from '@vueuse/core'
import { reportApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { useAuthStore } from '@/stores/auth'
import ReportTabGroup from './components/ReportTabGroup.vue'
import ReportFilterBar from './components/ReportFilterBar.vue'
import ReportTable from './components/ReportTable.vue'
import EditOrderItemModal from './components/EditOrderItemModal.vue'
import EditStockinModal from './components/EditStockinModal.vue'
import EditStockoutModal from './components/EditStockoutModal.vue'
import EditReturnModal from './components/EditReturnModal.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useReportConfig, type TabType } from './composables/useReportConfig'
import { useReportRowActions, TAB_ROW_PERMISSIONS, type ReportActionTab } from './composables/useReportRowActions'

const activeTab = ref<TabType>('order')
const page = ref(1)
const perPage = ref(15)
/**
 * 查询门槛（P1-24）：初始关闭——挂载/切 tab 不自动查；提交（显式点「查询」
 * 或筛选 300ms 防抖静默提交）后才开启。原先恒为 true，门槛形同虚设。
 */
const searched = ref(false)
/** 当前排序（服务端分页不变，这是当前页内的客户端排序） */
const sort = ref<{ field: string; order: number } | null>(null)

const filters = reactive({ customer: '', product: '' })
/**
 * 已提交的筛选快照（P1-24）：queryKey 与导出读它，而非 reactive 原对象——
 * ReportFilterBar 经 defineModel 就地 mutate filters，每敲一个字符 key 就变，
 * 造成每键一次后端请求。快照只在「提交」时更新。
 */
const appliedFilters = ref({ customer: '', product: '' })

/** 提交当前筛选：快照入 key、开查询门槛、回第 1 页（新筛选从第一页看起） */
function commitFilters() {
  appliedFilters.value = { customer: filters.customer, product: filters.product }
  searched.value = true
  page.value = 1
}

/**
 * 键入静默防抖提交（照 PurchasePlanView 的「防抖快照」模式）：连续键入只提交
 * 最终值。已显式提交后防抖才到期时，快照内容相同 → queryKey 结构化哈希相同 →
 * vue-query 判 key 未变不重发请求（@vueuse 的 useDebounceFn 无 cancel，靠 key
 * 幂等实现「立即提交且到期不重复」）。
 */
const debouncedCommit = useDebounceFn(commitFilters, 300)
watch(filters, () => { debouncedCommit() })

const authStore = useAuthStore()
/**
 * 行内编辑/删除的权限裁决（各维度独立职责分离码，2026-10-07）：
 * 订单/备货 = order_edit / order_delete（迁移 075）；出货 = stockout_*、抵扣 = deduction_*、
 * 退货 = return_*（迁移 079）。均在 /user 权限树「订单流水」下显式勾选，超管在
 * hasPermission 内短路放行。
 * 权限数组含后端 require_any 的 manage 兜底码（stockout_manage / stock_return_manage /
 * order_manage 等）——镜像后端全部可放行路径，持有页面级 manage 的用户不应被前端拦。
 * 当前 tab 两项皆无时整个「操作」列不渲染（连表头一起），而不是空壳列。
 */
const rowPerms = computed(() => TAB_ROW_PERMISSIONS[activeTab.value])
const canEditRowActions = computed(() => authStore.hasAnyPermission(rowPerms.value.edit))
const canDeleteRowActions = computed(() => authStore.hasAnyPermission(rowPerms.value.delete))
const canManageRowActions = computed(() => canEditRowActions.value || canDeleteRowActions.value)

const { currentCfg, currentTabEndpoint, reportColumns } = useReportConfig(activeTab, canManageRowActions)

const catalogStore = useCatalogStore()
catalogStore.ensureActiveCustomerNames().catch(() => {})

const customerOptions = computed(() =>
  catalogStore.activeCustomerNames.map((c) => ({ value: c.name, label: c.name })),
)

const rowActions = useReportRowActions()

/** 行内按钮 → 还原聚合行 → 单条直开 / 多条选择弹窗 */
function onRowEdit(row: Record<string, unknown>) {
  void rowActions.onRowAction(activeTab.value as ReportActionTab, 'edit', row)
}
function onRowDelete(row: Record<string, unknown>) {
  void rowActions.onRowAction(activeTab.value as ReportActionTab, 'delete', row)
}

const { data: reportData, isLoading, isFetching } = useQuery({
  queryKey: ['report-data', activeTab, page, perPage, appliedFilters],
  queryFn: async () => {
    const params: Record<string, string | number> = { page: page.value, per_page: perPage.value }
    if (appliedFilters.value.customer) params.customer = appliedFilters.value.customer
    if (appliedFilters.value.product) params.product = appliedFilters.value.product
    return await reportApi[currentTabEndpoint()](params)
  },
  enabled: searched,
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const logs = computed(() => reportData.value?.logs ?? [])
const pagination = computed(() => reportData.value?.pagination)

/** 排序取值：非数值列按 0，避免 NaN 让整列排序失效 */
function sortValue(row: Record<string, unknown>, field: string): number {
  const n = Number(row[field])
  return Number.isFinite(n) ? n : 0
}

const sortedLogs = computed(() => {
  const s = sort.value
  if (!s) return logs.value
  return [...logs.value].sort((a, b) => (sortValue(a, s.field) - sortValue(b, s.field)) * s.order)
})

/** PrimeVue 排序事件：order 为 1 升序 / -1 降序 / 0 取消 */
function onSort(event: { field: string; order: number }) {
  sort.value = event.order ? { field: event.field, order: event.order } : null
}

function doSearch() {
  // 显式提交：同步生效不等防抖；挂起的防抖到期时快照内容相同 → key 幂等不重复
  commitFilters()
}

function doReset() {
  Object.assign(filters, { customer: '', product: '' })
  // 同步提交空筛选并回第 1 页（不等防抖）；防抖到期时同快照为 no-op
  commitFilters()
}

function onTabChange(value: TabType) {
  activeTab.value = value
  page.value = 1
}

function onPageChange(event: { page: number; rows: number }) {
  page.value = event.page + 1
  perPage.value = event.rows
}

function exportReport() {
  const params = new URLSearchParams()
  params.set('report_type', activeTab.value)
  // 导出与查询同口径：读已提交的筛选快照，而非用户可能还在改的草稿输入（P1-24）
  if (appliedFilters.value.customer) params.set('customer', appliedFilters.value.customer)
  if (appliedFilters.value.product) params.set('product', appliedFilters.value.product)
  window.open(`/api/v1/reports/export?${params.toString()}`, '_blank')
}
</script>

<style scoped>
.rp-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.rp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 20px;
  min-height: 62px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  flex-shrink: 0;
}
.rp-title {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-shrink: 0;
}
.rp-title svg {
  width: 18px;
  height: 18px;
  color: var(--color-primary-600);
}
.rp-title h1 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
}
</style>
