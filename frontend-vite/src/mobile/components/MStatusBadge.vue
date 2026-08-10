<template>
  <span :class="['m-status-badge', variant]">
    <span class="m-status-dot" />
    <span class="m-status-text">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export type StatusVariant =
  | 'pending' | 'confirmed' | 'producing' | 'delayed'
  | 'shipped' | 'completed' | 'cancelled'

const props = defineProps<{
  status: StatusVariant
}>()

const STATUS_MAP: Record<StatusVariant, { variant: string; label: string }> = {
  pending: { variant: 'pending', label: '待出货' },
  confirmed: { variant: 'confirmed', label: '已确认' },
  producing: { variant: 'producing', label: '生产中' },
  delayed: { variant: 'delayed', label: '延期' },
  shipped: { variant: 'shipped', label: '已出货' },
  completed: { variant: 'completed', label: '已完成' },
  cancelled: { variant: 'cancelled', label: '已取消' },
}

const variant = computed(() => STATUS_MAP[props.status]?.variant ?? 'pending')
const label = computed(() => STATUS_MAP[props.status]?.label ?? props.status)
</script>

<style scoped>
.m-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--m-radius-chip);
  font-size: var(--m-font-label-sm);
  font-weight: var(--m-font-weight-medium);
  white-space: nowrap;
}

.m-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Pending */
.m-status-badge.pending {
  background: #FEF3C7;
  color: #92400E;
}
.m-status-badge.pending .m-status-dot { background: #F59E0B; }

/* Confirmed */
.m-status-badge.confirmed {
  background: #EFF6FF;
  color: #1E40AF;
}
.m-status-badge.confirmed .m-status-dot { background: #3B82F6; }

/* Producing */
.m-status-badge.producing {
  background: #F3E8FF;
  color: #6B21A8;
}
.m-status-badge.producing .m-status-dot { background: #8B5CF6; }

/* Delayed */
.m-status-badge.delayed {
  background: #FEE2E2;
  color: #991B1B;
}
.m-status-badge.delayed .m-status-dot { background: #EF4444; }

/* Shipped */
.m-status-badge.shipped {
  background: #DCFCE7;
  color: #166534;
}
.m-status-badge.shipped .m-status-dot { background: #22C55E; }

/* Completed */
.m-status-badge.completed {
  background: #E0F2FE;
  color: #075985;
}
.m-status-badge.completed .m-status-dot { background: #0EA5E9; }

/* Cancelled */
.m-status-badge.cancelled {
  background: #F5F5F4;
  color: #78716C;
}
.m-status-badge.cancelled .m-status-dot { background: #A8A29E; }
</style>
