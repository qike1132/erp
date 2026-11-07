<template>
  <UiDialog
    :open="open"
    max-width-class="max-w-[1280px]"
    overlay-z-class="z-[var(--z-overlay-nested)]"
    content-z-class="z-[var(--z-modal-nested)] sampling-import-card"
    body-class="sampling-import-body"
    :body-padded="false"
    description="按产品名称搜索打样单，并将最终版本部位导入 BOM 编辑态"
    @update:open="open = $event"
  >
    <template #title>
      <FontAwesomeIcon icon="file-import" class="text-primary-500" aria-hidden="true" />
      <span>从打样单导入</span>
    </template>

    <section class="sampling-search-section" aria-label="搜索打样单">
      <label for="sampling-product-keyword" class="sampling-label">产品名称</label>
      <div class="sampling-search-line">
        <input
          id="sampling-product-keyword"
          v-model="searchKeyword"
          class="sampling-input"
          type="search"
          placeholder="输入产品名称搜索打样单"
          autocomplete="off"
          @keydown.enter="emit('search')"
        />
        <button class="sampling-btn sampling-btn-primary" :disabled="searching" @click="emit('search')">
          <FontAwesomeIcon icon="search" aria-hidden="true" />{{ searching ? '搜索中…' : '搜索' }}
        </button>
      </div>
      <p class="sampling-help">打样单按产品名称匹配；同名打样单会全部列出，请选择一张。</p>
    </section>

    <div v-if="error" class="sampling-alert sampling-alert-error" role="alert">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />{{ error }}
    </div>

    <section v-if="projects.length" class="sampling-projects" aria-label="打样单搜索结果">
      <div class="sampling-table-wrap">
        <table class="sampling-table sampling-project-table">
          <thead><tr><th>打样单号</th><th>产品名称</th><th>状态</th><th>当前版本</th><th>角色数</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="option in projects" :key="option.project.id" :class="{ selected: selectedProjectId === option.project.id }">
              <td class="font-semibold">{{ option.project.sequence_no }}</td>
              <td>{{ option.project.product_name }}</td>
              <td>{{ statusLabel(option.project.status) }}</td>
              <td>{{ option.project.current_version || '—' }}</td>
              <td>{{ option.roleCount }}</td>
              <td>
                <button
                  class="sampling-btn sampling-btn-select"
                  :disabled="loadingParts && selectedProjectId === option.project.id"
                  @click="emit('select-project', option)"
                >{{ loadingParts && selectedProjectId === option.project.id ? '读取中…' : selectedProjectId === option.project.id ? '已选择' : '预览部位' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <div v-else-if="searched && !searching && !error" class="sampling-empty" role="status">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />
      <strong>未找到匹配的打样单</strong><span>请检查产品名称后重试</span>
    </div>

    <section v-if="selectedProjectId != null" class="sampling-preview" aria-label="部位导入预览">
      <div class="sampling-preview-heading">
        <h3>最终版本部位预览</h3>
        <span v-if="rows.length">默认全部勾选，可取消不需要的行</span>
      </div>
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
    </section>

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
import UiDialog from '@/components/ui/UiDialog.vue'
import type { PartDetail, ProjectStatus } from '@/api/patternRoom'
import { resolveSamplingSpecification, type SamplingImportRow } from '../composables/bomSamplingImport'
import type { SamplingProjectOption } from '../composables/useBomSamplingImport'

defineProps<{
  projects: SamplingProjectOption[]
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
  'select-project': [option: SamplingProjectOption]
  confirm: []
}>()

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
.sampling-search-section, .sampling-projects, .sampling-preview { padding: 16px; border: 1px solid var(--color-border-light); border-radius: 12px; background: #fff; margin-bottom: 14px; }
.sampling-label { display: block; margin-bottom: 6px; color: var(--color-text); font-size: 13px; font-weight: 600; }
.sampling-search-line { display: flex; gap: 8px; }
.sampling-input { flex: 1; min-width: 0; padding: 9px 12px; border: 1px solid #8592a3; border-radius: 8px; color: var(--color-text); background: #fff; }
.sampling-input:focus { outline: 2px solid var(--color-primary-400); outline-offset: 1px; }
.sampling-help, .sampling-mapping-note { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.sampling-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 14px; border: 1px solid var(--color-border-light); border-radius: 8px; background: #fff; color: var(--color-text); cursor: pointer; white-space: nowrap; }
.sampling-btn:disabled { opacity: .5; cursor: not-allowed; }
.sampling-btn-primary { border-color: var(--color-primary-700); background: var(--color-primary-700); color: #fff; }
.sampling-btn-select { padding: 5px 10px; color: var(--color-primary-700); border-color: var(--color-primary-300); }
.sampling-alert { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; margin-bottom: 14px; border-radius: 8px; font-size: 13px; line-height: 1.5; }
.sampling-alert-error { background: var(--color-danger-50); color: var(--color-danger-700); }
.sampling-alert-warning { background: var(--color-warning-50); color: var(--color-warning-700); }
.sampling-table-wrap { overflow-x: auto; }
.sampling-table { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--color-text); }
.sampling-table th { padding: 9px 10px; background: var(--color-surface); color: var(--color-text); text-align: left; white-space: nowrap; }
.sampling-table td { padding: 9px 10px; border-top: 1px solid var(--color-border-light); vertical-align: top; }
.sampling-project-table { min-width: 720px; }
.sampling-preview-table { min-width: 1120px; }
.sampling-preview-table-wrap { max-height: 340px; overflow: auto; }
.sampling-preview-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.sampling-preview-heading h3 { margin: 0; font-size: 15px; color: var(--color-text); }
.sampling-preview-heading span { color: var(--color-text-secondary); font-size: 12px; }
.sampling-row-conflict { background: var(--color-danger-50); }
.sampling-row-overwrite { background: var(--color-warning-50); }
.sampling-status { display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 600; white-space: nowrap; }
.sampling-status-new { color: var(--color-success-700); background: var(--color-success-50); }
.sampling-status-overwrite, .sampling-status-conflict { color: var(--color-warning-700); background: var(--color-warning-100); }
.sampling-status-conflict { color: var(--color-danger-700); background: var(--color-danger-50); }
.sampling-quantity-pending { display: inline-block; padding: 3px 7px; border-radius: 6px; background: #fef3c7; color: #92400e; white-space: nowrap; }
.sampling-omitted-values { max-width: 240px; color: var(--color-text-secondary); }
.sampling-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 100px; padding: 18px; color: var(--color-text-secondary); text-align: center; }
.sampling-selected-count { margin-right: auto; color: var(--color-text-secondary); font-size: 13px; }
.font-semibold { font-weight: 600; }
</style>

<style>
.sampling-import-card { height: 88vh !important; }
.sampling-import-body { padding: 20px 24px; background: var(--color-surface, #f8fafc); }
</style>
