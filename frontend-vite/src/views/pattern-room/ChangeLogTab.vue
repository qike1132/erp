<template>
  <div class="pr-log-tab">
    <!-- 顶部：BOM 选择 + 筛选 -->
    <div class="pr-log-toolbar">
      <div class="pr-toolbar-field">
        <label>BOM</label>
        <select v-model="selectedBomIdLocal" @change="onBomChange">
          <option :value="null">请选择 BOM</option>
          <option v-for="b in bomOptions" :key="b.id" :value="b.id">
            {{ b.bom_no }} - {{ b.product_name }}
          </option>
        </select>
      </div>
      <div class="pr-toolbar-field">
        <label>变更类型</label>
        <select v-model="filterType" @change="reloadList">
          <option value="">全部</option>
          <option v-for="t in changeTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
      </div>
      <div class="pr-toolbar-field">
        <label>开始日期</label>
        <input type="date" v-model="dateFrom" @change="reloadList" />
      </div>
      <div class="pr-toolbar-field">
        <label>结束日期</label>
        <input type="date" v-model="dateTo" @change="reloadList" />
      </div>
      <button class="pr-btn pr-btn-ghost" @click="resetFilters" :disabled="!hasFilters">
        <i class="fas fa-rotate-left" /> 重置
      </button>
      <div class="pr-toolbar-spacer" />
      <span class="pr-log-total">共 {{ total }} 条</span>
    </div>

    <!-- 时间线 -->
    <div class="pr-card pr-card-tl">
      <div class="pr-card-b pr-card-b--flush">
        <div v-if="isLoading" class="pr-empty">
          <UiSpinner />
        </div>
        <div v-else-if="!logs.length" class="pr-empty">
          <i class="fas fa-inbox" />
          <span>{{ selectedBomIdLocal ? '暂无变更记录' : '请先选择 BOM' }}</span>
        </div>
        <ul v-else class="pr-timeline">
          <li
            v-for="log in logs"
            :key="log.id"
            class="pr-tl-item"
            :class="`pr-tl-item--${log.change_type}`"
          >
            <div class="pr-tl-node">
              <i :class="changeTypeIcon(log.change_type)" />
            </div>
            <div class="pr-tl-card">
              <div class="pr-tl-card-head">
                <span class="pr-tl-type-badge" :class="`pr-tl-type-badge--${log.change_type}`">
                  {{ log.change_type_label }}
                </span>
                <span v-if="log.from_version && log.to_version" class="pr-tl-version">
                  <span class="pr-tl-version-from">{{ log.from_version }}</span>
                  <i class="fas fa-arrow-right pr-tl-version-arrow" />
                  <span class="pr-tl-version-to">{{ log.to_version }}</span>
                </span>
                <span class="pr-tl-time">{{ formatDateTime(log.created_at) }}</span>
                <span v-if="log.operator_name" class="pr-tl-operator">
                  <i class="fas fa-user" /> {{ log.operator_name }}
                </span>

              </div>
              <div v-if="log.change_reason" class="pr-tl-reason">
                <i class="fas fa-comment-dots" />
                <span>{{ log.change_reason }}</span>
              </div>
              <div v-if="log.change_details?.length" class="pr-tl-preview">
                <span class="pr-tl-preview-label">变更字段 ({{ log.change_details.length }}):</span>
                <span
                  v-for="(d, idx) in log.change_details.slice(0, 3)"
                  :key="idx"
                  class="pr-tl-preview-tag"
                >
                  {{ fieldLabel(d.field) }}
                </span>

                <span v-if="log.change_details.length > 3" class="pr-tl-preview-more">
                  +{{ log.change_details.length - 3 }}
                </span>

              </div>
              <div class="pr-tl-actions">
                <button class="pr-btn pr-btn-link" @click="viewDetail(log)">
                  <i class="fas fa-eye" /> 查看详情
                </button>
              </div>
            </div>
          </li>
        </ul>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="pr-pagination">
          <button class="pr-page-btn" :disabled="page <= 1" @click="goPage(page - 1)">
            <i class="fas fa-chevron-left" />
          </button>
          <span class="pr-page-info">{{ page }} / {{ totalPages }}</span>
          <button class="pr-page-btn" :disabled="page >= totalPages" @click="goPage(page + 1)">
            <i class="fas fa-chevron-right" />
          </button>
        </div>
      </div>
    </div>

    <!-- 详情对话框 -->
    <UiDialog v-model:open="detailOpen" title="变更详情" max-width-class="max-w-[680px]">
      <template #title-icon>
        <i class="fas fa-clock-rotate-left" style="color: var(--color-primary-500);"></i>
      </template>
      <div v-if="detailLog" class="pr-detail">
        <div class="pr-detail-meta">
          <div class="pr-detail-meta-item">
            <label>变更类型</label>
            <span class="pr-tl-type-badge" :class="`pr-tl-type-badge--${detailLog.change_type}`">
              {{ detailLog.change_type_label }}
            </span>
          </div>
          <div class="pr-detail-meta-item">
            <label>版本</label>
            <span class="pr-detail-version">
              <span class="pr-tl-version-from">{{ detailLog.from_version || '-' }}</span>
              <i class="fas fa-arrow-right pr-tl-version-arrow" />
              <span class="pr-tl-version-to">{{ detailLog.to_version || '-' }}</span>
            </span>
          </div>
          <div class="pr-detail-meta-item">
            <label>时间</label>
            <span>{{ formatDateTime(detailLog.created_at) }}</span>
          </div>
          <div class="pr-detail-meta-item">
            <label>操作人</label>
            <span>{{ detailLog.operator_name || '-' }}</span>
          </div>
        </div>

        <div v-if="detailLog.change_reason" class="pr-detail-reason">
          <label>变更原因</label>
          <div class="pr-detail-reason-text">{{ detailLog.change_reason }}</div>
        </div>

        <div v-if="detailLog.change_details?.length" class="pr-detail-diff">
          <label>字段变更明细</label>
          <table class="pr-detail-tbl">
            <thead>
              <tr>
                <th style="width: 140px;">字段</th>
                <th>原值</th>
                <th style="width: 30px;"></th>
                <th>新值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(d, idx) in detailLog.change_details" :key="idx">
                <td class="pr-detail-field">{{ fieldLabel(d.field) }}</td>
                <td class="pr-detail-old">{{ formatValue(d.old) }}</td>
                <td class="pr-detail-arrow"><i class="fas fa-arrow-right" /></td>
                <td class="pr-detail-new">{{ formatValue(d.new) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="!detailLog.change_details?.length" class="pr-detail-empty">
          <i class="fas fa-info-circle" />
          <span>本次变更未记录字段级明细</span>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
/**
 * ChangeLogTab.vue — 变更记录 Tab
 *
 * 职责：
 * - 选择 BOM + 变更类型 + 日期范围筛选
 * - 时间线视图（按 created_at 倒序）
 * - 字段级 diff 详情对话框
 */
import { ref, computed, watch, onMounted } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { showToast } from '@/composables/useToast'
import { patternRoomApi } from '@/api/patternRoom'
import type { ChangeLog, PatternRoomBom } from '@/api/patternRoom'

const props = defineProps<{ bomId: number | null }>()

const selectedBomIdLocal = ref<number | null>(props.bomId)
const bomOptions = ref<PatternRoomBom[]>([])
const logs = ref<ChangeLog[]>([])
const total = ref(0)
const page = ref(1)
const perPage = ref(20)
const totalPages = ref(0)
const isLoading = ref(false)

const filterType = ref('')
const dateFrom = ref('')
const dateTo = ref('')

const detailOpen = ref(false)
const detailLog = ref<ChangeLog | null>(null)

const changeTypes = [
  { value: 'create', label: '创建' },
  { value: 'version_upgrade', label: '版本升级' },
  { value: 'supplier_change', label: '供应商变更' },
  { value: 'status_change', label: '状态变更' },
  { value: 'item_edit', label: '物料编辑' },
]

const hasFilters = computed(
  () => !!filterType.value || !!dateFrom.value || !!dateTo.value,
)

async function loadBomOptions() {
  try {
    const res = await patternRoomApi.listBom({ per_page: 100 })
    bomOptions.value = res.items ?? []
  } catch {
    // 静默失败
  }
}

async function onBomChange() {
  page.value = 1
  await reloadList()
}

async function reloadList() {
  if (!selectedBomIdLocal.value) {
    logs.value = []
    total.value = 0
    totalPages.value = 0
    return
  }
  isLoading.value = true
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      per_page: perPage.value,
    }
    if (filterType.value) params.change_type = filterType.value
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    const res = await patternRoomApi.listChangeLogs(selectedBomIdLocal.value, params as any)
    logs.value = res.items ?? []
    total.value = res.total ?? 0
    totalPages.value = res.pages ?? 0
  } catch (e: any) {
    showToast(e?.detail || '加载变更记录失败', 'error')
    logs.value = []
  } finally {
    isLoading.value = false
  }
}

function resetFilters() {
  filterType.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  page.value = 1
  reloadList()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  reloadList()
}

async function viewDetail(log: ChangeLog) {
  // 优先使用列表数据，再尝试拉取完整详情
  detailLog.value = log
  detailOpen.value = true
  if (!log.change_details?.length && log.id) {
    try {
      const res = await patternRoomApi.getChangeLog(log.id)
      if (res?.log) detailLog.value = res.log
    } catch {
      // 保留列表数据
    }
  }
}

watch(
  () => props.bomId,
  (newId) => {
    if (newId && newId !== selectedBomIdLocal.value) {
      selectedBomIdLocal.value = newId
      page.value = 1
      reloadList()
    }
  },
)

function changeTypeIcon(type: string): string {
  const map: Record<string, string> = {
    create: 'fas fa-plus',
    version_upgrade: 'fas fa-code-branch',
    supplier_change: 'fas fa-truck',
    status_change: 'fas fa-flag',
    item_edit: 'fas fa-pen',
  }
  return map[type] || 'fas fa-circle'
}

function fieldLabel(field: string): string {
  const map: Record<string, string> = {
    supplier_name: '供应商',
    supplier_id: '供应商',
    material_spec: '规格',
    unit_price: '单价',
    contact_person: '联系人',
    contact_phone: '电话',
    delivery_days: '交期',
    material_name: '物料名称',
    quantity: '数量',
    unit: '单位',
    spec: '规格',
    remark: '备注',
    status: '状态',
    category: '类别',
    sort_order: '排序',
    parent_id: '父节点',
  }
  return map[field] || field
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'boolean') return v ? '是' : '否'
  return String(v)
}

function formatDateTime(dt: string): string {
  if (!dt) return '-'
  // 后端返回 'YYYY-MM-DD HH:MM' 或 ISO；统一展示
  return dt.replace('T', ' ').slice(0, 16)
}

onMounted(async () => {
  await loadBomOptions()
  if (selectedBomIdLocal.value) {
    await reloadList()
  }
})
</script>

<style scoped>
.pr-log-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.pr-log-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.pr-toolbar-field {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pr-toolbar-field label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.pr-toolbar-field select,
.pr-toolbar-field input {
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 13px;
  background: white;
  min-width: 130px;
}

.pr-toolbar-field input[type='date'] {
  min-width: 140px;
}

.pr-toolbar-spacer {
  flex: 1 1 auto;
}

.pr-log-total {
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 600;
}

.pr-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.pr-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-700);
}

.pr-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pr-btn-ghost {
  background: transparent;
}

.pr-btn-link {
  background: transparent;
  border: none;
  padding: 4px 8px;
  color: var(--color-primary-600);
  font-size: 12px;
}

.pr-btn-link:hover {
  color: var(--color-primary-700);
  text-decoration: underline;
}

.pr-card {
  background: white;
  border-radius: 12px;
  border: 1px solid var(--color-border-light);
  overflow: hidden;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.pr-card-b {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.pr-card-b--flush {
  padding: 0;
}

.pr-empty {
  text-align: center;
  padding: 60px 14px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.pr-empty i {
  margin-right: 8px;
}

/* 时间线 */
.pr-timeline {
  list-style: none;
  margin: 0;
  padding: 24px 28px;
  position: relative;
}

.pr-timeline::before {
  content: '';
  position: absolute;
  left: 44px;
  top: 24px;
  bottom: 24px;
  width: 2px;
  background: linear-gradient(
    to bottom,
    var(--color-border-light),
    var(--color-border),
    var(--color-border-light)
  );
}

.pr-tl-item {
  position: relative;
  padding-left: 56px;
  margin-bottom: 20px;
}

.pr-tl-item:last-child {
  margin-bottom: 0;
}

.pr-tl-node {
  position: absolute;
  left: 32px;
  top: 4px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: white;
  border: 2px solid var(--color-primary-300);
  color: var(--color-primary-600);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  z-index: 1;
}

.pr-tl-item--create .pr-tl-node {
  border-color: var(--color-info-400);
  color: var(--color-info-600);
  background: var(--color-info-50);
}

.pr-tl-item--version_upgrade .pr-tl-node {
  border-color: var(--color-primary-400);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.pr-tl-item--supplier_change .pr-tl-node {
  border-color: var(--color-warning-400);
  color: var(--color-warning-600);
  background: var(--color-warning-50);
}

.pr-tl-item--status_change .pr-tl-node {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
  background: var(--color-success-50);
}

.pr-tl-item--item_edit .pr-tl-node {
  border-color: var(--color-border);
  color: var(--color-text-secondary);
  background: var(--color-surface);
}

.pr-tl-card {
  background: white;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  padding: 12px 16px;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.pr-tl-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  border-color: var(--color-border);
}

.pr-tl-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.pr-tl-type-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-light);
}

.pr-tl-type-badge--create {
  background: var(--color-info-50);
  color: var(--color-info-700);
  border-color: var(--color-info-200);
}

.pr-tl-type-badge--version_upgrade {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-color: var(--color-primary-200);
}

.pr-tl-type-badge--supplier_change {
  background: var(--color-warning-50);
  color: var(--color-warning-700);
  border-color: var(--color-warning-200);
}

.pr-tl-type-badge--status_change {
  background: var(--color-success-50);
  color: var(--color-success-700);
  border-color: var(--color-success-200);
}

.pr-tl-type-badge--item_edit {
  background: var(--color-surface);
  color: var(--color-text-secondary);
  border-color: var(--color-border-light);
}

.pr-tl-version {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
}

.pr-tl-version-from {
  color: var(--color-text-muted);
  background: var(--color-surface);
  padding: 1px 8px;
  border-radius: 4px;
}

.pr-tl-version-to {
  color: var(--color-success-700);
  background: var(--color-success-50);
  padding: 1px 8px;
  border-radius: 4px;
}

.pr-tl-version-arrow {
  font-size: 9px;
  color: var(--color-text-muted);
}

.pr-tl-time {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: auto;
}

.pr-tl-operator {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.pr-tl-operator i {
  margin-right: 4px;
  font-size: 10px;
}

.pr-tl-reason {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 6px 0;
  padding: 8px 10px;
  background: var(--color-surface);
  border-radius: 6px;
  font-size: 13px;
  color: var(--color-text);
  line-height: 1.5;
}

.pr-tl-reason i {
  color: var(--color-primary-500);
  margin-top: 2px;
  flex-shrink: 0;
}

.pr-tl-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 6px 0;
  font-size: 12px;
}

.pr-tl-preview-label {
  color: var(--color-text-muted);
  font-weight: 600;
}

.pr-tl-preview-tag {
  display: inline-block;
  padding: 1px 8px;
  background: var(--color-warning-50);
  color: var(--color-warning-700);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.pr-tl-preview-more {
  color: var(--color-text-muted);
  font-size: 11px;
}

.pr-tl-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

/* 分页 */
.pr-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px;
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface);
}

.pr-page-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border);
  background: white;
  border-radius: 8px;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: all 0.2s;
}

.pr-page-btn:hover:not(:disabled) {
  border-color: var(--color-primary-400);
  color: var(--color-primary-600);
}

.pr-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pr-page-info {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 600;
}

/* 详情对话框 */
.pr-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pr-detail-meta {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  padding: 12px;
  background: var(--color-surface);
  border-radius: 8px;
}

.pr-detail-meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pr-detail-meta-item label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
}

.pr-detail-version {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}

.pr-detail-reason {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pr-detail-reason label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-detail-reason-text {
  padding: 10px 12px;
  background: var(--color-info-50);
  border: 1px solid var(--color-info-200);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
  line-height: 1.6;
  white-space: pre-wrap;
}

.pr-detail-diff {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pr-detail-diff label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-detail-tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  overflow: hidden;
}

.pr-detail-tbl th {
  background: var(--color-surface);
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  border-bottom: 1px solid var(--color-border);
}

.pr-detail-tbl td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border-light);
  vertical-align: middle;
}

.pr-detail-tbl tr:last-child td {
  border-bottom: none;
}

.pr-detail-field {
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-detail-old {
  color: var(--color-danger-600);
  text-decoration: line-through;
  word-break: break-all;
}

.pr-detail-arrow {
  text-align: center;
  color: var(--color-text-muted);
  font-size: 10px;
}

.pr-detail-new {
  color: var(--color-success-700);
  font-weight: 600;
  word-break: break-all;
}

.pr-detail-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--color-text-muted);
  background: var(--color-surface);
  border-radius: 8px;
  font-size: 13px;
}
</style>
