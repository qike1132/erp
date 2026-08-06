<template>
  <div class="cs-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="cs-header-left">
          <HeaderTabs />
        </div>
        <div class="cs-header-right">
          <div class="cs-tab-group" role="tablist">
            <button role="tab" :aria-selected="activeTab === 'stock'" :class="['cs-tab-btn', { active: activeTab === 'stock' }]" @click="activeTab = 'stock'">
              出入库
            </button>
            <button role="tab" :aria-selected="activeTab === 'inventory'" :class="['cs-tab-btn', { active: activeTab === 'inventory' }]" @click="activeTab = 'inventory'">
              库存查询
            </button>
          </div>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body">
        <CaseStockTab v-if="activeTab === 'stock'" />
        <CaseInventoryTab v-if="activeTab === 'inventory'" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseView.vue — 皮套出入库管理页面
 *
 * 职责：
 * - 提供出入库（CaseStockTab）和库存查询（CaseInventoryTab）两个标签页
 * - 通过 activeTab 控制标签页切换
 */
import { ref } from 'vue'
import CaseStockTab from './CaseStockTab.vue'
import CaseInventoryTab from './CaseInventoryTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

/** 当前激活的标签页：stock（出入库）/ inventory（库存查询） */
const activeTab = ref<'stock' | 'inventory'>('stock')
</script>

<style scoped>
/* Container */
.cs-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* Card Header */
/* 卡片头部样式已迁移到全局 .page-card-header（src/styles/app.css） */
.page-card-header :deep(.ht-bar) {
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
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
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
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.cs-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* Body */
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */
</style>
