<template>
  <div class="sk-container">
    <div class="page-card page-card-main">
      <InventoryTab />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * StockView.vue — 库存管理页面
 *
 * 职责：卡片容器 + 库存事件的缓存失效。
 * 页头（标题·搜索·汇总·导出）由 InventoryTab 内的 InventoryToolbar 渲染——
 * 原先导出按钮在此处、经 ref 调用子组件方法，改为工具条内直接触发后，
 * 这层 ref/itemCount 转发随之删除。
 * 订阅订单/库存 WebSocket 事件：订单创建、修改、删除（含其他端/其他标签页操作）
 * 后自动失效库存派生查询缓存，无需手动刷新。
 */
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useWebSocket } from '@/composables/useWebSocket'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'
import InventoryTab from './InventoryTab.vue'

const queryClient = useQueryClient()

/** 会改变库存视图的服务端事件（与后端 StockEvent 常量同名） */
const STOCK_REFRESH_EVENTS = new Set([
  'stock_changed',
  'order_created',
  'order_updated',
  'order_deleted',
])

useWebSocket({
  isActive: ref(true),
  onMessage: (data) => {
    if (!STOCK_REFRESH_EVENTS.has(String(data.type))) return
    invalidateOrderDerivedQueries(queryClient)
  },
})
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

/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */
</style>
