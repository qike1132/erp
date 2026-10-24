<template>
  <div
    class="m-dashboard"
    :class="{ 'm-pull-refreshing': refreshing }"
    :style="pullStyle"
  >
    <!-- 下拉刷新指示器 -->
    <div class="m-pull" :class="{ 'm-pull-show': pullDistance > 0 || refreshing }">
      <div
        class="m-pull-spinner"
        :class="{ 'm-pull-spinning': refreshing }"
        :style="{ transform: refreshing ? undefined : `rotate(${pullDistance * 3.2}deg)` }"
      />
      <span class="m-pull-text">{{ pullText }}</span>
    </div>

    <!-- iOS Large Title 导航区 -->
    <header class="m-header">
      <div class="m-header-main">
        <h1 class="m-title">概览</h1>
        <p class="m-subtitle">
          {{ todayLabel }}
          <span class="m-live"><i class="m-live-dot" />实时</span>
        </p>
      </div>
      <button class="m-refresh-btn" aria-label="刷新数据" @click="refresh">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12a9 9 0 1 1-2.64-6.36" />
          <polyline points="21 3 21 9 15 9" />
        </svg>
      </button>
    </header>

    <!-- 核心指标 Hero 卡 -->
    <section v-if="!loading || data" class="m-hero">
      <div class="m-hero-top">
        <span class="m-hero-eyebrow">今日业务</span>
        <span class="m-hero-update">{{ lastUpdateText }}</span>
      </div>
      <div class="m-hero-metrics">
        <div class="m-hero-metric">
          <span class="m-hero-label">今日订单</span>
          <span class="m-hero-value">{{ fmtNum(data?.orders?.daily_qty) }}</span>
        </div>
        <div class="m-hero-metric">
          <span class="m-hero-label">今日总产值</span>
          <span class="m-hero-value">{{ fmtMoney(data?.production?.total_value) }}</span>
        </div>
      </div>
      <div class="m-hero-foot">
        <!-- AUD-12（2026-10-24 审计）：orders.total_qty 是全历史累计件数（后端无
             月度字段），原标签「本月订单」恒显示累计值、与同屏「总订单数量」卡片
             同数字两个口径。标签改为与数据一致的「累计订单」；若产品要本月口径，
             需后端补 month_qty（SUM FILTER order_date >= month_start）后再改回。 -->
        <span>累计订单 {{ fmtNum(data?.orders?.total_qty) }}</span>
        <span>累计产值 {{ fmtMoney(data?.stock?.total_amount) }}</span>
      </div>
    </section>

    <!-- 错误横幅 -->
    <div v-if="error" class="m-error-banner" role="alert">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span class="m-error-text">数据加载异常</span>
      <button class="m-error-retry" @click="loadData">重试</button>
    </div>

    <!-- 加载骨架 -->
    <template v-if="loading && !data">
      <div v-for="i in 3" :key="'sk-' + i" class="m-skeleton">
        <div class="m-skel-head">
          <div class="m-skel-icon" />
          <div class="m-skel-title" />
        </div>
        <div class="m-skel-line" />
        <div class="m-skel-line short" />
      </div>
    </template>

    <!-- 分组卡片 -->
    <template v-else>
      <h2 class="m-section-title">业务</h2>
      <div :class="['m-card-wrap', { 'm-card-in': visibleCards[1] }]">
        <StockOverviewCard :data="data" :fmt-num="fmtNum" :fmt-money="fmtMoney" />
      </div>
      <div :class="['m-card-wrap', { 'm-card-in': visibleCards[0] }]">
        <OrderOverviewCard :data="data" :fmt-num="fmtNum" :fmt-money="fmtMoney" />
      </div>

      <h2 class="m-section-title">生产</h2>
      <div :class="['m-card-wrap', { 'm-card-in': visibleCards[2] }]">
        <ProductionDeptCard
          :data="data"
          :sorted-departments="sortedDepartments"
          :fmt-num="fmtNum"
          :fmt-money="fmtMoney"
          :rank-label="rankLabel"
        />
      </div>

      <h2 class="m-section-title">仓储</h2>
      <div :class="['m-card-wrap', { 'm-card-in': visibleCards[3] }]">
        <WarehouseCard :data="data" :fmt-num="fmtNum" :fmt-money="fmtMoney" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import StockOverviewCard from './components/StockOverviewCard.vue'
import OrderOverviewCard from './components/OrderOverviewCard.vue'
import ProductionDeptCard from './components/ProductionDeptCard.vue'
import WarehouseCard from './components/WarehouseCard.vue'
import { useDashboardMobileData } from './composables/useDashboardMobileData'

const {
  loading,
  refreshing,
  error,
  data,
  visibleCards,
  lastUpdateText,
  sortedDepartments,
  rankLabel,
  fmtNum,
  fmtMoney,
  loadData,
  refresh,
  onPullRefresh,
} = useDashboardMobileData()

/* ---------- 顶部日期 ---------- */
const todayLabel = computed(() => {
  const now = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()]
  return `${now.getMonth() + 1}月${now.getDate()}日 星期${week}`
})

/* ---------- 下拉刷新（iOS 橡皮筋） ---------- */
const PULL_THRESHOLD = 62
const pullDistance = ref(0)
const pulling = ref(false)
let startY = 0
let tracking = false
let containerEl: HTMLElement | null = null
const reduceMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function findScrollContainer(): HTMLElement | null {
  let el: HTMLElement | null = document.querySelector('.m-layout-content')
  if (!el) {
    el = document.querySelector('.m-dashboard')?.parentElement ?? null
  }
  return el
}

function onTouchStart(e: TouchEvent) {
  if (refreshing.value) return
  const el = containerEl
  if (!el) return
  if (el.scrollTop <= 0) {
    tracking = true
    startY = e.touches[0]!.clientY
    pulling.value = false
  }
}

function onTouchMove(e: TouchEvent) {
  if (!tracking || refreshing.value) return
  const delta = e.touches[0]!.clientY - startY
  if (delta <= 0) {
    pullDistance.value = 0
    return
  }
  // 橡皮筋：下拉距离越远阻力越大
  const resisted = Math.round(delta * 0.5)
  pullDistance.value = Math.min(resisted, 90)
  if (pullDistance.value > 0 && containerEl && containerEl.scrollTop <= 0) {
    e.preventDefault()
  }
}

async function onTouchEnd() {
  if (!tracking) return
  tracking = false
  if (pullDistance.value >= PULL_THRESHOLD) {
    await onPullRefresh()
  }
  pullDistance.value = 0
}

const pullStyle = computed(() => {
  if (reduceMotion) return {}
  return { transform: `translateY(${pullDistance.value}px)` }
})

const pullText = computed(() => {
  if (refreshing.value) return '刷新中…'
  return pullDistance.value >= PULL_THRESHOLD ? '松开刷新' : '下拉刷新'
})

onMounted(() => {
  containerEl = findScrollContainer()
  if (containerEl) {
    containerEl.addEventListener('touchstart', onTouchStart, { passive: true })
    containerEl.addEventListener('touchmove', onTouchMove, { passive: false })
    containerEl.addEventListener('touchend', onTouchEnd, { passive: true })
  }
})

onUnmounted(() => {
  if (containerEl) {
    containerEl.removeEventListener('touchstart', onTouchStart)
    containerEl.removeEventListener('touchmove', onTouchMove)
    containerEl.removeEventListener('touchend', onTouchEnd)
  }
})
</script>

<style scoped>
.m-dashboard {
  min-height: 100%;
  background: #f5f5f7;
  padding: calc(var(--m-safe-top, 0px) + 8px) 0 calc(var(--m-tabbar-safe, 72px) + 8px);
  transition: transform 0.25s var(--m-ease-out);
  will-change: transform;
}

.m-dashboard.m-pull-refreshing {
  transition: transform 0.35s var(--m-ease-spring);
}

/* ---------- 下拉刷新指示器 ---------- */
.m-pull {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 40px;
  opacity: 0;
  transform: translateY(-12px);
  transition: opacity 0.2s var(--m-ease-smooth), transform 0.2s var(--m-ease-smooth);
}
.m-pull-show { opacity: 1; transform: translateY(0); }
.m-pull-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(0, 113, 227, 0.2);
  border-top-color: #0071e3;
  border-radius: 50%;
}
.m-pull-spinning { animation: m-pull-spin 0.7s linear infinite; }
.m-pull-text { font-size: 12px; font-weight: 500; color: #86868b; }
@keyframes m-pull-spin {
  to { transform: rotate(360deg); }
}

/* ---------- 导航区 ---------- */
.m-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 8px 20px 4px;
}
.m-title {
  margin: 0;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.6px;
  color: #1d1d1f;
}
.m-subtitle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 500;
  color: #86868b;
}
.m-live { display: inline-flex; align-items: center; gap: 5px; color: #aeaeb2; }
.m-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #30d158;
}
.m-refresh-btn {
  width: 36px;
  height: 36px;
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.8);
  color: #0071e3;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  -webkit-tap-highlight-color: transparent;
}
.m-refresh-btn svg { width: 18px; height: 18px; }
.m-refresh-btn:active { transform: scale(0.9); opacity: 0.7; }

/* ---------- 核心 Hero 卡 ---------- */
.m-hero {
  margin: 12px 16px 0;
  padding: 18px 20px 16px;
  border-radius: 22px;
  color: #fff;
  background:
    radial-gradient(120% 160% at 100% 0%, rgba(41, 151, 255, 0.55) 0%, rgba(0, 113, 227, 0) 45%),
    linear-gradient(135deg, #0071e3 0%, #0a84ff 100%);
  box-shadow: 0 8px 24px rgba(0, 113, 227, 0.28);
  animation: m-fade-rise 0.5s var(--m-ease-out) both;
}
.m-hero-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.m-hero-eyebrow {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.4px;
  opacity: 0.85;
}
.m-hero-update { font-size: 11px; font-weight: 500; opacity: 0.75; }
.m-hero-metrics {
  display: flex;
  align-items: stretch;
  margin-top: 16px;
}
.m-hero-metric {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.m-hero-metric + .m-hero-metric {
  padding-left: 20px;
  border-left: 1px solid rgba(255, 255, 255, 0.22);
}
.m-hero-label { font-size: 13px; font-weight: 500; opacity: 0.8; }
.m-hero-value {
  font-size: 30px;
  font-weight: 800;
  letter-spacing: -0.8px;
  line-height: 1.1;
}
.m-hero-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 12px;
  font-weight: 500;
  opacity: 0.85;
}

/* ---------- 分节标题 ---------- */
.m-section-title {
  margin: 24px 20px 8px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: #86868b;
}

/* ---------- 卡片容器 ---------- */
.m-card-wrap {
  margin: 0 16px 12px;
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 0.4s var(--m-ease-out), transform 0.4s var(--m-ease-out);
}
.m-card-in { opacity: 1; transform: translateY(0); }

/* ---------- 错误横幅 ---------- */
.m-error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 16px 0;
  padding: 12px 14px;
  background: #fef2f2;
  border-radius: 14px;
  color: #dc2626;
}
.m-error-banner svg { width: 18px; height: 18px; flex-shrink: 0; }
.m-error-text { flex: 1; font-size: 13px; font-weight: 500; }
.m-error-retry {
  background: #dc2626;
  color: #fff;
  border: none;
  border-radius: 9px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

/* ---------- 骨架 ---------- */
.m-skeleton {
  margin: 12px 16px 0;
  background: #ffffff;
  border-radius: 20px;
  padding: 16px;
  border: 0.5px solid rgba(0, 0, 0, 0.04);
}
.m-skel-head { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.m-skel-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(90deg, #e2e8f0, #cbd5e1, #e2e8f0);
  background-size: 200% 100%;
  animation: m-shimmer 1.6s ease-in-out infinite;
}
.m-skel-title {
  width: 40%;
  height: 14px;
  border-radius: 7px;
  background: linear-gradient(90deg, #e2e8f0, #cbd5e1, #e2e8f0);
  background-size: 200% 100%;
  animation: m-shimmer 1.6s ease-in-out infinite;
}
.m-skel-line {
  height: 12px;
  border-radius: 6px;
  margin-bottom: 8px;
  background: linear-gradient(90deg, #f2f2f7, #e5e5ea, #f2f2f7);
  background-size: 200% 100%;
  animation: m-shimmer 1.6s ease-in-out infinite;
}
.m-skel-line.short { width: 60%; }

@keyframes m-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@keyframes m-fade-rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .m-dashboard { transition: none; }
  .m-hero, .m-card-wrap, .m-skeleton * { animation: none; }
  .m-card-wrap { transition: none; }
}
</style>
