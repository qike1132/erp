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
          :filters="filters"
          :customer-options="customerOptions"
          @search="doSearch"
          @reset="doReset"
          @export="exportReport"
        />
      </div>

      <!--
        错误反馈单通道（R40）：查询失败只在这里呈现，queryFn 内不再 toast。
        横幅常驻而非 toast，原因有两点：
          1. toast 会自行消失，用户回看时已无从得知上次查询为什么没数据；
          2. TanStack 的 queryKey 隔离让「过时请求」的 error 属于旧 query，当前 observer
             只读新 query 的 error——所以改筛选重搜后，旧请求失败不会串到这条横幅上。
      -->
      <UiAlert
        v-if="reportErrorMessage"
        class="rp-error-banner"
        variant="danger"
        :title="reportErrorMessage"
      />

      <ReportTable
        :logs="sortedLogs"
        :columns="reportColumns"
        :is-loading="isLoading"
        :is-fetching="isFetching"
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
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { useQuery, keepPreviousData, isCancelledError } from '@tanstack/vue-query'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
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
import UiAlert from '@/components/ui/UiAlert.vue'
import { reportError } from '@/utils/errorReporter'
import { useReportConfig, type TabType } from './composables/useReportConfig'
import { useReportRowActions, TAB_ROW_PERMISSIONS, type ReportActionTab } from './composables/useReportRowActions'

const activeTab = ref<TabType>('order')
const page = ref(1)
const perPage = ref(15)
/** 当前排序（服务端分页不变，这是当前页内的客户端排序） */
const sort = ref<{ field: string; order: number } | null>(null)

const filters = reactive({ customer: '', product: '' })
/**
 * 已提交的筛选快照（P1-24）：queryKey 与导出读它，而非 reactive 原对象——
 * ReportFilterBar 经 defineModel 就地 mutate filters，每敲一个字符 key 就变，
 * 造成每键一次后端请求。快照只在「提交」时更新。
 */
const appliedFilters = ref({ customer: '', product: '' })

/** 提交当前筛选：快照入 key、回第 1 页（新筛选从第一页看起） */
function commitFilters() {
  appliedFilters.value = { customer: filters.customer, product: filters.product }
  page.value = 1
}

/**
 * 键入静默防抖提交（统一走 useDebouncedSearch，与 approval/customer 等视图同一口径）：
 * 连续键入只提交最终值。已显式提交后防抖才到期时，先判快照是否真有变化再提交（OCR-3 M5）：
 * 显式提交/重置后 300ms 内翻页，挂起的防抖不得把页码无条件打回第 1 页。
 */
const { debounceSearch } = useDebouncedSearch(300)
watch(filters, () => {
  debounceSearch(() => {
    if (
      filters.customer !== appliedFilters.value.customer
      || filters.product !== appliedFilters.value.product
    ) {
      commitFilters()
    }
  })
})

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

// 解构名为 queryError 而非 reportError：后者是 utils/errorReporter 导出的上报函数，
// 同名会让本文件将来一旦 import 它就变成「局部 ref 遮蔽函数」，静默丢掉上报能力。
// 进路由即查询（2026-10-23 owner 要求）：不设 enabled 门槛，挂载/切 tab 直接取数。
const { data: reportData, isLoading, isFetching, error: queryError, refetch } = useQuery({
  queryKey: ['report-data', activeTab, page, perPage, appliedFilters],
  queryFn: async () => {
    const params: Record<string, string | number> = { page: page.value, per_page: perPage.value }
    if (appliedFilters.value.customer) params.customer = appliedFilters.value.customer
    if (appliedFilters.value.product) params.product = appliedFilters.value.product
    return await reportApi[currentTabEndpoint()](params)
  },
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

/** 查询错误的用户面文案（R40）：Error 取 message，其余 String() 化兜底 */
const reportErrorMessage = computed(() => {
  const err = queryError?.value
  if (!err) return ''
  if (err instanceof Error) return err.message || '查询失败'
  return String((err as { message?: unknown }).message ?? err)
})

/**
 * F5 恢复的持久化缓存（persistQueryClient → sessionStorage）若已过期（> staleTime），
 * TanStack 会在挂载时自动重查；30s 内的快照本身仍新鲜，直接呈现即可。
 */
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

/**
 * 触发一次查询刷新，并就地消化 rejection（R22-L1 防御契约）。
 *
 * cancelRefetch: false —— refetch 由用户点击触发、与组件生命周期无关，不该被
 * 「切换 queryKey」取消；被取消的 refetch 在 query-core 里会以 Cancel 错误 reject。
 *
 * .catch 留痕是**防御**：当前 query-core 的 QueryObserver 未开 throwOnError 时用
 * catch(noop) 吞掉 rejection，该分支今天不可达。但 query-core 一旦升级到不再吞错，
 * 没有 .catch 的 refetch 就变成 unhandled rejection——控制台报错、Sentry 噪音，
 * 而用户侧毫无反馈。错误对用户的呈现统一走错误横幅（R40 单通道），这里只留痕。
 */
function refreshReport() {
  // 不假设 refetch() 一定返回 Promise：测试替身与非标准实现可能返回 undefined，
  // 直接 .catch 会抛 TypeError（并成为 unhandled rejection）。用 Promise.resolve 归一。
  void Promise.resolve(refetch({ cancelRefetch: false })).catch((e: unknown) => {
    // 取消不是应用错误：登出时 auth.ts 的 queryClient.clear() 会取消在途查询，
    // refetch 随之以 CancelledError reject。上报它会污染 Sentry，更糟的是
    // reportError 的 MAX_REPORTS=10 是与全局错误处理器共享的会话级配额——
    // 反复登出会把真正的渲染错误遥测额度挤光。故取消类只留 console，不上报。
    if (isCancelledError(e)) {
      console.error('报表刷新已取消', e)
      return
    }
    console.error('报表刷新失败', e)
    reportError(e, { scope: 'report.refreshReport' })
  })
}

function doSearch() {
  // 显式提交：同步生效不等防抖；挂起的防抖到期时快照未变 → 不再提交（M5）。
  // 条件未变也必须真的发一次请求（OCR-3 M6）：unchanged 刻意不含 page 条件——
  // page≥2 时点「查询」，commitFilters 把页码归 1 后 key 切回 page-1，若该 key
  // 在 staleTime 内有缓存，TanStack 不会自动重查，「查询」会静默吃缓存（OCR-4 M:223）。
  const unchanged =
    appliedFilters.value.customer === filters.customer
    && appliedFilters.value.product === filters.product
  commitFilters()
  if (unchanged) {
    // 页码可能从 ≥2 归 1：等 observer 切到新 key 再 refetch，
    // 避免对旧 key（page≥2）强制重查后又被 key 切换丢弃、白查一次
    void nextTick(refreshReport)
    return
  }
  // 筛选已变：queryKey 变化让 observer 重新定位并发起新查询，无需手动 refetch
  refreshReport()
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
  // 草稿与已提交快照不一致时先同步提交（OCR-4 Low:247）：「导出」与「查询」一样是
  // 显式动作，立即生效不等防抖——导出文件必须与输入框当前所见一致；提交后挂起的
  // 防抖到期发现快照已一致，自然 no-op，不会二次请求。
  if (
    filters.customer !== appliedFilters.value.customer
    || filters.product !== appliedFilters.value.product
  ) {
    commitFilters()
  }
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
