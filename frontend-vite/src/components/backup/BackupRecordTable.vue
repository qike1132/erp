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
            <th>备份名称</th><th>类型</th><th>大小</th><th>时间</th><th>状态</th><th>来源</th><th class="brt-center">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id ?? r.filename">
            <td>{{ displayName(r) }}</td>
            <td><span class="brt-badge" :class="r.type === 'incremental' ? 'brt-badge-warning' : 'brt-badge-neutral'">{{ typeLabel(r.type) }}</span></td>
            <td class="mono">{{ r.size != null ? fmtSize(r.size) : '—' }}</td>
            <td class="mono">{{ fmtTime(r.created_at) }}</td>
            <td><span class="brt-badge" :class="r.status === 'success' ? 'brt-badge-success' : r.status === 'failed' ? 'brt-badge-danger' : 'brt-badge-processing'">{{ r.status || '—' }}</span></td>
            <td><span class="brt-badge" :class="r.source === 'fs' ? 'brt-badge-warning' : 'brt-badge-neutral'">{{ r.source === 'fs' ? '文件系统' : '数据库' }}</span></td>
            <td class="brt-center">
              <button class="brt-link brt-link-danger" :disabled="r.status === 'running'" @click="$emit('restore', r.filename)">还原</button>
              <button class="brt-link" @click="$emit('download', r.filename)">下载</button>
              <button class="brt-link brt-link-danger" @click="$emit('delete', r.filename)">删除</button>
            </td>
          </tr>
          <tr v-if="loading || rows.length === 0">
            <td colspan="7" class="brt-empty">{{ loading ? '加载中…' : '暂无备份记录' }}</td>
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
  source?: string  // 'db'=数据库记录 | 'fs'=文件系统补录
  encrypted?: boolean | null
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
  'delete': [filename: string]
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
    if (kw && !r.filename.toLowerCase().includes(kw) && !displayName(r).toLowerCase().includes(kw)) return false
    return true
  })
})

// B8 修复：分页由服务端负责（父组件按 page/page_size 请求），此处不再
// 二次切片——旧实现对已分页的当页数据再 slice，第 2 页起恒为空表

function typeLabel(t?: string) {
  if (t === 'incremental') return '增量'
  return '全量'
}

/** 备份名称：全量/增量备份 + 文件名中的本地日期，如 全量备份2026-08-26（磁盘文件名不变） */
function displayName(r: BackupRecordRow): string {
  const isInc = r.type === 'incremental' || /^erp_incremental_/.test(r.filename)
  const label = isInc ? '增量备份' : '全量备份'
  const m = r.filename.match(/(\d{4})(\d{2})(\d{2})/)
  if (m) {
    const [, y, mo, d] = m
    return `${label}${y}-${mo}-${d}`
  }
  return r.filename
}

/** 备份时间：UTC 转本地（Asia/Shanghai）精确到秒，如 2026-08-26 21:50:20 */
function fmtTime(createdAt?: string | null): string {
  if (!createdAt) return '—'
  const d = new Date(createdAt)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function fmtSize(bytes?: number | null) {
  if (bytes == null) return '—'
  const gb = bytes / 1024 / 1024 / 1024
  const mb = bytes / 1024 / 1024
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  if (mb >= 1) return `${Math.round(mb)} MB`
  return `${Math.round(bytes / 1024)} KB`
}
</script>

<style scoped>
.brt-card { border: 1px solid var(--color-border-light); border-radius: var(--radius-md, 14px); background: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,.04), 0 4px 12px rgba(0,0,0,.06); overflow: hidden; }
.brt-toolbar { display: flex; gap: 12px; padding: 20px 24px; flex-wrap: wrap; }
.brt-select, .brt-search { height: 36px; padding: 0 12px; border: 2px solid var(--color-border-light); border-radius: var(--radius-input, 12px); font-size: 13px; font-weight: 600; font-family: inherit; background: #ffffff; color: var(--color-text); transition: border-color 0.3s ease, box-shadow 0.3s ease; }
.brt-select:focus, .brt-search:focus { outline: none; border-color: var(--color-primary-300); box-shadow: 0 0 0 3px var(--color-primary-50); }
.brt-search { width: 220px; }
.brt-table-wrap { overflow-x: auto; border-top: 1px solid var(--color-border-light); }
.brt-table { width: 100%; border-collapse: collapse; min-width: 720px; }
.brt-table th { padding: 10px 14px; background: var(--color-surface); font-weight: 600; color: var(--color-text-secondary); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; border-bottom: 2px solid var(--color-border-light); text-align: left; white-space: nowrap; }
.brt-table td { padding: 10px 14px; font-size: 13px; color: var(--color-text); border-bottom: 1px solid var(--color-border-light); vertical-align: middle; }
.brt-table tbody tr:hover td { background: var(--color-primary-50); }
.mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 13px; }
.brt-center { display: flex; align-items: center; justify-content: center; gap: 16px; }
.brt-center .brt-link { margin-left: 0; }
.brt-badge { min-width: 20px; height: 20px; padding: 0 8px; border-radius: 10px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; white-space: nowrap; }
.brt-badge-success { background: var(--color-success-50); color: var(--color-success-700); }
.brt-badge-danger { background: var(--color-danger-50); color: var(--color-danger-700); }
.brt-badge-processing { background: var(--color-primary-50); color: var(--color-primary-700); }
.brt-badge-warning { background: var(--color-warning-50); color: var(--color-warning-700); }
.brt-badge-neutral { background: var(--color-border-light); color: var(--color-text-secondary); }
.brt-link { border: none; background: none; cursor: pointer; font-size: 12px; font-weight: 600; color: var(--color-primary-600); transition: color 0.3s ease; }
.brt-link:hover { color: var(--color-primary-700); }
.brt-link-danger { color: var(--color-danger-500); }
.brt-link-danger:hover { color: var(--color-danger-600); }
.brt-link:disabled { color: var(--color-text-muted); cursor: not-allowed; }
.brt-empty { text-align: center; color: var(--color-text-muted); }
.brt-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 20px 24px; font-size: 13px; color: var(--color-text-secondary); }
.brt-page { display: inline-flex; align-items: center; padding: 8px 14px; border: 2px solid var(--color-border-light); border-radius: var(--radius-button, 14px); font-size: 13px; font-weight: 600; font-family: inherit; background: #ffffff; color: var(--color-text); cursor: pointer; transition: border-color .3s ease, color .3s ease, background .3s ease; }
.brt-page:hover:not(:disabled) { background: var(--color-primary-50); color: var(--color-primary-600); border-color: var(--color-primary-200); }
.brt-page:disabled { opacity: .4; cursor: not-allowed; }
</style>