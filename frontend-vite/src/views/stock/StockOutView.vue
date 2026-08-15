<template>
  <div class="so-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="so-tab-bar">
          <button :class="['so-tab-btn', activeTab === 'input' && 'active']" @click="activeTab = 'input'">
            录入
          </button>
          <button :class="['so-tab-btn', activeTab === 'records' && 'active']" @click="activeTab = 'records'">
            记录查询
          </button>
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
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
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
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
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
