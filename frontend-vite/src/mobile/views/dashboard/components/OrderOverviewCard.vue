<template>
  <div class="ios-card">
    <div class="ios-card-head">
      <div class="ios-card-icon ios-icon-blue">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="5" y="4" width="14" height="17" rx="2" />
          <path d="M9 4a3 3 0 0 1 6 0" />
          <path d="M9 10h6M9 14h6M9 18h4" />
        </svg>
      </div>
      <div class="ios-card-title-wrap">
        <span class="ios-card-title">订单总览</span>
        <span class="ios-card-sub">Orders</span>
      </div>
    </div>

    <div class="ios-rows">
      <div class="ios-row">
        <span class="ios-row-label">总订单数量</span>
        <span class="ios-row-value">{{ fmtNum(data?.orders?.total_qty) }}</span>
      </div>
      <div class="ios-hairline" />
      <div class="ios-row">
        <span class="ios-row-label">总订单金额</span>
        <span class="ios-row-value ios-accent">{{ fmtMoney(data?.orders?.total_amount) }}</span>
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
.ios-card {
  background: #ffffff;
  border-radius: 20px;
  padding: 16px 0 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04);
  border: 0.5px solid rgba(0, 0, 0, 0.04);
  overflow: hidden;
}
.ios-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
}
.ios-card-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ios-card-icon svg { width: 20px; height: 20px; }
.ios-icon-blue { background: rgba(0, 113, 227, 0.1); color: #0071E3; }
.ios-card-title-wrap { display: flex; flex-direction: column; }
.ios-card-title { font-size: 15px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.2px; }
.ios-card-sub { font-size: 11px; color: #aeaeb2; margin-top: 1px; }
.ios-rows { margin-top: 12px; }
.ios-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 16px;
}
.ios-row-label { font-size: 14px; color: #86868b; }
.ios-row-value { font-size: 17px; font-weight: 700; color: #1d1d1f; letter-spacing: -0.3px; }
.ios-accent { color: #0071e3; }
.ios-hairline {
  height: 0.5px;
  background: rgba(60, 60, 67, 0.29);
  margin: 0 16px;
  transform: scaleY(0.5);
}
</style>
