<template>
  <div class="sk-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <button v-if="itemCount" class="sk-action-btn sk-action-success" @click="handleExport">
          <FontAwesomeIcon icon="file-excel" style="margin-right: 4px"  aria-hidden="true" />导出
        </button>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body">
        <InventoryTab ref="tabRef" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * StockView.vue — 库存管理页面
 *
 * 职责：作为库存管理的容器组件，承载 InventoryTab 子组件，
 * 提供导出按钮并根据子组件数据动态控制按钮显隐。
 */
import { ref, computed } from 'vue'
import InventoryTab from './InventoryTab.vue'

/** InventoryTab 子组件实例引用 */
const tabRef = ref<InstanceType<typeof InventoryTab> | null>(null)

/** 当前过滤后的库存条目数量，用于控制导出按钮显隐 */
const itemCount = computed(() => {
  const inv = tabRef.value?.filteredInventory
  return inv ? inv.length : 0
})

/** 触发子组件的导出操作 */
function handleExport() {
  tabRef.value?.handleExport()
}
</script>

<style scoped>
/* Container (Spec §1) */
.sk-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card Header (Spec §4) — 对齐 CaseView 布局 */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

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
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
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
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */
</style>
