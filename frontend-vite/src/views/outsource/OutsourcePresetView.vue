<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：HeaderTabs（工序预设页无筛选栏） -->
      <div class="page-card-header">
        <div class="hu-header-left">
          <HeaderTabs />
        </div>
      </div>

      <!-- Tab 导航：湖北订单 / 外发工序 / 工序预设（各自独立路由） -->
      <HubeiRouteTabs />

      <!-- 内容区 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <OutsourcePresetTab />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourcePresetView.vue — 工序预设页面（/outsource/presets）
 *
 * 原 /beile-order 合并页中「工序预设」Tab 拆分为独立路由页面，
 * 管理 SKU 外发工序模板（OutsourcePresetTab）。
 */
import OutsourcePresetTab from '@/views/outsource/components/OutsourcePresetTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
</script>

<style scoped>
.hu-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  contain: layout style;
  overflow-anchor: none;
  overflow: hidden;
}

.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.hu-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

/* 内容区 */
.page-card-body {
  padding: 0;
  scrollbar-gutter: auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.hu-tab-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 900px) {
  .page-card-header {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
