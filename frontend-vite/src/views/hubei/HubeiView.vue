<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：HeaderTabs + 筛选区（跟随当前 Tab） -->
      <div class="page-card-header">
        <div class="hu-header-left">
          <HeaderTabs />
        </div>
        <!-- 湖北订单 / 订单列表 两个 Tab 共享产品/客户筛选；工序预设 Tab 无筛选栏 -->
        <div v-if="activeTab === 'beile' || activeTab === 'orders'" class="hu-filter-bar">
          <div class="hu-search-field">
            <UiAutocomplete
              ref="productAc"
              v-model="filterOrderNo"
              :searchFn="searchProducts"
              placeholder="输入关键字，下拉选择产品"
              appendTo="self"
              suppress-after-select
              :search-delay-ms="500"
              :show-loading="false"
              @select="applyProductFilter(($event as ProductSuggestion).name)"
            >
              <template #option="{ item }">
                <div class="hu-ac-option">
                  <span class="hu-ac-name">{{ item.name }}</span>
                  <span v-if="item.barcode" class="hu-ac-barcode">{{ item.barcode }}</span>
                </div>
              </template>
            </UiAutocomplete>
          </div>
          <div class="hu-search-field">
            <UiAutocomplete
              ref="customerAc"
              v-model="filterCustomer"
              :searchFn="searchCustomers"
              placeholder="输入关键字，下拉选择客户"
              appendTo="self"
              suppress-after-select
              :search-delay-ms="500"
              :show-loading="false"
              @select="applyCustomerFilter(($event as CustomerSuggestion).name)"
            />
          </div>
          <!-- 订单列表 Tab：工序状态筛选 -->
          <div v-if="activeTab === 'orders'" class="hu-status-field">
            <select v-model="processStatusDraft" class="hu-status-select" title="按外发工序状态筛选">
              <option value="">全部工序状态</option>
              <option value="pending">待开始</option>
              <option value="in_progress">进行中</option>
              <option value="completed">已完成</option>
            </select>
          </div>
          <div class="hu-filter-actions">
            <button class="hu-action-btn hu-action-primary" @click="handleSearchClick()">
              <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
            </button>
            <button class="hu-action-btn" @click="handleReset()" aria-label="重置">
              <FontAwesomeIcon icon="redo" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <!-- 顶层 Tab：湖北订单 / 订单列表 / 工序预设 -->
      <div class="hu-tabs-bar">
        <UiTabs :model-value="activeTab" @update:model-value="activeTab = $event as ActiveTab">
          <UiTabTrigger v-if="canBeile" value="beile" :active="activeTab === 'beile'">
            <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /> 生产订单
          </UiTabTrigger>
          <UiTabTrigger v-if="canOutsource" value="orders" :active="activeTab === 'orders'">
            <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /> 外发工序
          </UiTabTrigger>
          <UiTabTrigger v-if="canOutsource" value="presets" :active="activeTab === 'presets'">
            <FontAwesomeIcon icon="cogs" aria-hidden="true" /> 工序预设
          </UiTabTrigger>
        </UiTabs>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body">
        <!-- 湖北订单：复用 BeileOrderTab（含详情弹窗/通知跳转高亮） -->
        <div v-show="activeTab === 'beile'" class="hu-tab-content">
          <BeileOrderTab ref="beileTab" />
        </div>

        <!-- 订单列表：外发订单 + 工序管理 -->
        <div v-show="activeTab === 'orders'" class="hu-tab-content">
          <OutsourceOrderTab
            :product-filter="appliedProduct"
            :customer-filter="appliedCustomer"
            :process-status-filter="appliedProcessStatus"
          />
        </div>

        <!-- 工序预设：SKU 外发工序模板 -->
        <div v-show="activeTab === 'presets'" class="hu-tab-content">
          <OutsourcePresetTab />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * HubeiView.vue — 湖北订单 + 湖北外发合并页面容器
 *
 * 原 /beile-order（湖北订单）与 /outsource（湖北外发）两个页面合并为
 * 一个页面，顶层 Tab 为：湖北订单 / 订单列表 / 工序预设（原「湖北外发」
 * Tab 已删除，其下两个子 Tab 提升为顶层）。子组件（BeileOrderTab /
 * OutsourceOrderTab / OutsourcePresetTab）原样复用，后端代码与权限体系
 * 均未改动。
 *
 * - 路由：/beile-order 进入时默认「湖北订单」Tab，/outsource 进入时
 *   默认「订单列表」Tab；切换 Tab 不改变 URL（保持导航高亮与通知跳转行为）。
 * - 筛选栏：与 HeaderTabs 同行的产品/客户搜索（湖北订单 / 订单列表共享），
 *   工序状态下拉仅订单列表 Tab 显示；工序预设 Tab 无筛选栏。
 * - 权限：湖北订单 Tab 需 beile_order_view；订单列表 / 工序预设 Tab 需
 *   outsource_manage / outsource_view；无权限的 Tab 直接隐藏。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import BeileOrderTab from '@/views/beile-order/BeileOrderTab.vue'
import OutsourceOrderTab from '@/views/outsource/components/OutsourceOrderTab.vue'
import OutsourcePresetTab from '@/views/outsource/components/OutsourcePresetTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import UiTabs from '@/components/ui/UiTabs.vue'
import UiTabTrigger from '@/components/ui/UiTabTrigger.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import { useAuthStore } from '@/stores/auth'
import { productApi, customerApi } from '@/api'
// FontAwesomeIcon 已在 main.ts 全局注册

const authStore = useAuthStore()
const route = useRoute()

// ===== 权限 =====
const canBeile = computed(() => authStore.hasPermission('beile_order_view'))
const canOutsource = computed(() => authStore.hasAnyPermission(['outsource_manage', 'outsource_view']))

// ===== Tab 状态 =====
type ActiveTab = 'beile' | 'orders' | 'presets'
const activeTab = ref<ActiveTab>('beile')

/** 根据路由路径选择默认顶层 Tab（同时受权限约束） */
function resolveActiveTab(path: string): ActiveTab {
  const preferred: ActiveTab = path.startsWith('/outsource') ? 'orders' : 'beile'
  if (preferred === 'orders' && canOutsource.value) return 'orders'
  if (preferred === 'beile' && canBeile.value) return 'beile'
  if (canOutsource.value) return 'orders'
  return 'beile'
}

onMounted(() => {
  activeTab.value = resolveActiveTab(route.path)
})

// 侧边栏在 /beile-order 与 /outsource 之间切换时（组件复用）同步默认 Tab
watch(() => route.path, (p) => {
  activeTab.value = resolveActiveTab(p)
})

// ===== 筛选状态 =====
/** 湖北订单筛选：状态在 BeileOrderTab 内部，经 ref 暴露 */
const beileTab = ref<InstanceType<typeof BeileOrderTab> | null>(null)

/** 外发订单筛选：容器维护，传入 OutsourceOrderTab */
const filters = ref({ orderNo: '', customer: '' })
const appliedProduct = ref('')
const appliedCustomer = ref('')
/** 工序状态筛选（仅订单列表 Tab）：''=全部 / pending / in_progress / completed */
const processStatusDraft = ref('')
const appliedProcessStatus = ref('')

/** 筛选栏 v-model：按当前 Tab 路由到对应状态 */
const filterOrderNo = computed({
  get: () => (activeTab.value === 'beile' ? beileTab.value?.filters.orderNo ?? '' : filters.value.orderNo),
  set: (v: string) => {
    if (activeTab.value === 'beile') {
      if (beileTab.value) beileTab.value.filters.orderNo = v
    } else {
      filters.value.orderNo = v
    }
  },
})

const filterCustomer = computed({
  get: () => (activeTab.value === 'beile' ? beileTab.value?.filters.customer ?? '' : filters.value.customer),
  set: (v: string) => {
    if (activeTab.value === 'beile') {
      if (beileTab.value) beileTab.value.filters.customer = v
    } else {
      filters.value.customer = v
    }
  },
})

/** UiAutocomplete 为泛型组件，InstanceType 无法推导，用结构化类型描述暴露的句柄 */
type AutocompleteHandle = { setSuppressed: (v: boolean) => void }
const productAc = ref<AutocompleteHandle | null>(null)
const customerAc = ref<AutocompleteHandle | null>(null)

/**
 * 点击查询：确认筛选后抑制两个下拉面板再次展开，
 * 避免编辑已提交的搜索词时面板遮挡表格造成闪烁。
 */
function handleSearchClick() {
  if (activeTab.value === 'beile') {
    beileTab.value?.handleSearch()
    if (beileTab.value?.filters.orderNo.trim()) {
      productAc.value?.setSuppressed?.(true)
    }
    if (beileTab.value?.filters.customer.trim()) {
      customerAc.value?.setSuppressed?.(true)
    }
  } else {
    appliedProduct.value = filters.value.orderNo
    appliedCustomer.value = filters.value.customer
    appliedProcessStatus.value = processStatusDraft.value
    if (filters.value.orderNo.trim()) {
      productAc.value?.setSuppressed?.(true)
    }
    if (filters.value.customer.trim()) {
      customerAc.value?.setSuppressed?.(true)
    }
  }
}

/** 直接选择候选项时同步确认筛选值（不依赖查询按钮） */
function applyProductFilter(name: string) {
  if (activeTab.value === 'beile') {
    beileTab.value?.applyProductFilter(name)
  } else {
    appliedProduct.value = name
  }
}

function applyCustomerFilter(name: string) {
  if (activeTab.value === 'beile') {
    beileTab.value?.applyCustomerFilter(name)
  } else {
    appliedCustomer.value = name
  }
}

function handleReset() {
  if (activeTab.value === 'beile') {
    beileTab.value?.handleReset()
  } else {
    filters.value = { orderNo: '', customer: '' }
    appliedProduct.value = ''
    appliedCustomer.value = ''
    processStatusDraft.value = ''
    appliedProcessStatus.value = ''
  }
}

// ===== 产品自动补全 =====
type ProductSuggestion = { id: number; name: string; barcode?: string }

async function searchProducts(q: string): Promise<ProductSuggestion[]> {
  if (!q.trim()) return []
  try {
    const res = await productApi.search(q)
    const list = Array.isArray(res) ? res : ((res as unknown as { items?: unknown[] }).items ?? [])
    return (list as Array<Record<string, unknown>>).slice(0, 8).map((p) => ({
      id: Number(p.id),
      name: String(p.name ?? ''),
      barcode: p.barcode ? String(p.barcode) : undefined,
    }))
  } catch {
    return []
  }
}

// ===== 客户自动补全 =====
type CustomerSuggestion = { id: number; name: string }

let cachedCustomerNames: CustomerSuggestion[] | null = null

async function searchCustomers(q: string): Promise<CustomerSuggestion[]> {
  try {
    if (!cachedCustomerNames) {
      const names = await customerApi.activeNames()
      cachedCustomerNames = (Array.isArray(names) ? names : []).map((c: unknown) => {
        const entry = c as Record<string, unknown>
        return { id: Number(entry.id), name: String(entry.name ?? '') }
      })
    }
    const kw = q.trim().toLowerCase()
    if (!kw) return cachedCustomerNames.slice(0, 8)
    return cachedCustomerNames.filter((c) => c.name.toLowerCase().includes(kw)).slice(0, 8)
  } catch {
    return []
  }
}
</script>

<style scoped>
.hu-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  contain: layout style;
  overflow-anchor: none;
  overflow: hidden;
}

.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.hu-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

/* 筛选区：header 右侧，与 HeaderTabs 同行 */
.hu-filter-bar {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  padding: 0;
  border-bottom: none;
  flex-shrink: 0;
}
.hu-search-field {
  width: 220px;
}
.hu-ac-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
}
.hu-ac-name {
  color: var(--color-text);
  font-weight: 500;
  font-size: 13px;
}
.hu-ac-barcode {
  color: var(--color-text-muted);
  font-size: 12px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
}
.hu-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.hu-status-field {
  display: flex;
  align-items: center;
}
.hu-status-select {
  height: 33px;
  padding: 0 10px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  box-sizing: border-box;
  cursor: pointer;
  font-family: inherit;
}
.hu-status-select:focus {
  outline: none;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.hu-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  font-family: inherit;
  line-height: inherit;
}
.hu-action-primary { color: var(--color-primary-600); }
.hu-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.hu-action-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}

/* 顶层 Tab 栏 */
.hu-tabs-bar {
  padding: 4px 16px 0;
  display: flex;
  align-items: center;
}
.hu-tabs-bar :deep(.ui-tab-group) {
  margin-bottom: 0;
}

/* 内容区 */
.page-card-body {
  padding: 0;
  scrollbar-gutter: auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.hu-tab-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 900px) {
  .page-card-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  .hu-filter-bar {
    flex-wrap: wrap;
    width: 100%;
  }
  .hu-search-field { width: 160px; }
}
</style>
