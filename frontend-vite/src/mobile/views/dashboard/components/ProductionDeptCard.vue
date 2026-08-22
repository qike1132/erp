<template>
  <div class="ios-card">
    <div class="ios-card-head">
      <div class="ios-card-icon ios-icon-violet">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <line x1="6" y1="20" x2="6" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="18" y1="20" x2="18" y2="14" />
        </svg>
      </div>
      <div class="ios-card-title-wrap">
        <span class="ios-card-title">生产数据 · 按部门</span>
        <span class="ios-card-sub">Production</span>
      </div>
    </div>

    <div class="ios-prod-total">
      <span class="ios-prod-label">今日总产值</span>
      <span class="ios-prod-value">{{ fmtMoney(data?.production?.total_value) }}</span>
    </div>

    <template v-if="sortedDepartments.length > 0">
      <div class="ios-hairline-full" />
      <div class="ios-dept">
        <div
          v-for="(dept, di) in sortedDepartments"
          :key="di"
          class="ios-dept-row"
        >
          <div :class="['ios-dept-rank', di === 0 ? 'ios-rank-top' : 'ios-rank-other']">
            {{ rankLabel(di) }}
          </div>
          <div class="ios-dept-info">
            <div class="ios-dept-name">{{ dept.name }}</div>
            <div class="ios-dept-sub">{{ dept.daily_output }} 件/日</div>
          </div>
          <div class="ios-dept-stats">
            <div class="ios-dept-output">{{ fmtNum(dept.daily_output) }}</div>
            <div class="ios-dept-amount">{{ fmtMoney(dept.output_value) }}</div>
          </div>
          <div v-if="di < sortedDepartments.length - 1" class="ios-hairline-inset" />
        </div>
      </div>
    </template>
    <div v-else class="ios-empty">暂无部门数据</div>
  </div>
</template>

<script setup lang="ts">
import type { MobileDashboardData, MobileDeptData } from '@/api/dashboard'

defineProps<{
  data: MobileDashboardData | null
  sortedDepartments: MobileDeptData[]
  fmtNum: (n: number | null | undefined) => string
  fmtMoney: (n: number | null | undefined) => string
  rankLabel: (idx: number) => string
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
.ios-icon-violet { background: rgba(175, 82, 222, 0.12); color: #af52de; }
.ios-card-title-wrap { display: flex; flex-direction: column; }
.ios-card-title { font-size: 15px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.2px; }
.ios-card-sub { font-size: 11px; color: #aeaeb2; margin-top: 1px; }
.ios-prod-total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 16px 16px 14px;
}
.ios-prod-label { font-size: 13px; color: #86868b; }
.ios-prod-value { font-size: 24px; font-weight: 800; color: #0071e3; letter-spacing: -0.5px; }
.ios-hairline-full {
  height: 0.5px;
  background: rgba(60, 60, 67, 0.29);
  transform: scaleY(0.5);
}
.ios-dept-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 16px;
}
.ios-dept-rank {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 800;
  flex-shrink: 0;
}
.ios-rank-top { background: rgba(0, 113, 227, 0.1); color: #0071e3; }
.ios-rank-other { background: #f2f2f7; color: #86868b; }
.ios-dept-info { flex: 1; min-width: 0; }
.ios-dept-name { font-size: 15px; font-weight: 600; color: #1d1d1f; }
.ios-dept-sub { font-size: 12px; color: #aeaeb2; margin-top: 1px; }
.ios-dept-stats { text-align: right; }
.ios-dept-output { font-size: 16px; font-weight: 700; color: #1d1d1f; letter-spacing: -0.2px; }
.ios-dept-amount { font-size: 12px; font-weight: 500; color: #0071e3; margin-top: 1px; }
.ios-hairline-inset {
  position: absolute;
  left: 54px;
  right: 0;
  bottom: 0;
  height: 0.5px;
  background: rgba(60, 60, 67, 0.18);
  transform: scaleY(0.5);
}
.ios-empty {
  text-align: center;
  font-size: 13px;
  color: #aeaeb2;
  padding: 16px 0;
}
</style>
