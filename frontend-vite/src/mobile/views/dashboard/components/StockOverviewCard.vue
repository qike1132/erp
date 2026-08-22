<template>
  <div class="ios-card">
    <div class="ios-card-head">
      <div class="ios-card-icon ios-icon-blue">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M1 3h15v13H1z" />
          <path d="M16 8h4l3 3v5h-7V8z" />
          <circle cx="5.5" cy="18.5" r="2.5" />
          <circle cx="18.5" cy="18.5" r="2.5" />
        </svg>
      </div>
      <div class="ios-card-title-wrap">
        <span class="ios-card-title">出库总览</span>
        <span class="ios-card-sub">Shipments</span>
      </div>
    </div>

    <div class="ios-rows">
      <div class="ios-row">
        <span class="ios-row-label">当日已出库 · 数量</span>
        <span class="ios-row-value">{{ fmtNum(data?.stock?.today_quantity) }}</span>
      </div>
      <div class="ios-hairline" />
      <div class="ios-row">
        <span class="ios-row-label">当日已出库 · 产值</span>
        <span class="ios-row-value ios-accent">{{ fmtMoney(data?.stock?.today_amount) }}</span>
      </div>
      <div class="ios-hairline" />
      <div class="ios-row">
        <span class="ios-row-label">当月已出库 · 数量</span>
        <span class="ios-row-value">{{ fmtNum(data?.stock?.month_quantity) }}</span>
      </div>
      <div class="ios-hairline" />
      <div class="ios-row">
        <span class="ios-row-label">当月已出库 · 产值</span>
        <span class="ios-row-value ios-accent">{{ fmtMoney(data?.stock?.month_amount) }}</span>
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
