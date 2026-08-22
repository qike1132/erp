<template>
  <div class="brt-card">
    <div class="brt-toolbar">
      <select v-model="typeFilter" class="brt-select">
        <option value="">全部类型</option><option value="full">全量</option><option value="incremental">增量</option>
      </select>
      <select v-model="statusFilter" class="brt-select">
        <option value="">全部状态</option><option value="success">成功</option><option value="failed">失败</option><option value="running">进行中</option>
      </select>
      <input v-model="keyword" class="brt-search" placeholder="搜索备份名称" />
    </div>
    <div class="brt-table-wrap">
      <table class="brt-table">
        <thead>
          <tr>
            <th>备份名称</th><th>类型</th><th>大小</th><th>时间</th><th>状态</th><th class="brt-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in paged" :key="r.id ?? r.filename">
            <td class="mono">{{ r.filename }}</td>
            <td><span class="brt-badge" :class="r.type === 'incremental' ? 'brt-badge-warning' : 'brt-badge-neutral'">{{ typeLabel(r.type) }}</span></td>
            <td class="mono">{{ r.size != null ? fmtSize(r.size) : '—' }}</td>
            <td class="mono">{{ r.created_at?.slice(0, 16) ?? '—' }}</td>
            <td><span class="brt-badge" :class="r.status === 'success' ? 'brt-badge-success' : r.status === 'failed' ? 'brt-badge-danger' : 'brt-badge-processing'">{{ r.status || '—' }}</span></td>
            <td class="brt-right">
              <button class="brt-link brt-link-danger" :disabled="r.status === 'running'" @click="$emit('restore', r.filename)">还原</button>
              <button class="brt-link" @click="$emit('download', r.filename)">下载</button>
            </td>
          </tr>
          <tr v-if="loading || rows.length === 0">
            <td colspan="6" class="brt-empty">{{ loading ? '加载中…' : '暂无备份记录' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="brt-pagination">
      <span>共 {{ total }} 条</span>
      <button class="brt-page" :disabled="page <= 1" @click="$emit('page-change', page - 1)">上一页</button>
      <span class="mono">第 {{ page }} / {{ pageCount }} 页</span>
      <button class="brt-page" :disabled="page >= pageCount" @click="$emit('page-change', page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

export interface BackupRecordRow {
  id?: number | null
  filename: string
  type?: string
  size?: number | null
  created_at?: string | null
  status?: string
}

const props = defineProps<{
  rows: BackupRecordRow[]
  total: number
  page: number
  pageSize: number
  loading?: boolean
  onPageChange: (page: number) => void
}>()

defineEmits<{
  'restore': [filename: string]
  'download': [filename: string]
  'page-change': [page: number]
}>()

const typeFilter = ref('')
const statusFilter = ref('')
const keyword = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.rows.filter((r) => {
    if (typeFilter.value && (r.type ?? '') !== typeFilter.value) return false
    if (statusFilter.value && (r.status ?? '') !== statusFilter.value) return false
    if (kw && !r.filename.toLowerCase().includes(kw)) return false
    return true
  })
})

const paged = computed(() => {
  const start = (props.page - 1) * props.pageSize
  return filtered.value.slice(start, start + props.pageSize)
})

function typeLabel(t?: string) {
  if (t === 'incremental') return '增量'
  return '全量'
}
function fmtSize(bytes?: number | null) {
  if (bytes == null) return '—'
  const gb = bytes / 1024 / 1024 / 1024
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1024 / 1024)} MB`
}
</script>

<style scoped>
.brt-card { border: 1px solid var(--color-border, #e5e6eb); border-radius: 8px; background: var(--color-surface, #fff); }
.brt-toolbar { display: flex; gap: 12px; padding: 16px; flex-wrap: wrap; }
.brt-select, .brt-search { height: 32px; padding: 0 12px; border: 1px solid var(--color-border-strong, #c9cdd4); border-radius: 6px; font-size: 14px; }
.brt-search { width: 220px; }
.brt-table-wrap { overflow-x: auto; border-top: 1px solid var(--color-border, #e5e6eb); }
.brt-table { width: 100%; border-collapse: collapse; min-width: 720px; }
.brt-table th { text-align: left; font-size: 12px; font-weight: 500; color: var(--color-text-tertiary, #86909c); padding: 12px; }
.brt-table td { padding: 0 12px; height: 44px; font-size: 14px; color: var(--color-text-secondary, #4e5969); border-top: 1px solid var(--color-surface-muted, #f2f3f5); white-space: nowrap; }
.brt-table tbody tr:hover { background: var(--color-surface-hover, #f7f8fa); }
.mono { font-family: var(--font-mono, Consolas, monospace); font-size: 13px; }
.brt-right { text-align: right; }
.brt-badge { padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 500; }
.brt-badge-success { background: #e6faf1; color: #047857; }
.brt-badge-danger { background: #ffece8; color: #b91c1c; }
.brt-badge-processing { background: #e9eafe; color: #4338ca; }
.brt-badge-warning { background: #fef6e6; color: #b45309; }
.brt-badge-neutral { background: var(--color-surface-muted, #f2f3f5); color: #6b7280; }
.brt-link { border: none; background: none; cursor: pointer; font-size: 14px; color: var(--color-primary, #2f7bff); margin-left: 16px; }
.brt-link-danger { color: var(--color-danger, #ef4444); }
.brt-link:disabled { color: var(--color-text-disabled, #c9cdd4); cursor: not-allowed; }
.brt-empty { text-align: center; color: var(--color-text-tertiary, #86909c); }
.brt-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 16px; font-size: 13px; color: var(--color-text-secondary, #4e5969); }
.brt-page { height: 28px; padding: 0 12px; border: 1px solid var(--color-border-strong, #c9cdd4); border-radius: 6px; background: var(--color-surface, #fff); cursor: pointer; }
.brt-page:disabled { opacity: .5; cursor: not-allowed; }
</style>