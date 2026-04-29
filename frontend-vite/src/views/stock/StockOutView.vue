<template>
  <div class="so-container">
    <div class="so-card so-card-main">
      <!-- 卡片头部 -->
      <div class="so-card-header">
        <div class="so-card-title-group">
          <div class="so-icon-box so-icon-danger"><i class="fas fa-shipping-fast"></i></div>
          <div>
            <h3>出货管理</h3>
            <small>产品出货录入、暂存与记录管理</small>
          </div>
        </div>
        <div class="so-header-actions">
          <div class="so-tab-bar">
            <button :class="['so-tab-btn', activeTab === 'input' && 'active']" @click="activeTab = 'input'">
              <i class="fas fa-edit" />录入
            </button>
            <button :class="['so-tab-btn', activeTab === 'records' && 'active']" @click="activeTab = 'records'">
              <i class="fas fa-search" />记录查询
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

const activeTab = ref<'input' | 'records'>('input')
</script>

<style scoped>
.so-container {
  padding: 12px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.so-card {
  background: white;
  border-radius: 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
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
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 16px 48px rgba(0,0,0,0.12);
  transform: translateY(-2px);
}
.so-card-header {
  padding: 14px 24px 10px;
  background: transparent;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
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
.so-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.so-tab-bar {
  display: flex;
  gap: 4px;
}
.so-tab-btn {
  padding: 7px 16px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
}
.so-tab-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.so-tab-btn.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-color: var(--color-primary-400);
}
</style>
