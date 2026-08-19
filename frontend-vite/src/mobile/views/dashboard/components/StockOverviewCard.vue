<template>
  <div class="m-card">
    <div class="m-card-header">
      <div class="m-card-icon">
        <span class="m-card-emoji">📁</span>
      </div>
      <span class="m-card-title">出库总览</span>
    </div>
    <div class="m-card-gap-12"></div>

    <div class="m-section-title">
      <span class="m-section-dot" style="background: #0071E3"></span>
      <span>当日已出库</span>
    </div>
    <div class="m-section-gap-10"></div>
    <div class="m-stock-package">
      <div class="m-stock-metric">
        <span class="m-stock-label">总数量</span>
        <span class="m-stock-gap-8"></span>
        <span class="m-stock-value">{{ fmtNum(data?.stock?.today_quantity) }}</span>
      </div>
      <div class="m-stock-metric">
        <span class="m-stock-label">总产值</span>
        <span class="m-stock-gap-8"></span>
        <span class="m-stock-value">{{ fmtMoney(data?.stock?.today_amount) }}</span>
      </div>
    </div>

    <div style="margin-top: 16px;"></div>
    <div class="m-section-title">
      <span class="m-section-dot" style="background: #2997FF"></span>
      <span>当月已出库</span>
    </div>
    <div class="m-section-gap-10"></div>
    <div class="m-stock-package">
      <div class="m-stock-metric">
        <span class="m-stock-label">累计数量</span>
        <span class="m-stock-gap-8"></span>
        <span class="m-stock-value">{{ fmtNum(data?.stock?.month_quantity) }}</span>
      </div>
      <div class="m-stock-metric">
        <span class="m-stock-label">累计产值</span>
        <span class="m-stock-gap-8"></span>
        <span class="m-stock-value">{{ fmtMoney(data?.stock?.month_amount) }}</span>
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
.m-card-gap-12 { height: 12px; }
.m-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #86868B;
  padding: 2px 0;
}
.m-section-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.m-section-gap-10 { height: 10px; }
.m-stock-package {
  background: #F5F5F7;
  border-radius: 16px;
  padding: 18px;
  display: flex;
  justify-content: space-evenly;
}
.m-stock-metric { display: flex; flex-direction: column; }
.m-stock-label { font-size: 11px; font-weight: 500; color: #AEAEB2; }
.m-stock-gap-8 { height: 8px; }
.m-stock-value {
  font-size: 18px;
  font-weight: 800;
  color: #0071E3;
  letter-spacing: -0.3px;
}
</style>