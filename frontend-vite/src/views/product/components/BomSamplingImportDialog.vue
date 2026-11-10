<template>
  <UiDialog
    :open="open"
    max-width-class="max-w-[1280px]"
    overlay-z-class="z-[var(--z-overlay-nested)]"
    content-z-class="z-[var(--z-modal-nested)] sampling-import-card"
    body-class="sampling-import-body"
    :body-padded="false"
    description="打样间全部打样单，选择一张后将其最终版本部位导入 BOM 编辑态"
    @update:open="open = $event"
  >
    <template #title>
      <FontAwesomeIcon icon="file-import" class="text-primary-500" aria-hidden="true" />
      <span>从打样单导入</span>
    </template>

    <div class="sampling-layout">
      <aside class="sampling-side" aria-label="打样单列表">
        <div class="sampling-side-toolbar">
          <div class="sampling-search-line">
            <input
              id="sampling-product-keyword"
              v-model="searchKeyword"
              class="sampling-input"
              type="search"
              placeholder="搜索产品名称或打样单号（可留空）"
              aria-label="搜索产品名称或打样单号"
              autocomplete="off"
              @keydown.enter="emit('search')"
            />
            <button class="sampling-btn sampling-btn-primary" :disabled="searching" @click="emit('search')">
              <FontAwesomeIcon icon="search" aria-hidden="true" />{{ searching ? '加载中…' : '搜索' }}
            </button>
          </div>
          <div class="sampling-side-meta">
            <span>共 {{ projects.length }} 张 · 按更新时间倒序</span>
            <div class="sampling-chips" role="group" aria-label="按状态筛选">
              <button
                v-for="filter in statusFilters"
                :key="filter.key"
                type="button"
                class="sampling-chip"
                :class="{ on: statusFilter === filter.key }"
                :aria-pressed="statusFilter === filter.key"
                @click="emit('filter-status', filter.key)"
              >{{ filter.label }}</button>
            </div>
          </div>
        </div>

        <div v-if="searching" class="sampling-empty sampling-side-state" role="status">正在加载打样单…</div>
        <div v-else-if="!visibleProjects.length" class="sampling-empty sampling-side-state" role="status">
          <FontAwesomeIcon icon="inbox" aria-hidden="true" />
          <strong>{{ searched ? '没有符合条件的打样单' : '正在加载打样单…' }}</strong>
          <span v-if="searched">可清空搜索词或切换状态筛选</span>
        </div>
        <div v-else class="sampling-cards">
          <button
            v-for="project in visibleProjects"
            :key="project.id"
            type="button"
            class="sampling-project-card"
            :class="{ selected: selectedProjectId === project.id }"
            :aria-pressed="selectedProjectId === project.id"
            @click="emit('select-project', project)"
          >
            <span class="sampling-card-thumb">
              <img
                v-if="thumbSrc(project) && !failedThumbIds.has(project.id)"
                :src="thumbSrc(project)!"
                alt=""
                loading="lazy"
                decoding="async"
                @error="onThumbError($event, project)"
              />
              <FontAwesomeIcon v-else icon="shirt" class="sampling-card-placeholder" aria-hidden="true" />
              <span class="sampling-card-status" :class="`sampling-card-status-${project.status}`">{{ statusLabel(project.status) }}</span>
            </span>
            <span class="sampling-card-body">
              <span class="sampling-card-name">{{ project.product_name }}</span>
              <span class="sampling-card-no">
                {{ project.sequence_no }}<template v-if="project.current_version"> · {{ project.current_version }}</template>
              </span>
              <span class="sampling-card-time">更新 {{ formatUpdatedAt(project.updated_at) }}</span>
              <span v-if="selectedProjectId === project.id" class="sampling-card-selflag">
                <FontAwesomeIcon icon="check" aria-hidden="true" /> 当前选择
              </span>
            </span>
          </button>
        </div>
      </aside>

      <main class="sampling-main">
        <div v-if="error" class="sampling-alert sampling-alert-error" role="alert">
          <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />{{ error }}
        </div>

        <section class="sampling-preview" aria-label="部位导入预览">
          <div class="sampling-preview-heading">
            <h3>最终版本部位预览</h3>
            <span v-if="rows.length">默认全部勾选，可取消不需要的行</span>
          </div>
          <div v-if="selectedProjectId == null" class="sampling-empty sampling-preview-empty" role="status">
            <FontAwesomeIcon icon="hand-pointer" aria-hidden="true" />
            <strong>点击左侧打样单</strong>
            <span>选择一张打样单后，这里会列出可导入的最终版本部位</span>
          </div>
          <template v-else>
            <div v-if="hasConflict" class="sampling-alert sampling-alert-warning">
              <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
              同一部位出现在多个角色中，已标为「冲突」。请逐行勾选需要保留的角色数据。
            </div>
            <div v-if="loadingParts" class="sampling-empty" role="status">正在读取各角色的最终版本部位…</div>
            <div v-else-if="!hasRoles" class="sampling-empty" role="status">该打样单暂无角色，无法导入部位</div>
            <div v-else-if="!rows.length && !error" class="sampling-empty" role="status">该打样单各角色的最终版本均无可导入部位</div>
            <div v-else-if="rows.length" class="sampling-table-wrap sampling-preview-table-wrap">
              <table class="sampling-table sampling-preview-table">
                <thead><tr><th>导入</th><th>部位名</th><th>布料名</th><th>规格型号</th><th>供应商</th><th>来源角色</th><th>状态</th><th>数量</th><th>未导入字段</th></tr></thead>
                <tbody>
                  <tr v-for="row in rows" :key="row.key" :class="`sampling-row-${row.status}`">
                    <td><input v-model="row.selected" type="checkbox" :aria-label="`导入 ${row.sourceRoleName} 的 ${row.part.part_name}`" /></td>
                    <td class="font-semibold">{{ row.part.part_name }}</td>
                    <td>{{ row.part.fabric_name || '—' }}</td>
                    <td>{{ resolveSamplingSpecification(row.part) || '—' }}</td>
                    <td>{{ row.part.supplier_name || '—' }}</td>
                    <td>{{ row.sourceRoleName }}</td>
                    <td><span class="sampling-status" :class="`sampling-status-${row.status}`">{{ statusText(row.status) }}</span></td>
                    <td><span class="sampling-quantity-pending">0 · 数量待补</span></td>
                    <td class="sampling-omitted-values">{{ omittedFieldValues(row.part) || '无值' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="rows.length" class="sampling-mapping-note">
              打样色号将进入 BOM 规格型号（无色号时使用布料规格），原备注保持不变；数量统一填 0 并标黄，请补录后保存。以下字段未导入：单价、交期、联系人、联系电话（BOM 无对应列）。
            </p>
          </template>
        </section>
      </main>
    </div>

    <template #footer>
      <span v-if="rows.length" class="sampling-selected-count">已选 {{ selectedCount }} / {{ rows.length }} 条</span>
      <button class="sampling-btn" @click="open = false">取消</button>
      <button class="sampling-btn sampling-btn-primary sampling-confirm" :disabled="!selectedCount || loadingParts" @click="emit('confirm')">
        <FontAwesomeIcon icon="file-import" aria-hidden="true" />导入到 BOM 编辑态
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { PartDetail, ProjectStatus, ProjectSummary } from '@/api/patternRoom'
import { resolveSamplingSpecification, type SamplingImportRow } from '../composables/bomSamplingImport'

type StatusFilter = 'all' | Extract<ProjectStatus, 'in_progress' | 'completed'>

const props = defineProps<{
  projects: ProjectSummary[]
  visibleProjects: ProjectSummary[]
  statusFilter: StatusFilter
  selectedProjectId: number | null
  rows: SamplingImportRow[]
  selectedCount: number
  searched: boolean
  searching: boolean
  loadingParts: boolean
  hasRoles: boolean
  hasConflict: boolean
  error: string
}>()

const open = defineModel<boolean>('open', { default: false })
const searchKeyword = defineModel<string>('searchKeyword', { default: '' })
const emit = defineEmits<{
  search: []
  'filter-status': [filter: StatusFilter]
  'select-project': [project: ProjectSummary]
  confirm: []
}>()

const statusFilters: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'in_progress', label: '进行中' },
  { key: 'completed', label: '已完成' },
]

const failedThumbIds = ref(new Set<number>())

watch(() => props.projects, () => {
  failedThumbIds.value = new Set()
})

function thumbSrc(project: ProjectSummary): string {
  return project.product_image_thumbnail_url || project.product_image_url || ''
}

function onThumbError(event: Event, project: ProjectSummary): void {
  const img = event.target as HTMLImageElement
  if (!img.dataset.fallback && project.product_image_url && img.src !== project.product_image_url) {
    img.dataset.fallback = '1'
    img.src = project.product_image_url
    return
  }
  failedThumbIds.value = new Set(failedThumbIds.value).add(project.id)
}

function formatUpdatedAt(value: string | undefined): string {
  if (!value) return '—'
  const match = value.match(/^\d{4}-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/)
  return match ? `${match[1]}-${match[2]} ${match[3]}:${match[4]}` : value
}

function statusLabel(status: ProjectStatus | undefined): string {
  return { in_progress: '进行中', completed: '已完成', cancelled: '已取消' }[status ?? 'in_progress']
}

function statusText(status: SamplingImportRow['status']): string {
  return { new: '新增', overwrite: '覆盖', conflict: '冲突' }[status]
}

function omittedFieldValues(part: PartDetail): string {
  return [
    part.unit_price != null ? `单价：${part.unit_price}` : '',
    part.delivery_days != null ? `交期：${part.delivery_days} 天` : '',
    part.contact_person ? `联系人：${part.contact_person}` : '',
    part.contact_phone ? `电话：${part.contact_phone}` : '',
  ].filter(Boolean).join('；')
}
</script>

<style scoped>
.sampling-layout { display: flex; height: 100%; min-height: 0; }
.sampling-side { width: 470px; flex: 0 0 470px; display: flex; flex-direction: column; min-height: 0; background: #fff; border-right: 1px solid var(--color-border-light); }
.sampling-side-toolbar { padding: 14px 16px 12px; border-bottom: 1px solid var(--color-border-light); }
.sampling-search-line { display: flex; gap: 8px; }
.sampling-input { flex: 1; min-width: 0; padding: 8px 11px; border: 1px solid #8592a3; border-radius: 8px; color: var(--color-text); background: #fff; }
.sampling-input:focus { outline: 2px solid var(--color-primary-400); outline-offset: 1px; }
.sampling-side-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 9px; color: var(--color-text-secondary); font-size: 12px; }
.sampling-chips { display: flex; gap: 6px; flex: none; }
.sampling-chip { padding: 2px 9px; border: 1px solid var(--color-border-light); border-radius: 999px; background: #fff; color: var(--color-text-secondary); font-size: 11.5px; cursor: pointer; white-space: nowrap; }
.sampling-chip.on { border-color: var(--color-primary-700); background: var(--color-primary-50); color: var(--color-primary-700); font-weight: 600; }
.sampling-cards { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-content: start; }
.sampling-project-card { display: flex; flex-direction: column; padding: 0; border: 1px solid var(--color-border-light); border-radius: 10px; overflow: hidden; background: #fff; text-align: left; cursor: pointer; }
.sampling-project-card:hover { border-color: var(--color-primary-300); }
.sampling-project-card.selected { border-color: var(--color-primary-700); box-shadow: 0 0 0 2px var(--color-primary-100); }
.sampling-card-thumb { position: relative; display: flex; align-items: center; justify-content: center; height: 104px; background: linear-gradient(135deg, #eef2f9, #dfe7f4); }
.sampling-card-thumb img { width: 100%; height: 100%; object-fit: cover; }
.sampling-card-placeholder { font-size: 34px; color: #9fb0c8; }
.sampling-card-status { position: absolute; top: 7px; left: 7px; padding: 1px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 700; }
.sampling-card-status-in_progress { background: var(--color-primary-50); color: var(--color-primary-700); }
.sampling-card-status-completed { background: var(--color-success-50); color: var(--color-success-700); }
.sampling-card-status-cancelled { background: var(--color-surface); color: var(--color-text-muted); }
.sampling-card-body { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px 9px; }
.sampling-card-name { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 35px; color: var(--color-text); font-size: 13px; font-weight: 700; line-height: 1.35; }
.sampling-card-no { color: var(--color-text-secondary); font-size: 11.5px; font-variant-numeric: tabular-nums; }
.sampling-card-time { color: var(--color-text-muted); font-size: 11px; }
.sampling-card-selflag { margin-top: 3px; color: var(--color-primary-700); font-size: 11px; font-weight: 700; }
.sampling-main { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 12px; padding: 14px 16px; overflow: hidden; }
.sampling-preview { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 14px 16px; border: 1px solid var(--color-border-light); border-radius: 12px; background: #fff; }
.sampling-preview-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.sampling-preview-heading h3 { margin: 0; color: var(--color-text); font-size: 15px; }
.sampling-preview-heading span { color: var(--color-text-secondary); font-size: 12px; }
.sampling-preview-empty { flex: 1; }
.sampling-preview-empty strong { font-size: 14px; color: var(--color-text); }
.sampling-preview-empty span { font-size: 12.5px; }
.sampling-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 14px; border: 1px solid var(--color-border-light); border-radius: 8px; background: #fff; color: var(--color-text); cursor: pointer; white-space: nowrap; }
.sampling-btn:disabled { opacity: .5; cursor: not-allowed; }
.sampling-btn-primary { border-color: var(--color-primary-700); background: var(--color-primary-700); color: #fff; }
.sampling-alert { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.5; }
.sampling-alert-error { background: var(--color-danger-50); color: var(--color-danger-700); }
.sampling-alert-warning { margin-bottom: 10px; background: var(--color-warning-50); color: var(--color-warning-700); }
.sampling-table-wrap { overflow: auto; }
.sampling-table { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--color-text); }
.sampling-table th { padding: 9px 10px; background: var(--color-surface); color: var(--color-text); text-align: left; white-space: nowrap; }
.sampling-table td { padding: 9px 10px; border-top: 1px solid var(--color-border-light); vertical-align: top; }
.sampling-preview-table { min-width: 1000px; }
.sampling-preview-table-wrap { flex: 1; min-height: 0; }
.sampling-row-conflict { background: var(--color-danger-50); }
.sampling-row-overwrite { background: var(--color-warning-50); }
.sampling-status { display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 600; white-space: nowrap; }
.sampling-status-new { color: var(--color-success-700); background: var(--color-success-50); }
.sampling-status-overwrite, .sampling-status-conflict { color: var(--color-warning-700); background: var(--color-warning-100); }
.sampling-status-conflict { color: var(--color-danger-700); background: var(--color-danger-50); }
.sampling-quantity-pending { display: inline-block; padding: 3px 7px; border-radius: 6px; background: #fef3c7; color: #92400e; white-space: nowrap; }
.sampling-omitted-values { max-width: 240px; color: var(--color-text-secondary); }
.sampling-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 100px; padding: 18px; color: var(--color-text-secondary); text-align: center; }
.sampling-empty > .svg-inline--fa { font-size: 28px; color: #9fb0c8; }
.sampling-side-state { flex: 1; }
.sampling-mapping-note { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.sampling-selected-count { margin-right: auto; color: var(--color-text-secondary); font-size: 13px; }
.font-semibold { font-weight: 600; }
</style>

<style>
.sampling-import-card { height: 88vh !important; }
.sampling-import-body { padding: 0; background: var(--color-surface, #f8fafc); overflow: hidden !important; }
</style>
