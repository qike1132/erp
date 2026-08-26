<template>
  <div class="boc-grid">
    <div v-for="c in cards" :key="c.label" class="boc-card">
      <div class="boc-head">
        <span class="boc-dot" :class="c.dotClass"></span>
        <span class="boc-label">{{ c.label }}</span>
      </div>
      <div class="boc-value">{{ c.value }}<span v-if="c.unit" class="boc-unit">{{ c.unit }}</span></div>
      <div class="boc-desc">{{ c.desc }}</div>
      <div v-if="c.barPct != null" class="boc-progress">
        <div class="boc-progress-fill" :class="c.barClass" :style="{ width: c.barPct + '%' }"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface StatusPayload {
  last_full_backup?: { filename?: string; created_at?: string | null } | null
  total_backups?: number
  total_size_bytes?: number
  disk_usage_percent?: number | null
  [key: string]: unknown
}

const props = defineProps<{ status: StatusPayload | null; loading?: boolean }>()

const cards = computed(() => {
  const s = props.status ?? {}
  const lastFull = (s.last_full_backup ?? null) as StatusPayload['last_full_backup'] | null
  const usedPct = typeof s.disk_usage_percent === 'number' ? Math.round(s.disk_usage_percent) : null
  const healthy = usedPct != null && usedPct < 90
  return [
    { label: '上次备份', dotClass: 'boc-dot-success', value: lastFull?.created_at?.slice(0, 16) ?? (props.loading ? '—' : '暂无'), unit: '', desc: lastFull?.filename ? '全量备份' : '尚未生成备份', barPct: null, barClass: '' },
    { label: '备份总数', dotClass: 'boc-dot-muted', value: s.total_backups ?? 0, unit: ' 个', desc: '服务器默认目录历史备份', barPct: null, barClass: '' },
    { label: '空间占用', dotClass: 'boc-dot-muted', value: usedPct != null ? usedPct : '—', unit: '%', desc: '服务器磁盘已用空间', barPct: usedPct ?? 0, barClass: usedPct != null && usedPct >= 90 ? 'boc-fill-danger' : 'boc-fill-primary' },
    { label: '健康度', dotClass: healthy ? 'boc-dot-success' : 'boc-dot-warning', value: usedPct != null ? (healthy ? '良好' : '偏高') : '—', unit: '', desc: '磁盘占用 < 90% 视为良好', barPct: null, barClass: '' },
  ]
})
</script>

<style scoped>
.boc-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
@media (max-width: 1279px) { .boc-grid { grid-template-columns: repeat(2, 1fr); } }
.boc-card {
  background: #ffffff;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md, 14px);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  padding: 24px;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.boc-card:hover {
  transform: translateY(-2px) scale(1.01);
  box-shadow: 0 8px 25px rgba(135, 206, 235, 0.35);
}
.boc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.boc-dot { width: 8px; height: 8px; border-radius: 50%; }
.boc-dot-success { background: var(--color-success-500, #28c76f); }
.boc-dot-warning { background: var(--color-warning-500, #ff9f43); }
.boc-dot-muted { background: var(--color-border, #e4e7ed); }
.boc-label { font-size: 12px; font-weight: 500; color: var(--color-text-muted); letter-spacing: .02em; }
.boc-value { font-variant-numeric: tabular-nums; font-size: 20px; font-weight: 600; line-height: 1.3; color: var(--color-text); }
.boc-lg { font-size: 28px; font-weight: 700; }
.boc-unit { font-size: 13px; font-weight: 500; color: var(--color-text-muted); margin-left: 2px; }
.boc-desc { margin-top: 6px; font-size: 13px; color: var(--color-text-secondary); }
.boc-progress { height: 8px; background: var(--color-border-light); border-radius: 999px; overflow: hidden; margin-top: 10px; }
.boc-progress-fill { height: 100%; border-radius: 999px; transition: width .2s ease; }
.boc-fill-primary { background: var(--color-primary-500, #5b8def); }
.boc-fill-danger { background: var(--color-danger-500, #ea5455); }
</style>