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
            <MSearchBar v-model="productQuery" placeholder="搜索皮套名称 / 69码" @search="onSearch" />
            <!-- 权限/网络失败要留常驻提示：全局 403 toast 有 3 秒去重，可能一次都不弹 -->
            <p v-if="searchError" role="alert" class="m-case-search-error">
              {{ searchError }}
            </p>
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
          <button class="m-submit-btn" :disabled="!selected || !Number.isInteger(quantity) || quantity < 1 || submitting" @click="submit">
            {{ submitting ? '提交中…' : direction === 'in' ? '入库' : '出库' }}
          </button>
        </div>
      </template>

      <!-- 库存 -->
      <template v-if="activeTab === 'inventory'">
        <div style="margin-top: 12px">
          <MSearchBar v-model="invKeyword" placeholder="搜索库存..." @search="onInvSearch" />
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
        <UiPagination
          v-if="invTotal > MOBILE_LIST_PAGE_SIZE"
          :current-page="invPage"
          :total-pages="Math.ceil(invTotal / MOBILE_LIST_PAGE_SIZE)"
          :total-items="invTotal"
          @update:current-page="(p: number) => { invPage = p; loadInventory() }"
        />
      </template>

      <!-- 皮套设置（产品 → 配件维护） -->
      <template v-if="activeTab === 'settings'">
        <div style="margin-top: 12px">
          <MSearchBar v-model="keyword" placeholder="搜索产品名称 / 69码" />
        </div>
        <MFilterChips v-model="partsFilter" :chips="filterChips" style="margin: 12px 0" />
        <div v-if="isLoading && !products.length" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!filtered.length" title="没有匹配的产品" />
        <MList v-else>
          <MListItem
            v-for="p in filtered"
            :key="p.id"
            :title="p.name"
            :subtitle="p.barcode || '—'"
            @click="openSettings(p)"
          >
            <template #value>{{ p.has_parts ? '有配件' : '无配件' }}</template>
          </MListItem>
        </MList>
      </template>
    </div>

    <!-- 配件维护（底部抽屉） -->
    <MBottomSheet :visible="sheetOpen" :title="selectedMain?.name || '配件维护'" @update:visible="sheetOpen = $event">
      <div v-if="loadingTree" class="m-center"><MSpinner /></div>
      <template v-else>
        <div v-for="pt in selectedParts" :key="pt.id" class="m-part-row">
          <span class="m-part-name">{{ pt.name }}</span>
          <button class="m-part-del" :disabled="saving" @click="askRemovePart(pt)">删除</button>
        </div>
        <div v-if="!selectedParts.length" class="m-part-empty">暂无配件</div>
        <div class="m-part-add">
          <input v-model="newPartName" class="m-input" placeholder="新配件名称（如：鲨鱼帽子）" aria-label="新配件名称" />
          <button class="m-submit-btn" :disabled="!newPartName.trim() || saving" @click="addNewPart">添加配件</button>
        </div>
      </template>
    </MBottomSheet>
  </div>
</template>

<script setup lang="ts">
/**
 * MCaseView — 移动端皮套管理：出入库（搜索选择 SKU + 数量提交）/ 库存查询 / 皮套设置（产品 → 配件）。
 * 出入库与桌面端语义一致：**直接提交**（不经暂存单）。
 */
import { ref, onMounted } from 'vue'
import { caseApi } from '@/api'
import { MOBILE_LIST_PAGE_SIZE } from '@/mobile/constants'
import type { CaseSearchItem, CaseItem, CaseMovementPayload, CaseProduct } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { getErrorStatus } from '@/types/errors'
import { isCanceledError } from '@/api/request'
import { toISODate } from '@/utils/format'
import { useCaseSettings, type PartsFilter } from '@/views/case/composables/useCaseSettings'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import MBottomSheet from '@/mobile/components/MBottomSheet.vue'

const activeTab = ref('stock')
const tabChips = [
  { label: '出入库', value: 'stock' },
  { label: '库存', value: 'inventory' },
  { label: '皮套设置', value: 'settings' },
]
const direction = ref<'in' | 'out'>('in')
const dirChips = [{ label: '入库', value: 'in' }, { label: '出库', value: 'out' }]

const productQuery = ref('')
const results = ref<CaseSearchItem[]>([])
const selected = ref<CaseSearchItem | null>(null)
const quantity = ref(1)
const note = ref('')
const submitting = ref(false)

// 2026-10-17 审计 P1-27：搜索框改为显式提交（@search），并加请求序号——
// 旧请求后到不得覆盖新关键词的结果。
let searchSeq = 0
/** 搜索失败/无权限的常驻提示（不依赖会被去重的全局 403 toast） */
const searchError = ref('')

async function onSearch() {
  const seq = ++searchSeq
  const q = productQuery.value.trim()
  searchError.value = ''
  if (!q) { results.value = []; return }
  try {
    const res = await caseApi.search(q)
    if (seq !== searchSeq) return
    results.value = res
  } catch (e) {
    if (seq !== searchSeq) return
    // 换页/切 tab 会 abort 在途 GET，这不是失败，不能在新页面弹错
    if (isCanceledError(e)) return
    results.value = []
    // 403 也留页面内提示：全局拦截器的 403 toast 有 3 秒去重，可能被前一个请求吃掉
    const status = getErrorStatus(e)
    searchError.value = status === 403 ? '没有皮套查看权限，请联系管理员' : '搜索失败，请重试'
    if (status !== 403) showToast('搜索失败，请重试', 'error')
  }
}

function selectItem(item: CaseSearchItem) {
  selected.value = item
  productQuery.value = item.name
  results.value = []
  searchSeq++ // 选中后作废仍在途的搜索响应
}

async function submit() {
  // 必须同时判整数：小数如 1.5 不满足 `<1` 会被放行，随后后端 int 校验 422，
  // 用户只看到笼统"提交失败"（桌面端 checkedRows 用的是 Number.isInteger，此处对齐）。
  if (!selected.value || !Number.isInteger(quantity.value) || quantity.value < 1 || submitting.value) return
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
    // 提交后必须刷新库存：否则「库存 xx」一直是提交前的数字，
    // 连续出库会按旧库存操作，直到刷新页面才发现超发。
    void loadInventory()
  } catch (e) {
    // 403 已由全局拦截器提示，这里只兜住其余失败，避免同一次失败弹两条
    if (getErrorStatus(e) !== 403) showToast('提交失败，请重试', 'error')
  } finally {
    submitting.value = false
  }
}

const invKeyword = ref('')
const inventory = ref<CaseItem[]>([])
const invLoading = ref(false)
const invPage = ref(1)
const invTotal = ref(0)
// 2026-10-18 OCR 评审：请求序号。库存搜索框 @update:model-value 逐字符触发，
// 翻页也会发新请求，旧响应后到会覆盖成旧关键词的结果。
let invLoadSeq = 0
/** 最近一次成功加载的页码：失败时回退，避免分页器停在无数据的空页 */
let invLoadedPage = 1

async function loadInventory() {
  const seq = ++invLoadSeq
  invLoading.value = true
  try {
    // 2026-10-17 审计 AUD-22：服务端分页（此前固定 per_page=200 无页码，
    // 第 201 条起永久不可达）
    const res = await caseApi.inventory({
      search: invKeyword.value || undefined,
      page: invPage.value,
      per_page: MOBILE_LIST_PAGE_SIZE,
    })
    if (seq !== invLoadSeq) return // 2026-10-18 OCR 评审：丢弃过期响应
    const flat: CaseItem[] = []
    for (const node of res.inventory) {
      flat.push(node)
      flat.push(...node.children)
    }
    inventory.value = flat
    invTotal.value = res.total ?? 0
    invLoadedPage = invPage.value
  } catch {
    if (seq !== invLoadSeq) return
    // 2026-10-18 OCR 复评：页码已前进但数据仍是旧的 → 回退到上次成功页，
    // 保留旧列表（回退会由分页器触发一次重载）
    invPage.value = invLoadedPage
    showToast('库存加载失败，请重试', 'error')
  } finally {
    // 过期请求的 finally 不能关掉新请求的 loading
    if (seq === invLoadSeq) invLoading.value = false
  }
}

function onInvSearch() {
  invPage.value = 1
  void loadInventory()
}

// ===== 皮套设置（复用桌面端 composable） =====
const {
  keyword,
  partsFilter,
  products,
  filtered,
  isLoading,
  selectedMain,
  selectedParts,
  loadingTree,
  selectProduct,
  saving,
  addPart,
  removePart,
} = useCaseSettings()

const filterChips: { label: string; value: PartsFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '有配件', value: 'yes' },
  { label: '无配件', value: 'no' },
]
const sheetOpen = ref(false)
const newPartName = ref('')

async function openSettings(p: CaseProduct) {
  sheetOpen.value = true
  await selectProduct(p.id)
}

async function addNewPart() {
  const n = newPartName.value
  if (!n.trim()) return
  newPartName.value = ''
  await addPart(n)
}

/** 二次确认：误触即删配置项，与桌面端 CaseSettingsPanel 的确认弹窗同口径 */
async function askRemovePart(pt: { id: number; name: string }) {
  if (!window.confirm(`删除配件「${pt.name}」？`)) return
  await removePart(pt.id)
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

/* 配件维护抽屉 */
.m-part-row { display: flex; align-items: center; gap: 10px; padding: 12px 0; border-bottom: 1px solid var(--m-bg-grouped); }
.m-part-name { flex: 1; min-width: 0; font-size: 15px; color: var(--m-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-part-del { height: 32px; padding: 0 12px; border: none; border-radius: 8px; background: var(--color-danger-50); color: var(--color-danger-600); font-size: 13px; font-weight: 600; cursor: pointer; }
.m-part-empty { padding: 16px 0; text-align: center; color: var(--m-text-secondary); font-size: 14px; }
.m-part-add { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; }
.m-case-search-error { margin: 6px 0 0; color: var(--m-accent-red, #d93025); font-size: 13px; }
</style>
