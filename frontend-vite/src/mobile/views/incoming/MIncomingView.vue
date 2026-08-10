<template>
  <div class="m-page">
    <MobileNavBar title="来料登记" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <template v-if="activeTab === 'overview'">
        <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
        <template v-else-if="overview">
          <div class="m-stats-row">
            <MStatCard :value="overview.total ?? 0" label="总登记数" icon-bg="rgba(0,113,227,0.1)">
              <template #icon><svg viewBox="0 0 24 24" fill="none" stroke="#0071E3" stroke-width="2" width="20" height="20"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></template>
            </MStatCard>
            <MStatCard :value="overview.pending ?? 0" label="待收货" icon-bg="rgba(255,149,0,0.1)">
              <template #icon><svg viewBox="0 0 24 24" fill="none" stroke="#FF9500" stroke-width="2" width="20" height="20"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></template>
            </MStatCard>
          </div>
        </template>
      </template>

      <template v-if="activeTab === 'records'">
        <MSearchBar v-model="keyword" placeholder="搜索物料/供应商..." />
        <div v-if="recordsLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="!records.length" title="暂无登记记录" />
        <MList v-else>
          <MListItem v-for="r in records" :key="r.id" :title="r.purchase_order_no || r.product_name || '—'" :subtitle="`${r.supplier_name || '—'} · ${r.product_quantity || 0}`">
            <template #icon>
              <div class="m-icon-bg" :style="{ background: r.status === 'completed' ? 'var(--m-accent-emerald)' : 'var(--m-accent-amber)' }">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              </div>
            </template>
            <template #value><span :class="['m-badge', r.status === 'completed' ? 'done' : 'pending']">{{ r.status === 'completed' ? '已收货' : (r.status === 'partial' ? '部分收货' : '待收货') }}</span></template>
          </MListItem>
        </MList>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { materialApi } from '@/api'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MFilterChips from '@/mobile/components/MFilterChips.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MStatCard from '@/mobile/components/MStatCard.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'
import MEmpty from '@/mobile/components/MEmpty.vue'
import MSpinner from '@/mobile/components/MSpinner.vue'

const activeTab = ref('overview')
const tabChips = [{ label: '概览', value: 'overview' }, { label: '记录', value: 'records' }]
const keyword = ref('')
const overview = ref<any>(null)
const loading = ref(false)
const records = ref<any[]>([])
const recordsLoading = ref(false)

async function loadOverview() {
  loading.value = true
  try { overview.value = await materialApi.overview() } finally { loading.value = false }
}

async function loadRecords() {
  recordsLoading.value = true
  try { records.value = (await materialApi.registrations({ page: 1, per_page: 50 }))?.registrations || [] } finally { recordsLoading.value = false }
}

onMounted(() => { loadOverview(); loadRecords() })
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-center { display: flex; justify-content: center; padding: 48px 0; }
.m-stats-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.m-icon-bg { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-badge { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.m-badge.done { color: var(--m-accent-emerald); background: rgba(48,209,88,0.1); }
.m-badge.pending { color: var(--m-accent-amber); background: rgba(255,149,0,0.1); }
</style>
