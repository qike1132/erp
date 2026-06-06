 <template>
  <div class="mr-container">
    <div class="mr-main-card">
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
          <table class="mr-tbl" style="min-width:900px;">
            <thead><tr><th style="width:160px;">供应商</th><th style="width:160px;">关联订单</th><th>物料进度</th><th style="width:220px;">总进度</th><th style="width:80px;">操作</th></tr></thead>
            <tbody>
              <tr v-if="pIsLoading && !progressGroups.length"><td colspan="5" class="mr-empty"><i class="fas fa-spinner fa-spin" /><span>加载中...</span></td></tr>
              <tr v-else-if="!progressGroups.length"><td colspan="5" class="mr-empty"><i class="fas fa-inbox" /><span>暂无进行中的来料登记</span></td></tr>
              <tr v-if="pIsFetching && progressGroups.length"><td colspan="5" class="mr-fetching-bar"><div class="mr-fetching-progress" /></td></tr>
              <tr v-for="row in progressOrderRows" :key="row.order_no" class="mr-order-row">
                <td class="mr-td-bold">{{ row.supplier_name }}</td>
                <td><span class="mr-order-link" @click="previewOrder(row.order_no)" title="点击预览订单详情">{{ row.order_no }}</span></td>
                <td><div class="mr-items-container"><div v-for="i in row.items" :key="i.material_name" class="mr-list-item-row"><span class="mr-list-item-name" :title="i.material_name">{{ i.material_name }}</span><span class="mr-list-item-qty">数量:<b>{{ parseFloat(String(i.ordered_quantity || 0)).toFixed(0) }}</b></span><span class="mr-list-item-rcv">已到货:<b>{{ parseFloat(String(i.received_quantity || 0)).toFixed(0) }}</b></span><div class="mr-list-item-bar"><div :class="['mr-sku-fill', fillClass(i)]" :style="{ width: (i.progress || 0) + '%', height: '100%', borderRadius: '5px' }"></div></div><span class="mr-list-item-pct">{{ i.progress || 0 }}%</span></div></div></td>
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
              <tr v-if="hIsLoading && !hRegistrations.length"><td colspan="7" class="mr-empty"><i class="fas fa-spinner fa-spin" /><span>加载中...</span></td></tr>
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
    <UiDialog v-model:open="showDetailDialog" title="来料进度详情" title-icon="" max-width-class="max-w-[1000px]">
      <template #title-icon><i class="fas fa-clipboard-list" style="color:var(--color-primary-500);"></i></template>
      <div v-if="detailData">
        <div class="mr-det-grid">
          <div><div class="mr-det-lb">订单号</div><div class="mr-det-vl" style="color:var(--color-primary-500);">{{ detailData.purchase_order_no }}</div></div>
          <div><div class="mr-det-lb">客户</div><div class="mr-det-vl">{{ detailData.customer_name || '-' }}</div></div>
          <div><div class="mr-det-lb">产品/数量</div><div class="mr-det-vl">{{ detailData.product_name || '-' }}{{ detailData.product_quantity ? ' x' + detailData.product_quantity : '' }}</div></div>
          <div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">{{ detailData.supplier_name || '-' }}</div></div>
          <div><div class="mr-det-lb">状态</div><div class="mr-det-vl"><span :class="['mr-badge', 'mr-badge-' + detailData.status]">{{ STATUS_MAP[detailData.status] || detailData.status }}</span></div></div>
          <div><div class="mr-det-lb">总进度</div><div class="mr-det-vl" style="display:flex;align-items:center;gap:8px;"><div class="mr-pbar" style="flex:1;min-width:120px;"><div :class="['mr-pfill', detailData.progress >= 100 ? 'completed' : 'pending']" :style="{ width: (detailData.progress || 0) + '%' }"></div></div><span>{{ detailData.progress }}% (已到货 {{ detailData.total_received }} / 数量 {{ detailData.total_ordered }})</span></div></div>
        </div>
        <h4 style="margin:18px 0 14px;font-size:16px;"><i class="fas fa-cubes" style="color:var(--color-primary-500);"></i> SKU物料来料进度</h4>
        <VirtualList
          :items="detailData.items || []"
          :itemHeight="90"
          :containerHeight="360"
          :itemKey="(i: any) => i.id"
        >
          <template #default="{ item: i }">
            <div class="mr-sku-row" style="margin-bottom:0;">
              <div class="mr-sku-top"><span><span class="mr-sku-name">{{ i.material_name }}</span><span class="mr-sku-spec">{{ i.specification || '' }}</span></span><span class="mr-sku-pct" :style="{ color: i.received_quantity >= i.ordered_quantity ? 'var(--color-success-500)' : (i.progress >= 50 ? 'var(--color-primary-500)' : 'var(--color-warning-500)') }">{{ i.progress }}%</span></div>
              <div class="mr-sku-bar"><div :class="['mr-sku-fill', fillClass(i)]" :style="{ width: i.progress + '%' }"></div></div>
              <div class="mr-sku-info">
                <span>分类: <b>{{ CATEGORY_MAP[i.material_category] || '-' }}</b></span>
                <span>数量: <b>{{ i.ordered_quantity }}</b> {{ i.unit || '' }}</span>
                <span>已到货: <b style="color:var(--color-success-500);">{{ i.received_quantity }}</b></span>
                <span>未到: <b style="color:var(--color-warning-500);">{{ i.remaining_quantity }}</b></span>
                <button v-if="canManage && i.received_quantity < i.ordered_quantity" class="mr-btn mr-btn-success mr-btn-sm" @click="openReceive(i)" title="登记收货数量"><i class="fas fa-box" /> 收货</button>
                <span v-else-if="i.received_quantity >= i.ordered_quantity" style="color:var(--color-success-500);font-weight:600;">&#10003; 已完成</span>
              </div>
            </div>
          </template>
        </VirtualList>
      </div>
    </UiDialog>

    <!-- Supplier Detail Dialog -->
    <UiDialog v-model:open="showSupplierDialog" :title="`来料详情 - ${supplierDetailOrderNo}`" title-icon="" max-width-class="max-w-[1000px]">
      <template #title-icon><i class="fas fa-clipboard-list" style="color:var(--color-primary-500);"></i></template>
      <div v-if="supplierDetail">
        <div class="mr-det-grid">
          <div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">{{ supplierDetail.name }}</div></div>
          <div><div class="mr-det-lb">关联订单</div><div class="mr-det-vl">{{ supplierDetail.orders.length }} 个</div></div>
          <div><div class="mr-det-lb">总进度</div><div class="mr-det-vl">{{ supplierDetail.totalPct }}% (已到货 {{ supplierDetail.totalReceived.toFixed(0) }} / 数量 {{ supplierDetail.totalOrdered.toFixed(0) }})</div></div>
        </div>
        <div v-for="o in supplierDetail.orders" :key="o.orderNo" class="mr-source-card" style="margin-bottom:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <div style="font-weight:600;font-size:14px;"><i class="fas fa-file-invoice" style="color:var(--color-primary-500);margin-right:6px;"></i>{{ o.orderNo }}<span style="color:var(--color-text-muted);margin-left:8px;font-weight:400;font-size:12px;">{{ o.customerName }} · {{ o.productName }} x{{ o.productQuantity }}</span></div>
            <span :class="['mr-badge', o.pct >= 100 ? 'mr-badge-completed' : o.pct > 0 ? 'mr-badge-pending' : 'mr-badge-overdue']">{{ o.pct }}%</span>
          </div>
          <div v-for="m in o.items" :key="m.name" class="mr-det-mat-card">
            <div class="mr-det-mat-row">
              <div class="mr-det-mat-info">
                <span class="mr-det-mat-name">{{ m.name }}</span>
                <span v-if="m.spec" class="mr-det-mat-spec">{{ m.spec }}</span>
              </div>
              <div class="mr-det-mat-metrics">
                <div class="mr-det-mat-metric">
                  <span class="mr-det-mat-label">采购数量</span>
                  <span class="mr-det-mat-value">{{ m.ordered.toFixed(0) }}</span>
                </div>
                <div class="mr-det-mat-metric">
                  <span class="mr-det-mat-label">已到货</span>
                  <span class="mr-det-mat-value received">{{ m.received.toFixed(0) }}</span>
                </div>
                <div class="mr-det-mat-metric">
                  <span class="mr-det-mat-label">未到货</span>
                  <span class="mr-det-mat-value remaining">{{ m.remaining.toFixed(0) }}</span>
                </div>
                <div class="mr-det-mat-metric">
                  <span class="mr-det-mat-label">完成率</span>
                  <span class="mr-det-mat-value" :class="m.received >= m.ordered ? 'completed' : (m.pct >= 50 ? 'half' : 'low')">{{ m.pct }}%</span>
                </div>
              </div>
              <div class="mr-det-mat-right">
                <div class="mr-det-mat-status">
                  <span v-if="m.received >= m.ordered" class="mr-status-completed"><i class="fas fa-check-circle" /> 已完成</span>
                  <span v-else class="mr-status-pending">进行中</span>
                </div>
                <div v-if="canManage && m.received < m.ordered && m.firstItemId" class="mr-det-mat-action">
                  <button class="mr-btn mr-btn-success" @click="openReceiveById(m.firstItemId, m.name, m.ordered, m.received)" title="登记收货"><i class="fas fa-box" /> 登记收货</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </UiDialog>

    <!-- Receive Dialog -->
    <UiDialog v-model:open="showReceiveDialog" title="收货登记" title-icon="" max-width-class="max-w-[540px]">
      <template #title-icon><i class="fas fa-box" style="color:var(--color-success-500);"></i></template>
      <div class="mr-fg2"><label>物料名称</label><div style="font-weight:600;font-size:17px;">{{ receiveItem.name }}</div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
        <div class="mr-fg2"><label>采购数量</label><div style="font-size:17px;">{{ receiveItem.ordered }}</div></div>
        <div class="mr-fg2"><label>已收货</label><div style="font-size:17px;color:var(--color-success-500);">{{ receiveItem.received }}</div></div>
        <div class="mr-fg2"><label>待收货</label><div style="font-size:17px;color:var(--color-warning-500);">{{ receiveItem.remaining }}</div></div>
      </div>
      <div class="mr-fg2"><label>本次收货数量</label><input type="number" v-model.number="receiveQty" min="0.01" step="0.01" placeholder="输入本次收货数量"></div>
      <div class="mr-fg2"><label>备注</label><textarea v-model="receiveRemark" rows="2" placeholder="可选备注..."></textarea></div>
      <template #footer>
        <button class="mr-btn mr-btn-ghost" @click="showReceiveDialog = false">取消</button>
        <button class="mr-btn mr-btn-success" @click="submitReceive"><i class="fas fa-check" /> 确认收货</button>
      </template>
    </UiDialog>

    <!-- Order Preview Dialog -->
    <UiDialog v-model:open="showOrderPreviewDialog" title="采购订单详情" title-icon="" max-width-class="max-w-[720px]">
      <template #title-icon><i class="fas fa-file-invoice" style="color:var(--color-primary-500);"></i></template>
      <div v-if="orderPreview">
        <!-- 来源销售订单 -->
        <div v-if="orderPreview.source_orders && orderPreview.source_orders.length" class="mr-source-section">
          <div class="mr-preview-section-label"><i class="fas fa-link" /> 来源销售订单</div>
          <div v-for="so in orderPreview.source_orders" :key="so.id" class="mr-source-card">
            <div class="mr-det-grid" style="grid-template-columns:1fr 1fr;">
              <div><div class="mr-det-lb">销售订单号</div><div class="mr-det-vl" style="color:var(--color-success-600, #059669);">{{ so.order_no || '-' }}</div></div>
              <div><div class="mr-det-lb">客户</div><div class="mr-det-vl">{{ so.customer_name || '-' }}</div></div>
              <div><div class="mr-det-lb">产品</div><div class="mr-det-vl">{{ so.product_name || '-' }}</div></div>
              <div><div class="mr-det-lb">数量</div><div class="mr-det-vl">{{ so.quantity || '-' }}</div></div>
            </div>
          </div>
        </div>

        <div v-if="orderPreview.remark" style="margin-top:12px;padding:10px 14px;background:var(--color-surface,#f8fafc);border-radius:8px;font-size:13px;color:var(--color-text-secondary);"><b>备注:</b> {{ orderPreview.remark }}</div>
        <div class="mr-preview-section-label"><i class="fas fa-list" /> 物料明细 <span class="mr-preview-count">{{ orderPreview.item_count || (orderPreview.items ? orderPreview.items.length : 0) }} 项</span></div>
        <table v-if="orderPreview.items && orderPreview.items.length" class="mr-item-tbl">
          <thead><tr><th style="width:40%;">物料名称</th><th style="width:30%;">规格</th><th style="width:15%;text-align:right;">数量</th><th style="width:15%;">分类</th></tr></thead>
          <tbody><tr v-for="it in orderPreview.items" :key="it.material_name + it.specification"><td>{{ it.material_name || '-' }}</td><td style="color:var(--color-text-secondary);">{{ it.specification || '-' }}</td><td style="text-align:right;font-weight:500;">{{ it.quantity || 0 }} {{ it.unit || '' }}</td><td>{{ CATEGORY_MAP[it.material_category || ''] || '-' }}</td></tr></tbody>
        </table>
        <div v-else style="text-align:center;padding:20px;color:var(--color-text-muted);">暂无物料明细</div>
      </div>
    </UiDialog>

    <div :class="['mr-toast', { show: toastMsg }, toastType]"><i :class="['fas', toastIcon]"></i> {{ toastMsg }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { materialApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

// --- API Response Types ---

interface CategoryStatRow {
  category: string
  category_name?: string
  ordered: number
  received: number
}

interface MaterialOverview {
  total: number
  recent_registrations: number
  pending: number
  partial: number
  completed: number
  overall_progress: number
  total_received: number
  total_ordered: number
  category_stats: CategoryStatRow[]
}

interface TrendItem {
  date: string
  registered: number
  received: number
}

interface DistItem {
  status: string
  count: number
}

interface RegItem {
  id: number
  material_name: string
  specification: string
  material_category: string
  ordered_quantity: number | string
  received_quantity: number | string
  remaining_quantity: number | string
  progress: number
  unit: string
}

interface Registration {
  id: number
  purchase_order_no: string
  supplier_name: string
  customer_name: string
  product_name: string
  product_quantity: number
  items: RegItem[]
  status: string
  progress: number
  total_ordered: number | string
  total_received: number | string
  update_time?: string
}

interface SourceOrder {
  id?: number
  order_no: string
  customer_name?: string
  product_name?: string
  quantity?: number
}

interface OrderItem {
  material_name: string
  specification?: string
  material_category?: string
  ordered_quantity: number | string
  quantity?: number | string
  unit?: string
}

interface OrderPreview {
  order_no: string
  status: string
  supplier_name: string
  order_date: string
  customer_name?: string
  product_name?: string
  product_quantity?: number
  items: OrderItem[]
  item_count: number
  source_orders?: SourceOrder[]
  remark?: string
}

// --- Internal Types ---

interface SupplierGroup {
  supplier_name: string
  orders: OrderSummary[]
  allItems: MatSummary[]
}

interface OrderSummary {
  id: number
  order_no: string
  customer_name: string
  product_name: string
  product_quantity: number
  items: RegItem[]
  status: string
  progress: number
  total_ordered: number | string
  total_received: number | string
  update_time?: string
  supplier_name?: string
}

interface MatSummary {
  material_name: string
  material_category: string
  specification: string
  unit: string
  ordered_quantity: number
  received_quantity: number
  remaining_quantity: number
  progress: number
}

interface SupMat {
  name: string
  ordered: number
  received: number
  remaining: number
  pct: number
  firstItemId: number | null
  unit: string
  spec: string
}

interface SupOrder {
  orderNo: string
  customerName: string
  productName: string
  productQuantity: number
  items: SupMat[]
  totalOrdered: number
  totalReceived: number
  pct: number
}

interface SupplierDetail {
  name: string
  orders: SupOrder[]
  totalOrdered: number
  totalReceived: number
  totalPct: number
}

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('product_manage'))

const STATUS_MAP: Record<string, string> = { pending: '未开始', partial: '部分到货', completed: '全部到货' }
const STATUS_NAMES: Record<string, string> = { pending: '未开始', partial: '部分到货', completed: '全部到货', overdue: '延期' }
const STATUS_COLORS: Record<string, string> = { pending: '#FF9F43', partial: '#5B8DEF', completed: '#28C76F', overdue: '#EA5456' }
const CATEGORY_MAP: Record<string, string> = { fabric: '面料', filling: '填充', accessory: '辅料', packaging: '包装' }
const ORDER_STATUS_MAP: Record<string, string> = { pending: '待处理', completed: '已完成', cancelled: '已取消', '已完成': '已完成' }

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

const { data: overviewData } = useQuery({
  queryKey: ['material-overview'],
  queryFn: async () => { const res = await materialApi.overview() as { overview: MaterialOverview }; return res.overview ?? res },
  staleTime: 30_000,
})
const overview = computed(() => overviewData.value as MaterialOverview | undefined)

const categoryStats = computed(() => {
  const o = overview.value
  if (!o?.category_stats) return []
  return o.category_stats.map((c: CategoryStatRow) => ({ ...c, remaining: (c.ordered || 0) - (c.received || 0), progress: c.ordered > 0 ? Math.round(c.received / c.ordered * 100) : 0 }))
})

const { data: trendRaw } = useQuery({ queryKey: ['material-trend'], queryFn: async () => { const res = await materialApi.trend(30) as { trend: TrendItem[] }; return res.trend ?? res ?? [] }, staleTime: 30_000 })
const trendData = computed(() => Array.isArray(trendRaw.value) ? trendRaw.value as TrendItem[] : [])
const trendMax = computed(() => Math.max(...trendData.value.map((t: TrendItem) => Math.max(t.registered, t.received)), 1))

const { data: distRaw } = useQuery({ queryKey: ['material-distribution'], queryFn: async () => { const res = await materialApi.distribution() as { distribution: DistItem[] }; return res.distribution ?? res ?? [] }, staleTime: 30_000 })
const distributionData = computed(() => Array.isArray(distRaw.value) ? distRaw.value as DistItem[] : [])
const pieGradient = computed(() => {
  const d = distributionData.value; const total = d.reduce((s: number, x: DistItem) => s + x.count, 0) || 1; let cumPct = 0
  return `conic-gradient(${d.map((item: DistItem) => { const pct = item.count / total * 100; const part = `${STATUS_COLORS[item.status] || '#999'} ${cumPct}% ${cumPct + pct}%`; cumPct += pct; return part }).join(',')})`
})

const pPage = ref(1), pPages = ref(1), pIsLoading = ref(false), pIsFetching = ref(false)
const progressGroups = ref<SupplierGroup[]>([])
const progressCount = computed(() => progressGroups.value.length)
const progressOrderRows = computed(() => {
  const rows: OrderSummary[] = []
  progressGroups.value.forEach((g: SupplierGroup) => {
    g.orders.forEach((o: OrderSummary) => {
      rows.push({ ...o, supplier_name: g.supplier_name })
    })
  })
  return rows
})
const pFilters = reactive({ supplier: '', orderNo: '', customer: '', category: '', startDate: '', endDate: '' })

const hPage = ref(1), hPages = ref(1), hIsLoading = ref(false), hIsFetching = ref(false)
const hRegistrations = ref<Registration[]>([])
const hFilters = reactive({ orderNo: '', supplier: '', customer: '', category: '', startDate: '', endDate: '' })

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
    const data = await materialApi.history(params) as any
    hRegistrations.value = data.registrations || []
    hPages.value = data.pages ?? data.total_pages ?? 1
  } catch (e) { console.error('历史加载失败:', e); toast('加载失败', 'error') } finally { hIsLoading.value = false; hIsFetching.value = false }
}

function resetHistoryFilters() { Object.assign(hFilters, { orderNo: '', supplier: '', customer: '', category: '', startDate: '', endDate: '' }); loadHistory(1) }
function materialSummary(r: Registration) {
  const items = r.items || []
  if (!items.length) return '-'
  return items.map(i => i.material_name).join(', ')
}

async function loadProgress(page = 1) {
  pPage.value = page
  const isInitial = progressGroups.value.length === 0
  if (isInitial) pIsLoading.value = true
  else pIsFetching.value = true
  try {
    const params: Record<string, string | number> = { page, per_page: 20 }
    if (pFilters.supplier) params.supplier = pFilters.supplier
    if (pFilters.orderNo) params.order_no = pFilters.orderNo
    if (pFilters.customer) params.customer_name = pFilters.customer
    if (pFilters.category) params.material_category = pFilters.category
    if (pFilters.startDate) params.start_date = pFilters.startDate
    if (pFilters.endDate) params.end_date = pFilters.endDate
    const data = await materialApi.registrations(params) as any
    progressGroups.value = groupBySupplier((data.registrations || []).filter((r: Registration) => r.status !== 'completed'))
    pPages.value = data.pages ?? data.total_pages ?? 1
  } catch (e) { console.error('进度加载失败:', e); toast('加载失败', 'error') } finally { pIsLoading.value = false; pIsFetching.value = false }
}

function groupBySupplier(registrations: Registration[]): SupplierGroup[] {
  const map: Record<string, SupplierGroup> = {}
  const itemMaps: Record<string, Map<string, MatSummary>> = {}
  registrations.forEach(r => {
    const key = r.supplier_name || '未知供应商'
    if (!map[key]) { map[key] = { supplier_name: key, orders: [], allItems: [] }; itemMaps[key] = new Map() }
    const displayItems = pFilters.category ? (r.items || []).filter((i: RegItem) => i.material_category === pFilters.category) : (r.items || [])
    map[key].orders.push({ id: r.id, order_no: r.purchase_order_no, customer_name: r.customer_name, product_name: r.product_name, product_quantity: r.product_quantity, items: displayItems, status: r.status, progress: r.progress, total_ordered: Number(r.total_ordered), total_received: Number(r.total_received) })
    const iMap = itemMaps[key]
    displayItems.forEach((item: RegItem) => {
      const itemKey = `${item.material_name}|${item.material_category}`
      const exist = iMap.get(itemKey)
      if (exist) { exist.ordered_quantity += parseFloat(String(item.ordered_quantity || 0)); exist.received_quantity += parseFloat(String(item.received_quantity || 0)); exist.remaining_quantity = exist.ordered_quantity - exist.received_quantity; exist.progress = exist.ordered_quantity > 0 ? (exist.received_quantity >= exist.ordered_quantity ? 100.0 : Math.min(Math.round(exist.received_quantity / exist.ordered_quantity * 100 * 10) / 10, 99.9)) : 0 }
      else { const newItem: MatSummary = { material_name: item.material_name, material_category: item.material_category, specification: item.specification || '', unit: item.unit || '', ordered_quantity: parseFloat(String(item.ordered_quantity || 0)), received_quantity: parseFloat(String(item.received_quantity || 0)), remaining_quantity: parseFloat(String(item.remaining_quantity || 0)), progress: item.progress || 0 }; iMap.set(itemKey, newItem) }
    })
  })
  for (const key of Object.keys(map)) { map[key].allItems = Array.from(itemMaps[key].values()) }
  return Object.values(map)
}

function resetProgressFilters() { Object.assign(pFilters, { supplier: '', orderNo: '', customer: '', category: '', startDate: '', endDate: '' }); loadProgress(1) }
function switchToProgress() { activeTab.value = 'progress'; if (!progressGroups.value.length && !pIsLoading.value) loadProgress(1) }
function switchToHistory() { activeTab.value = 'history'; if (!hRegistrations.value.length && !hIsLoading.value) loadHistory(1) }
function fillClass(item: { progress?: number; received_quantity: number | string; ordered_quantity: number | string }) { const pct = item.progress || 0; if (pct >= 100 || Number(item.received_quantity) >= Number(item.ordered_quantity)) return 'full'; return 'low' }
function progressCls(g: SupplierGroup) { return supplierPct(g) >= 100 ? 'completed' : 'pending' }
function supplierPct(g: SupplierGroup) { const o = g.allItems.reduce((s: number, i: MatSummary) => s + i.ordered_quantity, 0); const r = g.allItems.reduce((s: number, i: MatSummary) => s + i.received_quantity, 0); const c = g.allItems.every((i: MatSummary) => i.received_quantity >= i.ordered_quantity); if (o <= 0) return 0; return c ? 100.0 : Math.min(Math.round(r / o * 100 * 10) / 10, 99.9) }

const showDetailDialog = ref(false), detailData = ref<Registration | null>(null)
async function viewDetail(regId: number) { try { const res = await materialApi.registrationDetail(regId) as any; if (res.success === false) { toast('加载失败', 'error'); return }; detailData.value = res.registration ?? null; showDetailDialog.value = true } catch (e) { console.error('详情加载失败:', e); toast('加载失败', 'error') } }

const showSupplierDialog = ref(false), supplierDetail = ref<SupplierDetail | null>(null), supplierDetailOrderNo = ref('')
async function viewSupplierDetail(supplierName: string, orderNo: string) {
  try {
    const data = await materialApi.registrations({ supplier: supplierName, order_no: orderNo, per_page: 50 }) as any
    if (!data.registrations) { toast('加载失败', 'error'); return }
    const regList: any[] = data.registrations.filter((r: any) => r.status !== 'completed')
    if (!regList.length) { toast('无采购中数据', 'warning'); return }
    let allOrdered = 0, allReceived = 0
    const orders: SupOrder[] = regList.map((r: any) => {
      const items: SupMat[] = (r.items || []).map((i: RegItem) => {
        const ordered = parseFloat(String(i.ordered_quantity || 0))
        const received = parseFloat(String(i.received_quantity || 0))
        const pct = ordered > 0 && received < ordered ? Math.min(Math.round(received / ordered * 100 * 10) / 10, 99.9) : (received >= ordered && ordered > 0 ? 100 : 0)
        return { name: i.material_name, ordered, received, remaining: ordered - received, pct, firstItemId: received < ordered ? i.id : null, unit: i.unit || '', spec: i.specification || '' }
      })
      const oTotal = parseFloat(String(r.total_ordered || 0))
      const rTotal = parseFloat(String(r.total_received || 0))
      allOrdered += oTotal; allReceived += rTotal
      const allComplete = items.every(m => m.received >= m.ordered)
      const orderPct = oTotal > 0 ? (allComplete ? 100.0 : Math.min(Math.round(rTotal / oTotal * 100 * 10) / 10, 99.9)) : 0
      return { orderNo: r.purchase_order_no || '', customerName: r.customer_name || '', productName: r.product_name || '', productQuantity: r.product_quantity || 0, items, totalOrdered: oTotal, totalReceived: rTotal, pct: orderPct }
    })
    const allComplete = orders.every(o => o.items.every(m => m.received >= m.ordered))
    const totalPct = allOrdered > 0 ? (allComplete ? 100.0 : Math.min(Math.round(allReceived / allOrdered * 100 * 10) / 10, 99.9)) : 0
    supplierDetailOrderNo.value = orderNo
    supplierDetail.value = { name: supplierName, orders, totalOrdered: allOrdered, totalReceived: allReceived, totalPct }; showSupplierDialog.value = true
  } catch (e) { console.error('供应商详情加载失败:', e); toast('加载失败', 'error') }
}

const showReceiveDialog = ref(false)
const receiveItem = reactive({ id: 0, name: '', ordered: 0, received: 0, remaining: 0 })
const receiveQty = ref<number | null>(null), receiveRemark = ref('')
function openReceive(item: RegItem) { receiveItem.id = item.id; receiveItem.name = item.material_name; receiveItem.ordered = parseFloat(String(item.ordered_quantity || 0)); receiveItem.received = parseFloat(String(item.received_quantity || 0)); receiveItem.remaining = receiveItem.ordered - receiveItem.received; receiveQty.value = null; receiveRemark.value = ''; showReceiveDialog.value = true }
function openReceiveById(itemId: number, name: string, ordered: number, received: number) { receiveItem.id = itemId; receiveItem.name = name; receiveItem.ordered = ordered; receiveItem.received = received; receiveItem.remaining = ordered - received; receiveQty.value = null; receiveRemark.value = ''; showReceiveDialog.value = true }
async function submitReceive() { if (!receiveQty.value || receiveQty.value <= 0) { toast('请输入有效的收货数量', 'warning'); return }; try { const res = await materialApi.receive(receiveItem.id, { received_quantity: receiveQty.value, remark: receiveRemark.value }) as any; if (res.success) { toast(res.auto_completed ? '收货完成，该订单已全部到货，已转入历史记录' : (res.message || '收货登记成功'), res.auto_completed ? 'success' : 'info'); showReceiveDialog.value = false; const newReceived = receiveItem.received + (receiveQty.value || 0); if (showSupplierDialog.value && supplierDetail.value) { for (const o of supplierDetail.value.orders) { for (const m of o.items) { if (m.firstItemId === receiveItem.id || m.name === receiveItem.name) { m.received = newReceived; m.remaining = m.ordered - newReceived; m.pct = m.ordered > 0 && newReceived < m.ordered ? Math.min(Math.round(newReceived / m.ordered * 100 * 10) / 10, 99.9) : (newReceived >= m.ordered && m.ordered > 0 ? 100 : 0); if (newReceived >= m.ordered) m.firstItemId = null } } } const oAllComplete = supplierDetail.value.orders.every(o => o.items.every(m => m.received >= m.ordered)); supplierDetail.value.totalReceived = supplierDetail.value.orders.reduce((s, o) => s + o.items.reduce((s2, m) => s2 + m.received, 0), 0); supplierDetail.value.totalPct = supplierDetail.value.totalOrdered > 0 ? (oAllComplete ? 100.0 : Math.min(Math.round(supplierDetail.value.totalReceived / supplierDetail.value.totalOrdered * 100 * 10) / 10, 99.9)) : 0 } if (showDetailDialog.value && detailData.value) { const dItem = (detailData.value.items || []).find((i: RegItem) => i.id === receiveItem.id); if (dItem) { dItem.received_quantity = newReceived; dItem.remaining_quantity = parseFloat(String(dItem.ordered_quantity || 0)) - newReceived; dItem.progress = dItem.ordered_quantity > 0 && newReceived < dItem.ordered_quantity ? Math.min(Math.round(newReceived / dItem.ordered_quantity * 100 * 10) / 10, 99.9) : (newReceived >= dItem.ordered_quantity && dItem.ordered_quantity > 0 ? 100 : 0) } } loadProgress(pPage.value) } else toast(res.message || '登记失败', 'error') } catch (e) { console.error('收货操作失败:', e); toast('操作失败', 'error') } }

const showOrderPreviewDialog = ref(false), orderPreview = ref<OrderPreview | null>(null)
async function previewOrder(orderNo: string) { try { const res = await materialApi.purchaseOrderPreview(orderNo) as any; if (res.success === false) { toast(res.message || '加载失败', 'error'); return }; orderPreview.value = res.order ?? null; showOrderPreviewDialog.value = true } catch (e) { console.error('订单预览加载失败:', e); toast('加载失败', 'error') } }

async function exportData() { toast('正在导出...', 'info'); try { const res = await materialApi.export({ order_no: pFilters.orderNo, supplier: pFilters.supplier, start_date: pFilters.startDate, end_date: pFilters.endDate }) as any; if (res.success && res.html) { const blob = new Blob([res.html], { type: 'application/vnd.ms-excel' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = '来料进度汇总.xls'; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); toast('导出成功', 'success') } else toast(res.message || '导出失败', 'error') } catch (e) { console.error('导出失败:', e); toast('导出失败', 'error') } }
async function exportHistory() { toast('正在导出...', 'info'); try { const res = await materialApi.export({}) as any; if (res.success && res.html) { const blob = new Blob([res.html], { type: 'application/vnd.ms-excel' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = '来料历史汇总.xls'; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); toast('导出成功', 'success') } else toast(res.message || '导出失败', 'error') } catch (e) { console.error('导出失败:', e); toast('导出失败', 'error') } }

onMounted(() => {
  switchToProgress()
})
</script>

<style scoped>
/* === Layout === */
.mr-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.mr-main-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.mr-main-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
}

/* === Top Bar (Header + Tabs unified) === */
.mr-top-bar {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: flex-start;
  padding: 10px 24px;
  background: transparent;
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

.mr-top-left h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.mr-top-left small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

.mr-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.mr-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
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
  transition: all 2s ease;
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

/* === Stats Cards === */
.mr-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.mr-sc {
  border-radius: 14px;
  padding: 18px 20px;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: transform 0.3s ease;
}

.mr-sc:hover {
  transform: translateY(-1px);
}

.mr-sc.s-total { background: var(--color-purple-50, #FAF5FF); }
.mr-sc.s-pending { background: #FFF7ED; }
.mr-sc.s-partial { background: var(--color-primary-50, #EFF6FF); }
.mr-sc.s-completed { background: var(--color-success-50, #ECFDF5); }
.mr-sc.s-progress { background: linear-gradient(135deg, var(--color-primary-50, #EFF6FF), var(--color-success-50, #ECFDF5)); }

.mr-sc-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.s-total .mr-sc-icon { background: var(--color-purple-100, #E9D5FF); color: var(--color-purple-600, #7C3AED); }
.s-pending .mr-sc-icon { background: #FED7AA; color: #C2410C; }
.s-partial .mr-sc-icon { background: var(--color-primary-100, #DBEAFE); color: var(--color-primary-600, #4A7DE8); }
.s-completed .mr-sc-icon { background: var(--color-success-100, #D1FAE5); color: var(--color-success-600, #059669); }
.s-progress .mr-sc-icon { background: var(--color-primary-100, #DBEAFE); color: var(--color-primary-600, #4A7DE8); }

.mr-sc-info { flex: 1; min-width: 0; }

.mr-sv { font-size: 28px; font-weight: 800; line-height: 1.1; }
.mr-sc.s-pending .mr-sv { color: #C2410C; }
.mr-sc.s-partial .mr-sv { color: var(--color-primary-600, #4A7DE8); }
.mr-sc.s-completed .mr-sv { color: var(--color-success-600, #059669); }
.mr-sc.s-total .mr-sv { color: var(--color-purple-600, #7C3AED); }
.mr-sc.s-progress .mr-sv { color: var(--color-primary-600, #4A7DE8); }

.mr-sl { font-size: 13px; color: var(--color-text-secondary); margin-top: 2px; }

.mr-sc-sub {
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

/* === Section Label === */
.mr-section-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.mr-section-label i {
  color: var(--color-primary-500);
  font-size: 13px;
}

/* === Category Cards === */
.mr-cat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.mr-cat-card {
  border-radius: 12px;
  padding: 18px;
  border-left: 4px solid transparent;
  background: var(--color-surface, #f8fafc);
  transition: all 0.3s ease;
  cursor: default;
}

.mr-cat-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.mr-cat-card.mr-cat-fabric { border-left-color: var(--color-purple-500, #8B5CF6); }
.mr-cat-card.mr-cat-filling { border-left-color: var(--color-warning-500, #FF9F43); }
.mr-cat-card.mr-cat-accessory { border-left-color: var(--color-info-500, #00CFE8); }
.mr-cat-card.mr-cat-packaging { border-left-color: var(--color-success-500, #28C76F); }

.mr-cat-hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.mr-cat-nm { font-size: 14px; font-weight: 700; color: var(--color-text); }
.mr-cat-pg { font-size: 14px; color: var(--color-success-600, #059669); font-weight: 700; }

.mr-cat-bar { height: 6px; background: #E5E7EB; border-radius: 5px; overflow: hidden; margin-bottom: 10px; }

.mr-cat-fill { height: 100%; border-radius: 5px; transition: width 0.5s ease; }
.mr-cat-fill.fabric { background: var(--color-purple-500, #8B5CF6); }
.mr-cat-fill.filling { background: var(--color-warning-500, #FF9F43); }
.mr-cat-fill.accessory { background: var(--color-info-500, #00CFE8); }
.mr-cat-fill.packaging { background: var(--color-success-500, #28C76F); }

.mr-cat-det { display: flex; justify-content: space-between; font-size: 12px; color: var(--color-text-secondary); }

/* === Cards === */
.mr-card {
  background: white;
  border-radius: 14px;
  margin-bottom: 18px;
  overflow: hidden;
}

.mr-card-h {
  padding: 16px 24px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mr-card-t {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}

.mr-card-t i {
  color: var(--color-primary-500);
  font-size: 15px;
}

.mr-card-actions {
  display: flex;
  gap: 8px;
}

.mr-card-b {
  padding: 24px;
}

.mr-card-b--flush {
  padding: 0;
  overflow-x: auto;
}

/* === Chart Row === */
.mr-chart-row {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}

.mr-chart-card {
  background: var(--color-surface, #f8fafc);
  border-radius: 14px;
  padding: 18px;
  overflow: hidden;
}

.mr-chart-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.mr-chart-title i {
  color: var(--color-primary-500);
  font-size: 13px;
}

.mr-chart-body {
  min-height: 160px;
}

.mr-trend { height: 150px; display: flex; align-items: flex-end; gap: 2px; padding: 4px 0; }

.mr-tb {
  flex: 1;
  min-width: 4px;
  border-radius: 2px 2px 0 0;
  transition: height 0.5s ease;
  position: relative;
  cursor: pointer;
}

.mr-tb:hover { background: var(--color-primary-400) !important; }

.mr-tip {
  display: none;
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: var(--color-text, #2D3748);
  color: white;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  z-index: 10;
}

.mr-tb:hover .mr-tip { display: block; }

.mr-pie { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
.mr-pie-chart { width: 160px; height: 160px; border-radius: 50%; position: relative; }
.mr-pie-legend { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.mr-pie-item { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--color-text-secondary); }
.mr-pie-dot { width: 10px; height: 10px; border-radius: 50%; }

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
  font-family: 'Courier New', monospace;
  font-size: 14px;
  color: var(--color-primary-500);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
  transition: color 0.2s ease;
}

.mr-order-link:hover { color: var(--color-primary-700); }

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
@media (max-width: 1200px) {
  .mr-stats { grid-template-columns: repeat(3, 1fr); }
  .mr-cat-grid { grid-template-columns: repeat(2, 1fr); }
  .mr-chart-row { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .mr-stats { grid-template-columns: repeat(2, 1fr); }
  .mr-cat-grid { grid-template-columns: 1fr; }
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
