<template>
  <div class="sk-container">
    <div class="sk-card sk-card-main">
      <!-- 卡片头部 -->
      <div class="sk-card-header">
        <div class="sk-header-left">
          <HeaderTabs />
        </div>
        <div class="sk-header-right">
          <span v-if="itemCount" class="sk-badge">{{ itemCount }} 条</span>
          <button v-if="itemCount" class="sk-action-btn sk-action-success" @click="handleExport">
            <i class="fas fa-file-excel" style="margin-right: 4px" />导出
          </button>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="sk-body">
        <InventoryTab ref="tabRef" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import InventoryTab from './InventoryTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

const tabRef = ref<InstanceType<typeof InventoryTab> | null>(null)

const itemCount = computed(() => {
  const inv = tabRef.value?.filteredInventory
  return inv ? inv.length : 0
})

function handleExport() {
  tabRef.value?.handleExport()
}
</script>

<style scoped>
/* Container (Spec §1) */
.sk-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card (Spec §3) */
.sk-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
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

/* Card Header (Spec §4) — 对齐 CaseView 布局 */
.sk-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: flex-start;
  padding: 10px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.sk-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.sk-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.sk-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 10px;
}

/* Badge (Spec §9) */
.sk-badge {
  border-radius: 20px;
  padding: 6px 14px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 13px;
  font-weight: 600;
}

/* Action Button (Spec §10) */
.sk-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-success-200);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-success-600);
  display: inline-flex;
  align-items: center;
}
.sk-action-btn:hover {
  background: var(--color-success-50);
  border-color: var(--color-success-300);
  transform: translateY(-1px);
}

/* Body */
.sk-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
