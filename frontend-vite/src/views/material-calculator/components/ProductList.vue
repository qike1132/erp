<template>
  <div ref="productListRef" class="mc-product-list">
    <div v-if="loading" class="mc-loading-state">
      <UiSpinner />
    </div>
    <div v-else-if="products.length === 0" class="mc-empty-state">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />
      <span>暂无产品</span>
    </div>
    <template v-else>
      <VirtualList
        :items="products"
        :item-height="56"
        :container-height="productListHeight"
        :item-key="(p) => p.id"
      >
        <template #default="{ item: p }">
          <div
            :class="[
              'mc-product-item',
              selectedIds.includes(p.id) ? 'selected' : '',
              !p.has_bom ? 'disabled' : '',
            ]"
            @click="p.has_bom && emit('toggle', p)"
          >
            <FontAwesomeIcon :icon="selectedIds.includes(p.id) ? 'square-check' : 'square'" class="mc-checkbox" aria-hidden="true" />
            <div class="mc-product-details">
              <div class="mc-product-name">
                {{ p.name }}
              </div>
              <div v-if="p.barcode" class="mc-product-code">
                {{ p.barcode }}
              </div>
            </div>
            <span :class="['mc-bom-badge', p.has_bom ? 'has-bom' : 'no-bom']">
              {{ p.has_bom ? '有BOM' : '无BOM' }}
            </span>
          </div>
        </template>
      </VirtualList>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import type { MaterialCalcProduct } from '@/api'
import VirtualList from '@/components/ui/VirtualList.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

defineProps<{
  products: MaterialCalcProduct[]
  loading: boolean
  selectedIds: number[]
}>()

const emit = defineEmits<{
  'toggle': [p: MaterialCalcProduct]
}>()

const productListRef = ref<HTMLElement | null>(null)
const productListHeight = ref(600)
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (productListRef.value) {
    resizeObserver = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height
      if (h && h > 0) productListHeight.value = Math.floor(h)
    })
    resizeObserver.observe(productListRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.mc-product-list {
  padding: 8px 12px;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

/* 行高 72 → 52px（虚拟列表步长同步 80 → 56），同屏可见条数 6 → 15。
   边框收敛为 1px，且默认透明 —— 靠 hover/selected 才显形，避免整列被框线切碎。
   去掉 hover 的 translateX(4px)：逐行扫读时横向抖动反而降低可读性。 */
.mc-product-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  margin: 0 0 4px;
  cursor: pointer;
  background: #fff;
  height: calc(100% - 4px);
  box-sizing: border-box;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.mc-product-item:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}

.mc-product-item.selected {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}

.mc-product-item.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.mc-product-item.disabled:hover {
  border-color: transparent;
  background: #fff;
}

/* FontAwesomeIcon 渲染的是 <svg>，尺寸打在 svg 上才生效 */
.mc-checkbox {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: var(--color-slate-300);
  transition: color 0.15s ease;
}

.selected .mc-checkbox {
  color: var(--color-primary-500);
}

/* 名称与条码同一行（原先两行堆叠），行高才能真正压下来 */
.mc-product-details {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.mc-product-name {
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-product-code {
  flex-shrink: 0;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--color-text-muted);
}

.mc-bom-badge {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid;
}

.mc-bom-badge.has-bom {
  background: var(--color-success-50);
  color: var(--color-success-700);
  border-color: var(--color-success-200);
}

/* 「无BOM」是常态而非错误：改用中性灰，避免整列飘红造成告警疲劳 */
.mc-bom-badge.no-bom {
  background: var(--color-slate-100);
  color: var(--color-text-muted);
  border-color: var(--color-border);
}

.mc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 13px;
}

.mc-empty-state svg {
  width: 26px;
  height: 26px;
  opacity: 0.4;
}

.mc-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 13px;
}
</style>