<script setup lang="ts">
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi } from '@/api'
import { formatDateTime } from '@/utils/format'
import PlanDetailCardList from './PlanDetailCardList.vue'

interface PlanInfo {
  customer_name: string
  plan_month: string
  status: string
  created_by: string
  create_time: string
  remark: string
}

interface PlanDetailItem {
  id: number
  shipment_status: string
  product_name: string
  barcode: string
  plan_date: string
  quantity: number
  shipped_qty: number
  remaining_qty: number
  inventory_qty: number
}

interface PlanDetailResponse {
  plan: PlanInfo
  details: PlanDetailItem[]
}

const props = defineProps<{
  visible: boolean
  planId: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  edited: []
}>()

const { data: detailData, isLoading, isError } = useQuery({
  queryKey: ['plan-detail', () => props.planId],
  queryFn: async (): Promise<PlanDetailResponse | null> => {
    if (!props.planId) return null
    return (await planApi.detail(props.planId)) as unknown as PlanDetailResponse
  },
  enabled: () => props.visible && props.planId > 0,
  staleTime: 10_000,
})

const planData = computed(() => detailData.value?.plan ?? null)
const details = computed(() => detailData.value?.details ?? [])

const STATUS_CLASS: Record<string, string> = {
  completed: 'drw-st-completed',
  confirmed: 'drw-st-confirmed',
  cancelled: 'drw-st-cancelled',
}
const STATUS_TEXT: Record<string, string> = {
  completed: '已完成',
  confirmed: '已确认',
  cancelled: '已取消',
}

function planStatusCls(s: string) { return STATUS_CLASS[s] || 'drw-st-pending' }
function planStatusTxt(s: string) { return STATUS_TEXT[s] || '待确认' }
</script>

<template>
  <UiDrawer :visible="visible" title="计划详情" @update:visible="emit('update:visible', $event)">
    <div v-if="isLoading" class="flex items-center justify-center py-12 text-text-muted">
      <UiSpinner />
    </div>

    <div v-else-if="isError" class="flex items-center justify-center gap-2 py-12 text-text-muted">
      <FontAwesomeIcon icon="exclamation-circle" class="text-danger-600" aria-hidden="true" />
      加载失败
    </div>

    <template v-else-if="planData">
      <section class="mb-6">
        <h4 class="section-title">基本信息</h4>
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">客户名称</span>
            <span class="info-value">{{ planData.customer_name }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">计划月份</span>
            <span class="info-value">{{ planData.plan_month }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">状态</span>
            <span class="status-badge" :class="planStatusCls(planData.status)">
              {{ planStatusTxt(planData.status) }}
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">创建人</span>
            <span class="info-value">{{ planData.created_by || '-' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">创建时间</span>
            <span class="info-value">{{ formatDateTime(planData.create_time) }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">备注</span>
            <span class="info-value">{{ planData.remark || '-' }}</span>
          </div>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h4 class="section-title">计划明细</h4>
          <span class="detail-count">共 {{ details.length }} 条</span>
        </div>
        <PlanDetailCardList :details="details" />
      </section>
    </template>
  </UiDrawer>
</template>

<style scoped>
.section-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 12px;
  padding-bottom: 4px;
  border-bottom: 2px solid var(--color-primary-100);
  display: inline-block;
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.detail-count {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.info-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.info-value {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text);
}

.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 600;
  width: fit-content;
}
.drw-st-completed { background: var(--color-success-50); color: var(--color-success-600); }
.drw-st-confirmed { background: var(--color-primary-50); color: var(--color-primary-600); }
.drw-st-cancelled { background: var(--color-danger-50); color: var(--color-danger-600); }
.drw-st-pending { background: var(--color-warning-50); color: var(--color-warning-600); }

@media (max-width: 640px) {
  .info-grid { grid-template-columns: 1fr; }
}
</style>
