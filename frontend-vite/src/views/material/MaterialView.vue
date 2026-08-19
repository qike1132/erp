 <template>
  <div class="mr-container">
    <div class="page-card page-card-main">
    <!-- Unified Header + Tabs -->
    <div class="mr-top-bar">
      <div class="mr-tabs">
        <button :class="['mr-tab-btn', { active: activeTab === 'progress' }]" @click="switchToProgress" aria-label="来料进度 0' :class='['notification-badge', a">
          来料进度 <span v-if="progressCount > 0" :class="['notification-badge', activeTab === 'progress' ? 'notification-badge-active' : '']">{{ progressCount }}</span>
        </button>
        <button :class="['mr-tab-btn', { active: activeTab === 'history' }]" @click="switchToHistory" aria-label="历史查询">
          历史查询
        </button>
        <button v-if="canManage && activeTab === 'progress'" class="mr-btn mr-btn-ghost" @click="exportData" title="导出来料进度数据" aria-label="导出"><FontAwesomeIcon icon="file-export" /> 导出</button>
        <button v-if="canManage && activeTab === 'history'" class="mr-btn mr-btn-ghost" @click="exportHistory" title="导出历史数据" aria-label="导出"><FontAwesomeIcon icon="file-export" /> 导出</button>
      </div>
    </div>

    <!-- ========== 来料进度（子组件化，模板与列定义原样搬移） ========== -->
    <ProgressTab
      v-if="activeTab === 'progress'"
      :progress-order-rows="progressOrderRows"
      :progress-rows="progressRows"
      :p-is-loading="pIsLoading"
      :p-is-fetching="pIsFetching"
      :p-per-page="pPerPage"
      :p-pages="pPages"
      @page="onProgressPageChange"
      @view-supplier="viewSupplierDetail"
    />

    <!-- ========== 历史查询（子组件化，模板与列定义原样搬移） ========== -->
    <HistoryTab
      v-if="activeTab === 'history'"
      :h-registrations="hRegistrations"
      :h-is-loading="hIsLoading"
      :h-is-fetching="hIsFetching"
      :h-per-page="hPerPage"
      :h-pages="hPages"
      @page="onHistoryPageChange"
      @view-detail="viewDetail"
    />

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
 * - 来料进度标签页：展示供应商-订单-物料层级的收货进度（ProgressTab）
 * - 历史查询标签页：查询已完成的来料登记记录（HistoryTab）
 * - 收货登记、供应商详情、数据导出
 * - 数据加载 / SWR 缓存逻辑抽至 composables/useMaterialRegistrations.ts
 */
import { ref, reactive, computed, onMounted, defineAsyncComponent } from 'vue'
import { materialApi } from '@/api'
import type { RegItem, Registration } from '@/api/material'
import { useAuthStore } from '@/stores/auth'
import { useExport } from '@/composables/useExport'
import type { SupMat, SupMatItem, SupGroup, SupplierDetail } from './material-types'
import { useMaterialRegistrations } from './composables/useMaterialRegistrations'
import ProgressTab from './components/ProgressTab.vue'
import HistoryTab from './components/HistoryTab.vue'
const MaterialDetailDialog = defineAsyncComponent(() => import('./components/MaterialDetailDialog.vue'))
const SupplierDialog = defineAsyncComponent(() => import('./components/SupplierDialog.vue'))
const ReceiveDialog = defineAsyncComponent(() => import('./components/ReceiveDialog.vue'))

// --- Internal Types ---

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('product_manage'))

const activeTab = ref('progress')

// 数据加载 / SWR 缓存 / 后台刷新 / 页内 toast（原文件逻辑抽至 composable，行为不变）
const {
  toastMsg, toastType, toastIcon, toast,
  pPage, pPerPage, pPages, pIsLoading, pIsFetching, progressRows, progressCount, progressOrderRows,
  hPerPage, hPages, hIsLoading, hIsFetching, hRegistrations,
  loadProgress, ensureProgressLoaded, ensureHistoryLoaded,
  onProgressPageChange, onHistoryPageChange,
} = useMaterialRegistrations()

/** 计算完成百分比：全部到货返回 100，否则上限 99.9 */
function computePct(ordered: number, received: number): number {
  if (ordered <= 0) return 0
  if (received >= ordered) return 100
  return Math.min(Math.round(received / ordered * 100 * 10) / 10, 99.9)
}

function switchToProgress() {
  activeTab.value = 'progress'
  ensureProgressLoaded()
}
function switchToHistory() {
  activeTab.value = 'history'
  ensureHistoryLoaded()
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

const { runExport } = useExport()

function exportData() {
  runExport(() => materialApi.export({}, '来料进度汇总.xlsx'))
}

function exportHistory() {
  runExport(() => materialApi.export({}, '来料历史汇总.xlsx'))
}

onMounted(() => {
  switchToProgress()
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
}
</style>
