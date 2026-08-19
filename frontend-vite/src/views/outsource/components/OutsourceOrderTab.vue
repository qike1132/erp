<template>
  <div class="oso-inventory">
    <!-- 表格区 -->
    <div class="oso-card-main">
      <div v-if="isLoading && orders.length === 0" class="oso-empty">
        <UiSpinner />
      </div>
      <div v-else-if="orders.length === 0" class="oso-empty">
        <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />
        <span>暂无湖北外发订单</span>
      </div>
      <template v-else>
        <div v-if="isFetching" class="oso-fetching-bar"><div class="oso-fetching-progress" /></div>
        <div class="oso-table-wrap">
          <table class="oso-table">
            <thead>
              <tr>
                <th class="oso-th-center" style="width: 90px;">订单类型</th>
                <th class="oso-th-center" style="white-space:nowrap; width: 170px;">下单时间</th>
                <th class="oso-th-center" style="width: 160px;">客户名称</th>
                <th class="oso-th-center" style="width: 360px;">产品名称</th>
                <th class="oso-th-center" style="width: 78px;">工厂</th>
                <th class="oso-th-center" style="width: 90px;">数量</th>
                <th class="oso-th-center" style="width: 170px;">外发进度</th>
                <th class="oso-th-center" style="width: 130px;">外发工序</th>
                <th class="oso-th-left">备注</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in displayOrders"
                :key="item.id"
                class="oso-row-clickable"
                @click="openDetail(item)"
              >
                <td class="oso-td-center oso-td-nowrap" style="width: 90px;">
                  <span v-if="item.record_type === 'stockin'" class="oso-type-badge oso-type-badge--stockin">备货</span>
                  <span v-else class="oso-type-badge oso-type-badge--order">订单</span>
                </td>
                <td class="oso-td-center oso-td-nowrap" style="width: 170px;">
                  <span class="oso-order-date" :title="item.order_date || ''">{{ item.order_date || '-' }}</span>
                </td>
                <td class="oso-td-center oso-td-middle oso-customer-cell" style="width:170px">{{ item.customer || '-' }}</td>
                <td class="oso-td-center oso-product-cell" style="width: 360px;">
                  <template v-if="visibleSkus(item).length > 0">
                    <div v-for="sku in visibleSkus(item)" :key="sku.id" class="oso-sku-line">
                      <span class="oso-sku-name" :title="sku.product_name || ''">{{ sku.product_name || '-' }}</span>
                    </div>
                  </template>
                  <span v-else class="oso-sku-name">{{ item.product_name || '-' }}</span>
                </td>
                <td class="oso-td-center oso-td-middle" style="width: 90px;"><span class="oso-cell-main">{{ item.factories?.join(', ') || '湖北' }}</span></td>
                <td class="oso-td-center" style="width: 90px;">
                  <strong>{{ totalQuantity(item) }}</strong>
                </td>
                <!-- 外发进度：进度条 + 状态标签 -->
                <td class="oso-td-center" style="width: 170px;">
                  <div v-if="(item.total_processes || 0) > 0" class="oso-progress-cell">
                    <div class="oso-progress-bar">
                      <div
                        class="oso-progress-fill"
                        :class="progressClass(item.progress || 0)"
                        :style="{ width: (item.progress || 0) + '%' }"
                      />
                    </div>
                    <span :class="['oso-status-badge', statusClass(item.status_label || '')]">{{ item.status_label }}</span>
                  </div>
                  <span v-else class="oso-cell-muted">未配置</span>
                </td>
                <td class="oso-td-center" style="width: 130px;">
                  <span class="oso-proc-badge" @click.stop="openDetail(item)">
                    <FontAwesomeIcon icon="route" aria-hidden="true" /> 查看工序
                  </span>
                </td>
                <td class="oso-td-left">
                  <template v-if="visibleSkus(item).length > 0">
                    <div v-for="sku in visibleSkus(item)" :key="sku.id" class="oso-sku-line">
                      <span v-if="sku.note" class="oso-sku-note" :title="sku.note">{{ sku.note }}</span>
                    </div>
                  </template>
                  <span v-if="item.note" class="oso-sku-note">{{ item.note }}</span>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="displayOrders.length === 0" class="oso-empty oso-empty-inline">
            <FontAwesomeIcon icon="search-minus" aria-hidden="true" />
            <span>当前页未匹配到该订单</span>
          </div>
        </div>

        <UiPagination
          v-if="totalPages > 1"
          :current-page="currentPage"
          :total-pages="totalPages"
          :total-items="totalItems"
          :page-size="perPage"
          :page-size-options="PAGE_SIZE_OPTIONS"
          @update:current-page="goPage"
          @update:page-size="perPage = $event"
        />
      </template>
    </div>

    <!-- 订单外发工序弹窗（步骤卡片流，拆分为子组件） -->
    <OutsourceProcessDialog
      v-model:open="detailOpen"
      :detail-data="detailData"
      @refresh="refetch"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourceOrderTab.vue — 湖北外发订单列表 + 外发工序管理
 *
 * 列表：展示 factory=湖北 的订单（复用 beile-list 数据链路），行内呈现外发进度。
 * 数据加载/筛选/分页逻辑下沉到 composables/useOutsourceOrders.ts，
 * 工序管理弹窗拆分为 components/OutsourceProcessDialog.vue。
 */
import { ref } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import OutsourceProcessDialog from '@/views/outsource/components/OutsourceProcessDialog.vue'
import { useOutsourceOrders } from '@/views/outsource/composables/useOutsourceOrders'
import type { OutsourceOrderRow } from '@/views/outsource/composables/useOutsourceOrders'

const props = defineProps<{
  productFilter: string
  customerFilter: string
}>()

// ==================== 列表：查询 + 筛选 + 分页（useOutsourceOrders） ====================
const {
  PAGE_SIZE_OPTIONS,
  perPage,
  currentPage,
  isLoading,
  isFetching,
  refetch,
  orders,
  totalItems,
  totalPages,
  visibleSkus,
  displayOrders,
  totalQuantity,
  goPage,
} = useOutsourceOrders(props)

// ==================== 工序管理弹窗（子组件） ====================
const detailOpen = ref(false)
const detailData = ref<OutsourceOrderRow | null>(null)

/** 打开工序详情弹窗（弹窗内部自行加载工序数据） */
function openDetail(item: OutsourceOrderRow) {
  detailData.value = item
  detailOpen.value = true
}

/** 进度条配色 */
function progressClass(progress: number): string {
  if (progress === 100) return 'oso-progress-fill--done'
  if (progress > 0) return 'oso-progress-fill--run'
  return 'oso-progress-fill--wait'
}

/** 状态徽章配色（按状态文案匹配） */
function statusClass(label: string): string {
  if (label === '外发完成') return 'oso-status-completed'
  if (label === '待开始' || label === '未配置工序') return 'oso-status-pending'
  if (label.startsWith('进行中')) return 'oso-status-in_progress'
  return 'oso-status-pending'
}
</script>

<style scoped>
.oso-inventory {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.oso-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.oso-table-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
.oso-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 13px;
}
.oso-table thead {
  background: var(--color-surface, #f8fafc);
  position: sticky;
  top: 0;
  z-index: 1;
}
.oso-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-right: 1px solid #d8dce2;
  border-bottom: 2px solid #b8bec6;
  color: var(--color-text-secondary);
  text-align: center;
  white-space: nowrap;
}
.oso-table thead th:last-child { border-right: none; }
.oso-th-left { text-align: left !important; }
.oso-th-center { text-align: center !important; }
.oso-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-right: 1px solid #d8dce2;
  border-bottom: 1px solid #d8dce2;
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.oso-table tbody td:last-child { border-right: none; }
.oso-table tbody tr:last-child td { border-bottom: none; }
.oso-td-left { text-align: left !important; }
.oso-td-center { text-align: center !important; }
.oso-td-nowrap { white-space: nowrap; }
.oso-table tbody tr:hover { background: var(--color-primary-50); }
.oso-customer-cell { font-weight: 600; white-space: nowrap; }
.oso-cell-main { font-weight: 600; }
.oso-sku-line { padding: 2px 0; font-size: 13px; line-height: 1.4; }
.oso-sku-name {
  display: block;
  white-space: nowrap;
  font-weight: 500;
}
.oso-sku-note {
  display: inline-block;
  color: var(--color-text-secondary);
  font-size: 12px;
  word-break: break-word;
  vertical-align: middle;
}
.oso-row-clickable { cursor: pointer; }
.oso-order-meta-cell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.oso-order-date { flex-shrink: 0; }
.oso-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  line-height: 1.5;
}
.oso-type-badge--order { background: var(--color-success-50, #e8f9ef); color: var(--color-success-600, #1e9e55); }
.oso-type-badge--stockin { background: var(--color-primary-50, #eff6ff); color: var(--color-primary-600, #2563eb); }
.oso-proc-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 8px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s ease;
}
.oso-proc-badge:hover { background: var(--color-primary-100); }

.oso-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.oso-empty span { font-size: 14px; }
.oso-empty-inline { padding: 24px 20px; }

.oso-fetching-bar { height: 2px; background: var(--color-primary-100, #e0f2fe); overflow: hidden; border-radius: 1px; }
.oso-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: oso-progress-slide 1s ease-in-out infinite;
}
@keyframes oso-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* 列表进度列 */
.oso-progress-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
}
.oso-progress-bar {
  width: 100%;
  max-width: 120px;
  height: 6px;
  border-radius: 999px;
  background: #e8ecf1;
  overflow: hidden;
}
.oso-progress-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}
.oso-progress-fill--done { background: var(--color-success-500); }
.oso-progress-fill--run { background: var(--color-warning-400); }
.oso-progress-fill--wait { background: var(--color-warning-400); }
.oso-cell-muted { color: var(--color-text-muted); font-size: 12px; }

.oso-status-badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.oso-status-pending { background: var(--color-warning-50); color: var(--color-warning-600); }
.oso-status-in_progress { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-status-completed { background: var(--color-success-50); color: var(--color-success-700); }
</style>
