<template>
  <div class="m-card">
    <div class="m-card-header">
      <div class="m-card-icon">
        <span class="m-card-emoji">🖥</span>
      </div>
      <span class="m-card-title">生产数据 · 按部门</span>
    </div>
    <div class="m-card-gap-10"></div>

    <div class="m-prod-total">
      <span class="m-prod-total-label">今日总产值</span>
      <span class="m-prod-total-value">{{ fmtMoney(data?.production?.total_value) }}</span>
    </div>

    <template v-if="sortedDepartments.length > 0">
      <div class="m-divider"></div>
      <div class="m-dept-list">
        <div
          v-for="(dept, di) in sortedDepartments"
          :key="di"
          class="m-dept-item"
        >
          <div :class="['m-dept-rank', rankClass(di)]">
            {{ rankLabel(di) }}
          </div>
          <div class="m-dept-info">
            <div class="m-dept-name">{{ dept.name }}</div>
            <div class="m-dept-sub">{{ dept.daily_output }} 件/日</div>
          </div>
          <div class="m-dept-stats">
            <div class="m-dept-output">{{ fmtNum(dept.daily_output) }}</div>
            <div class="m-dept-amount">{{ fmtMoney(dept.output_value) }}</div>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="m-empty-dept">暂无部门数据</div>
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
  rankClass: (idx: number) => string
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
.m-card-gap-10 { height: 10px; }
.m-prod-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.m-prod-total-label { font-size: 12px; color: #AEAEB2; }
.m-prod-total-value {
  font-size: 20px;
  font-weight: 800;
  color: #0071E3;
}
.m-divider {
  height: 1px;
  background: rgba(0, 0, 0, 0.04);
  margin: 14px 0;
}
.m-dept-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.m-dept-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #F1F5F9;
  border-radius: 12px;
}
.m-dept-rank {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}
.m-rank-1 { background: rgba(0, 113, 227, 0.08); color: #0071E3; }
.m-rank-other { background: #F1F5F9; color: #86868B; }
.m-dept-info { flex: 1; min-width: 0; }
.m-dept-name {
  font-size: 13px;
  font-weight: 600;
  color: #1D1D1F;
}
.m-dept-sub { font-size: 11px; color: #AEAEB2; }
.m-dept-stats { text-align: right; }
.m-dept-output {
  font-size: 15px;
  font-weight: 600;
  color: #1D1D1F;
}
.m-dept-amount {
  font-size: 11px;
  font-weight: 500;
  color: #0071E3;
}
.m-empty-dept {
  text-align: center;
  font-size: 13px;
  color: #AEAEB2;
  padding: 16px 0;
}
</style>