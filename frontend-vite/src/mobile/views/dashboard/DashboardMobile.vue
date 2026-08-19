<template>
  <div class="m-dashboard">
    <!-- Status Bar -->
    <div class="m-status-bar">
      <span class="m-time">{{ currentTime }}</span>
      <div class="m-status-icons">
        <span class="m-status-signal"></span>
        <span class="m-status-battery"></span>
      </div>
    </div>

    <!-- Header Section -->
    <div class="m-header">
      <h1 class="m-header-title">数据概览</h1>
      <div class="m-header-sub">
        <span class="m-dot"></span>
        <span>实时业务数据</span>
      </div>
    </div>

    <!-- Refresh Bar -->
    <div class="m-refresh-bar">
      <span class="m-last-update">{{ lastUpdateText }}</span>
      <button class="m-refresh-btn" @click="refresh" aria-label="刷新数据">
        <span>刷新数据</span>
      </button>
    </div>

    <!-- Error Banner -->
    <div v-if="error" class="m-error-banner">
      <span class="m-error-icon">⚠</span>
      <span class="m-error-text">数据加载异常</span>
      <button class="m-error-retry" @click="loadData" aria-label="重试">重试</button>
    </div>

    <!-- Loading Skeleton -->
    <template v-if="loading">
      <div v-for="i in 4" :key="'sk-' + i" class="m-skeleton-card">
        <div class="m-skel-row">
          <div class="m-skel-icon"></div>
          <div class="m-skel-title"></div>
        </div>
        <div v-for="j in 2" :key="'skl-' + j" class="m-skel-line"></div>
      </div>
    </template>

    <!-- Dashboard Cards -->
    <template v-else>
      <div
        v-for="(card, idx) in visibleCards"
        :key="idx"
        :class="['m-card-wrapper', { 'm-card-visible': card }]"
      >
        <OrderOverviewCard
          v-if="idx === 0"
          :data="data"
          :fmt-num="fmtNum"
          :fmt-money="fmtMoney"
        />
        <StockOverviewCard
          v-else-if="idx === 1"
          :data="data"
          :fmt-num="fmtNum"
          :fmt-money="fmtMoney"
        />
        <ProductionDeptCard
          v-else-if="idx === 2"
          :data="data"
          :sorted-departments="sortedDepartments"
          :fmt-num="fmtNum"
          :fmt-money="fmtMoney"
          :rank-label="rankLabel"
          :rank-class="rankClass"
        />
        <WarehouseCard
          v-else-if="idx === 3"
          :data="data"
          :fmt-num="fmtNum"
          :fmt-money="fmtMoney"
        />
      </div>

      <!-- Scroll Hint -->
      <div class="m-scroll-hint">↓ 继续滑动查看更多</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import OrderOverviewCard from './components/OrderOverviewCard.vue'
import StockOverviewCard from './components/StockOverviewCard.vue'
import ProductionDeptCard from './components/ProductionDeptCard.vue'
import WarehouseCard from './components/WarehouseCard.vue'
import { useDashboardMobileData } from './composables/useDashboardMobileData'

const {
  loading,
  error,
  data,
  visibleCards,
  currentTime,
  lastUpdateText,
  sortedDepartments,
  rankLabel,
  rankClass,
  fmtNum,
  fmtMoney,
  loadData,
  refresh,
} = useDashboardMobileData()
</script>

<style scoped>
/*
 * 完全匹配 Android DashboardScreen.kt
 * Apple Design System Colors (from Color.kt):
 *   AccentPrimary: #0071E3 | AccentEmerald: #30D158 | BgDeep: #F5F5F7
 *   TextPrimary: #1D1D1F | TextSecondary: #86868B | TextTertiary: #AEAEB2
 * CardShapeLg: 22px · CardPadding: 20px · IconBox: 38px · AccentGlow: rgba(0,113,227,0.08)
 */

/* --- Layout --- */
.m-dashboard {
  min-height: 100%;
  background: #F5F5F7;
  padding-bottom: calc(var(--m-tabbar-safe, 24px) + 16px);
}

/* --- Status Bar --- */
.m-status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 28px;
}
.m-time {
  font-size: 11px;
  font-weight: 700;
  color: #1D1D1F;
}
.m-status-icons { display: flex; gap: 5px; align-items: center; }
.m-status-signal, .m-status-battery { width: 14px; height: 14px; }

/* --- Header --- */
.m-header { padding: 4px 20px; }
.m-header-title {
  font-size: 22px;
  font-weight: 800;
  color: #1D1D1F;
  margin: 0;
  letter-spacing: -0.4px;
}
.m-header-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #AEAEB2;
  margin-top: 2px;
}
.m-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
  background: #30D158;
  flex-shrink: 0;
}

/* --- Refresh Bar --- */
.m-refresh-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 16px;
}
.m-last-update {
  font-size: 11px;
  font-weight: 500;
  color: #AEAEB2;
}
.m-refresh-btn {
  background: #F8FAFC;
  border: none;
  border-radius: 20px;
  padding: 5px 14px;
  font-size: 11px;
  font-weight: 500;
  color: #86868B;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.m-refresh-btn:active { opacity: 0.7; }

/* --- Error Banner --- */
.m-error-banner {
  display: flex;
  align-items: center;
  margin: 6px 16px;
  padding: 10px 14px;
  background: #FEF2F2;
  border-radius: 12px;
  gap: 8px;
}
.m-error-icon { font-size: 14px; flex-shrink: 0; }
.m-error-text {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: #DC2626;
}
.m-error-retry {
  background: #DC2626;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.m-error-retry:active { background: #B91C1C; }

/* --- Card Wrapper (AnimatedCard from Android) --- */
.m-card-wrapper {
  padding: 0 16px;
  margin-top: 12px;
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 400ms ease, transform 400ms ease;
}
.m-card-visible {
  opacity: 1;
  transform: translateY(0);
}

/* --- Scroll Hint --- */
.m-scroll-hint {
  text-align: center;
  padding: 8px 0 16px;
  font-size: 10px;
  color: #AEAEB2;
  letter-spacing: 0.5px;
}

/* --- Skeleton --- */
.m-skeleton-card {
  margin: 12px 16px 0;
  background: #FFFFFF;
  border-radius: 22px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(0, 0, 0, 0.04);
}
.m-skel-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.m-skel-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: linear-gradient(90deg, #E2E8F0, #CBD5E1, #E2E8F0);
  background-size: 200% 100%;
  animation: shimmer 1.8s ease-in-out infinite;
}
.m-skel-title {
  width: 40%;
  height: 14px;
  border-radius: 7px;
  background: linear-gradient(90deg, #E2E8F0, #CBD5E1, #E2E8F0);
  background-size: 200% 100%;
  animation: shimmer 1.8s ease-in-out infinite;
}
.m-skel-line {
  height: 10px;
  border-radius: 5px;
  margin-bottom: 8px;
  background: linear-gradient(90deg, #E2E8F0, #CBD5E1, #E2E8F0);
  background-size: 200% 100%;
  animation: shimmer 1.8s ease-in-out infinite;
}
.m-skel-line:last-child { width: 60%; }

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
