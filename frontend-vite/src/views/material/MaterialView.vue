 <template>
  <div class="mr-container">
    <div class="page-card page-card-main">
    <!-- Unified Header + Tabs -->
    <div class="mr-top-bar">
      <div class="mr-tabs">
        <button :class="['mr-tab-btn', { active: activeTab === 'progress' }]" @click="switchToProgress">
          来料进度 <span v-if="progressCount > 0" :class="['notification-badge', activeTab === 'progress' ? 'notification-badge-active' : '']">{{ progressCount }}</span>
        </button>
        <button :class="['mr-tab-btn', { active: activeTab === 'history' }]" @click="switchToHistory">
          历史查询
        </button>
        <button v-if="canManage && activeTab === 'progress'" class="mr-btn mr-btn-ghost" @click="exportData" title="导出来料进度数据"><FontAwesomeIcon icon="file-export" /> 导出</button>
        <button v-if="canManage && activeTab === 'history'" class="mr-btn mr-btn-ghost" @click="exportHistory" title="导出历史数据"><FontAwesomeIcon icon="file-export" /> 导出</button>
      </div>
    </div>

    <!-- ========== 来料进度 ========== -->
    <div v-if="activeTab === 'progress'" class="mr-content">
      <div class="mr-card">
        <div class="mr-card-b mr-card-b--flush">
          <div v-if="pIsFetching && progressRows.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>
          <UiDataTable
            :data="progressOrderRows"
            :columns="progressColumns"
            :loading="pIsLoading && !progressRows.length"
            :paginator="true"
            :rows="pPerPage"
            :total-records="pPages * pPerPage"
            row-key="order_no"
            @page="onProgressPageChange"
          >
            <template #empty>
              <div class="mr-empty"><FontAwesomeIcon icon="inbox" /><span>暂无进行中的来料登记</span></div>
            </template>
            <template #column-body-po_create_time="{ row }">
              <span class="mr-td-date">{{ row.po_create_time || '-' }}</span>
            </template>
            <template #column-body-customer_name="{ row }">
              {{ row.customer_name || '-' }}
            </template>
            <template #column-body-product_name="{ row }">
              <template v-if="row.sku_items && row.sku_items.length > 1">
                <div v-for="(sku, idx) in row.sku_items" :key="idx" class="mr-sku-line">{{ sku.product_name || '-' }}</div>
              </template>
              <span v-else class="mr-order-link">{{ row.product_name || '-' }}</span>
            </template>
            <template #column-body-product_quantity="{ row }">
              <span class="mr-td-qty">
                <template v-if="row.sku_items && row.sku_items.length > 1">
                  <div v-for="(sku, idx) in row.sku_items" :key="idx" class="mr-sku-line">{{ sku.quantity != null ? sku.quantity : '-' }}</div>
                </template>
                <template v-else>{{ row.product_quantity != null ? row.product_quantity : '-' }}</template>
              </span>
            </template>
            <template #column-body-groupedItems="{ row }">
              <div class="mr-supplier-groups">
                <div v-for="grp in row.groupedItems" :key="grp.supplierName" class="mr-supplier-group">
                  <div class="mr-supplier-label"><FontAwesomeIcon icon="truck" /><span>{{ grp.supplierName || '未指定' }}</span><span class="mr-supplier-count">{{ grp.items.length }} 项</span></div>
                  <div class="mr-items-container">
                    <div v-for="i in grp.items" :key="i.material_name" class="mr-list-item-row">
                      <span class="mr-list-item-name" :title="i.material_name">{{ i.material_name }}</span>
                      <span class="mr-list-item-qty">数量:<b>{{ parseFloat(String(i.ordered_quantity || 0)).toFixed(0) }}</b></span>
                      <span class="mr-list-item-rcv">已到货:<b>{{ parseFloat(String(i.received_quantity || 0)).toFixed(0) }}</b></span>
                      <div class="mr-list-item-bar"><div :class="['mr-sku-fill', fillClass(i)]" :style="{ width: (i.progress || 0) + '%', height: '100%', borderRadius: '5px' }"></div></div>
                      <span class="mr-list-item-pct">{{ i.progress || 0 }}%</span>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            <template #column-body-progress="{ row }">
              <div class="mr-pbar-wrap"><div class="mr-pbar"><div :class="['mr-pfill', row.progress >= 100 ? 'completed' : 'pending']" :style="{ width: (row.progress || 0) + '%' }"></div></div><span class="mr-pbar-pct">{{ row.progress || 0 }}%</span></div>
            </template>
            <template #column-body-actions="{ row }">
              <div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" @click="viewSupplierDetail(row.supplier_name || '', row.order_no)" title="查看供应商详情"><FontAwesomeIcon icon="eye" /></button></div>
            </template>
          </UiDataTable>
        </div>
      </div>
    </div>

    <!-- ========== 历史查询 ========== -->
    <div v-if="activeTab === 'history'" class="mr-content">
      <div class="mr-card">
        <div class="mr-card-b mr-card-b--flush">
          <div v-if="hIsFetching && hRegistrations.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>
          <UiDataTable
            :data="hRegistrations"
            :columns="historyColumns"
            :loading="hIsLoading && !hRegistrations.length"
            :paginator="true"
            :rows="hPerPage"
            :total-records="hPages * hPerPage"
            row-key="id"
            @page="onHistoryPageChange"
          >
            <template #empty>
              <div class="mr-empty"><FontAwesomeIcon icon="archive" /><span>暂无历史记录</span></div>
            </template>
            <template #column-body-purchase_order_no="{ row }">
              <span class="mr-td-order">{{ (row as Registration).purchase_order_no }}</span>
            </template>
            <template #column-body-customer_name="{ row }">
              {{ (row as Registration).customer_name || '-' }}
            </template>
            <template #column-body-product="{ row }">
              <span class="mr-td-small">{{ (row as Registration).product_name || '-' }}{{ (row as Registration).product_quantity ? ' x' + (row as Registration).product_quantity : '' }}</span>
            </template>
            <template #column-body-supplier_name="{ row }">
              {{ (row as Registration).supplier_name || '-' }}
            </template>
            <template #column-body-materials="{ row }">
              <span class="mr-td-small">{{ materialSummary(row as Registration) }}</span>
            </template>
            <template #column-body-update_time="{ row }">
              <span class="mr-td-small mr-td-muted">{{ (row as Registration).update_time || '-' }}</span>
            </template>
            <template #column-body-actions="{ row }">
              <div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" @click="viewDetail((row as Registration).id)" title="查看详情"><FontAwesomeIcon icon="eye" /></button></div>
            </template>
          </UiDataTable>
        </div>
      </div>
    </div>

    <!-- Detail Dialog -->
    <MaterialDetailDialog
      v-model:open="showDetailDialog"
      :detail-data="detailData"
      :can-manage="canManage"
      @open-receive="openReceive"
    />

    <!-- Supplier Detail Dialog -->
    <SupplierDialog
      v-model:open="showSupplierDialog"
      :supplier-detail="supplierDetail"
      :supplier-detail-order-no="supplierDetailOrderNo"
      :can-manage="canManage"
      @open-receive-by-sub-items="openReceiveBySubItems"
    />

    <!-- Receive Dialog -->
    <ReceiveDialog
      v-model:open="showReceiveDialog"
      :item="receiveItem"
      @submit="submitReceive"
    />

    <div :class="['mr-toast', { show: toastMsg }, toastType]"><FontAwesomeIcon :icon="toastIcon" /> {{ toastMsg }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MaterialView.vue — 来料进度管理页面
 *
 * 职责：
 * - 来料进度标签页：展示供应商-订单-物料层级的收货进度
 * - 历史查询标签页：查询已完成的来料登记记录
 * - 收货登记、供应商详情、数据导出
 */
import { ref, reactive, computed, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { materialApi } from '@/api'
import type { RegItem, Registration } from '@/api/material'
import { useAuthStore } from '@/stores/auth'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { readMaterialCache, writeMaterialCache } from '@/composables/useMaterialCache'
import type { SupMat, SupMatItem, SupGroup, SupplierDetail } from './material-types'
const MaterialDetailDialog = defineAsyncComponent(() => import('./components/MaterialDetailDialog.vue'))
const SupplierDialog = defineAsyncComponent(() => import('./components/SupplierDialog.vue'))
const ReceiveDialog = defineAsyncComponent(() => import('./components/ReceiveDialog.vue'))

// --- Internal Types ---

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('product_manage'))

const activeTab = ref('progress')

const toastMsg = ref('')
const toastType = ref('info')
const toastIcon = computed(() => ({ success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' }[toastType.value] || 'fa-info-circle'))
let toastTimer: ReturnType<typeof setTimeout> | null = null
function toast(msg: string, type = 'info') {
  toastMsg.value = msg; toastType.value = type
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastMsg.value = '' }, 3000)
}
onUnmounted(() => { if (toastTimer) clearTimeout(toastTimer) })

/** 计算完成百分比：全部到货返回 100，否则上限 99.9 */
function computePct(ordered: number, received: number): number {
  if (ordered <= 0) return 0
  if (received >= ordered) return 100
  return Math.min(Math.round(received / ordered * 100 * 10) / 10, 99.9)
}

const pPage = ref(1), pPerPage = ref(20), pPages = ref(1), pIsLoading = ref(false), pIsFetching = ref(false)
const progressRows = ref<Registration[]>([])
const pTotal = ref(0)
/** 待处理订单数（用于 tab 徽章，取后端 total 而非当前页行数） */
const progressCount = computed(() => pTotal.value)
/**
 * 模板渲染行：对每个登记按当前分类筛选客户端展示的 items。
 * 服务端已通过 material_category 筛选掉不含该分类物料的登记，
 * 但一个登记可能同时含多分类物料，这里只展示所选分类的明细行。
 *
 * groupedItems: 按物料供应商分组，便于前端按供应商分别展示物料进度。
 */
const progressOrderRows = computed(() =>
  progressRows.value.map(r => {
    // 只展示面料类(fabric)和辅料类(accessory)，填充类(filling)不显示
    const items = (r.items || []).filter(i => i.material_category !== 'filling')
    // 按 supplier_name 分组，保持供应商出现顺序
    const groupMap = new Map<string, typeof items>()
    for (const i of items) {
      const key = (i as { supplier_name?: string }).supplier_name || '未指定'
      if (!groupMap.has(key)) groupMap.set(key, [])
      groupMap.get(key)!.push(i)
    }
    // 同一供应商 + 同一物料型号(material_name)汇总显示：合并数量、按总进度计算
    const mergedGroupedItems = Array.from(groupMap, ([supplierName, items]) => {
      const mergedMap = new Map<string, typeof items[number] & { ordered_quantity: number; received_quantity: number; progress: number }>()
      for (const i of items) {
        const key = i.material_name
        const ordered = parseFloat(String(i.ordered_quantity || 0))
        const received = parseFloat(String(i.received_quantity || 0))
        const existing = mergedMap.get(key)
        if (existing) {
          existing.ordered_quantity += ordered
          existing.received_quantity += received
          existing.progress = existing.ordered_quantity > 0
            ? Math.round((existing.received_quantity / existing.ordered_quantity) * 100)
            : 0
        } else {
          const progress = ordered > 0 ? Math.round((received / ordered) * 100) : 0
          mergedMap.set(key, { ...i, ordered_quantity: ordered, received_quantity: received, progress })
        }
      }
      return { supplierName, items: Array.from(mergedMap.values()) }
    })
    return {
      ...r,
      order_no: r.purchase_order_no,
      items,
      groupedItems: mergedGroupedItems,
    }
  })
)

const hPage = ref(1), hPerPage = ref(20), hPages = ref(1), hIsLoading = ref(false), hIsFetching = ref(false)
const hRegistrations = ref<Registration[]>([])

/** 加载历史查询数据（服务端分页 + SWR 缓存） */
async function loadHistory(page = 1) {
  hPage.value = page
  const params: Record<string, string | number> = { page, per_page: hPerPage.value }

  // SWR: 先尝试从缓存渲染
  const { cached, fresh } = readMaterialCache('history', params)
  if (cached) {
    hRegistrations.value = cached.registrations || []
    hPages.value = cached.pages ?? 1
    if (fresh) {
      // 缓存未过期，直接返回，异步静默刷新
      scheduleBackgroundRefresh(() => loadHistoryFromApi(params))
      return
    }
    // 缓存已过期，先渲染旧数据，同时显示轻量进度条
    hIsFetching.value = true
  } else {
    hIsLoading.value = true
  }

  await loadHistoryFromApi(params)
}

/** 实际 API 调用（供首次加载和后台刷新复用） */
async function loadHistoryFromApi(params: Record<string, string | number>) {
  try {
    const data = await materialApi.history(params)
    hRegistrations.value = data.registrations || []
    hPages.value = data.pages ?? data.total_pages ?? 1
    // 成功时写入缓存
    writeMaterialCache('history', params, {
      registrations: data.registrations || [],
      pages: data.pages ?? data.total_pages ?? 1,
      total: data.total ?? 0,
    })
  } catch { toast('加载失败', 'error') } finally { hIsLoading.value = false; hIsFetching.value = false }
}

/** 拼接历史记录的物料名称摘要 */
function materialSummary(r: Registration) {
  const items = r.items || []
  if (!items.length) return '-'
  return items.map(i => i.material_name).join(', ')
}

/** 后台静默刷新调度器：延迟 200ms 避免阻塞首屏渲染 */
let _bgRefreshTimer: ReturnType<typeof setTimeout> | null = null
function scheduleBackgroundRefresh(fn: () => Promise<void>) {
  if (_bgRefreshTimer) clearTimeout(_bgRefreshTimer)
  _bgRefreshTimer = setTimeout(() => {
    fn().catch(() => { /* 静默刷新失败不影响已渲染内容 */ })
  }, 200)
}

/** 加载来料进度数据（服务端分页 + SWR 缓存） */
async function loadProgress(page = 1) {
  pPage.value = page
  const params: Record<string, string | number | boolean> = { page, per_page: pPerPage.value, exclude_completed: true }

  // SWR: 先尝试从缓存渲染
  const { cached, fresh } = readMaterialCache('progress', params)
  if (cached) {
    progressRows.value = cached.registrations || []
    pPages.value = cached.pages ?? 1
    pTotal.value = cached.total ?? 0
    if (fresh) {
      // 缓存未过期，直接返回，异步静默刷新
      scheduleBackgroundRefresh(() => loadProgressFromApi(params))
      return
    }
    // 缓存已过期，先渲染旧数据，同时显示轻量进度条
    pIsFetching.value = true
  } else {
    pIsLoading.value = true
  }

  await loadProgressFromApi(params)
}

/** 实际 API 调用（供首次加载和后台刷新复用） */
async function loadProgressFromApi(params: Record<string, string | number | boolean>) {
  try {
    const data = await materialApi.registrations(params)
    progressRows.value = data.registrations || []
    pPages.value = data.pages ?? data.total_pages ?? 1
    pTotal.value = data.total ?? 0
    // 成功时写入缓存
    writeMaterialCache('progress', params, {
      registrations: data.registrations || [],
      pages: data.pages ?? data.total_pages ?? 1,
      total: data.total ?? 0,
    })
  } catch { toast('加载失败', 'error') } finally { pIsLoading.value = false; pIsFetching.value = false }
}

function switchToProgress() {
  activeTab.value = 'progress'
  if (!progressRows.value.length && !pIsLoading.value) {
    // 尝试从缓存恢复，实现即时渲染
    const params: Record<string, string | number | boolean> = { page: 1, per_page: 20, exclude_completed: true }
    const { cached } = readMaterialCache('progress', params)
    if (cached) {
      progressRows.value = cached.registrations || []
      pPages.value = cached.pages ?? 1
      pTotal.value = cached.total ?? 0
      // 后台静默刷新
      scheduleBackgroundRefresh(() => loadProgressFromApi({ ...params }))
    } else {
      loadProgress(1)
    }
  }
}
function switchToHistory() {
  activeTab.value = 'history'
  if (!hRegistrations.value.length && !hIsLoading.value) {
    const params: Record<string, string | number> = { page: 1, per_page: 20 }
    const { cached } = readMaterialCache('history', params)
    if (cached) {
      hRegistrations.value = cached.registrations || []
      hPages.value = cached.pages ?? 1
      scheduleBackgroundRefresh(() => loadHistoryFromApi({ ...params }))
    } else {
      loadHistory(1)
    }
  }
}
function fillClass(item: { progress?: number; received_quantity: number | string; ordered_quantity: number | string }) { const pct = item.progress || 0; if (pct >= 100 || Number(item.received_quantity) >= Number(item.ordered_quantity)) return 'full'; return 'low' }

/** UiDataTable 列定义 */
const progressColumns: TableColumn[] = [
  { field: 'po_create_time', header: '订单时间', width: '110px', align: 'center' },
  { field: 'customer_name', header: '客户', width: '120px', align: 'center' },
  { field: 'product_name', header: '产品名称', align: 'left' },
  { field: 'product_quantity', header: '订单数量', width: '100px', align: 'center' },
  { field: 'groupedItems', header: '物料进度（按供应商分组）', align: 'left' },
  { field: 'progress', header: '总进度', width: '200px', align: 'center' },
  { field: 'actions', header: '操作', width: '80px', align: 'center' },
]
const historyColumns: TableColumn[] = [
  { field: 'purchase_order_no', header: '订单号', width: '150px', align: 'center' },
  { field: 'customer_name', header: '客户', width: '100px', align: 'center' },
  { field: 'product', header: '产品/数量', width: '120px', align: 'center' },
  { field: 'supplier_name', header: '供应商', width: '100px', align: 'center' },
  { field: 'materials', header: '物料名称', align: 'left' },
  { field: 'update_time', header: '完成时间', width: '120px', align: 'center' },
  { field: 'actions', header: '操作', width: '80px', align: 'center' },
]

/** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
function onProgressPageChange(event: { page: number; rows: number }) {
  pPerPage.value = event.rows
  loadProgress(event.page + 1)
}
function onHistoryPageChange(event: { page: number; rows: number }) {
  hPerPage.value = event.rows
  loadHistory(event.page + 1)
}

const showDetailDialog = ref(false), detailData = ref<Registration | null>(null)
/** 查看来料登记详情 */
async function viewDetail(regId: number) { try { const res = await materialApi.registrationDetail(regId); if (res.registration === undefined) { toast('加载失败', 'error'); return }; detailData.value = res.registration ?? null; showDetailDialog.value = true } catch { toast('加载失败', 'error') } }

const showSupplierDialog = ref(false), supplierDetail = ref<SupplierDetail | null>(null), supplierDetailOrderNo = ref('')
/** 查看来料详情（按供应商分组，组内按物料型号汇总） */
async function viewSupplierDetail(_supplierName: string, orderNo: string) {
  try {
    const data = await materialApi.registrations({ order_no: orderNo, per_page: 50, exclude_completed: true })
    if (!data.registrations) { toast('加载失败', 'error'); return }
    const regList: Registration[] = data.registrations
    if (!regList.length) { toast('无采购中数据', 'warning'); return }
    // 跨所有登记收集 items（过滤填充类），按 supplier_name 分组，组内按 material_name 汇总
    const supplierMap = new Map<string, Map<string, SupMat>>()
    for (const r of regList) {
      for (const i of (r.items || [])) {
        if (i.material_category === 'filling') continue
        const supName = (i as RegItem & { supplier_name?: string }).supplier_name || '未指定'
        if (!supplierMap.has(supName)) supplierMap.set(supName, new Map())
        const matMap = supplierMap.get(supName)!
        const ordered = parseFloat(String(i.ordered_quantity || 0))
        const received = parseFloat(String(i.received_quantity || 0))
        const existing = matMap.get(i.material_name)
        if (existing) {
          existing.ordered += ordered
          existing.received += received
          existing.remaining = existing.ordered - existing.received
          existing.pct = computePct(existing.ordered, existing.received)
          existing.subItems.push({ id: i.id, ordered, received })
        } else {
          matMap.set(i.material_name, {
            name: i.material_name,
            ordered,
            received,
            remaining: ordered - received,
            pct: computePct(ordered, received),
            subItems: [{ id: i.id, ordered, received }],
            unit: i.unit || '',
            spec: i.specification || '',
          })
        }
      }
    }
    let allOrdered = 0, allReceived = 0
    const supplierGroups: SupGroup[] = []
    for (const [supName, matMap] of supplierMap) {
      const items = Array.from(matMap.values())
      const oTotal = items.reduce((s, m) => s + m.ordered, 0)
      const rTotal = items.reduce((s, m) => s + m.received, 0)
      allOrdered += oTotal; allReceived += rTotal
      const allComplete = items.every(m => m.received >= m.ordered)
      supplierGroups.push({ supplierName: supName, items, totalOrdered: oTotal, totalReceived: rTotal, pct: computePct(oTotal, allComplete ? oTotal : rTotal) })
    }
    const allComplete = supplierGroups.every(g => g.items.every(m => m.received >= m.ordered))
    const totalPct = computePct(allOrdered, allComplete ? allOrdered : allReceived)
    supplierDetailOrderNo.value = orderNo
    supplierDetail.value = { supplierGroups, totalOrdered: allOrdered, totalReceived: allReceived, totalPct }; showSupplierDialog.value = true
  } catch { toast('加载失败', 'error') }
}

const showReceiveDialog = ref(false)
const receiveItem = reactive({ id: 0, subItems: [] as SupMatItem[], name: '', ordered: 0, received: 0, remaining: 0 })
function openReceive(item: RegItem) { receiveItem.id = item.id; receiveItem.subItems = [{ id: item.id, ordered: parseFloat(String(item.ordered_quantity || 0)), received: parseFloat(String(item.received_quantity || 0)) }]; receiveItem.name = item.material_name; receiveItem.ordered = parseFloat(String(item.ordered_quantity || 0)); receiveItem.received = parseFloat(String(item.received_quantity || 0)); receiveItem.remaining = receiveItem.ordered - receiveItem.received; showReceiveDialog.value = true }
function openReceiveBySubItems(subItems: SupMatItem[], name: string, ordered: number, received: number) { receiveItem.id = subItems[0]?.id || 0; receiveItem.subItems = subItems; receiveItem.name = name; receiveItem.ordered = ordered; receiveItem.received = received; receiveItem.remaining = ordered - received; showReceiveDialog.value = true }

/** 收货登记提交：按每条 item 的剩余额度切分，依次调用 API */
async function submitReceive(payload: { qty: number | null; remark: string }) {
  if (!payload.qty || payload.qty <= 0) { toast('请输入有效的收货数量', 'warning'); return }
  let remainingToReceive = payload.qty
  let totalDelta = 0
  let lastAutoCompleted = false
  try {
    for (const sub of receiveItem.subItems) {
      if (remainingToReceive <= 0) break
      const itemRemaining = sub.ordered - sub.received
      if (itemRemaining <= 0) continue
      const qtyForThisItem = Math.min(remainingToReceive, itemRemaining)
      const res = await materialApi.receive(sub.id, { received_quantity: qtyForThisItem, remark: payload.remark })
      if (!res.success) { toast(res.message || '登记失败', 'error'); return }
      lastAutoCompleted = !!res.auto_completed
      sub.received += qtyForThisItem
      totalDelta += qtyForThisItem
      remainingToReceive -= qtyForThisItem
    }
    if (remainingToReceive > 0) { toast('收货数量超过采购总量', 'warning') }
    toast(lastAutoCompleted ? '收货完成，该订单已全部到货，已转入历史记录' : '收货登记成功', lastAutoCompleted ? 'success' : 'info')
    showReceiveDialog.value = false
    const newReceived = receiveItem.received + totalDelta
    updateSupplierDialogLocally(newReceived)
    updateDetailDialogLocally(newReceived)
    loadProgress(pPage.value)
  } catch { toast('操作失败', 'error') }
}

/** 乐观更新供应商详情对话框中对应物料的收货数量与进度（含供应商级与全局汇总） */
function updateSupplierDialogLocally(newReceived: number) {
  if (!showSupplierDialog.value || !supplierDetail.value) return
  const delta = newReceived - receiveItem.received
  if (delta <= 0) return
  for (const g of supplierDetail.value.supplierGroups) {
    let groupChanged = false
    for (const m of g.items) {
      if (m.name === receiveItem.name && m.subItems.some(s => receiveItem.subItems.some(rs => rs.id === s.id))) {
        m.received += delta
        m.remaining = m.ordered - m.received
        m.pct = computePct(m.ordered, m.received)
        groupChanged = true
      }
    }
    if (groupChanged) {
      g.totalReceived = g.items.reduce((s, m) => s + m.received, 0)
      const gComplete = g.items.every(m => m.received >= m.ordered)
      g.pct = computePct(g.totalOrdered, gComplete ? g.totalOrdered : g.totalReceived)
    }
  }
  const allComplete = supplierDetail.value.supplierGroups.every(g => g.items.every(m => m.received >= m.ordered))
  supplierDetail.value.totalReceived = supplierDetail.value.supplierGroups.reduce((s, g) => s + g.items.reduce((s2, m) => s2 + m.received, 0), 0)
  supplierDetail.value.totalPct = computePct(supplierDetail.value.totalOrdered, allComplete ? supplierDetail.value.totalOrdered : supplierDetail.value.totalReceived)
}

/** 乐观更新登记详情对话框中对应物料的收货数量与进度 */
function updateDetailDialogLocally(newReceived: number) {
  if (!showDetailDialog.value || !detailData.value) return
  const dItem = (detailData.value.items || []).find((i: RegItem) => i.id === receiveItem.id)
  if (!dItem) return
  dItem.received_quantity = newReceived
  const dOrdered = parseFloat(String(dItem.ordered_quantity || 0))
  dItem.remaining_quantity = dOrdered - newReceived
  dItem.progress = computePct(dOrdered, newReceived)
}


async function exportData() {
  toast('正在导出...', 'info')
  try {
    await materialApi.export({}, '来料进度汇总.xlsx')
    toast('导出成功', 'success')
  } catch { toast('导出失败', 'error') }
}

async function exportHistory() {
  toast('正在导出...', 'info')
  try {
    await materialApi.export({}, '来料历史汇总.xlsx')
    toast('导出成功', 'success')
  } catch { toast('导出失败', 'error') }
}

onMounted(() => {
  switchToProgress()
})

onUnmounted(() => {
  if (_bgRefreshTimer) clearTimeout(_bgRefreshTimer)
})
</script>

<style scoped lang="scss">
@use './material-dialogs.scss' as *;
/* === Layout === */
.mr-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* 主卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* === Top Bar (Header + Tabs unified) === */
.mr-top-bar {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 0;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  box-shadow: none;
  margin-bottom: 0;
  gap: 12px;
  flex-shrink: 0;
}

/* === Tabs === */
.mr-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.mr-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all 0.3s ease;
}

.mr-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.mr-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* === Content area === */
.mr-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 24px 24px;
}

/* === Cards === */
.mr-card {
  background: white;
  border-radius: 14px;
  margin-bottom: 18px;
  overflow: hidden;
}

.mr-card-b {
  padding: 24px;
}

.mr-card-b--flush {
  padding: 0;
  overflow-x: auto;
}

/* === Table === */
.mr-td-bold { font-size: 14px; font-weight: 600; }
.mr-td-order { font-family: 'Courier New', monospace; font-weight: 600; color: var(--color-primary-500); font-size: 14px; }
.mr-td-small { font-size: 13px; }
.mr-td-muted { color: var(--color-text-muted); }

/* 每个订单（行）之间显示分割线 */
.mr-card-b--flush :deep(.p-datatable-tbody > tr) {
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.mr-order-link {
  font-size: 14px;
  color: var(--color-text);
}

.mr-sku-line {
  font-size: 14px;
  color: var(--color-text);
  padding: 2px 0;
  line-height: 1.4;
}
.mr-sku-line + .mr-sku-line {
  border-top: 1px dashed var(--color-border, #e5e7eb);
}

.mr-td-qty {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.mr-td-date {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* 供应商分组容器 */
.mr-supplier-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mr-supplier-group {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 6px;
  background: var(--color-surface, #f8fafc);
  overflow: hidden;
}

.mr-supplier-label {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-primary-50, #eff6ff);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-700, #1d4ed8);
}

.mr-supplier-label i {
  font-size: 11px;
}

.mr-supplier-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #94a3b8);
}

.mr-supplier-group .mr-items-container {
  padding: 4px 8px;
  background: white;
}

/* === Item List === */
.mr-items-container { min-width: 500px; }

.mr-list-item-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.15s ease;
}

.mr-list-item-row:last-child { margin-bottom: 0; }
.mr-list-item-row:hover { background: var(--color-primary-50, #eff6ff); }

.mr-list-item-name { font-size: 13px; width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; flex-shrink: 0; }
.mr-list-item-qty { font-size: 12px; color: var(--color-text-secondary); white-space: nowrap; width: 105px; flex-shrink: 0; }
.mr-list-item-rcv { font-size: 12px; color: var(--color-success-600, #059669); white-space: nowrap; width: 115px; flex-shrink: 0; }
.mr-list-item-bar { flex: 1; height: 10px; background: #E5E7EB; border-radius: 8px; min-width: 60px; }
.mr-list-item-pct { font-size: 12px; color: var(--color-text-muted); width: 50px; flex-shrink: 0; text-align: right; }

/* === Progress Bar === */
.mr-pbar-wrap { display: flex; align-items: center; gap: 8px; }

.mr-pbar { width: 160px; height: 10px; background: #E5E7EB; border-radius: 8px; overflow: hidden; }

.mr-pfill { height: 100%; border-radius: 8px; transition: width 0.5s ease; }
.mr-pfill.pending { background: var(--color-warning-500, #FF9F43); }
.mr-pfill.partial { background: var(--color-primary-500, #5B8DEF); }
.mr-pfill.completed { background: var(--color-success-500, #28C76F); }

.mr-pbar-pct { font-size: 13px; color: var(--color-text-secondary); }

/* === Action Buttons === */
.mr-action-group { display: flex; gap: 6px; }

.mr-action-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: all 0.2s ease;
  cursor: pointer;
}

.mr-action-view {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.mr-action-view:hover {
  background: var(--color-primary-500);
  color: white;
  transform: translateY(-1px);
}

/* === Badge === */
.mr-badge {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
}

.mr-badge-pending { background: #FEF3C7; color: #D97706; }
.mr-badge-partial { background: var(--color-primary-50, #E8F2FF); color: var(--color-primary-600, #4A7DE8); }
.mr-badge-completed { background: #D1FAE5; color: #059669; }
.mr-badge-overdue { background: #FEE2E2; color: #DC2626; }

/* === SKU Fill Colors === */
.mr-sku-fill.full { background: var(--color-success-500, #28C76F); }
.mr-sku-fill.half { background: var(--color-primary-500, #5B8DEF); }
.mr-sku-fill.low { background: var(--color-warning-500, #FF9F43); }
.mr-sku-fill.zero { background: #E5E7EB; }

.mr-sku-bar { height: 10px; background: #E5E7EB; border-radius: 8px; overflow: hidden; margin-bottom: 10px; }

/* === Empty State === */
.mr-empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.mr-empty i { font-size: 28px; opacity: 0.5; }

/* Fetching progress bar */
.mr-fetching-bar {
  padding: 0 !important;
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
}
.mr-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: mr-progress-slide 1s ease-in-out infinite;
}
@keyframes mr-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.mr-empty-inline {
  grid-column: 1 / -1;
  text-align: center;
  padding: 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

/* === Pagination === */

/* === Material Detail Card (Dialog) 特有部分 === */
.mr-det-mat-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 0 0 140px;
}
.mr-det-mat-metrics {
  display: flex;
  gap: 8px;
  flex: 1;
  justify-content: center;
}
.mr-det-mat-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 16px;
  background: white;
  border-radius: 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  min-width: 72px;
}
.mr-det-mat-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #94a3b8);
}
.mr-det-mat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text, #1e293b);
  line-height: 1.2;
}
.mr-det-mat-value.received { color: var(--color-success-500, #28C76F); }
.mr-det-mat-value.remaining { color: var(--color-warning-500, #FF9F43); }
.mr-det-mat-value.completed { color: var(--color-success-500, #28C76F); }
.mr-det-mat-value.half { color: var(--color-primary-500, #5B8DEF); }
.mr-det-mat-value.low { color: var(--color-warning-500, #FF9F43); }
.mr-det-mat-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  min-width: 180px;
  justify-content: flex-end;
}
.mr-det-mat-status {
  flex-shrink: 0;
}
.mr-status-completed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-success-600, #059669);
  background: var(--color-success-50, #f0fdf4);
  padding: 5px 12px;
  border-radius: 20px;
  border: 1px solid var(--color-success-200, #bbf7d0);
}
.mr-status-pending {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb);
  padding: 5px 12px;
  border-radius: 20px;
  border: 1px solid var(--color-warning-200, #fde68a);
}
.mr-det-mat-action {
  flex-shrink: 0;
}
.mr-det-mat-action .mr-btn-success {
  font-size: 12px;
  padding: 7px 16px;
  border-radius: 8px;
  white-space: nowrap;
}

/* === Toast === */
.mr-toast {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 12px 20px;
  border-radius: 10px;
  color: white;
  font-size: 14px;
  z-index: 2000;
  display: none;
  animation: mrSlide 0.3s ease;
}

.mr-toast.show { display: flex; align-items: center; gap: 8px; }
.mr-toast.success { background: var(--color-success-500, #28C76F); }
.mr-toast.error { background: var(--color-danger-500, #EA5456); }
.mr-toast.warning { background: var(--color-warning-500, #FF9F43); }
.mr-toast.info { background: var(--color-primary-500, #5B8DEF); }

@keyframes mrSlide { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* === Responsive === */
@media (max-width: 768px) {
  .mr-top-bar { flex-direction: column; gap: 12px; align-items: flex-start; }
  .mr-det-grid { grid-template-columns: 1fr; }
  .mr-det-mat-row { flex-wrap: wrap; gap: 12px; padding: 12px; }
  .mr-det-mat-info { flex: 0 0 120px; }
  .mr-det-mat-metrics { flex-wrap: wrap; gap: 6px; }
  .mr-det-mat-metric { min-width: 65px; padding: 8px 12px; }
  .mr-det-mat-value { font-size: 16px; }
}
</style>
