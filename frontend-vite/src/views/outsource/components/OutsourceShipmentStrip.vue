<template>
  <!-- 发货单页单行信息条：台账标题 + 待办概览（动作按钮已上移页头，与 TAB 同行，用户裁决） -->
  <div class="oss-strip">
    <h4 class="oss-strip-title">发货单台账</h4>
    <span class="oss-sep" />
    <span class="oss-item">
      <span class="oss-dot oss-dot--warn" />
      待收货 <strong>{{ shippedCount }}</strong> 张
    </span>
    <template v-if="unshippedQty !== null">
      <span class="oss-sep" />
      <span class="oss-item">
        <span class="oss-dot oss-dot--ok" />
        未到货 <strong>{{ unshippedQty.toLocaleString() }}</strong> 件
      </span>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourceShipmentStrip.vue — 发货单页单行信息条（方案B + 用户裁决布局）
 *
 * 仅承载概览信息：发货单台账标题、待收货张数、未到货件数；
 * 状态切换/导出/打印/批量发货位于页头右侧 OutsourceShipmentActions（与 TAB 同行）。
 * 未到货件数 = 订单数量 − 已发数量（跨全部湖北订单聚合，后端 /outsource/unshipped），
 * 由父组件拉取后传入；null 表示尚未取得（不渲染该段，避免显示假 0）。
 */
defineProps<{
  shippedCount: number
  /** 未到货总件数；null = 未加载成功，隐藏该段 */
  unshippedQty: number | null
}>()
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

.oss-strip {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 9px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  background: var(--color-surface, #f8fafc);
  font-size: 12.5px;
  color: var(--color-text-secondary, #64748b);
}
.oss-strip-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--color-text);
}
.oss-sep {
  width: 1px;
  height: 16px;
  background: var(--color-border-light, #e2e8f0);
}
.oss-item strong { color: var(--color-text); font-size: 13.5px; }
.oss-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.oss-dot--warn { background: var(--color-warning-400, #fbbf24); }
.oss-dot--ok { background: var(--color-success-400, #4ade80); }
</style>
