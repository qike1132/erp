<template>
  <div class="m-card">
    <div class="m-card-header">
      <div class="m-card-icon">
        <span class="m-card-emoji">🏭</span>
      </div>
      <span class="m-card-title">皮套仓储</span>
    </div>
    <div class="m-card-gap-14"></div>

    <div class="m-wh-grid">
      <div class="m-wh-block">
        <span class="m-wh-label">📥 进仓数量</span>
        <span class="m-wh-value">{{ fmtNum(data?.warehouse?.in_qty) }}</span>
        <span class="m-wh-sub">{{ fmtMoney(data?.warehouse?.in_amount) }} 元</span>
      </div>
      <div class="m-wh-block">
        <span class="m-wh-label">💸 进仓金额</span>
        <span class="m-wh-value">{{ fmtMoney(data?.warehouse?.in_amount) }}</span>
        <span class="m-wh-sub">总金额</span>
      </div>
      <div class="m-wh-block">
        <span class="m-wh-label">📤 出仓数量</span>
        <span class="m-wh-value">{{ fmtNum(data?.warehouse?.out_qty) }}</span>
        <span class="m-wh-sub">{{ fmtMoney(data?.warehouse?.out_amount) }} 元</span>
      </div>
      <div class="m-wh-block">
        <span class="m-wh-label">💸 出仓金额</span>
        <span class="m-wh-value">{{ fmtMoney(data?.warehouse?.out_amount) }}</span>
        <span class="m-wh-sub">总金额</span>
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
.m-wh-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.m-wh-block {
  background: #F8FAFC;
  border-radius: 12px;
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.m-wh-label { font-size: 10px; font-weight: 500; color: #AEAEB2; }
.m-wh-value {
  font-size: 16px;
  font-weight: 800;
  color: #0071E3;
}
.m-wh-sub { font-size: 11px; font-weight: 500; color: #AEAEB2; }
</style>