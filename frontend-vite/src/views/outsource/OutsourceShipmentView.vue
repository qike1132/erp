<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：Tab 导航 + 待收货提醒 + 一键发货 + 发货单状态筛选 -->
      <div class="page-card-header">
        <HubeiRouteTabs />
        <!-- 待收货提醒 -->
        <div v-if="shippedCount > 0" class="osv-hint">
          <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
          <span>提醒：共有 <strong>{{ shippedCount }}</strong> 张发货单待收货</span>
        </div>
        <!-- 批量发货：仅非贝乐用户（外协方/工厂/管理员）可见，贝乐账号只收货不发货 -->
        <div class="osv-header-actions">
          <button
            v-if="canShip && !isBeile"
            type="button"
            class="osv-toolbar-btn osv-toolbar-btn--ship"
            @click="shipOpen = true"
          >
            <FontAwesomeIcon icon="truck-fast" aria-hidden="true" /> 批量发货
          </button>
        </div>
        <!-- 发货单状态 TAB（待收货/已完成）参照 beile-order 未确认/已确认；置于最右 -->
        <div class="osv-confirm-filter">
          <button
            type="button"
            :class="['osv-confirm-filter-btn', { 'is-active': statusFilter === 'shipped' }]"
            @click="setStatus('shipped')"
          >待收货</button>
          <button
            type="button"
            :class="['osv-confirm-filter-btn', { 'is-active': statusFilter === 'received' }]"
            @click="setStatus('received')"
          >已完成</button>
        </div>
      </div>

      <!-- 内容区：发货单列表 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
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
                      <th class="osv-th-center" style="width: 150px;">发货时间</th>
                      <th class="osv-th-center" style="width: 90px;">明细数</th>
                      <th class="osv-th-center" style="width: 90px;">发货总量</th>
                      <th class="osv-th-center" style="width: 100px;">状态</th>
                      <th class="osv-th-center" style="width: 190px;">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="s in shipments" :key="s.id">
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
 * 一键发货工作流：
 * - 一键发货 → 生成发货单（贝乐用户端「待收货」订单）
 * - 发货单列表（待收货/已完成 TAB，参照 beile-order 未确认/已确认）
 * - 贝乐账号「确认收货」→ 状态「已完成」闭环
 * - 「明细」→ SKU + 工序 + 发货/收货数量
 */
import { computed, ref } from 'vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import OutsourceShipDialog from '@/views/outsource/components/OutsourceShipDialog.vue'
import OutsourceShipmentDetailDialog from '@/views/outsource/components/OutsourceShipmentDetailDialog.vue'
import { outsourceApi, type Shipment } from '@/api/outsource'
import { useAuthStore } from '@/stores/auth'
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
  // 一键发货成功：回到「待收货」并刷新
  statusFilter.value = 'shipped'
  currentPage.value = 1
  load()
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
.osv-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ===== 状态筛选 TAB（参照 beile-order） ===== */
/* 置于头部最右：margin-left:auto 吃掉剩余空间，把本块推到行尾 */
.osv-confirm-filter {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}
.osv-confirm-filter-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary, #6b7280);
  background: #fff;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 9px;
  cursor: pointer;
  font-family: inherit;
  user-select: none;
  transition: all 0.15s ease;
}
.osv-confirm-filter-btn:hover {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.osv-confirm-filter-btn.is-active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #3b82f6), var(--color-primary-600, #2563eb));
  border-color: var(--color-primary-600, #2563eb);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.25);
}

/* ===== 待收货提醒 ===== */
.osv-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 9px;
  background: var(--color-warning-50);
  border: 1px solid var(--color-warning-200);
  color: var(--color-warning-700);
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.osv-hint strong { color: var(--color-warning-800); font-size: 15px; }

/* ===== 工具栏按钮 ===== */
.osv-toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.osv-toolbar-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #2563eb);
  background: var(--color-primary-50, #eff6ff);
}
.osv-toolbar-btn--ship {
  color: #fff;
  background: var(--color-primary-600, #2563eb);
  border-color: var(--color-primary-600, #2563eb);
}
.osv-toolbar-btn--ship:hover:not(:disabled) {
  color: #fff;
  background: var(--color-primary-700, #1d4ed8);
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
