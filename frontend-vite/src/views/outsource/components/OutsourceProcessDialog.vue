<template>
  <!-- ============ 订单外发工序弹窗（重新设计：步骤卡片流 + 甘特图排期） ============ -->
  <UiDialog v-model:open="detailOpen" title="订单外发工序" max-width-class="max-w-[1180px]">
    <div v-if="detailData" class="oso-detail">
      <!-- ① 订单信息 + 总体进度 -->
      <div class="oso-detail-head">
        <div class="oso-detail-meta">
          <span class="oso-detail-no">{{ detailData.order_no || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">客户</span>{{ detailData.customer || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">下单</span>{{ detailData.order_date || '-' }}</span>
          <span class="oso-detail-meta-item"><span class="oso-detail-meta-label">数量</span><strong class="oso-detail-meta-num">{{ detailTotalQuantity }}</strong></span>
        </div>
        <div class="oso-detail-overview">
          <div class="oso-detail-progress">
            <UiProgressBar :percent="detailProgress" :variant="progressVariant(detailProgress)" />
          </div>
          <span class="oso-detail-progress-text">
            <strong>{{ detailProgress }}%</strong>
            <span>{{ completedProcesses }}/{{ totalProcesses }} 道完成</span>
          </span>
          <span v-if="totalProcesses > 0" :class="['oso-status-badge', `oso-status-${detailStatusClass}`]">{{ detailStatusLabel }}</span>
        </div>
      </div>

      <!-- ② 操作条 -->
      <div v-if="isStockinRecord" class="oso-detail-actions">
        <span class="oso-detail-hint">备货记录不参与外发工序管理，请在订单记录上操作</span>
      </div>
      <div v-else-if="canManage" class="oso-detail-actions">
        <UiButton variant="primary" size="sm" :disabled="generating" @click="handleGenerate">
          <FontAwesomeIcon icon="wand-magic-sparkles" aria-hidden="true" /> {{ generating ? '生成中…' : '按SKU预设生成工序' }}
        </UiButton>
        <span class="oso-detail-hint">返单时系统已按 SKU 预设自动带出工序，可在此补生成</span>
      </div>

      <!-- ③ 内容区 -->
      <div v-if="loadingProcesses" class="oso-empty">
        <UiSpinner />
      </div>
      <template v-else>
        <div v-if="processRows.length === 0" class="oso-empty">
          <FontAwesomeIcon icon="route" aria-hidden="true" />
          <span v-if="isStockinRecord">备货记录无外发工序，仅订单参与外发流程</span>
          <span v-else>该订单尚未配置外发工序{{ canManage ? '，可点击上方按钮按 SKU 预设生成' : '' }}</span>
        </div>
        <template v-else>
          <!-- 工序步骤卡片流：直观展示状态流转 -->
          <div v-for="group in processGroups" :key="String(group.itemId)" class="oso-flow">
            <div class="oso-flow-head">
              <span class="oso-flow-sku">{{ group.skuName || 'SKU' }}</span>
              <span class="oso-flow-qty">× {{ group.skuQty }}</span>
            </div>
            <div class="oso-flow-row">
              <template v-for="(p, idx) in group.processes" :key="p.id">
                <!-- 连接箭头 -->
                <div v-if="idx > 0" class="oso-flow-arrow">
                  <FontAwesomeIcon icon="angle-right" aria-hidden="true" />
                </div>
                <!-- 工序卡片：一眼看清工序 + 开始时间 -->
                <div :class="['oso-flow-card', `oso-flow-card--${p.status}`]">
                  <div class="oso-flow-card-top">
                    <span class="oso-flow-seq">{{ idx + 1 }}</span>
                    <span class="oso-flow-name">{{ p.process_type }}</span>
                    <span :class="['oso-status-badge', `oso-status-${p.status}`]">{{ statusLabel(p.status) }}</span>
                  </div>
                  <!-- 开始时间：最醒目 -->
                  <div class="oso-flow-start">
                    <span class="oso-flow-start-label">
                      <FontAwesomeIcon icon="play-circle" aria-hidden="true" /> 开始
                    </span>
                    <span class="oso-flow-start-time" :class="p.actual_start_time ? 'oso-flow-start-time--actual' : ''">
                      {{ shortDate(p.actual_start_time || p.planned_start_time || '待排期') }}
                    </span>
                    <span v-if="canManage" class="oso-flow-start-edit">
                      <input
                        class="oso-dt-input"
                        type="datetime-local"
                        :value="toDateTimeLocal(p.planned_start_time)"
                        title="设置计划开始时间"
                        @change="updatePlanned(p, 'planned_start_time', ($event.target as HTMLInputElement).value)"
                      />
                    </span>
                  </div>
                  <!-- 完成时间 -->
                  <div class="oso-flow-times">
                    <div class="oso-flow-time-row">
                      <span class="oso-flow-time-label">完成</span>
                      <span class="oso-flow-time-val">
                        {{ shortDate(p.actual_end_time || p.planned_end_time || '-') }}
                      </span>
                      <input
                        v-if="canManage"
                        class="oso-dt-input oso-dt-input--end"
                        type="datetime-local"
                        :value="toDateTimeLocal(p.planned_end_time)"
                        title="设置计划完成时间"
                        @change="updatePlanned(p, 'planned_end_time', ($event.target as HTMLInputElement).value)"
                      />
                    </div>
                  </div>
                  <div class="oso-flow-card-actions">
                    <UiButton v-if="canManage && p.status !== 'completed'" variant="success" size="sm" @click="handleStart(p)">
                      {{ p.status === 'in_progress' ? '完成' : '开始' }}
                    </UiButton>
                    <UiButton v-if="canManage && p.status !== 'in_progress' && p.status !== 'completed'" variant="outline" size="sm" @click="handleCompleteDirect(p)">
                      直接完成
                    </UiButton>
                    <UiButton v-if="canManage" variant="ghost" size="sm" @click="handleDeleteProcess(p)">
                      <FontAwesomeIcon icon="trash" aria-hidden="true" />
                    </UiButton>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </template>
      </template>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * OutsourceProcessDialog.vue — 订单外发工序管理弹窗
 *
 * 从 OutsourceOrderTab.vue 拆出的详情弹窗：工序以「步骤卡片流」展示——
 * 每道工序一张卡片，一眼看清该产品有什么工序、何时开始/完成（待开始/
 * 进行中/已完成 + 开始时间醒目展示 + 计划时间可编辑 + 操作按钮）。
 * 支持按 SKU 预设补生成工序；管理操作按 outsource_manage 权限控制显示。
 * 工序变更后 emit('refresh') 通知父组件刷新列表进度列。
 */
import { computed, ref, toRef, watch } from 'vue'
import { outsourceApi } from '@/api/outsource'
import type { OrderOutsourceProcess } from '@/api/outsource'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiProgressBar from '@/components/ui/UiProgressBar.vue'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'
import type { OutsourceOrderRow } from '@/views/outsource/composables/useOutsourceOrders'

const props = defineProps<{
  /** 当前查看的订单行（列表行数据） */
  detailData: OutsourceOrderRow | null
}>()

const emit = defineEmits<{
  /** 工序操作后刷新列表进度列 */
  refresh: []
}>()

/** 弹窗开关（父组件 v-model:open） */
const detailOpen = defineModel<boolean>('open', { default: false })

// ==================== 权限 ====================
const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('outsource_manage'))

// ==================== 工序数据 ====================
const processes = ref<OrderOutsourceProcess[]>([])
const loadingProcesses = ref(false)
const generating = ref(false)

/** 备货记录：不参与外发工序（列表 id 为 StockIn.id，无订单工序） */
const isStockinRecord = computed(() => props.detailData?.record_type === 'stockin')

const detailTotalQuantity = computed(() => {
  if (!props.detailData) return 0
  const items = props.detailData.items || []
  if (items.length === 0) return props.detailData.quantity || 0
  return items.reduce((sum, s) => sum + (s.quantity || 0), 0)
})

/** 弹窗内总体进度 */
const totalProcesses = computed(() => processes.value.length)
const completedProcesses = computed(() => processes.value.filter((p) => p.status === 'completed').length)
const detailProgress = computed(() => {
  const total = totalProcesses.value
  if (!total) return 0
  return Math.round((completedProcesses.value / total) * 100)
})
const detailStatusLabel = computed(() => {
  const total = totalProcesses.value
  if (!total) return '未配置工序'
  if (completedProcesses.value === total) return '外发完成'
  const started = processes.value.filter((p) => p.status !== 'pending').length
  const cur = processes.value.find((p) => p.status !== 'completed')
  return started > 0 ? `进行中（${cur?.process_type || ''}）` : '待开始'
})
const detailStatusClass = computed(() => {
  if (detailProgress.value === 100) return 'completed'
  if (detailProgress.value > 0) return 'in_progress'
  return 'pending'
})

/** 弹窗内工序行：按 SKU 分组（order_item_id） */
interface ProcessGroup {
  itemId: number | null
  skuName: string
  skuQty: number
  processes: OrderOutsourceProcess[]
}

const processGroups = computed<ProcessGroup[]>(() => {
  const groups = new Map<string, ProcessGroup>()
  for (const p of processes.value) {
    const key = String(p.order_item_id ?? 'order')
    if (!groups.has(key)) {
      const sku = (props.detailData?.items || []).find((s) => s.id === p.order_item_id)
      groups.set(key, {
        itemId: p.order_item_id ?? null,
        skuName: sku?.product_name || p.product_name || 'SKU',
        skuQty: sku?.quantity || 0,
        processes: [],
      })
    }
    groups.get(key)!.processes.push(p)
  }
  // 无工序时按 SKU 明细兜底分组（仅展示占位）
  if (groups.size === 0 && props.detailData) {
    const items = props.detailData.items || []
    if (items.length > 0) {
      for (const sku of items) {
        groups.set(String(sku.id), { itemId: sku.id, skuName: sku.product_name || 'SKU', skuQty: sku.quantity || 0, processes: [] })
      }
    } else {
      groups.set('order', { itemId: null, skuName: props.detailData.product_name || 'SKU', skuQty: props.detailData.quantity || 0, processes: [] })
    }
  }
  return Array.from(groups.values())
})

const processRows = computed(() => processes.value)

// 模板以 detailData 名字访问 prop，脚本逻辑保持原实现用 detailData.value
const detailData = toRef(props, 'detailData')

/** 弹窗打开（或切换订单）时加载该订单的外发工序 */
watch([detailOpen, detailData], ([open, data]) => {
  if (open && data) loadProcesses(data.id)
})

/** 工序操作后：重载工序 + 通知父组件刷新列表进度列 */
function reloadDetail() {
  if (detailData.value) loadProcesses(detailData.value.id)
  emit('refresh')
}

function progressVariant(progress: number): 'primary' | 'success' | 'warning' | 'danger' {
  if (progress === 100) return 'success'
  if (progress > 0) return 'warning'
  return 'primary'
}

async function loadProcesses(orderId: number) {
  loadingProcesses.value = true
  processes.value = []
  try {
    const res = await outsourceApi.orderProcesses(orderId)
    processes.value = res.data ?? []
  } catch {
    toast.error('加载外发工序失败')
  } finally {
    loadingProcesses.value = false
  }
}

async function handleGenerate() {
  if (!detailData.value) return
  generating.value = true
  try {
    const res = await outsourceApi.generateProcesses(detailData.value.id)
    toast.success(res.message || '工序已生成')
    await loadProcesses(detailData.value.id)
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '生成工序失败')
  } finally {
    generating.value = false
  }
}

async function handleStart(p: OrderOutsourceProcess) {
  try {
    if (p.status === 'in_progress') {
      await outsourceApi.completeProcess(p.id)
      toast.success(`「${p.process_type}」已完成`)
    } else {
      await outsourceApi.startProcess(p.id)
      toast.success(`「${p.process_type}」已开始`)
    }
    reloadDetail()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '操作失败')
  }
}

async function handleCompleteDirect(p: OrderOutsourceProcess) {
  try {
    await outsourceApi.completeProcess(p.id)
    toast.success(`「${p.process_type}」已完成`)
    reloadDetail()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '操作失败')
  }
}

async function handleDeleteProcess(p: OrderOutsourceProcess) {
  try {
    await outsourceApi.deleteProcess(p.id)
    toast.success(`已删除工序「${p.process_type}」`)
    reloadDetail()
  } catch {
    toast.error('删除失败')
  }
}

async function updatePlanned(p: OrderOutsourceProcess, field: 'planned_start_time' | 'planned_end_time', value: string) {
  try {
    const iso = value ? new Date(value).toISOString() : null
    await outsourceApi.updateProcess(p.id, { [field]: iso })
    toast.success('计划时间已更新')
    if (detailData.value) await loadProcesses(detailData.value.id)
  } catch {
    toast.error('更新失败')
  }
}

/** 'YYYY-MM-DD HH:MM' → datetime-local 输入值 */
function toDateTimeLocal(v?: string | null): string {
  if (!v) return ''
  const [datePart, timePart] = v.split(' ')
  if (!timePart) return datePart || ''
  return `${datePart}T${timePart}`
}

function statusLabel(status: string): string {
  return ({ pending: '待开始', in_progress: '进行中', completed: '已完成' } as Record<string, string>)[status] || status
}

function shortDate(v?: string | null): string {
  if (!v) return '-'
  return v.length > 16 ? v.slice(0, 16) : v
}
</script>

<style scoped>
/* ===== 详情弹窗 ===== */
.oso-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  font-size: 14px;
  color: var(--color-text);
}

/* ① 订单信息 + 总体进度 */
.oso-detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e8ecf1;
  border-radius: 12px;
}
.oso-detail-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  min-width: 0;
}
.oso-detail-no {
  font-weight: 700;
  font-size: 15px;
  color: var(--color-text);
  white-space: nowrap;
}
.oso-detail-meta-item { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; font-size: 13px; }
.oso-detail-meta-label { color: var(--color-text-muted, #64748b); font-size: 12px; }
.oso-detail-meta-num { color: var(--color-primary-700, #2d5ab8); }
.oso-detail-overview {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.oso-detail-progress { width: 140px; }
.oso-detail-progress-text {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.oso-detail-progress-text strong { font-size: 16px; color: var(--color-primary-600); }

/* ② 操作条 */
.oso-detail-actions { display: flex; align-items: center; gap: 12px; }
.oso-detail-hint { font-size: 12px; color: var(--color-text-muted); }

/* 弹窗内空/加载态 */
.oso-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.oso-empty span { font-size: 14px; }

/* 状态徽章（弹窗内总体状态 + 工序卡片状态） */
.oso-status-badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.oso-status-pending { background: var(--color-warning-50); color: var(--color-warning-600); }
.oso-status-in_progress { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-status-completed { background: var(--color-success-50); color: var(--color-success-700); }

/* ③ 工序步骤卡片流 */
.oso-flow {
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  padding: 12px 14px;
  background: #fcfdfe;
}
.oso-flow-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.oso-flow-sku { font-weight: 700; font-size: 13.5px; color: var(--color-text); }
.oso-flow-qty { font-size: 12px; color: var(--color-text-muted); }
.oso-flow-row {
  display: flex;
  align-items: stretch;
  gap: 0;
  overflow-x: auto;
  padding-bottom: 4px;
}
.oso-flow-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #cbd5e1;
  font-size: 16px;
  padding: 0 6px;
  flex-shrink: 0;
}
.oso-flow-card {
  flex-shrink: 0;
  width: 220px;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  padding: 10px 12px;
  background: white;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: box-shadow 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
.oso-flow-card:hover { box-shadow: 0 2px 10px rgba(0,0,0,0.08); transform: translateY(-1px); }
.oso-flow-card--pending { border-color: #e2e8f0; }
.oso-flow-card--in_progress {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.10);
}
.oso-flow-card--completed {
  border-color: var(--color-success-400);
  background: #f6fdf8;
}
.oso-flow-card-top {
  display: flex;
  align-items: center;
  gap: 7px;
}
.oso-flow-seq {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: #f1f5f9;
  color: var(--color-text-muted);
  font-size: 11.5px;
  font-weight: 700;
  flex-shrink: 0;
}
.oso-flow-card--in_progress .oso-flow-seq { background: var(--color-primary-50); color: var(--color-primary-600); }
.oso-flow-card--completed .oso-flow-seq { background: var(--color-success-100); color: var(--color-success-700); }
.oso-flow-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 开始时间：醒目展示 */
.oso-flow-start {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 8px 10px;
  background: var(--color-primary-50);
  border-radius: 9px;
  border: 1px solid var(--color-primary-100);
}
.oso-flow-card--completed .oso-flow-start {
  background: var(--color-success-50);
  border-color: var(--color-success-100);
}
.oso-flow-start-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--color-primary-600);
}
.oso-flow-card--completed .oso-flow-start-label { color: var(--color-success-700); }
.oso-flow-start-time {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-primary-700);
  line-height: 1.2;
  white-space: nowrap;
}
.oso-flow-card--completed .oso-flow-start-time { color: var(--color-success-700); }
.oso-flow-start-time--actual { color: var(--color-text); }
.oso-flow-start-edit { width: 100%; }

/* 完成时间 */
.oso-flow-times {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.oso-flow-time-row {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
}
.oso-flow-time-label {
  color: var(--color-text-muted);
  font-size: 10.5px;
  font-weight: 600;
  flex-shrink: 0;
  width: 24px;
}
.oso-flow-time-val {
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.oso-dt-input {
  flex: 1;
  min-width: 0;
  padding: 3px 6px;
  font-size: 11px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: white;
  color: var(--color-text);
  box-sizing: border-box;
}
.oso-dt-input--end { max-width: 105px; }
.oso-dt-input:focus { outline: 2px solid var(--color-primary-500); outline-offset: 1px; border-color: var(--color-primary-400); }
.oso-flow-card-actions {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: auto;
}
</style>
