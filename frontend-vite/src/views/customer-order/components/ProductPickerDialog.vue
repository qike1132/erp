<template>
  <UiDialog
    :open="open"
    max-width-class="max-w-[560px]"
    @update:open="emit('update:open', $event)"
  >
    <template #title>选择产品</template>

    <div class="pp-body">
      <p v-if="customerName" class="pp-sub">客户：{{ customerName }}</p>

      <input
        ref="searchRef"
        v-model="keyword"
        class="pp-search"
        type="text"
        placeholder="输入产品名称或69码搜索…"
        aria-label="搜索产品"
      />

      <div class="pp-list">
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          class="pp-item"
          @click="pick(item)"
        >{{ item.name }}</button>
        <p v-if="!items.length" class="pp-empty">{{ emptyText }}</p>
      </div>
    </div>

    <template #footer>
      <div class="pp-foot">
        <span>点击一行即选中并关闭</span>
        <span>仅显示该客户可选</span>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { refDebounced } from '@vueuse/core'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { ProductSuggestion } from '../composables/types'

const props = withDefaults(defineProps<{
  open: boolean
  /** 当前已选客户名；为空表示还没选客户 —— 此时不列 SKU，直接提示先选客户 */
  customerName: string
  /** 浏览模式：列出该客户可见的全部 SKU */
  fetchSkuList: () => Promise<ProductSuggestion[]>
  /** 搜索模式：关键字模糊匹配（与输入框、OCR 共用同一个函数） */
  searchProducts: (q: string) => Promise<ProductSuggestion[]>
  /** 浏览列表的失败原因（空 = 正常）。前置条件（没选客户）由本组件自己判断并提示 */
  skuListError?: string
  searchFailed?: boolean
  /** 输入防抖；测试传 0 可立即生效 */
  debounceMs?: number
}>(), {
  skuListError: '',
  searchFailed: false,
  debounceMs: 250,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  select: [item: ProductSuggestion]
}>()

const keyword = ref('')
const items = ref<ProductSuggestion[]>([])
const searchRef = ref<HTMLInputElement | null>(null)

const dKeyword = refDebounced(keyword, props.debounceMs)
const isSearching = computed(() => !!dKeyword.value.trim())

/**
 * 已经载入过的查询词。用来吃掉「打开时显式加载」与「防抖 watcher」之间的重复请求，
 * 又不误伤「清空关键字要回到浏览列表」这一步（两者查询词不同，不会被误跳）。
 */
let lastLoaded: string | null = null

async function load(rawQuery: string) {
  const query = rawQuery.trim()
  if (query === lastLoaded) return
  lastLoaded = query
  // 浏览模式必须有客户：没客户连请求都不发，由 emptyText 给出「请先选择客户」
  if (!query && !props.customerName.trim()) {
    items.value = []
    return
  }
  items.value = query ? await props.searchProducts(query) : await props.fetchSkuList()
}

watch(() => props.open, async (open) => {
  if (!open) {
    lastLoaded = null
    return
  }
  keyword.value = ''
  await load('')          // 点开立即列出，不等防抖
  searchRef.value?.focus()
}, { immediate: true })

watch(dKeyword, (q) => { void load(q) })

/**
 * 无数据时的文案。三种「空」对用户的下一步完全不同，不能一律写成「暂无数据」：
 * 没选客户要去选客户、搜不到要换关键字、客户真没有要去产品页挂客户。
 */
const emptyText = computed(() => {
  if (!props.customerName.trim()) return props.skuListError || '请先选择客户'
  if (isSearching.value && props.searchFailed) return '搜索失败，请重试'
  if (isSearching.value) return '无匹配结果'
  return props.skuListError || '该客户暂无可用产品，请到产品页给 SKU 挂上该客户'
})

function pick(item: ProductSuggestion) {
  emit('select', item)
  emit('update:open', false)
}
</script>

<style scoped>
.pp-body { padding: 4px 0 0; }
.pp-sub { margin: 0 0 10px; font-size: 12.5px; color: var(--color-text-secondary); }

.pp-search {
  width: 100%;
  padding: 9px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 13.5px;
  color: var(--color-text);
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.pp-search:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.pp-search::placeholder { color: var(--color-text-muted, #94a3b8); }

.pp-list {
  margin-top: 10px;
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light, #f1f5f9);
  border-radius: 10px;
}
.pp-item {
  display: block;
  width: 100%;
  padding: 10px 12px;
  font-size: 13.5px;
  text-align: left;
  color: var(--color-text);
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  cursor: pointer;
  font-family: inherit;
}
.pp-item:last-child { border-bottom: none; }
.pp-item:hover { background: var(--color-primary-50); color: var(--color-primary-600); }

.pp-empty {
  margin: 0;
  padding: 26px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted, #94a3b8);
}

.pp-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  font-size: 11.5px;
  color: var(--color-text-muted, #94a3b8);
}
</style>
