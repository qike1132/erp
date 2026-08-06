<template>
  <div class="bo-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="bo-header-left">
          <HeaderTabs />
        </div>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body">
        <BeileOrderTab />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderView.vue — 湖北订单页面
 *
 * 职责：作为湖北订单的容器组件，承载 BeileOrderTab 子组件。
 * 页面锁定 factory=湖北，供管理员与湖北用户查看本厂订单。
 */
import BeileOrderTab from './BeileOrderTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
</script>

<style scoped>
/* Container */
.bo-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card Header — 对齐 StockView / CaseView 布局 */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */
.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.bo-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

/* 卡片主体样式复用全局 .page-card-body（src/styles/app.css） */
</style>
