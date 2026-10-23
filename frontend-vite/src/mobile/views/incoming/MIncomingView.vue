<template>
  <div class="m-page">
    <MobileNavBar title="来料登记" :show-back="true" />
    <div class="m-page-body">
      <MFilterChips v-model="activeTab" :chips="tabChips" />

      <template v-if="activeTab === 'overview'">
        <div v-if="loading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="overviewError" :title="overviewError">
          <template #action>
            <button class="m-retry-btn" @click="loadOverview">重试</button>
          </template>
        </MEmpty>
        <template v-else-if="overview">
          <div class="m-stats-row">
            <MStatCard :value="overview.total ?? 0" label="总登记数" icon-bg="rgba(0,113,227,0.1)">
              <template #icon><svg viewBox="0 0 24 24" fill="none" stroke="#0071E3" stroke-width="2" width="20" height="20"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg></template>
            </MStatCard>
            <MStatCard :value="overview.pending ?? 0" label="待收货" icon-bg="rgba(255,149,0,0.1)">
              <template #icon><svg viewBox="0 0 24 24" fill="none" stroke="#FF9500" stroke-width="2" width="20" height="20"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg></template>
            </MStatCard>
          </div>
        </template>
      </template>

      <template v-if="activeTab === 'records'">
        <MSearchBar v-model="keyword" placeholder="搜索订单号/供应商/物料..." @search="onRecordsSearch" />
        <div v-if="recordsLoading" class="m-center"><MSpinner size="lg" /></div>
        <MEmpty v-else-if="recordsError" :title="recordsError">
          <template #action>
            <button class="m-retry-btn" @click="loadRecords">重试</button>
          </template>
        </MEmpty>
        <MEmpty v-else-if="!records.length" title="暂无登记记录" />
        <MList v-else>
          <MListItem v-for="r in records" :key="r.id" :title="r.purchase_order_no || r.product_name || '—'" :subtitle="`${r.supplier_name || '—'} · ${r.product_quantity || 0}`">
            <template #icon>
              <div class="m-icon-bg" :style="{ background: r.status === 'completed' ? 'var(--m-accent-emerald)' : 'var(--m-accent-amber)' }">
                <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="16" height="16"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
              </div>
            </template>
            <template #value><span :class="['m-badge', r.status === 'completed' ? 'done' : 'pending']">{{ r.status === 'completed' ? '已收货' : (r.status === 'partial' ? '部分收货' : '待收货') }}</span></template>
          </MListItem>
        </MList>
        <UiPagination
          v-if="!recordsLoading && !recordsError && recordsTotal > recordsPerPage"
          :current-page="recordsPage"
          :total-pages="Math.ceil(recordsTotal / recordsPerPage)"
          :total-items="recordsTotal"
          @update:current-page="(p: number) => { recordsPage = p; loadRecords() }"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { materialApi } from '@/api'
import { MOBILE_PAGE_SIZE } from '@/mobile/constants'
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
// 概览/记录响应类型由 API 层签名推导，移动端不再自行声明后端 DTO（2026-10-17 审计 F1-3）
type IncomingOverview = Awaited<ReturnType<typeof materialApi.overview>>['overview']
type IncomingRecords = Awaited<ReturnType<typeof materialApi.registrations>>
const overview = ref<IncomingOverview | null>(null)
const loading = ref(false)
const overviewError = ref('')
const records = ref<IncomingRecords['registrations']>([])
const recordsLoading = ref(false)
const recordsError = ref('')
// 2026-10-17 审计 P1-30：服务端分页（此前固定 page=1/per_page=50，第 51 条起不可达）
const recordsPage = ref(1)
const recordsTotal = ref(0)
const recordsPerPage = MOBILE_PAGE_SIZE
let recordsSeq = 0

function errorText(e: unknown, fallback: string) {
  // 403 已由全局拦截器 toast；页面仍需可理解状态，不能只留空白
  return (e as { response?: { status?: number } })?.response?.status === 403 ? '无查看权限' : fallback
}

async function loadOverview() {
  loading.value = true
  overviewError.value = ''
  try {
    overview.value = (await materialApi.overview()).overview
  } catch (e) {
    overview.value = null
    overviewError.value = errorText(e, '概览加载失败，请点击重试')
  } finally {
    loading.value = false
  }
}

async function loadRecords() {
  const seq = ++recordsSeq
  recordsLoading.value = true
  recordsError.value = ''
  try {
    const res = await materialApi.registrations({
      page: recordsPage.value,
      per_page: recordsPerPage,
      keyword: keyword.value.trim() || undefined,
    })
    if (seq !== recordsSeq) return // 丢弃过期响应，旧响应不得覆盖新页/新关键词
    records.value = res?.registrations || []
    recordsTotal.value = res?.total ?? 0
  } catch (e) {
    if (seq !== recordsSeq) return
    records.value = []
    recordsError.value = errorText(e, '记录加载失败，请点击重试')
  } finally {
    if (seq === recordsSeq) recordsLoading.value = false
  }
}

/** 搜索框显式提交（回车）：回到第 1 页，不逐字符请求 */
function onRecordsSearch() {
  recordsPage.value = 1
  void loadRecords()
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
.m-retry-btn { margin-top: 12px; height: 36px; padding: 0 20px; border: none; border-radius: 10px; background: var(--m-accent); color: white; font-size: 14px; font-weight: 600; cursor: pointer; font-family: inherit; }
</style>
