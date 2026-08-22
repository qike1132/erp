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
        :item-height="80"
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
            <FontAwesomeIcon :icon="selectedIds.includes(p.id) ? 'check-square' : 'square'" class="mc-checkbox" aria-hidden="true" />
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
  padding: 0 16px 16px;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.mc-product-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  margin: 4px 0;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
  background: white;
  height: calc(100% - 8px);
  box-sizing: border-box;
}

.mc-product-item:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
  transform: translateX(4px);
  box-shadow: 0 2px 12px rgba(0, 148, 191, 0.1);
}

.mc-product-item.selected {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 3px 16px rgba(0, 148, 191, 0.15);
}

.mc-product-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mc-product-item.disabled:hover {
  border-color: var(--color-border-light, #e2e8f0);
  background: white;
  transform: none;
  box-shadow: none;
}

.mc-checkbox {
  font-size: 18px;
  cursor: pointer;
  flex-shrink: 0;
  color: var(--color-border, #cbd5e1);
  transition: color 0.2s;
}

.selected .mc-checkbox {
  color: var(--color-primary-500);
}

.mc-product-details {
  flex: 1;
  min-width: 0;
}

.mc-product-name {
  font-weight: 650;
  font-size: 14px;
  color: var(--color-text);
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-product-code {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.mc-bom-badge {
  padding: 5px 10px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.mc-bom-badge.has-bom {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.mc-bom-badge.no-bom {
  background: var(--color-danger-100);
  color: var(--color-danger-800);
}

.mc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}

.mc-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}

.mc-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

.mc-loading-state i {
  font-size: 20px;
}
</style>