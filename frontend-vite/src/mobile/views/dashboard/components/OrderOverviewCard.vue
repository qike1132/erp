<template>
  <div class="m-card">
    <div class="m-card-header">
      <div class="m-card-icon">
        <span class="m-card-emoji">📋</span>
      </div>
      <span class="m-card-title">订单总览</span>
    </div>
    <div class="m-card-gap-14"></div>
    <div class="m-metric-grid-2">
      <div class="m-metric-block">
        <span class="m-metric-label">📋 总订单数量</span>
        <span class="m-metric-value">{{ fmtNum(data?.orders?.total_qty) }}</span>
      </div>
      <div class="m-metric-block">
        <span class="m-metric-label">💰 总订单金额</span>
        <span class="m-metric-value">{{ fmtMoney(data?.orders?.total_amount) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { MobileDashboardData } from '@/api/dashboard'

defineProps<{
  data: MobileDashboardData | null
  fmtNum: (n: number | null | undefined) => string
  fmtMoney: (n: number | null | undefined) => string
}>()
</script>

<style scoped>
.m-card {
  background: #FFFFFF;
  border-radius: 22px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(0, 0, 0, 0.04);
}
.m-card-header { display: flex; align-items: center; gap: 10px; }
.m-card-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: rgba(0, 113, 227, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.m-card-emoji { font-size: 16px; line-height: 1; }
.m-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #86868B;
  letter-spacing: -0.1px;
}
.m-card-gap-14 { height: 14px; }
.m-metric-grid-2 { display: flex; gap: 12px; }
.m-metric-block {
  flex: 1;
  background: #F8FAFC;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.m-metric-label { font-size: 11px; font-weight: 500; color: #AEAEB2; }
.m-metric-value {
  font-size: 20px;
  font-weight: 800;
  color: #0071E3;
  letter-spacing: -0.3px;
}
</style>