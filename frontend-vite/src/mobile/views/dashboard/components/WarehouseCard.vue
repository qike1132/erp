<template>
  <div class="ios-card">
    <div class="ios-card-head">
      <div class="ios-card-icon ios-icon-teal">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="4" width="18" height="4" rx="1" />
          <path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8" />
          <path d="M10 12h4" />
        </svg>
      </div>
      <div class="ios-card-title-wrap">
        <span class="ios-card-title">皮套仓储</span>
        <span class="ios-card-sub">Warehouse</span>
      </div>
    </div>

    <div class="ios-wh-grid">
      <div class="ios-wh-block">
        <div class="ios-wh-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 19V5" />
            <path d="M5 12l7-7 7 7" />
          </svg>
          今日进仓
        </div>
        <div class="ios-wh-value">{{ fmtNum(data?.warehouse?.in_qty) }}</div>
        <div class="ios-wh-sub">{{ fmtMoney(data?.warehouse?.in_amount) }} 元</div>
      </div>
      <div class="ios-wh-block">
        <div class="ios-wh-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 5v14" />
            <path d="M19 12l-7 7-7-7" />
          </svg>
          今日出仓
        </div>
        <div class="ios-wh-value">{{ fmtNum(data?.warehouse?.out_qty) }}</div>
        <div class="ios-wh-sub">{{ fmtMoney(data?.warehouse?.out_amount) }} 元</div>
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
  padding: 16px 16px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04);
  border: 0.5px solid rgba(0, 0, 0, 0.04);
  overflow: hidden;
}
.ios-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 0 16px;
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
.ios-icon-teal { background: rgba(90, 200, 250, 0.15); color: #0a84ff; }
.ios-card-title-wrap { display: flex; flex-direction: column; }
.ios-card-title { font-size: 15px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.2px; }
.ios-card-sub { font-size: 11px; color: #aeaeb2; margin-top: 1px; }
.ios-wh-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.ios-wh-block {
  background: #f5f5f7;
  border-radius: 14px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.ios-wh-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 500;
  color: #86868b;
}
.ios-wh-label svg { width: 13px; height: 13px; }
.ios-wh-value { font-size: 20px; font-weight: 800; color: #1d1d1f; letter-spacing: -0.4px; }
.ios-wh-sub { font-size: 11px; font-weight: 500; color: #aeaeb2; }
</style>
