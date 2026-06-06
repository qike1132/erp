<template>
  <div class="m-page">
    <MobileNavBar title="出货计划" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <template v-if="activeTab === 'plans'">
        <div class="m-date-nav">
          <button class="m-date-btn" @click="prevDay">&lsaquo;</button>
          <span class="m-date-text">{{ dateRef }}</span>
          <button class="m-date-btn" @click="nextDay">&rsaquo;</button>
          <button class="m-date-btn today" @click="dateRef = todayStr()">今天</button>
        </div>
        <div v-if="plansLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!plans.length" title="暂无出货计划" />
        <MList v-else>
          <MListItem v-for="p in plans" :key="p.id" :title="p.customer_name || '—'" :subtitle="`${p.product_name || ''} · ${p.quantity || 0}件`">
            <template #icon>
              <div class="m-icon-bg" style="background:var(--m-accent)">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              </div>
            </template>
            <template #value>
              <span class="m-status" :style="{ color: planStatusColor(p.status) }">{{ planStatusLabel(p.status) }}</span>
            </template>
          </MListItem>
        </MList>
      </template>

      <template v-if="activeTab === 'progress'">
        <div v-if="progressLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!progressData" title="暂无进度数据" />
        <div v-else class="m-progress-cards">
          <MCard v-for="(val, key) in progressData" :key="key" padded>
            <div class="m-pg-label">{{ key }}</div>
            <MProgress :value="typeof val === 'number' ? val : 0" :max="100" show-percent animated />
          </MCard>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { planApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'
import MProgress from '@/mobile/components/MProgress.vue'
import MCard from '@/mobile/components/MCard.vue'

const activeTab = ref('plans')
const tabChips = [{ label: '出货计划', value: 'plans' }, { label: '出货进度', value: 'progress' }]
const dateRef = ref(todayStr())
const plans = ref<any[]>([])
const plansLoading = ref(false)
const progressData = ref<any>(null)
const progressLoading = ref(false)

function todayStr() { return new Date().toISOString().slice(0, 10) }
function prevDay() { const d = new Date(dateRef.value); d.setDate(d.getDate() - 1); dateRef.value = d.toISOString().slice(0, 10) }
function nextDay() { const d = new Date(dateRef.value); d.setDate(d.getDate() + 1); dateRef.value = d.toISOString().slice(0, 10) }

async function loadPlans() {
  plansLoading.value = true
  try { plans.value = (await planApi.list({ date: dateRef.value }))?.items || [] } finally { plansLoading.value = false }
}
async function loadProgress() {
  progressLoading.value = true
  try { progressData.value = await planApi.shippingProgress() } finally { progressLoading.value = false }
}

watch(dateRef, loadPlans)
onMounted(() => { loadPlans(); loadProgress() })

function planStatusColor(s: string) {
  if (s === 'shipped') return 'var(--m-accent-emerald)'
  if (s === 'partial') return 'var(--m-accent-amber)'
  return 'var(--m-text-secondary)'
}
function planStatusLabel(s: string) {
  const map: Record<string, string> = { shipped: '已出货', partial: '部分出货', pending: '待出货' }
  return map[s] || s || '—'
}
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-date-nav { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 12px; }
.m-date-btn { width: 32px; height: 32px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; background: var(--m-bg-surface); font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-family: inherit; }
.m-date-btn.today { width: auto; padding: 0 10px; font-size: 12px; }
.m-date-text { font-size: 15px; font-weight: 600; color: var(--m-text-primary); min-width: 100px; text-align: center; }
.m-icon-bg { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-status { font-size: 12px; font-weight: 600; }
.m-progress-cards { display: flex; flex-direction: column; gap: 10px; }
.m-pg-label { font-size: 14px; font-weight: 600; color: var(--m-text-primary); margin-bottom: 8px; }
</style>
