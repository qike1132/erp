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
            :class="['cs-tab-btn', { active: activeTab === tab.key, 'out-tab': tab.key === 'stockout' }]"
            :aria-label="tab.label"
            @click="activeTab = tab.key"
          >
            <FontAwesomeIcon :icon="tab.icon" aria-hidden="true" />
            {{ tab.label }}
          </button>
        </div>
      </div>

      <div class="page-card-body">
        <KeepAlive>
          <StockWorkbench v-if="activeTab === 'stockin'" mode="stockin" />
          <StockWorkbench v-else-if="activeTab === 'stockout'" mode="stockout" />
          <InventoryPanel v-else />
        </KeepAlive>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseView.vue — 皮套管理页面（/case）
 *
 * 结构：入库 / 出库 / 库存 三个主标签。
 * - 入库、出库各挂独立 StockWorkbench 实例（暂存单互不干扰，KeepAlive 保留状态）；
 * - 库存标签为汇总 + 流水查询；
 * - 订阅 WebSocket case_stock_changed 事件，多端任一出入库操作后自动刷新查询缓存。
 */
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useWebSocket } from '@/composables/useWebSocket'
import { caseQueryKeys } from './composables/useCaseStockWorkbench'
import StockWorkbench from './components/StockWorkbench.vue'
import InventoryPanel from './components/InventoryPanel.vue'

type CaseTab = 'stockin' | 'stockout' | 'inventory'

const TABS: { key: CaseTab; label: string; icon: string }[] = [
  { key: 'stockin', label: '入库', icon: 'truck-loading' },
  { key: 'stockout', label: '出库', icon: 'shipping-fast' },
  { key: 'inventory', label: '库存', icon: 'warehouse' },
]

const activeTab = ref<CaseTab>('stockin')
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
  padding: 8px 14px;
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
.cs-tab-btn.active.out-tab {
  background: linear-gradient(135deg, var(--color-danger-50), var(--color-danger-100));
  color: var(--color-danger-700);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(234, 84, 85, 0.2);
}
</style>
