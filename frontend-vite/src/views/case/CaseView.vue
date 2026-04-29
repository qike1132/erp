<template>
  <div class="cs-container">
    <div class="cs-card cs-card-main">
      <!-- 卡片头部 -->
      <div class="cs-card-header">
        <HeaderTabs />
        <div class="cs-header-actions">
          <div class="cs-tab-group">
            <button :class="['cs-tab-btn', { active: activeTab === 'stock' }]" @click="activeTab = 'stock'">
              <i class="fas fa-exchange-alt" style="margin-right: 4px" />出入库
            </button>
            <button :class="['cs-tab-btn', { active: activeTab === 'inventory' }]" @click="activeTab = 'inventory'">
              <i class="fas fa-warehouse" style="margin-right: 4px" />库存查询
            </button>
          </div>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="cs-body">
        <CaseStockTab v-if="activeTab === 'stock'" />
        <CaseInventoryTab v-if="activeTab === 'inventory'" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import CaseStockTab from './CaseStockTab.vue'
import CaseInventoryTab from './CaseInventoryTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

const activeTab = ref('stock')
</script>

<style scoped>
/* Container */
.cs-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.cs-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.cs-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.cs-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Card Header */
.cs-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 10px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.cs-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.cs-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cs-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.cs-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}
.cs-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Icon Box */
.cs-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.cs-icon-green {
  background: linear-gradient(135deg, var(--color-success-100), var(--color-success-200));
  color: var(--color-success-700);
}

/* Tab Group */
.cs-tab-group {
  display: inline-flex;
  border-radius: 9px;
  overflow: hidden;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: var(--color-surface, #f8fafc);
}
.cs-tab-btn {
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
}
.cs-tab-btn.active {
  background: var(--color-primary-500);
  color: white;
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.3);
}
.cs-tab-btn:not(.active):hover {
  background: rgba(91, 141, 239, 0.08);
}

/* Body */
.cs-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
