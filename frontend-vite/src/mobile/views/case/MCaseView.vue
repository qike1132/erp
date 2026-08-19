<template>
  <div class="m-page">
    <MobileNavBar title="皮套管理" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <template v-if="activeTab === 'stock'">
        <MFilterChips v-model="stockMode" :chips="modeChips" style="margin-bottom: 12px" />
        <div class="m-form-card">
          <div class="m-form-group">
            <label class="m-form-label">客户</label>
            <select v-model="form.customer" class="m-select" aria-label="客户">
              <option value="">请选择客户</option>
              <option v-for="c in customers" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
          <div class="m-form-group">
            <label class="m-form-label">产品</label>
            <MSearchBar v-model="productSearch" placeholder="搜索产品..." />
          </div>
          <div class="m-form-group">
            <label class="m-form-label">数量</label>
            <input v-model.number="form.quantity" type="number" min="1" class="m-input" aria-label="数量" />
          </div>
          <div class="m-form-group">
            <label class="m-form-label">备注</label>
            <input v-model="form.note" type="text" class="m-input" placeholder="可选" aria-label="可选" />
          </div>
          <button class="m-submit-btn" @click="handleStockSubmit" :aria-label="stockMode === 'stockin' ? '入库' : '出库'">{{ stockMode === 'stockin' ? '入库' : '出库' }}</button>
        </div>
      </template>

      <template v-if="activeTab === 'inventory'">
        <MSearchBar v-model="invKeyword" placeholder="搜索库存..." />
        <div v-if="invLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!inventory.length" title="暂无库存数据" />
        <MList v-else>
          <MListItem v-for="item in inventory" :key="item.product_id" :title="item.product_name || '—'" :subtitle="`${item.customer || ''} · ${item.current_stock || 0}件`" />
        </MList>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { customerApi, stockApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

const activeTab = ref('stock')
const tabChips = [{ label: '出入库', value: 'stock' }, { label: '库存', value: 'inventory' }]
const stockMode = ref('stockin')
const modeChips = [{ label: '入库', value: 'stockin' }, { label: '出库', value: 'stockout' }]

const customers = ref<string[]>([])
const productSearch = ref('')
const form = ref({ customer: '', quantity: 1, note: '' })

const invKeyword = ref('')
const inventory = ref<Array<{ product_id: number; product_name?: string; customer?: string; current_stock?: number }>>([])
const invLoading = ref(false)

async function loadCustomers() {
  try {
    const res = await customerApi.activeNames()
    // 后端返回 [{ id, name }, ...]，只需名称列表供下拉框使用
    customers.value = (res || []).map((c: { id?: number; name?: string }) => c.name).filter(Boolean) as string[]
  } catch { /* */ }
}
async function loadInventory() {
  invLoading.value = true
  try { inventory.value = (await stockApi.inventory({}))?.data || [] } finally { invLoading.value = false }
}

async function handleStockSubmit() {
  if (!form.value.customer || !form.value.quantity) return
  try {
    if (stockMode.value === 'stockin') {
      await stockApi.batchSubmitStockins([{ customer: form.value.customer, product_id: 0, quantity: form.value.quantity, note: form.value.note }])
    } else {
      await stockApi.batchSubmitStockouts([{ customer: form.value.customer, product_id: 0, quantity: form.value.quantity, note: form.value.note }])
    }
    form.value = { customer: '', quantity: 1, note: '' }
    loadInventory()
  } catch { /* */ }
}

onMounted(() => { loadCustomers(); loadInventory() })
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-form-card { background: var(--m-bg-card); border-radius: var(--m-radius-md); box-shadow: var(--m-shadow-card); padding: var(--m-gap-md); }
.m-form-group { margin-bottom: 16px; }
.m-form-label { display: block; font-size: 13px; font-weight: 600; color: var(--m-text-secondary); margin-bottom: 6px; }
.m-input, .m-select { width: 100%; padding: 10px 12px; border: none; border-radius: 10px; background: var(--m-bg-grouped); font-size: 15px; color: var(--m-text-primary); font-family: inherit; box-sizing: border-box; }
.m-select { appearance: none; -webkit-appearance: none; }
.m-submit-btn { width: 100%; height: 44px; border: none; border-radius: 12px; background: var(--m-accent); color: white; font-size: 16px; font-weight: 600; cursor: pointer; font-family: inherit; margin-top: 8px; }
.m-submit-btn:active { opacity: 0.85; }
</style>
