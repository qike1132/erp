<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：Tab 导航 + 页头动作组（状态切换/导出打印/批量发货 与 TAB 同行，用户裁决） -->
      <div class="page-card-header">
        <HubeiRouteTabs />
        <OutsourceShipmentActions
          :shipped-count="shippedCount"
          :received-count="receivedCount"
          :status-filter="statusFilter"
          :exporting="exporting"
          :unshipped-loading="unshippedLoading"
          :can-ship="canShip && !isBeile"
          @set-status="setStatus"
          @export="handleExport"
          @print="handlePrint"
          @ship="shipOpen = true"
        />
      </div>

      <!-- 内容区：发货单列表 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <OutsourceShipmentStrip
            :shipped-count="shippedCount"
            :unshipped-qty="unshippedQty"
          />
          <div class="osv-body">
            <div v-if="loading && shipments.length === 0" class="osv-empty">
              <UiSpinner />
            </div>
            <div v-else-if="shipments.length === 0" class="osv-empty">
              <FontAwesomeIcon icon="truck-fast" aria-hidden="true" />
              <span>暂无{{ statusFilter === 'shipped' ? '待收货' : '已完成' }}发货单</span>
            </div>
            <template v-else>
              <div v-if="isFetching" class="osv-fetching-bar"><div class="osv-fetching-progress" /></div>
              <div class="osv-table-wrap">
                <table class="osv-table">
                  <thead>
                    <tr>
                      <th class="osv-th-center" style="width: 170px;">发货单号</th>
                      <th class="osv-th-center" style="width: 150px;">发货时间</th>
                      <th class="osv-th-center" style="width: 90px;">明细数</th>
                      <th class="osv-th-center" style="width: 90px;">发货总量</th>
                      <th class="osv-th-center" style="width: 100px;">状态</th>
                      <th class="osv-th-center" style="width: 190px;">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="s in shipments" :key="s.id">
                      <td class="osv-td-center osv-td-nowrap osv-td-mono">{{ s.shipment_no }}</td>
                      <td class="osv-td-center osv-td-nowrap">{{ s.shipped_at || '-' }}</td>
                      <td class="osv-td-center">{{ s.item_count }}</td>
                      <td class="osv-td-center"><strong>{{ (s.total_shipped || 0).toLocaleString() }}</strong></td>
                      <td class="osv-td-center">
                        <span :class="['osv-status-badge', statusClass(s.status)]">{{ statusLabel(s.status) }}</span>
                      </td>
                      <td class="osv-td-center">
                        <div class="osv-actions">
                          <button type="button" class="osv-action-btn" @click="openDetail(s)">
                            <FontAwesomeIcon icon="eye" aria-hidden="true" /> 明细
                          </button>
                          <button
                            v-if="isBeile && canReceive && s.status === 'shipped'"
                            type="button"
                            class="osv-action-btn osv-action-btn--primary"
                            :disabled="receivingId === s.id"
                            @click="confirmReceive(s)"
                          >
                            <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> {{ receivingId === s.id ? '收货中…' : '确认收货' }}
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <UiPagination
                v-if="totalPages > 1"
                :current-page="currentPage"
                :total-pages="totalPages"
                :total-items="total"
                :page-size="perPage"
                :page-size-options="PAGE_SIZE_OPTIONS"
                @update:current-page="goPage"
                @update:page-size="onPageSize"
              />
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 一键发货弹窗 -->
    <OutsourceShipDialog v-model:open="shipOpen" @shipped="onShipped" />

    <!-- 发货单明细弹窗 -->
    <OutsourceShipmentDetailDialog v-model:open="detailOpen" :shipment-id="detailId" />
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourceShipmentView.vue — 外发发货单页面（/outsource/shipments）
 *
 * 发货工作流（方案B + 用户裁决布局，docs/outsource/外发模块TAB重构方案.md）：
 * - 页头 = Tab 导航 + 动作组（OutsourceShipmentActions：待收货/已完成切换、
 *   导出/打印未到货、批量发货，与 TAB 同行靠右）
 * - 信息条（OutsourceShipmentStrip）仅承载概览：待收货张数、未到货件数
 * - 一键发货 → 生成发货单（贝乐用户端「待收货」订单）
 * - 贝乐账号「确认收货」→ 状态「已完成」闭环
 * - 「明细」→ SKU + 工序 + 发货/收货数量；「导出/打印未到货」自外发进度页迁入
 */
import { computed, ref } from 'vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import OutsourceShipDialog from '@/views/outsource/components/OutsourceShipDialog.vue'
import OutsourceShipmentDetailDialog from '@/views/outsource/components/OutsourceShipmentDetailDialog.vue'
import OutsourceShipmentStrip from '@/views/outsource/components/OutsourceShipmentStrip.vue'
import OutsourceShipmentActions from '@/views/outsource/components/OutsourceShipmentActions.vue'
import { outsourceApi, type Shipment } from '@/api/outsource'
import { useAuthStore } from '@/stores/auth'
import { useOutsourceUnshipped } from '@/views/outsource/composables/useOutsourceUnshipped'
import { toast } from '@/composables/useToast'

const PAGE_SIZE_OPTIONS = [20, 50, 100, 200]

const authStore = useAuthStore()
const canShip = computed(() => authStore.hasPermission('outsource_ship'))
const canReceive = computed(() => authStore.hasPermission('outsource_receive'))
/** 贝乐账号：只收货不发货（与后端授权脚本 add_outsource_ship_receive_perms.py 的 BEILE_USERNAME 一致） */
const isBeile = computed(() => authStore.user?.username === '贝乐')

// ===== 列表状态 =====
const statusFilter = ref<'shipped' | 'received'>('shipped')
const currentPage = ref(1)
const perPage = ref(50)
const shipments = ref<Shipment[]>([])
const total = ref(0)
const shippedCount = ref(0)
const receivedCount = ref(0)
const loading = ref(false)
const isFetching = ref(false)
const receivingId = ref<number | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

// ===== 未到货导出/打印（方案B：自外发进度页迁入，跨全部订单聚合） =====
const { exporting, loading: unshippedLoading, handleExport, handlePrint } = useOutsourceUnshipped()
/** 未到货总件数（订单数量 − 已发数量）；null = 未取得，信息条不渲染该段 */
const unshippedQty = ref<number | null>(null)

async function loadUnshippedQty() {
  try {
    const items = await outsourceApi.unshipped()
    unshippedQty.value = items.reduce((sum, it) => sum + (it.remaining || 0), 0)
  } catch {
    unshippedQty.value = null
  }
}

async function load() {
  loading.value = shipments.value.length === 0
  isFetching.value = true
  try {
    const res = await outsourceApi.shipments({
      status: statusFilter.value,
      page: currentPage.value,
      per_page: perPage.value,
    })
    shipments.value = res.data
    total.value = res.total
    shippedCount.value = res.shipped_count
    receivedCount.value = res.received_count
  } catch {
    toast.error('加载发货单列表失败')
  } finally {
    loading.value = false
    isFetching.value = false
  }
}

function setStatus(s: 'shipped' | 'received') {
  if (statusFilter.value === s) return
  statusFilter.value = s
  currentPage.value = 1
  load()
}

function goPage(p: number) {
  currentPage.value = p
  load()
}

function onPageSize(s: number) {
  perPage.value = s
  currentPage.value = 1
  load()
}

// ===== 一键发货 / 明细 =====
const shipOpen = ref(false)
const detailOpen = ref(false)
const detailId = ref<number | null>(null)

function openDetail(s: Shipment) {
  detailId.value = s.id
  detailOpen.value = true
}

function onShipped() {
  // 一键发货成功：回到「待收货」并刷新（未到货件数同步减少）
  statusFilter.value = 'shipped'
  currentPage.value = 1
  load()
  loadUnshippedQty()
}

async function confirmReceive(s: Shipment) {
  receivingId.value = s.id
  try {
    const res = await outsourceApi.receiveShipment(s.id)
    toast.success(res.message || '确认收货成功')
    load()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '确认收货失败')
  } finally {
    receivingId.value = null
  }
}

function statusLabel(status: string): string {
  return status === 'received' ? '已完成' : '待收货'
}

function statusClass(status: string): string {
  return status === 'received' ? 'osv-status-received' : 'osv-status-shipped'
}

load()
loadUnshippedQty()
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

.page-card-header {
  flex-wrap: wrap;
  row-gap: 8px;
  gap: 12px;
}
.page-card-header :deep(.hu-tabs-bar) {
  padding: 0;
  flex-shrink: 0;
}

/* ===== 列表 ===== */
.osv-body { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.osv-table-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
.osv-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 13px; }
.osv-table thead { background: var(--color-surface, #f8fafc); position: sticky; top: 0; z-index: 1; }
.osv-table thead th {
  padding: 10px 14px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
  border-right: 1px solid #d8dce2; border-bottom: 2px solid #b8bec6; color: var(--color-text-secondary);
  text-align: center; white-space: nowrap;
}
.osv-table thead th:last-child { border-right: none; }
.osv-th-center { text-align: center !important; }
.osv-table tbody td {
  padding: 10px 14px; font-size: 13px; border-right: 1px solid #d8dce2; border-bottom: 1px solid #d8dce2;
  text-align: center; vertical-align: middle; color: var(--color-text);
}
.osv-table tbody td:last-child { border-right: none; }
.osv-table tbody tr:last-child td { border-bottom: none; }
.osv-table tbody tr:hover { background: var(--color-primary-50); }
.osv-td-center { text-align: center !important; }
.osv-td-nowrap { white-space: nowrap; }
.osv-td-mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px; }

.osv-status-badge { display: inline-block; padding: 2px 9px; border-radius: 7px; font-size: 11.5px; font-weight: 600; white-space: nowrap; }
.osv-status-shipped { background: var(--color-warning-50); color: var(--color-warning-600); }
.osv-status-received { background: var(--color-success-50); color: var(--color-success-700); }

.osv-actions { display: inline-flex; align-items: center; gap: 6px; justify-content: center; }
.osv-action-btn {
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; font-size: 12px; font-weight: 600;
  border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 7px; background: #fff;
  color: var(--color-text-secondary, #475569); cursor: pointer; font-family: inherit; transition: all 0.15s ease;
}
.osv-action-btn:hover:not(:disabled) { border-color: var(--color-primary-300, #93c5fd); color: var(--color-primary-600, #2563eb); background: var(--color-primary-50, #eff6ff); }
.osv-action-btn--primary { color: var(--color-success-600, #16a34a); border-color: var(--color-success-300, #86efac); }
.osv-action-btn--primary:hover:not(:disabled) { background: var(--color-success-50, #f0fdf4); color: var(--color-success-700, #15803d); }
.osv-action-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.osv-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 20px; color: var(--color-text-muted); }
.osv-empty span { font-size: 14px; }

.osv-fetching-bar { height: 2px; background: var(--color-primary-100, #e0f2fe); overflow: hidden; border-radius: 1px; }
.osv-fetching-progress {
  height: 100%; width: 30%; background: var(--color-primary-500, #3b82f6); border-radius: 1px;
  animation: osv-progress-slide 1s ease-in-out infinite;
}
@keyframes osv-progress-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }
</style>
