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
          <button :class="['mr-tab-btn', { active: activeTab === 'overview' }]" @click="activeTab = 'overview'">
            监控面板
          </button>
          <button :class="['mr-tab-btn', { active: activeTab === 'progress' }]" @click="switchToProgress">
            来料进度 <span v-if="progressCount > 0" :class="['notification-badge', activeTab === 'progress' ? 'notification-badge-active' : '']">{{ progressCount }}</span>
          </button>
          <button :class="['mr-tab-btn', { active: activeTab === 'history' }]" @click="switchToHistory">
            历史查询
          </button>
          <button v-if="canManage && activeTab === 'progress'" class="mr-btn mr-btn-ghost" @click="exportData" title="导出来料进度数据"><i class="fas fa-file-export" /> 导出</button>
          <button v-if="canManage && activeTab === 'history'" class="mr-btn mr-btn-ghost" @click="exportHistory" title="导出历史数据"><i class="fas fa-file-export" /> 导出历史</button>
        </div>
      </div>
    </div>

    <!-- ========== 监控面板 ========== -->
    <div v-show="activeTab === 'overview'" class="mr-content">
      <!-- Stats Row: colored tinted backgrounds -->
      <div class="mr-stats">
        <div class="mr-sc s-total">
          <div class="mr-sc-icon"><i class="fas fa-clipboard-list" /></div>
          <div class="mr-sc-info"><div class="mr-sv">{{ overview?.total ?? 0 }}</div><div class="mr-sl">总登记数</div></div>
          <div class="mr-sc-sub">近7天 +{{ overview?.recent_registrations ?? 0 }}</div>
        </div>
        <div class="mr-sc s-pending">
          <div class="mr-sc-icon"><i class="fas fa-hourglass-half" /></div>
          <div class="mr-sc-info"><div class="mr-sv">{{ overview?.pending ?? 0 }}</div><div class="mr-sl">未开始</div></div>
        </div>
        <div class="mr-sc s-partial">
          <div class="mr-sc-icon"><i class="fas fa-truck" /></div>
          <div class="mr-sc-info"><div class="mr-sv">{{ overview?.partial ?? 0 }}</div><div class="mr-sl">部分到货</div></div>
        </div>
        <div class="mr-sc s-completed">
          <div class="mr-sc-icon"><i class="fas fa-check-circle" /></div>
          <div class="mr-sc-info"><div class="mr-sv">{{ overview?.completed ?? 0 }}</div><div class="mr-sl">全部到货</div></div>
        </div>
        <div class="mr-sc s-progress">
          <div class="mr-sc-icon"><i class="fas fa-chart-line" /></div>
          <div class="mr-sc-info"><div class="mr-sv">{{ overview?.overall_progress ?? 0 }}%</div><div class="mr-sl">总体进度</div></div>
          <div class="mr-sc-sub">已收 {{ overview?.total_received ?? 0 }} / 采购 {{ overview?.total_ordered ?? 0 }}</div>
        </div>
      </div>

      <!-- Category Progress: compact horizontal bars -->
      <div class="mr-section-label"><i class="fas fa-th-large" /> 分类进度</div>
      <div class="mr-cat-grid">
        <div v-for="cat in categoryStats" :key="cat.category" class="mr-cat-card" :class="'mr-cat-' + cat.category">
          <div class="mr-cat-hd">
            <span class="mr-cat-nm">{{ cat.category_name || CATEGORY_MAP[cat.category] || cat.category }}</span>
            <span class="mr-cat-pg">{{ cat.progress }}%</span>
          </div>
          <div class="mr-cat-bar">
            <div :class="['mr-cat-fill', cat.category]" :style="{ width: cat.progress + '%' }"></div>
          </div>
          <div class="mr-cat-det">
            <span>采购 {{ cat.ordered }}</span>
            <span>已收 {{ cat.received }}</span>
            <span>待收 {{ cat.remaining }}</span>
          </div>
        </div>
        <div v-if="!categoryStats.length" class="mr-empty-inline">暂无分类数据</div>
      </div>

      <!-- Charts: side by side with subtle bg -->
      <div class="mr-section-label"><i class="fas fa-chart-bar" /> 数据趋势</div>
      <div class="mr-chart-row">
        <div class="mr-chart-card">
          <div class="mr-chart-title"><i class="fas fa-chart-line" /> 近30天到货趋势</div>
          <div class="mr-chart-body">
            <div class="mr-trend" v-if="trendData.length">
              <div v-for="(t, idx) in trendData" :key="t.date" class="mr-tb"
                :style="{ height: Math.max(Math.round((Math.max(t.registered, t.received) / trendMax) * 140), 4) + 'px', background: t.registered > 0 ? 'var(--color-primary-200)' : '#e5e7eb' }">
                <div class="mr-tip">{{ t.date }}<br>登记: {{ t.registered }} | 收货: {{ t.received }}</div>
              </div>
            </div>
            <div v-else class="mr-empty-inline">暂无趋势数据</div>
          </div>
        </div>
        <div class="mr-chart-card">
          <div class="mr-chart-title"><i class="fas fa-chart-pie" /> 状态分布</div>
          <div class="mr-chart-body">
            <div class="mr-pie" v-if="distributionData.length">
              <div class="mr-pie-chart" :style="{ background: pieGradient }"></div>
              <div class="mr-pie-legend">
                <div v-for="d in distributionData" :key="d.status" class="mr-pie-item">
                  <div class="mr-pie-dot" :style="{ background: STATUS_COLORS[d.status] || '#999' }"></div>
                  {{ STATUS_NAMES[d.status] || d.status }}: {{ d.count }}
                </div>
              </div>
            </div>
            <div v-else class="mr-empty-inline">暂无分布数据</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 来料进度 ========== -->
    <div v-show="activeTab === 'progress'" class="mr-content">
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
              <tr v-if="pIsLoading"><td colspan="5" class="mr-empty"><i class="fas fa-spinner fa-spin" /><span>加载中...</span></td></tr>
              <tr v-else-if="!progressGroups.length"><td colspan="5" class="mr-empty"><i class="fas fa-inbox" /><span>暂无进行中的来料登记</span></td></tr>
              <tr v-for="row in progressOrderRows" :key="row.order_no" class="mr-order-row"
                @mouseenter="onOrderRowEnter($event)" @mouseleave="onOrderRowLeave($event)">
                <td class="mr-td-bold">{{ row.supplier_name }}</td>
                <td><span class="mr-order-link" @click="previewOrder(row.order_no)" title="点击预览订单详情">{{ row.order_no }}</span></td>
                <td><div class="mr-items-container"><div v-for="i in row.items" :key="i.material_name" class="mr-list-item-row"><span class="mr-list-item-name" :title="i.material_name">{{ i.material_name }}</span><span class="mr-list-item-qty">数量:<b>{{ parseFloat(String(i.ordered_quantity || 0)).toFixed(0) }}</b></span><span class="mr-list-item-rcv">已到货:<b>{{ parseFloat(String(i.received_quantity || 0)).toFixed(0) }}</b></span><div class="mr-list-item-bar"><div :class="['mr-sku-fill', fillClass(i)]" :style="{ width: (i.progress || 0) + '%', height: '100%', borderRadius: '5px' }"></div></div><span class="mr-list-item-pct">{{ i.progress || 0 }}%</span></div></div></td>
                <td><div class="mr-pbar-wrap"><div class="mr-pbar"><div :class="['mr-pfill', row.progress >= 100 ? 'completed' : row.progress > 0 ? 'partial' : 'pending']" :style="{ width: (row.progress || 0) + '%' }"></div></div><span class="mr-pbar-pct">{{ row.progress || 0 }}%</span></div></td>
                <td><div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" @click="viewSupplierDetail(row.supplier_name || '')" title="查看供应商详情"><i class="fas fa-eye" /></button></div></td>
              </tr>
            </tbody>
          </table>
          <UiPagination v-if="pPages > 1" :current-page="pPage" :total-pages="pPages" @update:current-page="loadProgress" />
        </div>
      </div>
    </div>

    <!-- ========== 历史查询 ========== -->
    <div v-show="activeTab === 'history'" class="mr-content">
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
              <tr v-if="hIsLoading"><td colspan="7" class="mr-empty"><i class="fas fa-spinner fa-spin" /><span>加载中...</span></td></tr>
              <tr v-else-if="!hRegistrations.length"><td colspan="7" class="mr-empty"><i class="fas fa-archive" /><span>暂无历史记录</span></td></tr>
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
          <div><div class="mr-det-lb">总进度</div><div class="mr-det-vl">{{ detailData.progress }}% (已到货 {{ detailData.total_received }} / 数量 {{ detailData.total_ordered }})</div></div>
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
    <UiDialog v-model:open="showSupplierDialog" title="供应商来料详情" title-icon="" max-width-class="max-w-[1000px]">
      <template #title-icon><i class="fas fa-clipboard-list" style="color:var(--color-primary-500);"></i></template>
      <div v-if="supplierDetail">
        <div class="mr-det-grid">
          <div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">{{ supplierDetail.name }}</div></div>
          <div><div class="mr-det-lb">物料种类</div><div class="mr-det-vl">{{ supplierDetail.materials.length }} 种</div></div>
          <div><div class="mr-det-lb">总进度</div><div class="mr-det-vl">{{ supplierDetail.totalPct }}% (已到货 {{ supplierDetail.totalReceived.toFixed(0) }} / 数量 {{ supplierDetail.totalOrdered.toFixed(0) }})</div></div>
        </div>
        <h4 style="margin:20px 0 16px;font-size:16px;"><i class="fas fa-cubes" style="color:var(--color-primary-500);"></i> 物料汇总进度</h4>
        <div v-for="m in supplierDetail.materials" :key="m.name" class="mr-det-mat-card">
          <div class="mr-det-mat-top">
            <div class="mr-det-mat-title"><span class="mr-det-mat-name">{{ m.name }}</span><span v-if="m.spec" class="mr-det-mat-spec">{{ m.spec }}</span></div>
            <div class="mr-det-mat-nums"><div class="mr-det-mat-num s-ordered"><small>数量</small><b>{{ m.ordered.toFixed(0) }}</b></div><div class="mr-det-mat-num s-received"><small>已到货</small><b>{{ m.received.toFixed(0) }}</b></div><div class="mr-det-mat-num s-remaining"><small>未到</small><b>{{ m.remaining.toFixed(0) }}</b></div></div>
          </div>
          <div class="mr-det-mat-bottom">
            <div class="mr-det-mat-bar"><div :class="['mr-sku-fill', fillClass({ progress: m.pct, received_quantity: m.received, ordered_quantity: m.ordered })]" :style="{ width: m.pct + '%' }"></div></div>
            <span class="mr-det-mat-pct" :style="{ color: m.received >= m.ordered ? 'var(--color-success-500)' : (m.pct >= 50 ? 'var(--color-primary-500)' : 'var(--color-warning-500)') }">{{ m.pct }}%</span>
            <button v-if="canManage && m.received < m.ordered && m.firstItemId" class="mr-btn mr-btn-success" @click="openReceiveById(m.firstItemId, m.name, m.ordered, m.received)" title="登记收货"><i class="fas fa-box" /> 收货</button>
            <span v-else-if="m.received >= m.ordered" style="color:var(--color-success-500);font-weight:700;font-size:14px;">&#10003; 已完成</span>
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
        <!-- 采购订单基本信息 -->
        <div class="mr-preview-section-label"><i class="fas fa-shopping-cart" /> 采购订单</div>
        <div class="mr-det-grid" style="grid-template-columns:1fr 1fr;">
          <div><div class="mr-det-lb">订单号</div><div class="mr-det-vl" style="color:var(--color-primary-500);">{{ orderPreview.order_no }}</div></div>
          <div><div class="mr-det-lb">状态</div><div class="mr-det-vl"><span :class="['mr-badge', orderPreview.status === 'completed' || orderPreview.status === '已完成' ? 'mr-badge-completed' : orderPreview.status === 'cancelled' ? 'mr-badge-overdue' : 'mr-badge-pending']">{{ ORDER_STATUS_MAP[orderPreview.status] || orderPreview.status }}</span></div></div>
          <div><div class="mr-det-lb">供应商</div><div class="mr-det-vl">{{ orderPreview.supplier_name || '-' }}</div></div>
          <div><div class="mr-det-lb">下单日期</div><div class="mr-det-vl">{{ orderPreview.order_date || '-' }}</div></div>
          <div><div class="mr-det-lb">客户</div><div class="mr-det-vl">{{ orderPreview.customer_name || '-' }}</div></div>
          <div><div class="mr-det-lb">产品/数量</div><div class="mr-det-vl">{{ orderPreview.product_name || '-' }}{{ orderPreview.product_quantity ? ' x' + orderPreview.product_quantity : '' }}</div></div>
        </div>

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
        <div class="mr-preview-section-label" style="margin-top:16px;"><i class="fas fa-list" /> 物料明细 <span class="mr-preview-count">{{ orderPreview.item_count || (orderPreview.items ? orderPreview.items.length : 0) }} 项</span></div>
        <table v-if="orderPreview.items && orderPreview.items.length" class="mr-item-tbl">
          <thead><tr><th>物料名称</th><th>规格</th><th style="text-align:right;">数量</th><th>分类</th></tr></thead>
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
import { ref, reactive, computed } from 'vue'
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

interface SupplierDetail {
  name: string
  materials: SupMat[]
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

const activeTab = ref('overview')

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

const pPage = ref(1), pPages = ref(1), pIsLoading = ref(false)
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

const hPage = ref(1), hPages = ref(1), hIsLoading = ref(false)
const hRegistrations = ref<Registration[]>([])
const hFilters = reactive({ orderNo: '', supplier: '', customer: '', category: '', startDate: '', endDate: '' })

async function loadHistory(page = 1) {
  hPage.value = page; hIsLoading.value = true
  try {
    const params: Record<string, string | number> = { page, per_page: 50 }
    if (hFilters.orderNo) params.order_no = hFilters.orderNo
    if (hFilters.supplier) params.supplier = hFilters.supplier
    if (hFilters.customer) params.customer_name = hFilters.customer
    if (hFilters.category) params.material_category = hFilters.category
    if (hFilters.startDate) params.start_date = hFilters.startDate
    if (hFilters.endDate) params.end_date = hFilters.endDate
    const data = await materialApi.history(params) as any
    hRegistrations.value = data.registrations || []
    hPages.value = data.pages ?? data.total_pages ?? 1
  } catch (e) { console.error('历史加载失败:', e); toast('加载失败', 'error') } finally { hIsLoading.value = false }
}

function resetHistoryFilters() { Object.assign(hFilters, { orderNo: '', supplier: '', customer: '', category: '', startDate: '', endDate: '' }); loadHistory(1) }
function materialSummary(r: Registration) {
  const items = r.items || []
  if (!items.length) return '-'
  return items.map(i => i.material_name).join(', ')
}

async function loadProgress(page = 1) {
  pPage.value = page; pIsLoading.value = true
  try {
    const params: Record<string, string | number> = { page, per_page: 50 }
    if (pFilters.supplier) params.supplier = pFilters.supplier
    if (pFilters.orderNo) params.order_no = pFilters.orderNo
    if (pFilters.customer) params.customer_name = pFilters.customer
    if (pFilters.category) params.material_category = pFilters.category
    if (pFilters.startDate) params.start_date = pFilters.startDate
    if (pFilters.endDate) params.end_date = pFilters.endDate
    const data = await materialApi.registrations(params) as any
    progressGroups.value = groupBySupplier((data.registrations || []).filter((r: Registration) => r.status !== 'completed'))
    pPages.value = data.pages ?? data.total_pages ?? 1
  } catch (e) { console.error('进度加载失败:', e); toast('加载失败', 'error') } finally { pIsLoading.value = false }
}

function groupBySupplier(registrations: Registration[]): SupplierGroup[] {
  const map: Record<string, SupplierGroup> = {}
  registrations.forEach(r => {
    const key = r.supplier_name || '未知供应商'
    if (!map[key]) map[key] = { supplier_name: key, orders: [], allItems: [] }
    const displayItems = pFilters.category ? (r.items || []).filter((i: RegItem) => i.material_category === pFilters.category) : (r.items || [])
    map[key].orders.push({ id: r.id, order_no: r.purchase_order_no, customer_name: r.customer_name, product_name: r.product_name, product_quantity: r.product_quantity, items: displayItems, status: r.status, progress: r.progress, total_ordered: Number(r.total_ordered), total_received: Number(r.total_received) })
    displayItems.forEach((item: RegItem) => {
      const exist = map[key].allItems.find((ai: MatSummary) => ai.material_name === item.material_name && ai.material_category === item.material_category)
      if (exist) { exist.ordered_quantity += parseFloat(String(item.ordered_quantity || 0)); exist.received_quantity += parseFloat(String(item.received_quantity || 0)); exist.remaining_quantity = exist.ordered_quantity - exist.received_quantity; exist.progress = exist.ordered_quantity > 0 ? (exist.received_quantity >= exist.ordered_quantity ? 100.0 : Math.min(Math.round(exist.received_quantity / exist.ordered_quantity * 100 * 10) / 10, 99.9)) : 0 }
      else map[key].allItems.push({ material_name: item.material_name, material_category: item.material_category, specification: item.specification || '', unit: item.unit || '', ordered_quantity: parseFloat(String(item.ordered_quantity || 0)), received_quantity: parseFloat(String(item.received_quantity || 0)), remaining_quantity: parseFloat(String(item.remaining_quantity || 0)), progress: item.progress || 0 })
    })
  })
  return Object.values(map)
}

function resetProgressFilters() { Object.assign(pFilters, { supplier: '', orderNo: '', customer: '', category: '', startDate: '', endDate: '' }); loadProgress(1) }
function switchToProgress() { activeTab.value = 'progress'; loadProgress(1) }
function switchToHistory() { activeTab.value = 'history'; loadHistory(1) }
function fillClass(item: { progress?: number; received_quantity: number | string; ordered_quantity: number | string }) { const pct = item.progress || 0; if (Number(item.received_quantity) >= Number(item.ordered_quantity)) return 'full'; if (pct >= 50) return 'half'; if (pct > 0) return 'low'; return 'zero' }
function progressCls(g: SupplierGroup) { const pct = supplierPct(g); if (pct >= 100) return 'completed'; if (pct > 0) return 'partial'; return 'pending' }
function supplierPct(g: SupplierGroup) { const o = g.allItems.reduce((s: number, i: MatSummary) => s + i.ordered_quantity, 0); const r = g.allItems.reduce((s: number, i: MatSummary) => s + i.received_quantity, 0); const c = g.allItems.every((i: MatSummary) => i.received_quantity >= i.ordered_quantity); if (o <= 0) return 0; return c ? 100.0 : Math.min(Math.round(r / o * 100 * 10) / 10, 99.9) }

const showDetailDialog = ref(false), detailData = ref<Registration | null>(null)
async function viewDetail(regId: number) { try { const res = await materialApi.registrationDetail(regId) as any; if (res.success === false) { toast('加载失败', 'error'); return }; detailData.value = res.registration ?? null; showDetailDialog.value = true } catch (e) { console.error('详情加载失败:', e); toast('加载失败', 'error') } }

const showSupplierDialog = ref(false), supplierDetail = ref<SupplierDetail | null>(null)
async function viewSupplierDetail(supplierName: string) {
  try {
    const data = await materialApi.registrations({ supplier: supplierName, per_page: 50 }) as any
    if (!data.registrations) { toast('加载失败', 'error'); return }
    const regList: any[] = data.registrations.filter((r: any) => r.status !== 'completed')
    if (!regList.length) { toast('无采购中数据', 'warning'); return }
    const materialMap: Record<string, { ordered: number; received: number; remaining: number; unit: string; spec: string; itemIds: { id: number; ordered: number; received: number }[] }> = {}; let allOrdered = 0, allReceived = 0
    regList.forEach((r: any) => { allOrdered += parseFloat(String(r.total_ordered || 0)); allReceived += parseFloat(String(r.total_received || 0)); (r.items || []).forEach((i: RegItem) => { const key = (i.material_name || '').trim(); if (!materialMap[key]) materialMap[key] = { ordered: 0, received: 0, remaining: 0, unit: i.unit || '', spec: i.specification || '', itemIds: [] }; const m = materialMap[key]; m.ordered += parseFloat(String(i.ordered_quantity || 0)); m.received += parseFloat(String(i.received_quantity || 0)); m.remaining += parseFloat(String(i.remaining_quantity || 0)); m.itemIds.push({ id: i.id, ordered: parseFloat(String(i.ordered_quantity || 0)), received: parseFloat(String(i.received_quantity || 0)) }) }) })
    const materials: SupMat[] = Object.keys(materialMap).map(name => { const m = materialMap[name]; const pct = m.ordered > 0 ? (m.received >= m.ordered ? 100.0 : Math.min(Math.round(m.received / m.ordered * 100 * 10) / 10, 99.9)) : 0; return { name, ...m, pct, firstItemId: m.itemIds.find((x) => x.received < x.ordered)?.id ?? null } })
    const allComplete = materials.every(m => m.received >= m.ordered)
    const totalPct = allOrdered > 0 ? (allComplete ? 100.0 : Math.min(Math.round(allReceived / allOrdered * 100 * 10) / 10, 99.9)) : 0
    supplierDetail.value = { name: supplierName, materials, totalOrdered: allOrdered, totalReceived: allReceived, totalPct }; showSupplierDialog.value = true
  } catch (e) { console.error('供应商详情加载失败:', e); toast('加载失败', 'error') }
}

const showReceiveDialog = ref(false)
const receiveItem = reactive({ id: 0, name: '', ordered: 0, received: 0, remaining: 0 })
const receiveQty = ref<number | null>(null), receiveRemark = ref('')
function openReceive(item: RegItem) { receiveItem.id = item.id; receiveItem.name = item.material_name; receiveItem.ordered = parseFloat(String(item.ordered_quantity || 0)); receiveItem.received = parseFloat(String(item.received_quantity || 0)); receiveItem.remaining = receiveItem.ordered - receiveItem.received; receiveQty.value = null; receiveRemark.value = ''; showReceiveDialog.value = true }
function openReceiveById(itemId: number, name: string, ordered: number, received: number) { receiveItem.id = itemId; receiveItem.name = name; receiveItem.ordered = ordered; receiveItem.received = received; receiveItem.remaining = ordered - received; receiveQty.value = null; receiveRemark.value = ''; showReceiveDialog.value = true }
async function submitReceive() { if (!receiveQty.value || receiveQty.value <= 0) { toast('请输入有效的收货数量', 'warning'); return }; try { const res = await materialApi.receive(receiveItem.id, { received_quantity: receiveQty.value, remark: receiveRemark.value }) as any; if (res.success) { toast(res.auto_completed ? '收货完成，该订单已全部到货，已转入历史记录' : (res.message || '收货登记成功'), res.auto_completed ? 'success' : 'info'); showReceiveDialog.value = false; showDetailDialog.value = false; showSupplierDialog.value = false; loadProgress(pPage.value) } else toast(res.message || '登记失败', 'error') } catch (e) { console.error('收货操作失败:', e); toast('操作失败', 'error') } }

const showOrderPreviewDialog = ref(false), orderPreview = ref<OrderPreview | null>(null)
async function previewOrder(orderNo: string) { try { const res = await materialApi.purchaseOrderPreview(orderNo) as any; if (res.success === false) { toast(res.message || '加载失败', 'error'); return }; orderPreview.value = res.order ?? null; showOrderPreviewDialog.value = true } catch (e) { console.error('订单预览加载失败:', e); toast('加载失败', 'error') } }

async function exportData() { toast('正在导出...', 'info'); try { const res = await materialApi.export({ order_no: pFilters.orderNo, supplier: pFilters.supplier, start_date: pFilters.startDate, end_date: pFilters.endDate }) as any; if (res.success && res.html) { const blob = new Blob([res.html], { type: 'application/vnd.ms-excel' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = '来料进度汇总.xls'; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); toast('导出成功', 'success') } else toast(res.message || '导出失败', 'error') } catch (e) { console.error('导出失败:', e); toast('导出失败', 'error') } }
async function exportHistory() { toast('正在导出...', 'info'); try { const res = await materialApi.export({}) as any; if (res.success && res.html) { const blob = new Blob([res.html], { type: 'application/vnd.ms-excel' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = '来料历史汇总.xls'; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); toast('导出成功', 'success') } else toast(res.message || '导出失败', 'error') } catch (e) { console.error('导出失败:', e); toast('导出失败', 'error') } }

function onOrderRowEnter(e: MouseEvent) {
  const tr = e.currentTarget as HTMLElement
  tr.style.transition = 'box-shadow 5s ease, border-color 5s ease'
  tr.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1)'
  tr.style.borderColor = '#93c5fd'
  const tds = tr.querySelectorAll<HTMLElement>('td')
  if (tds[0]) { tds[0].style.transition = 'border-left-color 5s ease'; tds[0].style.borderLeftColor = '#93c5fd' }
  if (tds.length) { const last = tds[tds.length - 1]; last.style.transition = 'border-right-color 5s ease'; last.style.borderRightColor = '#93c5fd' }
}

function onOrderRowLeave(e: MouseEvent) {
  const tr = e.currentTarget as HTMLElement
  tr.style.boxShadow = ''
  tr.style.borderColor = ''
  const tds = tr.querySelectorAll<HTMLElement>('td')
  if (tds[0]) { tds[0].style.borderLeftColor = '' }
  if (tds.length) { tds[tds.length - 1].style.borderRightColor = '' }
}
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
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
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
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-light, #e2e8f0);
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
.mr-det-mat-card { margin-bottom: 20px; background: white; border-radius: 12px; border: 1px solid var(--color-border-light, #e2e8f0); overflow: hidden; }
.mr-det-mat-top { padding: 24px 28px; display: flex; align-items: center; gap: 32px; }
.mr-det-mat-title { display: flex; align-items: baseline; gap: 8px; flex-shrink: 0; min-width: 0; }
.mr-det-mat-name { font-size: 18px; font-weight: 700; color: var(--color-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; line-height: 1.2; }
.mr-det-mat-spec { font-size: 18px; font-weight: 700; color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.mr-det-mat-nums { display: flex; gap: 1px; flex: 1; background: var(--color-border-light, #e2e8f0); border-radius: 10px; overflow: hidden; }
.mr-det-mat-num { flex: 1; background: white; padding: 10px 16px; text-align: center; }
.mr-det-mat-num small { display: block; font-size: 14px; font-weight: 600; color: var(--color-text-muted); line-height: 1.2; margin-bottom: 8px; }
.mr-det-mat-num b { display: block; font-size: 22px; font-weight: 700; line-height: 1.2; }
.mr-det-mat-num.s-ordered b { color: var(--color-text); }
.mr-det-mat-num.s-received b { color: var(--color-success-500, #28C76F); }
.mr-det-mat-num.s-remaining b { color: var(--color-warning-500, #FF9F43); }
.mr-det-mat-bottom { padding: 18px 28px 24px; display: flex; align-items: center; gap: 16px; }
.mr-det-mat-bar { flex: 1; height: 14px; background: #E5E7EB; border-radius: 10px; overflow: hidden; }
.mr-det-mat-pct { font-size: 20px; font-weight: 800; width: 65px; text-align: right; flex-shrink: 0; }

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
  .mr-det-mat-top { flex-direction: column; align-items: stretch; }
  .mr-det-mat-nums { flex-direction: column; }
  .mr-det-mat-bottom { flex-wrap: wrap; }
}
</style>
