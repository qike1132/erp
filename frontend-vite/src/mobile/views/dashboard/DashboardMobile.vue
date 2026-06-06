<template>
  <div class="m-dashboard">
    <div class="m-dash-header">
      <div class="m-dash-greeting">
        <span class="m-dash-time">{{ greeting }}</span>
        <h1 class="m-dash-name">{{ authStore.user?.username || '用户' }}</h1>
      </div>
      <div class="m-dash-avatar">
        {{ (authStore.user?.username || 'U').charAt(0).toUpperCase() }}
      </div>
    </div>

    <div v-if="loading" class="m-dash-loading">
      <MSpinner size="lg" />
    </div>

    <template v-else>
      <section class="m-dash-section">
        <h2 class="m-section-title">今日概览</h2>
        <div class="m-stats-grid">
          <MStatCard
            :value="stats?.order_today ?? 0"
            label="今日订单"
            icon-bg="rgba(0,113,227,0.1)"
            :trend="orderTrend"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="#0071E3" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
                <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" /><line x1="3" y1="6" x2="21" y2="6" /><path d="M16 10a4 4 0 0 1-8 0" />
              </svg>
            </template>
          </MStatCard>
          <MStatCard
            :value="stats?.stockin_today ?? 0"
            label="今日入库"
            icon-bg="rgba(48,209,88,0.1)"
            :trend="stockinTrend"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="#30D158" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              </svg>
            </template>
          </MStatCard>
          <MStatCard
            :value="stats?.stockout_today ?? 0"
            label="今日出库"
            icon-bg="rgba(255,149,0,0.1)"
            :trend="stockoutTrend"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="#FF9500" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
                <polyline points="17 1 21 5 17 9" /><path d="M3 11V9a4 4 0 0 1 4-4h14" /><polyline points="7 23 3 19 7 15" /><path d="M21 13v2a4 4 0 0 1-4 4H3" />
              </svg>
            </template>
          </MStatCard>
          <MStatCard
            :value="stats?.pending_approvals ?? 0"
            label="待审批"
            icon-bg="rgba(175,82,222,0.1)"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="#AF52DE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </template>
          </MStatCard>
        </div>
      </section>

      <section class="m-dash-section">
        <h2 class="m-section-title">快捷入口</h2>
        <div class="m-quick-grid">
          <MCard clickable padded @click="$router.push('/purchase')">
            <div class="m-quick-card-icon" style="background:rgba(0,113,227,0.08)">
              <svg viewBox="0 0 24 24" fill="none" stroke="#0071E3" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
            </div>
            <span class="m-quick-card-label">采购中心</span>
          </MCard>
          <MCard clickable padded @click="$router.push('/material-calculator')">
            <div class="m-quick-card-icon" style="background:rgba(48,209,88,0.08)">
              <svg viewBox="0 0 24 24" fill="none" stroke="#30D158" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="10" x2="16" y2="10"/></svg>
            </div>
            <span class="m-quick-card-label">物料计算</span>
          </MCard>
          <MCard clickable padded @click="$router.push('/incoming')">
            <div class="m-quick-card-icon" style="background:rgba(255,149,0,0.08)">
              <svg viewBox="0 0 24 24" fill="none" stroke="#FF9500" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/></svg>
            </div>
            <span class="m-quick-card-label">来料登记</span>
          </MCard>
          <MCard clickable padded @click="$router.push('/production')">
            <div class="m-quick-card-icon" style="background:rgba(175,82,222,0.08)">
              <svg viewBox="0 0 24 24" fill="none" stroke="#AF52DE" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="24" height="24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            </div>
            <span class="m-quick-card-label">生产报表</span>
          </MCard>
        </div>
      </section>

      <section class="m-dash-section">
        <h2 class="m-section-title">预警提醒</h2>
        <MList>
          <MListItem title="库存预警" :subtitle="`${stats?.low_stock_count ?? 0} 种物料低于安全库存`" to="/batch">
            <template #icon>
              <div style="background:rgba(255,45,85,0.08);width:100%;height:100%;display:flex;align-items:center;justify-content:center;border-radius:8px">
                <svg viewBox="0 0 24 24" fill="none" stroke="#FF2D55" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              </div>
            </template>
          </MListItem>
          <MListItem title="待采购" :subtitle="`${stats?.pending_purchases ?? 0} 项采购待处理`" to="/purchase">
            <template #icon>
              <div style="background:rgba(255,149,0,0.08);width:100%;height:100%;display:flex;align-items:center;justify-content:center;border-radius:8px">
                <svg viewBox="0 0 24 24" fill="none" stroke="#FF9500" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
              </div>
            </template>
          </MListItem>
        </MList>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dashboardApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import MStatCard from '@/mobile/components/MStatCard.vue'
import MCard from '@/mobile/components/MCard.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

const authStore = useAuthStore()
const loading = ref(true)
const stats = ref<any>(null)

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

function calcTrend(today: number, yesterday: number): number | undefined {
  if (!yesterday) return undefined
  return Math.round(((today - yesterday) / yesterday) * 100)
}

const orderTrend = computed(() => calcTrend(stats.value?.order_today ?? 0, stats.value?.order_yesterday ?? 0))
const stockinTrend = computed(() => calcTrend(stats.value?.stockin_today ?? 0, stats.value?.stockin_yesterday ?? 0))
const stockoutTrend = computed(() => calcTrend(stats.value?.stockout_today ?? 0, stats.value?.stockout_yesterday ?? 0))

async function loadStats() {
  try {
    stats.value = await dashboardApi.stats()
  } catch {
    stats.value = {
      order_today: 0, order_yesterday: 0,
      stockin_today: 0, stockin_yesterday: 0,
      stockout_today: 0, stockout_yesterday: 0,
      pending_approvals: 0, low_stock_count: 0,
      pending_purchases: 0, pending_materials: 0,
    }
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)
</script>

<style scoped>
.m-dashboard {
  padding: var(--m-gap-md);
  padding-bottom: calc(var(--m-gap-md) + var(--m-tabbar-safe));
}

.m-dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(var(--m-safe-top) + 8px) 0 20px;
}

.m-dash-greeting {
  display: flex;
  flex-direction: column;
}

.m-dash-time {
  font-size: 13px;
  color: var(--m-text-secondary);
  font-weight: 500;
}

.m-dash-name {
  font-size: 28px;
  font-weight: 800;
  color: var(--m-text-primary);
  margin: 0;
  letter-spacing: -0.5px;
}

.m-dash-avatar {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: var(--m-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
}

.m-dash-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 80px 0;
}

.m-dash-section {
  margin-bottom: 20px;
}

.m-section-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--m-text-primary);
  margin: 0 0 10px;
}

.m-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.m-quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.m-quick-card-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 6px;
}

.m-quick-card-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--m-text-secondary);
}
</style>
