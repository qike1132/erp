<template>
  <UiDialog :open="open" :title="`来料详情 - ${supplierDetailOrderNo}`" title-icon="" max-width-class="max-w-[1000px]" @update:open="$emit('update:open', $event)">
    <template #title-icon><FontAwesomeIcon icon="clipboard-list" style="color:var(--color-primary-500);" /></template>
    <div v-if="supplierDetail">
      <div v-for="g in supplierDetail.supplierGroups" :key="g.supplierName" class="mr-source-card" style="margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div style="font-weight:600;font-size:14px;"><FontAwesomeIcon icon="truck" style="color:var(--color-primary-500);margin-right:6px;" />{{ g.supplierName }}<span style="color:var(--color-text-muted);margin-left:8px;font-weight:400;font-size:12px;">{{ g.items.length }} 项</span></div>
          <span :class="['mr-badge', g.pct >= 100 ? 'mr-badge-completed' : g.pct > 0 ? 'mr-badge-pending' : 'mr-badge-overdue']">{{ g.pct }}%</span>
        </div>
        <div v-for="m in g.items" :key="m.name" class="mr-det-mat-card">
          <div class="mr-det-mat-row">
            <div class="mr-det-mat-info">
              <span class="mr-det-mat-name">{{ m.name }}</span>
              <span v-if="m.spec" class="mr-det-mat-spec">{{ m.spec }}</span>
            </div>
            <div class="mr-det-mat-metrics">
              <span class="mr-det-mat-metric"><span class="mr-det-mat-label">采购</span><b class="mr-det-mat-value">{{ formatQuantity(m.ordered) }}</b></span>
              <span class="mr-det-mat-metric"><span class="mr-det-mat-label">已到货</span><b class="mr-det-mat-value received">{{ formatQuantity(m.received) }}</b></span>
              <span class="mr-det-mat-metric"><span class="mr-det-mat-label">未到货</span><b class="mr-det-mat-value remaining">{{ formatQuantity(m.remaining) }}</b></span>
              <span class="mr-det-mat-metric"><span class="mr-det-mat-label">完成率</span><b class="mr-det-mat-value" :class="m.received >= m.ordered ? 'completed' : (m.pct >= 50 ? 'half' : 'low')">{{ m.pct }}%</b></span>
            </div>
            <div class="mr-det-mat-right">
              <span v-if="m.received >= m.ordered" class="mr-status-completed"><FontAwesomeIcon icon="check-circle" /> 已完成</span>
              <span v-else class="mr-status-pending">未完成</span>
              <button v-if="canManage && m.received < m.ordered && m.subItems.length" class="mr-btn mr-btn-success" title="登记收货" aria-label="登记收货" @click="$emit('openReceiveBySubItems', m.subItems, m.name, m.ordered, m.received)"><FontAwesomeIcon icon="box" /> 登记收货</button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="open" class="mr-detail-loading">
      <FontAwesomeIcon icon="spinner" spin /> 加载中...
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'
import { formatQuantity } from '@/utils/quantity'
import type { SupMatItem, SupplierDetail } from '../material-types'

defineProps<{
  open: boolean
  supplierDetail: SupplierDetail | null
  supplierDetailOrderNo: string
  canManage: boolean
}>()

defineEmits<{
  'update:open': [value: boolean]
  openReceiveBySubItems: [subItems: SupMatItem[], name: string, ordered: number, received: number]
}>()
</script>

<style scoped lang="scss">
@use '../material-dialogs.scss' as *;

/* === Loading State === */
.mr-detail-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--color-text-secondary, #64748b);
}

/* === Material Detail Card (Dialog) 特有部分 === */
.mr-det-mat-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 0 0 auto;
  max-width: 180px;
}
.mr-det-mat-metrics {
  display: flex;
  gap: 8px;
  flex: 1;
  justify-content: center;
  flex-wrap: wrap;
}
.mr-det-mat-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 8px 14px;
  background: white;
  border-radius: 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  min-width: 72px;
  height: 56px;
  box-sizing: border-box;
}
.mr-det-mat-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #94a3b8);
  line-height: 1.2;
  margin: 0;
}
.mr-det-mat-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text, #1e293b);
  line-height: 1.2;
  margin: 2px 0 0;
}
.mr-det-mat-value.received { color: var(--color-success-500, #28C76F); }
.mr-det-mat-value.remaining { color: var(--color-warning-500, #FF9F43); }
.mr-det-mat-value.completed { color: var(--color-success-500, #28C76F); }
.mr-det-mat-value.half { color: var(--color-primary-500, #5B8DEF); }
.mr-det-mat-value.low { color: var(--color-warning-500, #FF9F43); }
.mr-det-mat-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  justify-content: flex-end;
  min-width: 180px;
}
.mr-status-completed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-success-600, #059669);
  background: var(--color-success-50, #f0fdf4);
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--color-success-200, #bbf7d0);
  min-width: 72px;
  justify-content: center;
}
.mr-status-pending {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb);
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--color-warning-200, #fde68a);
  min-width: 72px;
  justify-content: center;
}

/* === Buttons（覆盖公共版尺寸） === */
.mr-btn-success {
  padding: 10px 16px;
  border-radius: 10px;
}

/* === Responsive === */
@media (max-width: 768px) {
  .mr-det-mat-row { flex-wrap: wrap; gap: 12px; padding: 12px; }
  .mr-det-mat-info { max-width: 100%; flex: 1 1 100%; }
  .mr-det-mat-metrics { flex: 1 1 100%; justify-content: flex-start; gap: 6px; }
  .mr-det-mat-metric { min-width: 65px; padding: 8px 12px; }
  .mr-det-mat-value { font-size: 16px; }
}
</style>
