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
            <th>备份名称</th><th>类型</th><th>大小</th><th>时间</th><th>状态</th><th>来源</th><th class="brt-right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id ?? r.filename">
            <td class="mono">{{ r.filename }}</td>
            <td><span class="brt-badge" :class="r.type === 'incremental' ? 'brt-badge-warning' : 'brt-badge-neutral'">{{ typeLabel(r.type) }}</span></td>
            <td class="mono">{{ r.size != null ? fmtSize(r.size) : '—' }}</td>
            <td class="mono">{{ r.created_at?.slice(0, 16) ?? '—' }}</td>
            <td><span class="brt-badge" :class="r.status === 'success' ? 'brt-badge-success' : r.status === 'failed' ? 'brt-badge-danger' : 'brt-badge-processing'">{{ r.status || '—' }}</span></td>
            <td><span class="brt-badge" :class="r.source === 'fs' ? 'brt-badge-warning' : 'brt-badge-neutral'">{{ r.source === 'fs' ? '文件系统' : '数据库' }}</span></td>
            <td class="brt-right">
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

/** 本地筛选只作用于**当前页**：`/backup/records` 只接受 page/page_size，
 *  筛选没有服务端入口，跨页筛选需要后端支持后再上移。
 *  分页由父组件服务端完成（rows 已是第 page 页），此处**不能再切一次** ——
 *  再切会把第 2 页及以后整页切空（rows 只有 page_size 条，start 却已 ≥ page_size）。 */
const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.rows.filter((r) => {
    if (typeFilter.value && (r.type ?? '') !== typeFilter.value) return false
    if (statusFilter.value && (r.status ?? '') !== statusFilter.value) return false
    if (kw && !r.filename.toLowerCase().includes(kw)) return false
    return true
  })
})

function typeLabel(t?: string) {
  if (t === 'incremental') return '增量'
  return '全量'
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
/* 「操作」列整列居中（表头+按钮），与用户页 UiDataTable 操作列 align:'center' 一致。
   必须连写提升特异性：.brt-table th 的 text-align:left(0,1,1) 高于单类 .brt-right(0,1,0)，
   否则表头的对齐设置被吞掉，与列内按钮错位 */
.brt-table th.brt-right,
.brt-table td.brt-right { text-align: center; }
.brt-badge { min-width: 20px; height: 20px; padding: 0 8px; border-radius: 10px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; white-space: nowrap; }
.brt-badge-success { background: var(--color-success-50); color: var(--color-success-700); }
.brt-badge-danger { background: var(--color-danger-50); color: var(--color-danger-700); }
.brt-badge-processing { background: var(--color-primary-50); color: var(--color-primary-700); }
.brt-badge-warning { background: var(--color-warning-50); color: var(--color-warning-700); }
.brt-badge-neutral { background: var(--color-border-light); color: var(--color-text-secondary); }
.brt-link { border: none; background: none; cursor: pointer; font-size: 12px; font-weight: 600; color: var(--color-primary-600); transition: color 0.3s ease; }
/* 间距只放按钮之间：首按钮不带左 margin，居中时按钮组视觉重心才与列中心重合 */
.brt-link + .brt-link { margin-left: 16px; }
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