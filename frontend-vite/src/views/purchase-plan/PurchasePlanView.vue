<template>
  <div class="sp-container">
    <div class="sp-card sp-card-main">
      <div class="sp-card-header">
        <HeaderTabs />
        <div class="sp-header-content">
          <div class="sp-header-left">
            <div class="sp-tab-group">
              <button
                :class="['sp-tab', { 'sp-tab-active': viewTab === 'daily' }]"
                @click="viewTab = 'daily'"
              >每日计划</button>
              <button
                :class="['sp-tab', { 'sp-tab-active': viewTab === 'summary' }]"
                @click="viewTab = 'summary'"
              >月度汇总</button>
            </div>
          </div>
        </div>
      </div>

      <div class="sp-toolbar">
        <div class="sp-toolbar-actions">
          <div class="sp-nav">
            <button class="sp-nav-btn" @click="prevMonth"><i class="fas fa-chevron-left" /></button>
            <span class="sp-nav-label">{{ y }}年{{ String(m).padStart(2, '0') }}月</span>
            <button class="sp-nav-btn" @click="nextMonth"><i class="fas fa-chevron-right" /></button>
          </div>
          <div class="sp-search-box">
            <i class="fas fa-search" />
            <input v-model="globalKw" :placeholder="viewTab === 'daily' ? '搜索日期、客户...' : '搜索产品、SKU、客户...'" />
            <button v-if="globalKw" class="sp-search-clear" @click="globalKw = ''"><i class="fas fa-times" /></button>
          </div>
          <button class="sp-action-btn" @click="viewTab === 'daily' ? exportCSV() : exportSkuCSV()">导出</button>
          <button class="sp-action-btn sp-action-btn-primary" @click="showCreate = true"><i class="fas fa-plus" />新建</button>
        </div>
        <div v-if="summaryCustomers.length" class="sp-toolbar-stats-wrapper">
          <div class="sp-toolbar-stats">
            <div class="sp-stat">
              <span class="sp-stat-label">总计划</span>
              <span class="sp-stat-value">{{ sKpi.allQty }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-label">已出</span>
              <span class="sp-stat-value sp-stat-success">{{ sKpi.allShipped }}</span>
            </div>
            <div class="sp-stat">
              <span class="sp-stat-label">剩余</span>
              <span class="sp-stat-value sp-stat-warning">{{ sKpi.allRemain }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="viewTab === 'daily'" class="sp-body">
        <div v-if="isLoading" class="sp-empty"><i class="fas fa-spinner fa-spin" />加载中...</div>
        <div v-else-if="isError" class="sp-empty"><i class="fas fa-exclamation-circle" />加载失败</div>
        <div v-else-if="!rows.length" class="sp-empty"><i class="fas fa-inbox" />本月暂无出货计划</div>
        <div v-else>
          <div class="sp-day-grid">
            <div
              v-for="(r, idx) in filtered"
              :key="r.date"
              class="sp-day-card"
              :class="{
                'sp-day-selected': sel === r.date,
              }"
              @click="sel = sel === r.date ? '' : r.date"
            >
              <div class="sp-day-header">
                <span class="sp-day-badge">{{ r._fullDate }}：{{ fmtQty(r.totalQty) }}</span>
                <span v-if="r._pendingCount > 0" class="sp-day-alert" :class="getAlertClass(r.date)">{{ getAlertLabel(r.date) }}</span>
                <span v-else-if="r._shippedPct === 100" class="sp-day-alert sp-day-done"><i class="fas fa-check" /> 完成</span>
              </div>
              
              <span v-for="(cn, i) in r.customerNames" :key="cn" class="sp-day-customer-tag">
                {{ cn }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="sp-body">
        <div v-if="sLoading" class="sp-empty"><i class="fas fa-spinner fa-spin" />加载中...</div>
        <div v-else-if="!summaryCustomers.length" class="sp-empty"><i class="fas fa-inbox" />本月暂无数据</div>
        <div v-else>
          <div class="sp-customer-tags">
            <button
              :class="['sp-tag', { 'sp-tag-active': !custFilter }]"
              @click="custFilter = ''"
            >全部</button>
            <button
              v-for="c in allCustomers"
              :key="c.customer_id"
              :class="['sp-tag', { 'sp-tag-active': custFilter === c.customer_name }]"
              :title="c.customer_name"
              @click="custFilter = custFilter === c.customer_name ? '' : c.customer_name"
            >{{ c.customer_name }}</button>
          </div>
          <div class="sp-sku-table-container">
            <div class="sp-sku-table-wrapper">
              <table class="sp-sku-table">
                <thead>
                  <tr>
                    <th class="sp-sku-th-customer">客户名称</th>
                    <th class="sp-sku-th-product">产品名称</th>
                    <th class="sp-sku-th-barcode">
                      商品条码
                    </th>
                    <th class="sp-sku-th-number sp-sku-th-sortable" @click="toggleSkuSort('plan')">
                      <span class="sp-sku-th-text">计划数量
                        <i v-if="skuSortField === 'plan'" :class="skuSortDir === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"></i>
                        <i v-else class="fas fa-sort sp-sort-muted"></i>
                      </span>
                    </th>
                    <th class="sp-sku-th-number sp-sku-th-sortable" @click="toggleSkuSort('shipped')">
                      <span class="sp-sku-th-text">已出货
                        <i v-if="skuSortField === 'shipped'" :class="skuSortDir === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"></i>
                        <i v-else class="fas fa-sort sp-sort-muted"></i>
                      </span>
                    </th>
                    <th class="sp-sku-th-number sp-sku-th-sortable" @click="toggleSkuSort('remain')">
                      <span class="sp-sku-th-text">待出货
                        <i v-if="skuSortField === 'remain'" :class="skuSortDir === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down'"></i>
                        <i v-else class="fas fa-sort sp-sort-muted"></i>
                      </span>
                    </th>
                    <th class="sp-sku-th-progress">进度</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(s, i) in sortedSkuList" :key="`${s.customer_name}|${s.product_name}`" :class="{ 'sp-sku-row-odd': i % 2 === 1 }" class="sp-sku-row-clickable" @click="openSkuDetail(s.barcode, s.product_name, s.customer_name)">
                    <td class="sp-sku-td-customer">{{ s.customer_name }}</td>
                    <td class="sp-sku-td-product"><span class="sp-sku-product-name">{{ s.product_name }}</span></td>
                    <td class="sp-sku-td-barcode"><code class="sp-sku-barcode">{{ s.barcode }}</code></td>
                    <td class="sp-sku-td-number">{{ s.plan_qty }}</td>
                    <td class="sp-sku-td-number sp-sku-td-success">{{ s.shipped_qty }}</td>
                    <td class="sp-sku-td-number" :class="{ 'sp-sku-td-warning': s.remain_qty > 0 }">{{ s.remain_qty }}</td>
                    <td class="sp-sku-td-progress">
                      <div class="sp-sku-mini-bar">
                        <div class="sp-sku-mini-fill" :class="{ 'sp-sku-mini-done': s.remain_qty === 0 }" :style="{ width: s._pct + '%' }"></div>
                      </div>
                      <span class="sp-sku-mini-text">{{ s._pct }}%</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="sp-sku-table-footer">
              共 <b>{{ sortedSkuList.length }}</b> 个SKU · 计划总量 <b>{{ skuTotals.plan }}</b> · 已出货 <b class="sp-sku-foot-success">{{ skuTotals.shipped }}</b> · 待出货 <b class="sp-sku-foot-warning">{{ skuTotals.remain }}</b>
            </div>
          </div>
        </div>
      </div>
    </div>

    <Transition name="sp-modal">
      <div v-if="sel && selDetail" class="sp-modal-bg" @click.self="sel = ''">
        <div class="sp-modal">
          <div class="sp-modal-header">
            <div class="sp-modal-header-info">
              <span class="sp-modal-badge">{{ selDetail._dayNum }}日</span>
              <span class="sp-modal-title">{{ selDetail.date }} · 周{{ selDetail._weekday }}</span>
            </div>
            <div class="sp-modal-header-actions">
              <button class="sp-modal-btn" @click="exportDayCSV" title="导出当日"><i class="fas fa-file-export"></i></button>
              <button class="sp-modal-btn sp-modal-btn-close" @click="sel = ''"><i class="fas fa-times"></i></button>
            </div>
          </div>
          <div class="sp-modal-body">
            <div class="sp-modal-stats">
              <span class="sp-modal-stat"><b>{{ selDetail.customerCount }}</b> 客户</span>
              <span class="sp-modal-stat"><b>{{ selDetail.planCount }}</b> 条计划</span>
              <span class="sp-modal-stat"><b>{{ selDetail.totalQty }}</b> 件</span>
              <span class="sp-modal-stat"><b>{{ selDetail._shippedCount }}</b> 已出</span>
              <span class="sp-modal-stat"><b>{{ selDetail._pendingCount }}</b> 待出</span>
            </div>
            <div class="sp-modal-progress">
              <div class="sp-modal-progress-bar">
                <div class="sp-modal-progress-fill" :style="{ width: selDetail._shippedPct + '%' }"></div>
                <span class="sp-modal-progress-text">出货进度 {{ selDetail._shippedPct }}%</span>
              </div>
            </div>
            <div class="sp-modal-split">
              <div class="sp-modal-sidebar">
                <div class="sp-sidebar-search">
                  <i class="fas fa-search"></i>
                  <input v-model="modalKw" placeholder="搜索客户..." />
                </div>
                <div class="sp-sidebar-list">
                  <div
                    v-for="(group, cname) in filteredModalCustomers"
                    :key="cname"
                    class="sp-customer-item"
                    :class="{ 'sp-customer-selected': modalSelCust === cname }"
                    @click="modalSelCust = cname"
                  >
                    <div class="sp-customer-row">
                      <span class="sp-customer-name">{{ cname }}</span>
                      <span class="sp-customer-badge">{{ group.length }}</span>
                    </div>
                    <div class="sp-customer-row-info">
                      <span class="sp-customer-qty">{{ group.reduce((s, p) => s + Number(p.quantity || 0), 0) }} 件</span>
                      <span class="sp-customer-shipped">{{ group.filter(p => p.shipment_status === 'shipped').length }} 已出</span>
                    </div>
                  </div>
                </div>
              </div>
              <div class="sp-modal-main">
                <div v-if="modalSelGroup" class="sp-modal-main-header">
                  <span class="sp-modal-main-title">{{ modalSelCust }}</span>
                  <span class="sp-modal-main-meta">{{ modalSelGroup.length }} 条 · {{ modalSelGroup.reduce((s, p) => s + Number(p.quantity || 0), 0) }} 件</span>
                </div>
                <div v-if="modalSelGroup" class="sp-modal-main-list">
                  <div
                    v-for="p in modalSelGroup"
                    :key="p.detail_id"
                    class="sp-plan-item"
                  >
                    <div class="sp-plan-left">
                      <span class="sp-plan-name">{{ p.product_name }}</span>
                      <code class="sp-plan-barcode">{{ p.barcode }}</code>
                    </div>
                    <div class="sp-plan-middle">
                      <div class="sp-plan-qtys">
                        <div class="sp-plan-qty-item">
                          <span class="sp-plan-qty-label">计划</span>
                          <span class="sp-plan-qty-value">{{ p.quantity }}</span>
                        </div>
                        <div class="sp-plan-qty-item">
                          <span class="sp-plan-qty-label">已出</span>
                          <span class="sp-plan-qty-value sp-qty-green">{{ p.shipped_qty }}</span>
                        </div>
                        <div class="sp-plan-qty-item">
                          <span class="sp-plan-qty-label">待出</span>
                          <span class="sp-plan-qty-value" :class="p.remaining_qty > 0 ? 'sp-qty-orange' : ''">{{ p.remaining_qty }}</span>
                        </div>
                      </div>
                      <div class="sp-plan-progress">
                        <div class="sp-plan-progress-bar">
                          <div class="sp-plan-progress-fill" :class="{ 'sp-progress-done': p.shipped_qty >= p.quantity }" :style="{ width: (p.quantity > 0 ? Math.round((p.shipped_qty / p.quantity) * 100) : 0) + '%' }"></div>
                        </div>
                        <span class="sp-plan-progress-text">{{ p.quantity > 0 ? Math.round((p.shipped_qty / p.quantity) * 100) : 0 }}%</span>
                      </div>
                    </div>
                    <span :class="p.shipment_status === 'shipped' ? 'sp-status-done' : p.shipment_status === 'partial' ? 'sp-status-partial' : 'sp-status-pending'">
                      {{ p.shipment_status === 'shipped' ? '已出货' : p.shipment_status === 'partial' ? '部分出货' : '待出货' }}
                    </span>
                  </div>
                </div>
                <div v-else class="sp-modal-empty">
                  <i class="fas fa-hand-pointer"></i>请从左侧选择客户
                </div>
              </div>
            </div>
          </div>
          <div class="sp-modal-footer">
            <button class="sp-modal-footer-btn" @click="sel = ''">关闭</button>
            <button class="sp-modal-footer-btn sp-modal-footer-btn-primary" @click="exportDayCSV"><i class="fas fa-download"></i> 导出</button>
          </div>
        </div>
      </div>
    </Transition>

    <Transition name="sp-modal">
      <div v-if="skuDetailOpen" class="sp-modal-bg" @click.self="skuDetailOpen = false">
        <div class="sp-sku-detail-modal">
          <div class="sp-sku-detail-header">
            <div>
              <div class="sp-sku-detail-title">{{ skuDetailName }}</div>
              <div class="sp-sku-detail-sub">{{ skuDetailBarcode }}</div>
            </div>
            <button class="sp-modal-btn sp-modal-btn-close" @click="skuDetailOpen = false"><i class="fas fa-times"></i></button>
          </div>
          <div class="sp-sku-detail-body">
            <div v-if="!skuDateDetail.length" class="sp-sku-detail-empty">该 SKU 本月暂无出货计划</div>
            <div v-else class="sp-sku-detail-list">
              <div class="sp-sku-detail-header-row">
                <span class="sp-sku-detail-header-label">日期</span>
                <span class="sp-sku-detail-header-label">数量</span>
              </div>
              <div v-for="item in skuDateDetail" :key="item.date" class="sp-sku-detail-row" :class="{ 'sp-sku-detail-shipped': item.status === 'shipped' }">
                <span class="sp-sku-detail-date">{{ item.date }}</span>
                <span class="sp-sku-detail-qty">{{ item.qty }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>

  <PlanDetailDrawer v-model:open="drwOpen" :plan-id="drwId" @edited="onEdited" />
  <CreateShipmentPlanDialog v-model:open="showCreate" @created="onCreated" />
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useQuery, useQueryClient } from '@tanstack/vue-query';
import { planApi } from '@/api';
import { showToast } from '@/composables/useToast';
import HeaderTabs from '@/layouts/components/HeaderTabs.vue';
import PlanDetailDrawer from './components/PlanDetailDrawer.vue';
import CreateShipmentPlanDialog from './components/CreateShipmentPlanDialog.vue';

const qc = useQueryClient();

const t = new Date();
const y = ref(t.getFullYear());
const m = ref(t.getMonth() + 1);
const globalKw = ref('');
const sel = ref('');
const showCreate = ref(false);
const drwOpen = ref(false);
const drwId = ref(0);
const modalKw = ref('');
const modalSelCust = ref('');
const viewTab = ref<'daily' | 'summary'>('daily');
const skuSortField = ref('customer');
const skuSortDir = ref<'asc' | 'desc'>('desc');
const custFilter = ref('');
const skuDetailOpen = ref(false);
const skuDetailBarcode = ref('');
const skuDetailName = ref('');

watch(globalKw, () => { if (viewTab.value === 'daily') sel.value = ''; });
watch([y, m], () => { sel.value = ''; globalKw.value = ''; });
watch(viewTab, () => { globalKw.value = ''; });
watch(sel, () => {
  modalKw.value = '';
  const firstCust = selDetail.value ? Object.keys(selDetail.value._byCustomer)[0] : '';
  modalSelCust.value = firstCust;
});

const WDS = ['日', '一', '二', '三', '四', '五', '六'];

const { data: d, isLoading, isError, refetch } = useQuery({
  queryKey: ['pp-monthly', () => y.value, () => m.value],
  queryFn: async () => (await planApi.monthly({ year: y.value, month: m.value })) as any,
  staleTime: 30_000,
});

function refetchAll() { refetch(); refetchSummary(); }

interface Plan { detail_id: number; plan_id: number; customer_name: string; product_name: string; barcode: string; quantity: number; shipped_qty: number; remaining_qty: number; plan_date: string; shipment_status: string; }
interface Row { date: string; _dayNum: number; _weekday: string; customerCount: number; planCount: number; totalQty: number; _isPeak: boolean; _shippedCount: number; _pendingCount: number; _shippedPct: number; customerNames: string[]; plans: Plan[]; _byCustomer: Record<string, Plan[]>; _fullDate: string; }

interface CustSumItem { customer_id: number; customer_name: string; plan_qty: number; inventory_qty: number; shipped_qty: number; remaining_qty: number; warning_count: number; }

const { data: sData, isLoading: sLoading, refetch: refetchSummary } = useQuery({
  queryKey: ['pp-summary', () => y.value, () => m.value],
  queryFn: async () => (await planApi.customerSummary({ year: y.value, month: m.value })) as any,
  staleTime: 30_000,
});

const allCustomers = computed<CustSumItem[]>(() => {
  const arr = (sData.value?.customers ?? []) as CustSumItem[];
  return [...arr].sort((a, b) => b.remaining_qty - a.remaining_qty);
});

const summaryCustomers = computed<CustSumItem[]>(() => {
  if (!custFilter.value) return allCustomers.value;
  return allCustomers.value.filter(c => c.customer_name === custFilter.value);
});

const sKpi = computed(() => {
  const cs = summaryCustomers.value;
  const kpi0 = custFilter.value ? String(cs[0]?.plan_qty || 0) + ' 件' : cs.length + ' 客户';
  const lbl0 = custFilter.value ? cs[0]?.customer_name || '—' : '客户合计';
  const planQty = cs.reduce((s, c) => s + Number(c.plan_qty || 0), 0);
  const shipQty = cs.reduce((s, c) => s + Number(c.shipped_qty || 0), 0);
  const remainQty = cs.reduce((s, c) => s + Number(c.remaining_qty || 0), 0);
  const pct = planQty > 0 ? Math.round(shipQty / planQty * 100) : 0;
  return {
    kpi0,
    lbl0,
    allQty: String(planQty),
    allShipped: String(shipQty),
    allRemain: String(remainQty),
    pct,
  };
});

interface SkuRow { barcode: string; product_name: string; plan_qty: number; shipped_qty: number; remain_qty: number; customer_name: string; _pct: number; _odd: boolean; }

const skuSummary = computed<SkuRow[]>(() => {
  const pbd = (d.value?.plans_by_date ?? {}) as Record<string, Plan[]>;
  const byKey: Record<string, { customer_name: string; barcode: string; product_name: string; plan: number; shipped: number; remain: number; }> = {};
  for (const pl of Object.values(pbd)) {
    if (!pl?.length) continue;
    for (const p of pl) {
      if (custFilter.value && p.customer_name !== custFilter.value) continue;
      const customerName = p.customer_name || '未知客户';
      const pn = p.product_name || '—';
      const key = `${customerName}|${pn}`;
      if (!byKey[key]) byKey[key] = { customer_name: customerName, barcode: p.barcode || '—', product_name: pn, plan: 0, shipped: 0, remain: 0 };
      byKey[key].plan += Number(p.quantity || 0);
      byKey[key].shipped += Number(p.shipped_qty || 0);
      byKey[key].remain += Number(p.remaining_qty || 0);
    }
  }
  const list: SkuRow[] = [];
  for (const v of Object.values(byKey)) {
    list.push({
      barcode: v.barcode,
      product_name: v.product_name,
      plan_qty: v.plan,
      shipped_qty: v.shipped,
      remain_qty: v.remain,
      customer_name: v.customer_name,
      _pct: v.plan > 0 ? Math.round(v.shipped / v.plan * 100) : 0,
      _odd: false,
    });
  }
  return list.sort((a, b) => a.customer_name.localeCompare(b.customer_name) || a.barcode.localeCompare(b.barcode));
});

const sortedSkuList = computed<SkuRow[]>(() => {
  let list = [...skuSummary.value];
  if (globalKw.value && viewTab.value === 'summary') {
    const k = globalKw.value.toLowerCase();
    list = list.filter(s => 
      s.barcode.toLowerCase().includes(k) || 
      s.product_name.toLowerCase().includes(k) ||
      s.customer_name.toLowerCase().includes(k)
    );
  }
  const fieldMap: Record<string, keyof SkuRow> = { customer: 'customer_name', barcode: 'barcode', plan: 'plan_qty', shipped: 'shipped_qty', remain: 'remain_qty' };
  const sf = fieldMap[skuSortField.value] ?? 'plan_qty';
  const sd = skuSortDir.value === 'asc' ? 1 : -1;
  // compute total plan_qty per customer
  const custTotal: Record<string, number> = {};
  for (const s of list) {
    custTotal[s.customer_name] = (custTotal[s.customer_name] || 0) + s.plan_qty;
  }
  list.sort((a, b) => {
    const av = a[sf], bv = b[sf];
    let cmp: number;
    if (typeof av === 'string' && typeof bv === 'string') {
      cmp = av.localeCompare(bv);
    } else {
      cmp = ((av as number) - (bv as number));
    }
    if (cmp !== 0) return cmp * sd;
    // primary: customer group by total plan_qty desc
    const ct = (custTotal[b.customer_name] || 0) - (custTotal[a.customer_name] || 0);
    if (ct !== 0) return ct;
    // secondary: within customer, plan_qty desc
    return b.plan_qty - a.plan_qty;
  });
  return list;
});

const skuTotals = computed(() => {
  const list = sortedSkuList.value;
  return {
    plan: list.reduce((s, r) => s + r.plan_qty, 0),
    shipped: list.reduce((s, r) => s + r.shipped_qty, 0),
    remain: list.reduce((s, r) => s + r.remain_qty, 0),
  };
});

const skuDetailCustomer = ref('');

interface SkuDateItem { date: string; day: number; weekday: string; qty: number; customer: string; status: string; }

const skuDateDetail = computed<SkuDateItem[]>(() => {
  const pbd = (d.value?.plans_by_date ?? {}) as Record<string, Plan[]>;
  const pn = skuDetailName.value;
  const cn = skuDetailCustomer.value;
  if (!pn) return [];
  const byDate: Record<string, SkuDateItem> = {};
  for (const [dateStr, plans] of Object.entries(pbd)) {
    if (!plans?.length) continue;
    for (const p of plans) {
      if (p.product_name !== pn || p.customer_name !== cn) continue;
      if (!byDate[dateStr]) {
        const dt = new Date(dateStr + 'T00:00:00');
        byDate[dateStr] = { date: dateStr, day: dt.getDate(), weekday: WDS[dt.getDay()] || '?', qty: 0, customer: p.customer_name || '未知客户', status: p.shipment_status || 'pending' };
      }
      byDate[dateStr].qty += Number(p.quantity || 0);
    }
  }
  const result = Object.values(byDate);
  result.sort((a, b) => a.date.localeCompare(b.date));
  return result;
});

function openSkuDetail(barcode: string, name: string, customer: string) {
  skuDetailBarcode.value = barcode;
  skuDetailName.value = name;
  skuDetailCustomer.value = customer;
  skuDetailOpen.value = true;
}

const rows = computed<Row[]>(() => {
  const pbd = (d.value?.plans_by_date ?? {}) as Record<string, Plan[]>;
  const list: Row[] = [];
  for (const [ds, pl] of Object.entries(pbd)) {
    if (!pl?.length) continue;
    const dt = new Date(ds + 'T00:00:00');
    const ns = new Set(pl.map(p => p.customer_name));
    const tq = pl.reduce((s, p) => s + Number(p.quantity || 0), 0);
    const shipped = pl.filter(p => p.shipment_status === 'shipped').length;
    const pending = pl.filter(p => p.shipment_status !== 'shipped').length;
    const byCust: Record<string, Plan[]> = {};
    for (const p of pl) {
      const cn = p.customer_name || '未知';
      if (!byCust[cn]) byCust[cn] = [];
      byCust[cn].push(p);
    }
    const _fullDate = `${dt.getMonth() + 1}月${dt.getDate()}日`;
    list.push({ date: ds, _dayNum: dt.getDate(), _weekday: WDS[dt.getDay()] || '?', customerCount: ns.size, planCount: pl.length, totalQty: tq, _isPeak: false, _shippedCount: shipped, _pendingCount: pending, _shippedPct: pl.length > 0 ? Math.round(shipped / pl.length * 100) : 0, customerNames: [...ns].sort(), plans: pl, _byCustomer: byCust, _fullDate });
  }
  list.sort((a, b) => a.date.localeCompare(b.date));
  let maxP = 0;
  for (const r of list) { if (r.planCount > maxP) maxP = r.planCount; }
  for (const r of list) { r._isPeak = r.planCount === maxP && maxP > 0; }
  return list;
});

const filtered = computed(() => {
  if (!globalKw.value || viewTab.value !== 'daily') return rows.value;
  const k = globalKw.value.toLowerCase();
  return rows.value.filter(r => r.date.includes(k) || r.customerNames.some(n => n.toLowerCase().includes(k)));
});

const rowMap = computed(() => {
  const mp = new Map<string, Row>();
  for (const r of rows.value) mp.set(r.date, r);
  return mp;
});

const selDetail = computed(() => sel.value ? rowMap.value.get(sel.value) ?? null : null);

const filteredModalCustomers = computed(() => {
  if (!selDetail.value) return {};
  const bc = selDetail.value._byCustomer;
  if (!modalKw.value) return bc;
  const k = modalKw.value.toLowerCase();
  const out: Record<string, Plan[]> = {};
  for (const [cname, group] of Object.entries(bc)) {
    if (cname.toLowerCase().includes(k)) out[cname] = group;
  }
  return out;
});

const modalSelGroup = computed(() => {
  if (!modalSelCust.value || !selDetail.value) return null;
  return selDetail.value._byCustomer[modalSelCust.value] ?? null;
});

const kpis = computed(() => {
  const td = rows.value.length;
  const tp = rows.value.reduce((s, r) => s + r.planCount, 0);
  const allC = new Set<string>(); rows.value.forEach(r => r.customerNames.forEach(n => allC.add(n)));
  let pk = rows.value[0];
  for (const r of rows.value) { if (!pk || r.planCount > pk.planCount) pk = r; }
  return [
    { k: 'days', v: td, l: '出货日', click: undefined },
    { k: 'plans', v: String(tp), l: '计划总数', click: undefined },
    { k: 'peak', v: pk ? `${pk._dayNum}日` : '—', l: '高峰日', click: pk ? () => { sel.value = pk.date; } : undefined },
    { k: 'custs', v: allC.size, l: '客户数', click: undefined },
  ];
});

function fmtQty(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万';
  return String(n);
}

function getDaysDiff(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr + 'T00:00:00');
  return Math.ceil((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function getAlertClass(dateStr: string): string {
  const diff = getDaysDiff(dateStr);
  if (diff < 0) return 'sp-day-overdue';
  if (diff <= 3) return 'sp-day-due-soon';
  return '';
}

function getAlertLabel(dateStr: string): string {
  const diff = getDaysDiff(dateStr);
  if (diff < 0) return '延期 ' + Math.abs(diff) + ' 天';
  if (diff === 0) return '今日出货';
  if (diff <= 3) return '临期 ' + diff + ' 天';
  return '';
}

function exportDayCSV() {
  if (!selDetail.value) return;
  const r = selDetail.value;
  const h = '客户,产品,条码,数量,已出,待出,状态';
  const ls = [h];
  for (const p of r.plans) ls.push([p.customer_name, p.product_name, p.barcode, p.quantity, p.shipped_qty, p.remaining_qty, p.shipment_status === 'shipped' ? '已出货' : '待出货'].join(','));
  const blob = new Blob(['\uFEFF' + ls.join('\n')], { type: 'text/csv;charset=utf-8' });
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = u; a.download = `出货计划_${r.date}_详情.csv`; a.click();
  URL.revokeObjectURL(u);
  showToast('导出成功', 'success');
}

function toggleSkuSort(field: string) {
  if (skuSortField.value === field) {
    skuSortDir.value = skuSortDir.value === 'asc' ? 'desc' : 'asc';
  } else {
    skuSortField.value = field;
    skuSortDir.value = 'desc';
  }
}

function exportSkuCSV() {
  const list = sortedSkuList.value;
  if (!list.length) { showToast('无数据', 'error'); return; }
  const h = '客户名称,产品名称,商品条码,计划数量,已出货,待出货,进度';
  const ls = [h];
  for (const s of list) ls.push([s.customer_name, s.product_name, s.barcode, s.plan_qty, s.shipped_qty, s.remain_qty, s._pct + '%'].join(','));
  const blob = new Blob(['\uFEFF' + ls.join('\n')], { type: 'text/csv;charset=utf-8' });
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = u; a.download = `SKU月度统计_${y.value}年${m.value}月.csv`; a.click();
  URL.revokeObjectURL(u);
  showToast('导出成功', 'success');
}

function prevMonth() { m.value = m.value === 1 ? 12 : m.value - 1; if (m.value === 12) y.value--; }
function nextMonth() { m.value = m.value === 12 ? 1 : m.value + 1; if (m.value === 1) y.value++; }
function goToday() { const t2 = new Date(); y.value = t2.getFullYear(); m.value = t2.getMonth() + 1; }
function openDetail(pid: number) { drwId.value = pid; drwOpen.value = true; }
function onEdited() { qc.invalidateQueries({ queryKey: ['pp-monthly'] }); qc.invalidateQueries({ queryKey: ['pp-summary'] }); }
function onCreated() { showCreate.value = false; qc.invalidateQueries({ queryKey: ['pp-monthly'] }); qc.invalidateQueries({ queryKey: ['pp-summary'] }); }

function exportCSV() {
  const rl = filtered.value;
  if (!rl.length) { showToast('无数据', 'error'); return; }
  const h = '日期,星期,客户数,计划条目数,总量(件),客户';
  const ls = [h];
  for (const r of rl) ls.push([r.date, `周${r._weekday}`, r.customerCount, r.planCount, r.totalQty, `"${r.customerNames.join('、')}"`].join(','));
  const blob = new Blob(['\uFEFF' + ls.join('\n')], { type: 'text/csv;charset=utf-8' });
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = u; a.download = `出货计划_${y.value}年${m.value}月_日汇总.csv`; a.click();
  URL.revokeObjectURL(u);
  showToast('导出成功', 'success');
}
</script>

<style scoped>
.sp-container {
  height: 100%;
  padding: 8px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.sp-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.sp-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}

.sp-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.sp-card-header {
  padding: 14px 24px 0;
  background: transparent;
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.sp-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.sp-header-content {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  flex: 1;
}

.sp-header-left {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.sp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 24px;
  flex-wrap: wrap;
}

.sp-toolbar-stats-wrapper {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: flex-end;
}

.sp-toolbar-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  height: 45px;
  box-sizing: border-box;
  border-radius: var(--radius-input, 12px);
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: transparent;
  transition: all 0.3s ease;
}

.sp-toolbar-stats:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.sp-stat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0;
}

.sp-stat + .sp-stat {
  padding-left: 12px;
  border-left: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-stat-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.sp-stat-value {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.sp-stat-success {
  color: var(--color-success-600);
}

.sp-stat-success .sp-stat-value {
  color: var(--color-success-600);
}

.sp-stat-warning {
  color: var(--color-warning-600);
}

.sp-stat-warning .sp-stat-value {
  color: var(--color-warning-600);
}


.sp-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.sp-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  width: fit-content;
}

.sp-tab {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
  cursor: pointer;
  transition: all 0.3s ease;
  font-family: inherit;
}

.sp-tab:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.sp-tab-active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

.sp-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.sp-nav-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-input, 12px);
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  flex-shrink: 0;
}

.sp-nav-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-nav-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-heading);
  min-width: 90px;
  text-align: center;
  user-select: none;
}

.sp-nav-today {
  padding: 5px 12px;
  border-radius: var(--radius-input, 12px);
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--color-primary-200);
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  cursor: pointer;
  transition: all 0.3s ease;
  font-family: inherit;
  flex-shrink: 0;
}

.sp-nav-today:hover {
  background: var(--color-primary-100);
}

.sp-search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  background: white;
  transition: all 0.3s ease;
  min-width: 180px;
  box-sizing: border-box;
}

.sp-search-box i {
  color: var(--color-text-muted);
  font-size: 12px;
}

.sp-search-box input {
  border: none;
  background: transparent;
  font-size: 14px;
  padding: 10px 0;
  outline: none;
  flex: 1;
  color: var(--color-heading);
  font-family: inherit;
  min-width: 0;
}

.sp-search-box input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

.sp-search-box:focus-within {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(91, 141, 239, 0.1);
}

.sp-search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: var(--color-border-light, #e2e8f0);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 0;
  flex-shrink: 0;
}

.sp-search-clear:hover {
  background: var(--color-primary-100);
  color: var(--color-primary-600);
}

.sp-search-clear i {
  font-size: 10px;
}


.sp-action-btn {
  padding: 7px 14px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-primary-600);
  transition: all 0.3s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.sp-action-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-action-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-action-btn-primary:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  opacity: 0.95;
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.25);
}

.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-day-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.sp-day-card {
  padding: 18px;
  border-radius: 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
  position: relative;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sp-day-card:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.sp-day-selected {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

.sp-day-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 0 8px;
  margin-top: -10px;
}

.sp-day-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 700;
  border-radius: 6px;
  white-space: nowrap;
}

.sp-day-alert {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.sp-day-due-soon {
  background: var(--color-warning-100);
  color: var(--color-warning-700);
}

.sp-day-overdue {
  background: var(--color-danger-100);
  color: var(--color-danger-700);
}

.sp-day-done {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.sp-day-customer-tag {
  display: block;
  font-size: 14px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1.2;
}

.sp-day-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sp-day-metric {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.sp-day-metric-val {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.sp-day-metric-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted);
}


.sp-customer-tags {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  margin-bottom: 18px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  scrollbar-color: var(--color-border-light, #e2e8f0) transparent;
}

.sp-customer-tags::-webkit-scrollbar {
  height: 4px;
}

.sp-customer-tags::-webkit-scrollbar-track {
  background: transparent;
}

.sp-customer-tags::-webkit-scrollbar-thumb {
  background: var(--color-border-light, #e2e8f0);
  border-radius: 2px;
}

.sp-tag {
  padding: 5px 10px;
  border: 1.5px solid var(--color-border-light, #e2e8f0);
  border-radius: 16px;
  background: white;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
  user-select: none;
  white-space: nowrap;
  flex-shrink: 0;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sp-tag:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.sp-tag-active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-sku-table-container {
  margin-bottom: 18px;
}


.sp-sku-table-wrapper {
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-table {
  width: 100%;
  border-collapse: collapse;
}

.sp-sku-table thead {
  background: transparent;
}

.sp-sku-table th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  text-align: left;
}

.sp-sku-table td {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  transition: background 0.2s ease;
}

.sp-sku-table tbody tr:hover td {
  background: var(--color-primary-50);
}

.sp-sku-row-odd td {
  background: transparent;
}

.sp-sku-row-odd:hover td {
  background: var(--color-primary-50);
}

.sp-sku-th-sortable {
  cursor: pointer;
  user-select: none;
}

.sp-sku-th-sortable:hover {
  color: var(--color-primary-500);
}

.sp-sku-th-sortable i {
  margin-left: 4px;
  font-size: 10px;
}

.sp-sort-muted {
  opacity: 0.25;
}

.sp-sku-th-customer,
.sp-sku-td-customer {
  width: 18%;
}

.sp-sku-th-product,
.sp-sku-td-product {
  width: 22%;
}

.sp-sku-th-barcode,
.sp-sku-td-barcode {
  width: 16%;
}

.sp-sku-th-number,
.sp-sku-td-number {
  width: 11%;
  text-align: left;
}

.sp-sku-th-number {
  white-space: nowrap;
  text-align: left;
  padding-right: 4px;
}

.sp-sku-th-number .sp-sku-th-text {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 4px;
  width: 100%;
}

.sp-sku-th-progress,
.sp-sku-td-progress {
  width: 12%;
}

.sp-sku-product-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.sp-sku-barcode {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  font-family: inherit;
  background: transparent;
  padding: 0;
  border-radius: 0;
}

.sp-sku-td-success {
  color: var(--color-success-600);
  font-weight: 600;
}

.sp-sku-td-warning {
  color: var(--color-warning-600);
  font-weight: 600;
}

.sp-sku-td-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sp-sku-mini-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--color-border-light, #e2e8f0);
  overflow: hidden;
  min-width: 60px;
}

.sp-sku-mini-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  transition: width 0.4s ease;
}

.sp-sku-mini-done {
  background: linear-gradient(135deg, var(--color-success-500), var(--color-success-700));
}

.sp-sku-mini-text {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-secondary);
  min-width: 32px;
  text-align: right;
}

.sp-sku-table-footer {
  padding: 12px 14px;
  background: transparent;
  font-size: 12px;
  color: var(--color-text-muted);
  border-top: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-foot-success {
  color: var(--color-success-600);
}

.sp-sku-foot-warning {
  color: var(--color-warning-600);
}

.sp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.sp-empty i {
  font-size: 28px;
  opacity: 0.5;
}

.sp-modal-bg {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(0,0,0,0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.sp-modal {
  width: 1200px;
  max-width: 96vw;
  height: 720px;
  max-height: 94vh;
  background: white;
  border-radius: 18px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.08), 0 24px 80px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sp-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.sp-modal-header-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sp-modal-badge {
  padding: 5px 12px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 13px;
  font-weight: 600;
}

.sp-modal-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-modal-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sp-modal-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.3s ease;
}

.sp-modal-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-modal-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 20px 24px;
}

.sp-modal-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.sp-modal-stat {
  font-size: 14px;
  color: var(--color-text);
}

.sp-modal-stat b {
  color: var(--color-heading);
}

.sp-modal-progress {
  margin-bottom: 20px;
}

.sp-modal-progress-bar {
  position: relative;
  height: 36px;
  background: var(--color-surface);
  border-radius: var(--radius-input);
  overflow: hidden;
  border: 1px solid var(--color-border-light);
}

.sp-modal-progress-fill {
  height: 100%;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-radius: var(--radius-input);
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

.sp-modal-progress-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-modal-split {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 20px;
}

.sp-modal-sidebar {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--color-border-light);
  padding-right: 20px;
}

.sp-sidebar-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-input);
  background: white;
  margin-bottom: 12px;
}

.sp-sidebar-search i {
  color: var(--color-text-muted);
  font-size: 12px;
}

.sp-sidebar-search input {
  border: none;
  background: transparent;
  font-size: 14px;
  padding: 10px 0;
  outline: none;
  flex: 1;
  color: var(--color-heading);
  font-family: inherit;
}

.sp-sidebar-search input::placeholder {
  color: var(--color-text-muted);
  opacity: 1;
}

.sp-sidebar-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.sp-customer-item {
  padding: 12px 14px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  background: white;
  cursor: pointer;
  transition: all 0.3s ease;
}

.sp-customer-item:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
  transform: translateX(4px);
}

.sp-customer-selected {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}

.sp-customer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.sp-customer-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.sp-customer-badge {
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-size: 11px;
  font-weight: 600;
}

.sp-customer-row-info {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.sp-customer-qty {
  font-weight: 500;
}

.sp-customer-shipped {
  font-weight: 500;
  color: var(--color-success-600);
}

.sp-modal-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.sp-modal-main-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.sp-modal-main-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-modal-main-meta {
  font-size: 13px;
  color: var(--color-text-muted);
}

.sp-modal-main-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.sp-plan-item {
  padding: 14px 16px;
  margin-bottom: 10px;
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.3s ease;
}

.sp-plan-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.sp-plan-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.sp-plan-barcode {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.sp-plan-middle {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 20px;
  min-width: 0;
}

.sp-plan-qtys {
  display: flex;
  gap: 20px;
}

.sp-plan-qty-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sp-plan-qty-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sp-plan-qty-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-qty-green {
  color: var(--color-success-600);
}

.sp-qty-orange {
  color: var(--color-warning-600);
}

.sp-plan-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sp-plan-progress-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}

.sp-plan-progress-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  transition: width 0.4s ease;
}

.sp-progress-done {
  background: linear-gradient(135deg, var(--color-success-500), var(--color-success-700));
}

.sp-plan-progress-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  min-width: 36px;
  text-align: right;
}

.sp-status-done {
  padding: 5px 12px;
  border-radius: 8px;
  background: var(--color-success-50);
  color: var(--color-success-600);
  font-size: 12px;
  font-weight: 600;
}

.sp-status-partial {
  padding: 5px 12px;
  border-radius: 8px;
  background: var(--color-warning-50);
  color: var(--color-warning-600);
  font-size: 12px;
  font-weight: 600;
}

.sp-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.sp-modal-footer-btn {
  padding: 8px 18px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light);
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: all 0.3s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
}

.sp-modal-footer-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-modal-footer-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-modal-footer-btn-primary:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  opacity: 0.95;
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.25);
}

.sp-modal-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.sp-modal-empty i {
  font-size: 28px;
  opacity: 0.5;
}

/* ============ SKU Detail Modal ============ */
.sp-sku-row-clickable {
  cursor: pointer;
}

.sp-sku-detail-modal {
  background: white;
  border-radius: var(--radius-modal, 28px);
  box-shadow: 0 12px 48px rgba(0,0,0,0.15);
  width: 90%;
  max-width: 640px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sp-sku-detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-detail-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-sku-detail-sub {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.sp-sku-detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-sku-detail-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 40px 0;
  font-size: 14px;
}

.sp-sku-detail-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.sp-sku-detail-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  margin-bottom: 4px;
}

.sp-sku-detail-header-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.sp-sku-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-detail-row:last-child {
  border-bottom: none;
}

.sp-sku-detail-shipped .sp-sku-detail-date {
  color: var(--color-success-600);
}

.sp-sku-detail-date {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-heading);
}

.sp-sku-detail-qty {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-primary-700);
  font-variant-numeric: tabular-nums;
}
</style>