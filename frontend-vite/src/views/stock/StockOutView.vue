<template>
  <div class="so-container">
    <div class="so-card so-card-main">
      <!-- 卡片头部 -->
      <div class="so-card-header">
        <div class="so-header-left">
          <HeaderTabs />
        </div>
        <div class="so-header-right">
          <div class="so-tab-bar">
            <button :class="['so-tab-btn', activeTab === 'input' && 'active']" @click="activeTab = 'input'">
              录入
            </button>
            <button :class="['so-tab-btn', activeTab === 'records' && 'active']" @click="activeTab = 'records'">
              记录查询
            </button>
          </div>
        </div>
      </div>

      <StockOutTab :active-tab="activeTab" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import StockOutTab from './StockOutTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

const activeTab = ref<'input' | 'records'>('input')
</script>

<style scoped>
.so-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.so-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border, #cbd5e1);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}
.so-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.so-card-main:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.so-card-header {
  padding: 10px 24px;
  background: transparent;
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 2px solid var(--color-border, #cbd5e1);
  gap: 12px;
}
.so-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.so-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.so-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.so-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.so-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.so-icon-danger {
  background: linear-gradient(135deg, var(--color-danger-100, #fde8e8), var(--color-danger-200, #fbd0d0));
  color: var(--color-danger-500);
}
.so-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.so-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}
.so-tab-bar {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.so-tab-btn {
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
  transition: all 0.3s ease;
}
.so-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.so-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
</style>
