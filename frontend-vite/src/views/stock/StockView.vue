<template>
  <div class="sk-container">
    <div class="sk-card sk-card-main">
      <!-- 卡片头部 -->
      <div class="sk-card-header">
        <HeaderTabs />
        <div class="sk-card-title-group">
          <div class="sk-icon-box sk-icon-blue">
            <i class="fas fa-warehouse" />
          </div>
          <div>
            <h3>库存管理</h3>
            <small>库存汇总查询与导出</small>
          </div>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="sk-body">
        <InventoryTab />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import InventoryTab from './InventoryTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
</script>

<style scoped>
/* Container */
.sk-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.sk-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.sk-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.sk-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Card Header */
.sk-card-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px 10px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.sk-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.sk-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.sk-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* Icon Box */
.sk-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.sk-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* Body */
.sk-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
