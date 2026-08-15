<template>
  <UiDialog :open="open" @update:open="$emit('update:open', $event)" title="来料进度详情" title-icon="" max-width-class="max-w-[1000px]">
    <template #title-icon><FontAwesomeIcon icon="clipboard-list" style="color:var(--color-primary-500);" /></template>
    <div v-if="detailData">
      <div class="mr-det-grid">
        <div><div class="mr-det-lb">订单号</div><div class="mr-det-vl" style="color:var(--color-primary-500);">{{ detailData.purchase_order_no }}</div></div>
        <div><div class="mr-det-lb">客户</div><div class="mr-det-vl">{{ detailData.customer_name || '-' }}</div></div>
        <div><div class="mr-det-lb">产品/数量</div><div class="mr-det-vl">{{ detailData.product_name || '-' }}{{ detailData.product_quantity ? ' x' + detailData.product_quantity : '' }}</div></div>
        <div><div class="mr-det-lb">状态</div><div class="mr-det-vl"><span :class="['mr-badge', 'mr-badge-' + detailData.status]">{{ STATUS_MAP[detailData.status] || detailData.status }}</span></div></div>
        <div><div class="mr-det-lb">总进度</div><div class="mr-det-vl" style="display:flex;align-items:center;gap:8px;"><div class="mr-pbar" style="flex:1;min-width:120px;"><div :class="['mr-pfill', detailData.progress >= 100 ? 'completed' : 'pending']" :style="{ width: (detailData.progress || 0) + '%' }"></div></div><span>{{ detailData.progress }}% (已到货 {{ detailData.total_received }} / 数量 {{ detailData.total_ordered }})</span></div></div>
      </div>
      <h4 style="margin:18px 0 14px;font-size:16px;"><FontAwesomeIcon icon="cubes" style="color:var(--color-primary-500);" /> SKU物料来料进度</h4>
      <VirtualList
        :items="mergedItems"
        :itemHeight="90"
        :containerHeight="360"
        :itemKey="(i) => i.material_name"
      >
        <template #default="{ item: i }">
          <div class="mr-sku-row" style="margin-bottom:0;">
            <div class="mr-sku-top"><span><span class="mr-sku-name">{{ i.material_name }}</span><span class="mr-sku-spec">{{ i.specification || '' }}</span></span><span class="mr-sku-pct" :style="{ color: i.received_quantity >= i.ordered_quantity ? 'var(--color-success-500)' : (i.progress >= 50 ? 'var(--color-primary-500)' : 'var(--color-warning-500)') }">{{ i.progress }}%</span></div>
            <div class="mr-sku-bar"><div :class="['mr-sku-fill', fillClass(i)]" :style="{ width: i.progress + '%' }"></div></div>
            <div class="mr-sku-info">
              <span>分类: <b>{{ CATEGORY_MAP[i.material_category] || '-' }}</b></span>
              <span>数量: <b>{{ i.ordered_quantity }}</b> {{ i.unit || '' }}</span>
              <span>已到货: <b style="color:var(--color-success-500);">{{ i.received_quantity }}</b></span>
              <span>未到: <b style="color:var(--color-warning-500);">{{ i.remaining_quantity }}</b></span>
              <button v-if="canManage && i.received_quantity < i.ordered_quantity" class="mr-btn mr-btn-success mr-btn-sm" @click="$emit('openReceive', i)" title="登记收货数量"><FontAwesomeIcon icon="box" /> 收货</button>
              <span v-else-if="i.received_quantity >= i.ordered_quantity" style="color:var(--color-success-500);font-weight:600;">&#10003; 已完成</span>
            </div>
          </div>
        </template>
      </VirtualList>
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import VirtualList from '@/components/ui/VirtualList.vue'

interface RegItem {
  id: number
  material_name: string
  specification: string
  material_category: string
  ordered_quantity: number | string
  received_quantity: number | string
  remaining_quantity: number | string
  progress: number
  unit: string
  supplier_name?: string
}

interface Registration {
  id: number
  purchase_order_no: string
  supplier_name: string
  customer_name: string
  product_name: string
  product_quantity: number
  items: RegItem[]
  status: string
  progress: number
  total_ordered: number | string
  total_received: number | string
  update_time?: string
}

const props = defineProps<{
  open: boolean
  detailData: Registration | null
  canManage: boolean
}>()

defineEmits<{
  'update:open': [value: boolean]
  openReceive: [item: RegItem]
}>()

const STATUS_MAP: Record<string, string> = { pending: '未开始', partial: '部分到货', completed: '全部到货', overdue: '延期' }
const CATEGORY_MAP: Record<string, string> = { fabric: '面料', filling: '填充', accessory: '辅料', packaging: '包装' }

// 过滤掉填充类(filling)，按 supplier_name + material_name 汇总
const mergedItems = computed<RegItem[]>(() => {
  const items = (props.detailData?.items || []).filter(i => i.material_category !== 'filling')
  const mergedMap = new Map<string, RegItem & { ordered_quantity: number; received_quantity: number; remaining_quantity: number; progress: number }>()
  for (const i of items) {
    const key = `${i.supplier_name || ''}|${i.material_name}`
    const ordered = parseFloat(String(i.ordered_quantity || 0))
    const received = parseFloat(String(i.received_quantity || 0))
    const remaining = parseFloat(String(i.remaining_quantity || 0))
    const existing = mergedMap.get(key)
    if (existing) {
      existing.ordered_quantity += ordered
      existing.received_quantity += received
      existing.remaining_quantity += remaining
      existing.progress = existing.ordered_quantity > 0
        ? Math.round((existing.received_quantity / existing.ordered_quantity) * 100)
        : 0
    } else {
      const progress = ordered > 0 ? Math.round((received / ordered) * 100) : 0
      mergedMap.set(key, { ...i, ordered_quantity: ordered, received_quantity: received, remaining_quantity: remaining, progress })
    }
  }
  return Array.from(mergedMap.values())
})

function fillClass(item: { progress?: number; received_quantity: number | string; ordered_quantity: number | string }) { const pct = item.progress || 0; if (pct >= 100 || Number(item.received_quantity) >= Number(item.ordered_quantity)) return 'full'; return 'low' }
</script>

<style scoped lang="scss">
@use '../material-dialogs.scss' as *;

/* === Progress Bar === */
.mr-pbar { width: 160px; height: 10px; background: #E5E7EB; border-radius: 8px; overflow: hidden; }
.mr-pfill { height: 100%; border-radius: 8px; transition: width 0.5s ease; }
.mr-pfill.pending { background: var(--color-warning-500, #FF9F43); }
.mr-pfill.partial { background: var(--color-primary-500, #5B8DEF); }
.mr-pfill.completed { background: var(--color-success-500, #28C76F); }

/* === SKU Fill Colors === */
.mr-sku-fill.full { background: var(--color-success-500, #28C76F); }
.mr-sku-fill.half { background: var(--color-primary-500, #5B8DEF); }
.mr-sku-fill.low { background: var(--color-warning-500, #FF9F43); }
.mr-sku-fill.zero { background: #E5E7EB; }
.mr-sku-bar { height: 10px; background: #E5E7EB; border-radius: 8px; overflow: hidden; margin-bottom: 10px; }
</style>
