<template>
  <div class="m-page">
    <MobileNavBar title="皮套管理" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <!-- 出入库 -->
      <template v-if="activeTab === 'stock'">
        <MFilterChips v-model="direction" :chips="dirChips" style="margin: 12px 0" />
        <div class="m-form-card">
          <div class="m-form-group">
            <label class="m-form-label">皮套 / 产品</label>
            <MSearchBar v-model="productQuery" placeholder="搜索皮套名称 / 69码" @update:model-value="onSearch" />
            <div v-if="results.length" class="m-results">
              <MListItem
                v-for="r in results"
                :key="r.id"
                :title="r.name"
                :subtitle="`库存 ${r.current_stock}`"
                @click="selectItem(r)"
              />
            </div>
            <div v-if="selected" class="m-selected">
              已选：<strong>{{ selected.name }}</strong>
              <span v-if="direction === 'out'">（库存 {{ selected.current_stock }}）</span>
            </div>
          </div>
          <div class="m-form-group">
            <label class="m-form-label">数量</label>
            <input v-model.number="quantity" type="number" min="1" class="m-input" aria-label="数量" />
          </div>
          <div class="m-form-group">
            <label class="m-form-label">备注（选填）</label>
            <input v-model="note" type="text" class="m-input" placeholder="可选" aria-label="备注" />
          </div>
          <button class="m-submit-btn" :disabled="!selected || quantity < 1 || submitting" @click="submit">
            {{ submitting ? '提交中…' : direction === 'in' ? '入库' : '出库' }}
          </button>
        </div>
      </template>

      <!-- 库存 -->
      <template v-if="activeTab === 'inventory'">
        <div style="margin-top: 12px">
          <MSearchBar v-model="invKeyword" placeholder="搜索库存..." @update:model-value="onInvSearch" />
        </div>
        <div v-if="invLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!inventory.length" title="暂无库存数据" />
        <MList v-else>
          <MListItem
            v-for="it in inventory"
            :key="it.id"
            :title="it.parent_id ? `↳ ${it.name}` : it.name"
            :subtitle="it.barcode || '—'"
          >
            <template #value>{{ it.current_stock }}</template>
          </MListItem>
        </MList>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MCaseView — 移动端皮套管理：出入库（搜索选择 SKU + 数量提交）/ 库存查询。
 */
import { ref, onMounted } from 'vue'
import { caseApi } from '@/api'
import type { CaseSearchItem, CaseItem, CaseMovementPayload } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { toISODate } from '@/utils/format'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

const activeTab = ref('stock')
const tabChips = [{ label: '出入库', value: 'stock' }, { label: '库存', value: 'inventory' }]
const direction = ref<'in' | 'out'>('in')
const dirChips = [{ label: '入库', value: 'in' }, { label: '出库', value: 'out' }]

const productQuery = ref('')
const results = ref<CaseSearchItem[]>([])
const selected = ref<CaseSearchItem | null>(null)
const quantity = ref(1)
const note = ref('')
const submitting = ref(false)

async function onSearch() {
  const q = productQuery.value.trim()
  if (!q) { results.value = []; return }
  try {
    results.value = await caseApi.search(q)
  } catch {
    results.value = []
  }
}

function selectItem(item: CaseSearchItem) {
  selected.value = item
  productQuery.value = item.name
  results.value = []
}

async function submit() {
  if (!selected.value || quantity.value < 1 || submitting.value) return
  submitting.value = true
  try {
    const payload: CaseMovementPayload = {
      case_id: selected.value.id,
      direction: direction.value,
      quantity: quantity.value,
      movement_date: toISODate(),
      note: note.value,
    }
    await caseApi.createMovement(payload)
    showToast('提交成功', 'success')
    selected.value = null
    productQuery.value = ''
    quantity.value = 1
    note.value = ''
  } catch {
    showToast('提交失败', 'error')
  } finally {
    submitting.value = false
  }
}

const invKeyword = ref('')
const inventory = ref<CaseItem[]>([])
const invLoading = ref(false)

async function loadInventory() {
  invLoading.value = true
  try {
    const res = await caseApi.inventory({ search: invKeyword.value || undefined, per_page: 200 })
    const flat: CaseItem[] = []
    for (const node of res.inventory) {
      flat.push(node)
      flat.push(...node.children)
    }
    inventory.value = flat
  } catch {
    inventory.value = []
  } finally {
    invLoading.value = false
  }
}

function onInvSearch() {
  void loadInventory()
}

onMounted(() => {
  void loadInventory()
})
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-form-card { background: var(--m-bg-card); border-radius: var(--m-radius-md); box-shadow: var(--m-shadow-card); padding: var(--m-gap-md); }
.m-form-group { margin-bottom: 16px; }
.m-form-label { display: block; font-size: 13px; font-weight: 600; color: var(--m-text-secondary); margin-bottom: 6px; }
.m-input { width: 100%; padding: 10px 12px; border: none; border-radius: 10px; background: var(--m-bg-grouped); font-size: 15px; color: var(--m-text-primary); font-family: inherit; box-sizing: border-box; }
.m-submit-btn { width: 100%; height: 44px; border: none; border-radius: 12px; background: var(--m-accent); color: white; font-size: 16px; font-weight: 600; cursor: pointer; font-family: inherit; margin-top: 8px; }
.m-submit-btn:disabled { opacity: 0.45; }
.m-submit-btn:active:not(:disabled) { opacity: 0.85; }
.m-results { margin-top: 8px; background: var(--m-bg-card); border-radius: 10px; box-shadow: var(--m-shadow-card); overflow: hidden; max-height: 260px; overflow-y: auto; }
.m-selected { margin-top: 8px; font-size: 13px; color: var(--m-text-secondary); }
</style>
