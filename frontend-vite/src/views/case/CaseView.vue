<template>
  <div class="cs-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <div class="cs-tab-group" role="tablist">
          <button
            v-for="tab in TABS"
            :key="tab.key"
            role="tab"
            :aria-selected="activeTab === tab.key"
            :class="['cs-tab-btn', { active: activeTab === tab.key }]"
            :aria-label="tab.label"
            @click="activeTab = tab.key"
          >
            <FontAwesomeIcon :icon="tab.icon" aria-hidden="true" />
            {{ tab.label }}
          </button>
        </div>
      </div>

      <div class="page-card-body">
        <!-- 出入库（方向分段切换；两个工作台常驻以保留各自暂存单） -->
        <div v-show="activeTab === 'stock'" class="cs-direction">
          <div class="cs-dir-row">
            <div class="cs-seg" role="tablist">
              <button
                role="tab"
                :aria-selected="direction === 'stockin'"
                :class="{ active: direction === 'stockin' }"
                @click="direction = 'stockin'"
              >
                <FontAwesomeIcon icon="truck-loading" aria-hidden="true" />入库
              </button>
              <button
                role="tab"
                :aria-selected="direction === 'stockout'"
                :class="['cs-seg-out', { active: direction === 'stockout' }]"
                @click="direction = 'stockout'"
              >
                <FontAwesomeIcon icon="shipping-fast" aria-hidden="true" />出库
              </button>
            </div>
            <span class="cs-dir-hint">{{ direction === 'stockin' ? '入库 · 增加库存' : '出库 · 减少库存（不足会拦下）' }}</span>
          </div>
          <StockWorkbench v-show="direction === 'stockin'" mode="stockin" />
          <StockWorkbench v-show="direction === 'stockout'" mode="stockout" />
        </div>

        <InventoryPanel v-if="activeTab === 'inventory'" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseView.vue — 皮套管理页面（/case）
 *
 * 结构：出入库（入库/出库方向分段切换）/ 库存 两个主标签。
 * - 出入库：两个 StockWorkbench 常驻，暂存单互不干扰；
 * - 库存：按主件分组的汇总 + 单 SKU 流水查询；
 * - 订阅 WebSocket case_stock_changed 事件，多端任一出入库操作后自动刷新查询缓存。
 */
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useWebSocket } from '@/composables/useWebSocket'
import { caseQueryKeys } from './composables/useCaseStockWorkbench'
import StockWorkbench from './components/StockWorkbench.vue'
import InventoryPanel from './components/InventoryPanel.vue'

type CaseTab = 'stock' | 'inventory'
type CaseDirection = 'stockin' | 'stockout'

const TABS: { key: CaseTab; label: string; icon: string }[] = [
  { key: 'stock', label: '出入库', icon: 'right-left' },
  { key: 'inventory', label: '库存', icon: 'warehouse' },
]

const activeTab = ref<CaseTab>('stock')
const direction = ref<CaseDirection>('stockin')
const queryClient = useQueryClient()

// 皮套库存变更事件：失效全部相关查询，由 vue-query 按需重拉
useWebSocket({
  isActive: ref(true),
  onMessage: (data) => {
    if (data.type !== 'case_stock_changed') return
    for (const key of caseQueryKeys()) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  },
})
</script>

<style scoped>
.cs-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.cs-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
}
.cs-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}
.cs-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}
.cs-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

.cs-direction {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.cs-dir-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.cs-seg {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
}
.cs-seg > button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.25s ease, color 0.25s ease, box-shadow 0.25s ease;
}
.cs-seg > button:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.cs-seg > button.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.2);
}
.cs-seg > button.cs-seg-out.active {
  background: linear-gradient(135deg, var(--color-danger-50), var(--color-danger-100));
  color: var(--color-danger-700);
  box-shadow: 0 2px 8px rgba(234, 84, 85, 0.2);
}
.cs-dir-hint {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
}
</style>
