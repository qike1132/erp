 <template>
  <div class="mr-container">
    <div class="page-card page-card-main">
    <!-- Unified Header + Tabs -->
    <div class="mr-top-bar">
      <div class="mr-top-left">
        <HeaderTabs />
      </div>
      <div class="mr-top-right">
        <div class="mr-tabs">
          <button :class="['mr-tab-btn', { active: activeTab === 'progress' }]" @click="switchToProgress">
            来料进度 <span v-if="progressCount > 0" :class="['notification-badge', activeTab === 'progress' ? 'notification-badge-active' : '']">{{ progressCount }}</span>
          </button>
          <button :class="['mr-tab-btn', { active: activeTab === 'history' }]" @click="switchToHistory">
            历史查询
          </button>
          <button v-if="canManage && activeTab === 'progress'" class="mr-btn mr-btn-ghost" @click="exportData" title="导出来料进度数据"><i class="fas fa-file-export" /> 导出</button>
          <button v-if="canManage && activeTab === 'history'" class="mr-btn mr-btn-ghost" @click="exportHistory" title="导出历史数据"><i class="fas fa-file-export" /> 导出</button>
        </div>
      </div>
    </div>

    <!-- ========== 来料进度 ========== -->
    <div v-if="activeTab === 'progress'" class="mr-content">
      <div class="mr-filters">
        <div class="mr-fg"><label>供应商</label><input type="text" v-model="pFilters.supplier" placeholder="搜索..." @keyup.enter="loadProgress(1)"></div>
        <div class="mr-fg"><label>订单号</label><input type="text" v-model="pFilters.orderNo" placeholder="搜索..." @keyup.enter="loadProgress(1)"></div>
        <div class="mr-fg"><label>客户</label><input type="text" v-model="pFilters.customer" placeholder="搜索..." @keyup.enter="loadProgress(1)"></div>
        <div class="mr-fg"><label>分类</label><select v-model="pFilters.category" @change="loadProgress(1)"><option value="">全部</option><option value="fabric">面料</option><option value="filling">填充</option><option value="accessory">辅料</option><option value="packaging">包装</option></select></div>
        <div class="mr-fg"><label>日期</label><UiDatePicker v-model="pFilters.startDate" @update:model-value="loadProgress(1)" /><span class="mr-date-sep">~</span><UiDatePicker v-model="pFilters.endDate" @update:model-value="loadProgress(1)" /></div>
        <button class="mr-btn mr-btn-ghost" @click="resetProgressFilters"><i class="fas fa-redo" /> 重置</button>
      </div>
      <div class="mr-card">
        <div class="mr-card-b mr-card-b--flush">
          <table class="mr-tbl" style="min-width:1000px;">
            <thead><tr><th style="width:110px;">订单时间</th><th style="width:120px;">客户</th><th>产品名称</th><th style="width:100px;">订单数量</th><th>物料进度（按供应商分组）</th><th style="width:200px;">总进度</th><th style="width:80px;">操作</th></tr></thead>
            <tbody>
              <tr v-if="pIsLoading && !progressRows.length"><td colspan="7" class="mr-empty"><UiSpinner /></td></tr>
              <tr v-else-if="!progressRows.length"><td colspan="7" class="mr-empty"><i class="fas fa-inbox" /><span>暂无进行中的来料登记</span></td></tr>
              <tr v-if="pIsFetching && progressRows.length"><td colspan="7" class="mr-fetching-bar"><div class="mr-fetching-progress" /></td></tr>
              <tr v-for="row in progressOrderRows" :key="row.order_no" class="mr-order-row">
                <td class="mr-td-date">{{ row.po_create_time || '-' }}</td>
                <td>{{ row.customer_name || '-' }}</td>
                <td>
                  <template v-if="row.sku_items && row.sku_items.length > 1">
                    <div v-for="(sku, idx) in row.sku_items" :key="idx" class="mr-sku-line">{{ sku.product_name || '-' }}</div>
                  </template>
                  <span v-else class="mr-order-link">{{ row.product_name || '-' }}</span>
                </td>
                <td class="mr-td-qty">
                  <template v-if="row.sku_items && row.sku_items.length > 1">
                    <div v-for="(sku, idx) in row.sku_items" :key="idx" class="mr-sku-line">{{ sku.quantity != null ? sku.quantity : '-' }}</div>
                  </template>
                  <template v-else>{{ row.product_quantity != null ? row.product_quantity : '-' }}</template>
                </td>
                <td>
                  <div class="mr-supplier-groups">
                    <div v-for="grp in row.groupedItems" :key="grp.supplierName" class="mr-supplier-group">
                      <div class="mr-supplier-label"><i class="fas fa-truck" /><span>{{ grp.supplierName || '未指定' }}</span><span class="mr-supplier-count">{{ grp.items.length }} 项</span></div>
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
                </td>
                <td><div class="mr-pbar-wrap"><div class="mr-pbar"><div :class="['mr-pfill', row.progress >= 100 ? 'completed' : 'pending']" :style="{ width: (row.progress || 0) + '%' }"></div></div><span class="mr-pbar-pct">{{ row.progress || 0 }}%</span></div></td>
                <td><div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" @click="viewSupplierDetail(row.supplier_name || '', row.order_no)" title="查看供应商详情"><i class="fas fa-eye" /></button></div></td>
              </tr>
            </tbody>
          </table>
          <UiPagination v-if="pPages > 1" :current-page="pPage" :total-pages="pPages" @update:current-page="loadProgress" />
        </div>
      </div>
    </div>

    <!-- ========== 历史查询 ========== -->
    <div v-if="activeTab === 'history'" class="mr-content">
      <div class="mr-filters">
        <div class="mr-fg"><label>订单号</label><input type="text" v-model="hFilters.orderNo" placeholder="搜索..." @keyup.enter="loadHistory(1)"></div>
        <div class="mr-fg"><label>供应商</label><input type="text" v-model="hFilters.supplier" placeholder="搜索..." @keyup.enter="loadHistory(1)"></div>
        <div class="mr-fg"><label>客户</label><input type="text" v-model="hFilters.customer" placeholder="搜索..." @keyup.enter="loadHistory(1)"></div>
        <div class="mr-fg"><label>分类</label><select v-model="hFilters.category" @change="loadHistory(1)"><option value="">全部</option><option value="fabric">面料</option><option value="filling">填充</option><option value="accessory">辅料</option><option value="packaging">包装</option></select></div>
        <div class="mr-fg"><label>完成日期</label><UiDatePicker v-model="hFilters.startDate" @update:model-value="loadHistory(1)" /><span class="mr-date-sep">~</span><UiDatePicker v-model="hFilters.endDate" @update:model-value="loadHistory(1)" /></div>
        <button class="mr-btn mr-btn-ghost" @click="resetHistoryFilters"><i class="fas fa-redo" /> 重置</button>
      </div>
      <div class="mr-card">
        <div class="mr-card-b mr-card-b--flush">
          <table class="mr-tbl" style="min-width:900px;">
            <thead><tr><th style="width:150px;">订单号</th><th style="width:100px;">客户</th><th style="width:120px;">产品/数量</th><th style="width:100px;">供应商</th><th>物料名称</th><th style="width:120px;">完成时间</th><th style="width:80px;">操作</th></tr></thead>
            <tbody>
              <tr v-if="hIsLoading && !hRegistrations.length"><td colspan="7" class="mr-empty"><UiSpinner /></td></tr>
              <tr v-else-if="!hRegistrations.length"><td colspan="7" class="mr-empty"><i class="fas fa-archive" /><span>暂无历史记录</span></td></tr>
              <tr v-if="hIsFetching && hRegistrations.length"><td colspan="7" class="mr-fetching-bar"><div class="mr-fetching-progress" /></td></tr>
              <tr v-for="r in hRegistrations" :key="r.id">
                <td class="mr-td-order">{{ r.purchase_order_no }}</td>
                <td>{{ r.customer_name || '-' }}</td>
                <td class="mr-td-small">{{ r.product_name || '-' }}{{ r.product_quantity ? ' x' + r.product_quantity : '' }}</td>
                <td>{{ r.supplier_name || '-' }}</td>
                <td class="mr-td-small">{{ materialSummary(r) }}</td>
                <td class="mr-td-small mr-td-muted">{{ r.update_time || '-' }}</td>
                <td><div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" @click="viewDetail(r.id)" title="查看详情"><i class="fas fa-eye" /></button></div></td>
              </tr>
            </tbody>
          </table>
          <UiPagination v-if="hPages > 1" :current-page="hPage" :total-pages="hPages" @update:current-page="loadHistory" />
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

    <div :class="['mr-toast', { show: toastMsg }, toastType]"><i :class="['fas', toastIcon]"></i> {{ toastMsg }}</div>
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
import UiPagination from '@/components/ui/UiPagination.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
const MaterialDetailDialog = defineAsyncComponent(() => import('./components/MaterialDetailDialog.vue'))
const SupplierDialog = defineAsyncComponent(() => import('./components/SupplierDialog.vue'))
const ReceiveDialog = defineAsyncComponent(() => import('./components/ReceiveDialog.vue'))

// --- Internal Types ---

interface SupMatItem {
  id: number
  ordered: number
  received: number
}

interface SupMat {
  name: string
  ordered: number
  received: number
  remaining: number
  pct: number
  /** 同物料合并的所有 item 详情（含 id、ordered、received，用于按额度切分收货） */
  subItems: SupMatItem[]
  unit: string
  spec: string
}

interface SupGroup {
  supplierName: string
  items: SupMat[]
  totalOrdered: number
  totalReceived: number
  pct: number
}

interface SupplierDetail {
  supplierGroups: SupGroup[]
  totalOrdered: number
  totalReceived: number
  totalPct: number
}

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

const pPage = ref(1), pPages = ref(1), pIsLoading = ref(false), pIsFetching = ref(false)
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
    const filteredItems = pFilters.category
      ? items.filter(i => i.material_category === pFilters.category)
      : items
    // 按 supplier_name 分组，保持供应商出现顺序
    const groupMap = new Map<string, typeof filteredItems>()
    for (const i of filteredItems) {
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
      items: filteredItems,
      groupedItems: mergedGroupedItems,
    }
  })
)
const pFilters = reactive({ supplier: '', orderNo: '', customer: '', category: '', startDate: '', endDate: '' })

const hPage = ref(1), hPages = ref(1), hIsLoading = ref(false), hIsFetching = ref(false)
const hRegistrations = ref<Registration[]>([])
const hFilters = reactive({ orderNo: '', supplier: '', customer: '', category: '', startDate: '', endDate: '' })

/** 加载历史查询数据（服务端分页 + 筛选） */
async function loadHistory(page = 1) {
  hPage.value = page
  const isInitial = hRegistrations.value.length === 0
  if (isInitial) hIsLoading.value = true
  else hIsFetching.value = true
  try {
    const params: Record<string, string | number> = { page, per_page: 20 }
    if (hFilters.orderNo) params.order_no = hFilters.orderNo
    if (hFilters.supplier) params.supplier = hFilters.supplier
    if (hFilters.customer) params.customer_name = hFilters.customer
    if (hFilters.category) params.material_category = hFilters.category
    if (hFilters.startDate) params.start_date = hFilters.startDate
    if (hFilters.endDate) params.end_date = hFilters.endDate
    const data = await materialApi.history(params)
    hRegistrations.value = data.registrations || []
    hPages.value = data.pages ?? data.total_pages ?? 1
  } catch { toast('加载失败', 'error') } finally { hIsLoading.value = false; hIsFetching.value = false }
}

/** 重置历史筛选条件并重新加载 */
function resetHistoryFilters() { Object.assign(hFilters, { orderNo: '', supplier: '', customer: '', category: '', startDate: '', endDate: '' }); loadHistory(1) }

/** 拼接历史记录的物料名称摘要 */
function materialSummary(r: Registration) {
  const items = r.items || []
  if (!items.length) return '-'
  return items.map(i => i.material_name).join(', ')
}

/** 加载来料进度数据（服务端分页 + 筛选 + 服务端排除已完成） */
async function loadProgress(page = 1) {
  pPage.value = page
  const isInitial = progressRows.value.length === 0
  if (isInitial) pIsLoading.value = true
  else pIsFetching.value = true
  try {
    const params: Record<string, string | number | boolean> = { page, per_page: 20, exclude_completed: true }
    if (pFilters.supplier) params.supplier = pFilters.supplier
    if (pFilters.orderNo) params.order_no = pFilters.orderNo
    if (pFilters.customer) params.customer_name = pFilters.customer
    if (pFilters.category) params.material_category = pFilters.category
    if (pFilters.startDate) params.start_date = pFilters.startDate
    if (pFilters.endDate) params.end_date = pFilters.endDate
    const data = await materialApi.registrations(params)
    progressRows.value = data.registrations || []
    pPages.value = data.pages ?? data.total_pages ?? 1
    pTotal.value = data.total ?? 0
  } catch { toast('加载失败', 'error') } finally { pIsLoading.value = false; pIsFetching.value = false }
}

function resetProgressFilters() { Object.assign(pFilters, { supplier: '', orderNo: '', customer: '', category: '', startDate: '', endDate: '' }); loadProgress(1) }
function switchToProgress() { activeTab.value = 'progress'; if (!progressRows.value.length && !pIsLoading.value) loadProgress(1) }
function switchToHistory() { activeTab.value = 'history'; if (!hRegistrations.value.length && !hIsLoading.value) loadHistory(1) }
function fillClass(item: { progress?: number; received_quantity: number | string; ordered_quantity: number | string }) { const pct = item.progress || 0; if (pct >= 100 || Number(item.received_quantity) >= Number(item.ordered_quantity)) return 'full'; return 'low' }

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
    const res = await materialApi.export({
      order_no: pFilters.orderNo,
      supplier: pFilters.supplier,
      customer_name: pFilters.customer,
      material_category: pFilters.category,
      start_date: pFilters.startDate,
      end_date: pFilters.endDate,
    })
    if (res.success && res.html) {
      const blob = new Blob([res.html], { type: 'application/vnd.ms-excel' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = '来料进度汇总.xls'
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast('导出成功', 'success')
    } else toast('导出失败', 'error')
  } catch { toast('导出失败', 'error') }
}

async function exportHistory() {
  toast('正在导出...', 'info')
  try {
    const res = await materialApi.export({
      order_no: hFilters.orderNo,
      supplier: hFilters.supplier,
      customer_name: hFilters.customer,
      material_category: hFilters.category,
      start_date: hFilters.startDate,
      end_date: hFilters.endDate,
    })
    if (res.success && res.html) {
      const blob = new Blob([res.html], { type: 'application/vnd.ms-excel' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = '来料历史汇总.xls'
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast('导出成功', 'success')
    } else toast('导出失败', 'error')
  } catch { toast('导出失败', 'error') }
}

onMounted(() => {
  switchToProgress()
})
</script>

<style scoped>
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
.mr-top-bar :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.mr-top-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
}

.mr-top-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 24px;
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

/* === Filters === */
.mr-filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }

.mr-fg {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mr-fg label { font-size: 12px; color: var(--color-text-secondary); white-space: nowrap; font-weight: 600; }

.mr-fg select,
.mr-fg input {
  padding: 7px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  min-width: 110px;
  transition: all 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
}

.mr-fg select:focus,
.mr-fg input:focus {
  outline: none;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}

.mr-date-sep { color: var(--color-text-muted); font-size: 13px; }

/* === Buttons === */
.mr-btn {
  padding: 7px 14px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.mr-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  transform: translateY(-1px);
}

.mr-btn-ghost {
  border-color: var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
}

.mr-btn-ghost:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.mr-btn-success {
  border-color: var(--color-success-200, #A7F3D0);
  color: var(--color-success-600, #059669);
  background: var(--color-success-50, #ECFDF5);
}

.mr-btn-success:hover {
  background: var(--color-success-500, #28C76F);
  color: white;
  border-color: transparent;
}

.mr-btn-sm { padding: 5px 10px; font-size: 11px; }

/* === Table === */
.mr-tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: auto;
}

.mr-tbl th {
  background: var(--color-surface, #f8fafc);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
}

.mr-tbl td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
}

.mr-tbl { border-collapse: separate; border-spacing: 0 8px; }

.mr-tbl thead tr th { border-bottom: 2px solid var(--color-border-light, #e2e8f0); }

.mr-tbl tbody tr.mr-order-row {
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  background: white;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

.mr-tbl tbody tr.mr-order-row:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
  border-color: #93c5fd;
}

.mr-tbl tbody tr.mr-order-row:hover td:first-child {
  border-left-color: #93c5fd;
}

.mr-tbl tbody tr.mr-order-row:hover td:last-child {
  border-right-color: #93c5fd;
}

.mr-tbl tbody tr.mr-order-row td {
  background: white;
  border-top: none;
  border-bottom: none;
  border-left: none;
  border-right: none;
}

.mr-tbl tbody tr.mr-order-row td:first-child { border-left: 1px solid var(--color-border-light); border-radius: 12px 0 0 12px; }
.mr-tbl tbody tr.mr-order-row td:last-child { border-right: 1px solid var(--color-border-light); border-radius: 0 12px 12px 0; }

.mr-tbl tbody tr:last-child td { border-bottom: none; }

.mr-td-bold { font-size: 14px; font-weight: 600; }
.mr-td-order { font-family: 'Courier New', monospace; font-weight: 600; color: var(--color-primary-500); font-size: 14px; }
.mr-td-small { font-size: 13px; }
.mr-td-muted { color: var(--color-text-muted); }

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
/* === Dialog Form Fields === */
.mr-fg2 { margin-bottom: 16px; }
.mr-fg2 label { display: block; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
.mr-fg2 input,
.mr-fg2 select,
.mr-fg2 textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: all 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
}

.mr-fg2 input:focus,
.mr-fg2 select:focus,
.mr-fg2 textarea:focus {
  outline: none;
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}

/* === Detail Grid === */
.mr-det-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.mr-det-lb { font-size: 12px; color: var(--color-text-muted); margin-bottom: 6px; }
.mr-det-vl { font-size: 15px; font-weight: 600; color: var(--color-text); }

/* === Preview Dialog Sections === */
.mr-preview-section-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}
.mr-preview-section-label i {
  font-size: 13px;
  color: var(--color-primary-500);
}
.mr-preview-count {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-text-muted);
  margin-left: 4px;
}
.mr-source-section {
  margin-bottom: 16px;
}
.mr-source-card {
  padding: 14px 16px;
  background: linear-gradient(135deg, var(--color-success-50, #ECFDF5), var(--color-surface, #f8fafc));
  border: 1px solid var(--color-success-200, #A7F3D0);
  border-radius: 12px;
  margin-bottom: 8px;
}
.mr-source-card:last-child {
  margin-bottom: 0;
}

.mr-item-tbl { width: 100%; border-collapse: collapse; }
.mr-item-tbl th { background: var(--color-surface, #f8fafc); padding: 10px 12px; font-size: 12px; text-align: left; }
.mr-item-tbl td { padding: 10px 12px; border-bottom: 1px solid var(--color-border-light, #e2e8f0); font-size: 13px; }

/* === SKU Row (Dialog) === */
.mr-sku-row {
  background: #FAFBFC;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
}

.mr-sku-row:hover { border-color: var(--color-primary-300); background: var(--color-primary-50, #eff6ff); }

.mr-sku-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.mr-sku-name { font-weight: 600; color: var(--color-text); font-size: 15px; }
.mr-sku-spec { font-size: 13px; color: var(--color-text-secondary); margin-left: 10px; }
.mr-sku-pct { font-size: 14px; font-weight: 600; }
.mr-sku-info { display: flex; gap: 20px; font-size: 13px; color: var(--color-text-secondary); flex-wrap: wrap; align-items: center; }
.mr-sku-info span b { color: var(--color-text); font-weight: 600; }

/* === Material Detail Card (Dialog) === */
.mr-det-mat-card {
  margin-bottom: 10px;
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border-radius: 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  transition: all 0.2s ease;
  overflow: hidden;
}
.mr-det-mat-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  border-color: var(--color-primary-200, #bfdbfe);
}
.mr-det-mat-row {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.mr-det-mat-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 0 0 140px;
}
.mr-det-mat-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text, #1e293b);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
.mr-det-mat-spec {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-secondary, #64748b);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--color-surface, #f1f5f9);
  padding: 2px 8px;
  border-radius: 6px;
  width: fit-content;
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
  .mr-filters { flex-direction: column; align-items: stretch; }
  .mr-fg { width: 100%; }
  .mr-top-bar { flex-direction: column; gap: 12px; align-items: flex-start; }
  .mr-det-grid { grid-template-columns: 1fr; }
  .mr-det-mat-row { flex-wrap: wrap; gap: 12px; padding: 12px; }
  .mr-det-mat-info { flex: 0 0 120px; }
  .mr-det-mat-metrics { flex-wrap: wrap; gap: 6px; }
  .mr-det-mat-metric { min-width: 65px; padding: 8px 12px; }
  .mr-det-mat-value { font-size: 16px; }
}
</style>
