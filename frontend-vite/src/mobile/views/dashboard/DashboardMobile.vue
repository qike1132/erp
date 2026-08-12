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
      <button class="m-refresh-btn" @click="refresh">
        <span>刷新数据</span>
      </button>
    </div>

    <!-- Error Banner -->
    <div v-if="error" class="m-error-banner">
      <span class="m-error-icon">⚠</span>
      <span class="m-error-text">数据加载异常</span>
      <button class="m-error-retry" @click="loadData">重试</button>
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
        <!-- Card 1: 订单总览 -->
        <div v-if="idx === 0" class="m-card">
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

        <!-- Card 2: 出库总览 -->
        <div v-if="idx === 1" class="m-card">
          <div class="m-card-header">
            <div class="m-card-icon">
              <span class="m-card-emoji">📁</span>
            </div>
            <span class="m-card-title">出库总览</span>
          </div>
          <div class="m-card-gap-12"></div>

          <!-- 当日已出库 -->
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

          <!-- 当月已出库 -->
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

        <!-- Card 3: 生产数据 · 按部门 -->
        <div v-if="idx === 2" class="m-card">
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

        <!-- Card 4: 皮套仓储 -->
        <div v-if="idx === 3" class="m-card">
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
      </div>

      <!-- Scroll Hint -->
      <div class="m-scroll-hint">↓ 继续滑动查看更多</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dashboardApi } from '@/api'
import type { MobileDashboardData } from '@/api/dashboard'

// --- State ---
const loading = ref(true)
const error = ref<string | null>(null)
const data = ref<MobileDashboardData | null>(null)
const lastRefreshTime = ref<number>(0)
const visibleCards = ref([false, false, false, false])

let timeTimer: ReturnType<typeof setInterval> | null = null
let animTimer: ReturnType<typeof setTimeout> | null = null

// --- Current time ---
const currentTime = ref('')
function updateTime() {
  const now = new Date()
  currentTime.value = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0')
}
updateTime()
timeTimer = setInterval(updateTime, 10000)

onUnmounted(() => {
  if (timeTimer) clearInterval(timeTimer)
  if (animTimer) clearTimeout(animTimer)
})

// --- Last update text ---
const lastUpdateText = computed(() => {
  if (loading.value) return '加载中...'
  if (error.value) return `加载失败: ${error.value}`
  if (lastRefreshTime.value === 0) return '加载中...'
  const d = new Date(lastRefreshTime.value)
  return '最后更新: ' + String(d.getHours()).padStart(2, '0') + ':' +
    String(d.getMinutes()).padStart(2, '0') + ':' +
    String(d.getSeconds()).padStart(2, '0')
})

// --- Sorted departments ---
const sortedDepartments = computed(() => {
  if (!data.value?.production?.departments) return []
  return [...data.value.production.departments].sort((a, b) => b.output_value - a.output_value)
})

// --- Rank helpers ---
function rankLabel(idx: number): string {
  return idx < 3 ? (['#1', '#2', '#3'][idx] ?? '') : '#' + (idx + 1)
}

function rankClass(idx: number): string {
  return idx === 0 ? 'm-rank-1' : 'm-rank-other'
}

// --- Formatters (matches Android fmtNum/fmtMoney) ---
function fmtNum(n: any): string {
  if (n === null || n === undefined) return '—'
  if (typeof n === 'number') {
    if (n === Math.floor(n)) return n.toString()
    return n.toString()
  }
  return n.toString()
}

function fmtMoney(n: any): string {
  if (n === null || n === undefined) return '—'
  if (typeof n === 'number') {
    if (n >= 10000) return '¥' + Math.floor(n).toString()
    return '¥' + n.toFixed(2)
  }
  return n.toString()
}

// --- Reveal animation ---
function triggerReveal() {
  visibleCards.value.forEach((_, i) => {
    animTimer = setTimeout(() => {
      visibleCards.value = visibleCards.value.map((v, j) => j <= i ? true : v)
    }, 60 * (i + 1))
  })
}

// --- Load data ---
async function loadData() {
  error.value = null
  try {
    data.value = await dashboardApi.mobile()
    lastRefreshTime.value = Date.now()
  } catch (e: any) {
    error.value = e?.message || '网络请求失败'
    console.warn('[DashboardMobile] load error:', e)
  } finally {
    loading.value = false
  }
}

async function refresh() {
  loading.value = true
  error.value = null
  visibleCards.value = [false, false, false, false]
  await loadData()
  if (!loading.value) {
    triggerReveal()
  }
}

onMounted(async () => {
  await loadData()
  if (!loading.value) {
    triggerReveal()
  }
})
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

/* --- Card (DashboardCard: CardShapeLg=22px, padding=20px) --- */
.m-card {
  background: #FFFFFF;
  border-radius: 22px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(0, 0, 0, 0.04);
}

/* --- Card Header (icon 38px, 12px radius, AccentGlow bg) --- */
.m-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}
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
.m-card-gap-12 { height: 12px; }
.m-card-gap-14 { height: 14px; }

/* --- Metric Grid (2-col, MetricBlock style) --- */
.m-metric-grid-2 {
  display: flex;
  gap: 12px;
}
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
.m-metric-label {
  font-size: 11px;
  font-weight: 500;
  color: #AEAEB2;
}
.m-metric-value {
  font-size: 20px;
  font-weight: 800;
  color: #0071E3;
  letter-spacing: -0.3px;
}

/* --- Section Title (dot 6px + gap 8px) --- */
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

/* --- Stock Package (18px pad, 16px radius, AppleBgGrouped=#F5F5F7) --- */
.m-stock-package {
  background: #F5F5F7;
  border-radius: 16px;
  padding: 18px;
  display: flex;
  justify-content: space-evenly;
}
.m-stock-metric {
  display: flex;
  flex-direction: column;
}
.m-stock-label {
  font-size: 11px;
  font-weight: 500;
  color: #AEAEB2;
}
.m-stock-gap-8 { height: 8px; }
.m-stock-value {
  font-size: 18px;
  font-weight: 800;
  color: #0071E3;
  letter-spacing: -0.3px;
}

/* --- Production Total --- */
.m-prod-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.m-prod-total-label {
  font-size: 12px;
  color: #AEAEB2;
}
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

/* --- Department List --- */
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
.m-dept-sub {
  font-size: 11px;
  color: #AEAEB2;
}
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

/* --- Warehouse Grid --- */
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
.m-wh-label {
  font-size: 10px;
  font-weight: 500;
  color: #AEAEB2;
}
.m-wh-value {
  font-size: 16px;
  font-weight: 800;
  color: #0071E3;
}
.m-wh-sub {
  font-size: 11px;
  font-weight: 500;
  color: #AEAEB2;
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
