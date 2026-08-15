<template>
  <div class="hu-filter-bar">
    <div class="hu-search-field">
      <UiAutocomplete
        ref="productAc"
        v-model="productQuery"
        :searchFn="searchProducts"
        placeholder="输入关键字，下拉选择产品"
        appendTo="self"
        suppress-after-select
        :search-delay-ms="500"
        :show-loading="false"
        @select="onProductSelect($event as ProductSuggestion)"
      >
        <template #option="{ item }">
          <div class="hu-ac-option">
            <span class="hu-ac-name">{{ item.name }}</span>
            <span v-if="item.barcode" class="hu-ac-barcode">{{ item.barcode }}</span>
          </div>
        </template>
      </UiAutocomplete>
    </div>
    <div v-if="showCustomerSearch" class="hu-search-field">
      <UiAutocomplete
        ref="customerAc"
        v-model="customerQuery"
        :searchFn="searchCustomers"
        placeholder="输入关键字，下拉选择客户"
        appendTo="self"
        suppress-after-select
        :search-delay-ms="500"
        :show-loading="false"
        @select="onCustomerSelect($event as CustomerSuggestion)"
      />
    </div>
    <div v-if="showActions" class="hu-filter-actions">
      <button class="hu-action-btn hu-action-primary" @click="handleSearch()">
        <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
      </button>
      <button class="hu-action-btn" @click="emit('reset')" aria-label="重置">
        <FontAwesomeIcon icon="redo" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * HubeiSearchBar.vue — 湖北订单 / 外发工序 页面共用的筛选栏
 *
 * 原 HubeiView 内的筛选栏提取为独立组件：产品/客户自动补全
 * + 查询/重置按钮，通过 v-model 与事件解耦：
 *
 * Props:
 *   productQuery     - v-model: 产品搜索词
 *   customerQuery    - v-model: 客户搜索词
 *
 * Emits:
 *   selectProduct  - 下拉选中产品: (name: string) => void
 *   selectCustomer - 下拉选中客户: (name: string) => void
 *   search         - 点击查询按钮
 *   reset          - 点击重置按钮
 *
 * 抑制逻辑（选中/查询后下拉不再自动展开，避免面板遮挡表格闪烁）
 * 在组件内部处理，父页面无需关心。
 */
import { ref, computed, watch } from 'vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import { productApi, customerApi } from '@/api'

const productQuery = defineModel<string>('productQuery', { required: true })
const customerQuery = defineModel<string>('customerQuery', { required: true })
const props = defineProps<{ showCustomerSearch?: boolean; showActions?: boolean }>()
const showCustomerSearch = computed(() => props.showCustomerSearch ?? true)
const showActions = computed(() => props.showActions ?? true)

const emit = defineEmits<{
  selectProduct: [name: string]
  selectCustomer: [name: string]
  search: []
  reset: []
}>()

/** UiAutocomplete 为泛型组件，InstanceType 无法推导，用结构化类型描述暴露的句柄 */
type AutocompleteHandle = { setSuppressed: (v: boolean) => void }
const productAc = ref<AutocompleteHandle | null>(null)
const customerAc = ref<AutocompleteHandle | null>(null)

/** 点击查询：确认筛选后抑制两个下拉面板再次展开 */
function handleSearch() {
  if (productQuery.value.trim()) productAc.value?.setSuppressed?.(true)
  if (customerQuery.value.trim()) customerAc.value?.setSuppressed?.(true)
  emit('search')
}

function onProductSelect(item: ProductSuggestion) {
  productQuery.value = item.name
  emit('selectProduct', item.name)
}

function onCustomerSelect(item: CustomerSuggestion) {
  customerQuery.value = item.name
  emit('selectCustomer', item.name)
}

/** 自动重置：输入框被清空时（用户删除了所有关键字），触发重置效果恢复全量列表 */
watch(productQuery, (newVal, oldVal) => {
  if (newVal === '' && oldVal !== '') {
    emit('reset')
  }
})

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

@media (max-width: 900px) {
  .hu-filter-bar {
    flex-wrap: wrap;
    width: 100%;
  }
  .hu-search-field { width: 160px; }
}
</style>
