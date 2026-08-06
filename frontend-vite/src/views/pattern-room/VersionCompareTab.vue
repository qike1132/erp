<template>
  <div class="pr-compare-tab">
    <!-- 顶部：BOM 选择 + 版本对比选择 -->
    <div class="pr-compare-toolbar">
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
        <label>原版本</label>
        <select v-model="fromVersion" @change="loadCompare">
          <option value="">-</option>
          <option v-for="v in versions" :key="v" :value="v">{{ v }}</option>
        </select>
      </div>
      <div class="pr-toolbar-arrow"><i class="fas fa-arrow-right" /></div>
      <div class="pr-toolbar-field">
        <label>新版本</label>
        <select v-model="toVersion" @change="loadCompare">
          <option value="">-</option>
          <option v-for="v in versions" :key="v" :value="v">{{ v }}</option>
        </select>
      </div>
      <label class="pr-toggle-diff">
        <input type="checkbox" v-model="onlyDiff" />
        <span>只看差异</span>
      </label>
      <button class="pr-btn pr-btn-ghost" @click="createNewVersion" :disabled="!selectedBomIdLocal">
        <i class="fas fa-code-branch" /> 创建新版本
      </button>
    </div>

    <!-- BOM 概览 -->
    <div v-if="bom" class="pr-bom-summary">
      <div class="pr-summary-item">
        <label>产品名称</label>
        <span class="pr-summary-value">{{ bom.product_name }}</span>
      </div>
      <div class="pr-summary-item">
        <label>客户</label>
        <span class="pr-summary-value">{{ bom.customer_name || '-' }}</span>
      </div>
      <div class="pr-summary-item">
        <label>当前版本</label>
        <span class="pr-summary-value pr-version-current">{{ bom.current_version }}</span>
      </div>
      <div class="pr-summary-item">
        <label>状态</label>
        <UiStatusBadge :variant="statusVariant(bom.status)">{{ bom.status_label }}</UiStatusBadge>
      </div>
      <div class="pr-summary-item">
        <label>差异物料数</label>
        <span class="pr-summary-value pr-diff-count">{{ differences.length }}</span>
      </div>
    </div>

    <!-- 对比表格 -->
    <div class="pr-card">
      <div class="pr-card-b pr-card-b--flush">
        <table class="pr-tbl" style="min-width: 1100px;">
          <thead>
            <tr>
              <th style="width: 180px;">物料名称</th>
              <th style="width: 100px;">类别</th>
              <th style="width: 100px;">用量</th>
              <th style="width: 180px;">{{ fromVersion || '原版本' }} 供应商</th>
              <th style="width: 180px;">{{ toVersion || '新版本' }} 供应商</th>
              <th>变更明细</th>
              <th style="width: 70px;">标记</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="isLoading">
              <td colspan="7" class="pr-empty"><UiSpinner /></td>
            </tr>
            <tr v-else-if="!filteredDifferences.length">
              <td colspan="7" class="pr-empty">
                <i class="fas fa-check-circle" />
                <span>{{ differences.length ? '所有差异已隐藏' : '无差异，两个版本完全一致' }}</span>
              </td>
            </tr>
            <tr v-for="d in filteredDifferences" :key="d.bom_item_id" class="pr-diff-row">
              <td class="pr-td-bold">{{ d.material_name }}</td>
              <td>
                <UiStatusBadge :variant="categoryVariant(d.category)">{{ categoryLabel(d.category) }}</UiStatusBadge>
              </td>
              <td>{{ d.quantity }} {{ d.unit }}</td>
              <td class="pr-td-supplier pr-td-supplier-from">{{ d.from_supplier || '-' }}</td>
              <td class="pr-td-supplier pr-td-supplier-to">
                <span v-if="d.to_supplier && d.from_supplier !== d.to_supplier" class="pr-changed">
                  {{ d.to_supplier }}
                  <small v-if="d.from_supplier">（原: {{ d.from_supplier }}）</small>
                </span>
                <span v-else>{{ d.to_supplier || '-' }}</span>
              </td>
              <td>
                <div class="pr-diff-list">
                  <div v-for="(change, idx) in d.diff" :key="idx" class="pr-diff-item">
                    <span class="pr-diff-field">{{ fieldLabel(change.field) }}:</span>
                    <span class="pr-diff-old">{{ formatValue(change.old) }}</span>
                    <i class="fas fa-arrow-right pr-diff-arrow" />
                    <span class="pr-diff-new">{{ formatValue(change.new) }}</span>
                  </div>
                </div>
              </td>
              <td>
                <span class="pr-change-flag" title="有变更">
                  <i class="fas fa-triangle-exclamation" />
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 创建新版本对话框 -->
    <UiDialog v-model:open="createVersionOpen" title="创建新版本" max-width-class="max-w-[500px]">
      <template #title-icon>
        <i class="fas fa-code-branch" style="color: var(--color-primary-500);"></i>
      </template>
      <div class="pr-create-version-form">
        <div class="pr-form-field">
          <label>当前版本</label>
          <span class="pr-version-current">{{ bom?.current_version || '-' }}</span>
          <i class="fas fa-arrow-right" style="margin: 0 8px;" />
          <span class="pr-version-new">T{{ nextVersionNum }}</span>
        </div>
        <div class="pr-form-field">
          <label>变更原因 <span class="pr-req">*</span></label>
          <textarea
            v-model="versionReason"
            rows="4"
            placeholder="请详细描述本次版本升级的原因（≥10字符）"
            maxlength="500"
          ></textarea>
          <small class="pr-char-count">{{ versionReason.length }}/500</small>
        </div>
        <div class="pr-form-tip">
          <i class="fas fa-info-circle" />
          <span>系统会自动对所有物料节点当前数据做版本快照</span>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="createVersionOpen = false">取消</UiButton>
        <UiButton variant="primary" :disabled="submitting || versionReason.trim().length < 10" @click="submitCreateVersion">
          <i v-if="submitting" class="fas fa-spinner fa-spin" /> 创建版本
        </UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
/**
 * VersionCompareTab.vue — 布料版本对比 Tab
 *
 * 职责：
 * - 选择 BOM + 两个版本号
 * - 展示对比表格（按物料行 diff）
 * - 支持创建新版本（自动快照 + 写日志）
 */
import { ref, computed, watch, onMounted } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiStatusBadge from '@/components/ui/UiStatusBadge.vue'
import { showToast } from '@/composables/useToast'
import { patternRoomApi } from '@/api/patternRoom'
import type { PatternRoomBom, VersionDiff } from '@/api/patternRoom'

const props = defineProps<{ bomId: number | null }>()

const selectedBomIdLocal = ref<number | null>(props.bomId)
const bom = ref<PatternRoomBom | null>(null)
const bomOptions = ref<PatternRoomBom[]>([])
const versions = ref<string[]>([])
const fromVersion = ref('')
const toVersion = ref('')
const differences = ref<VersionDiff[]>([])
const isLoading = ref(false)
const onlyDiff = ref(true)

// 创建新版本
const createVersionOpen = ref(false)
const versionReason = ref('')
const submitting = ref(false)

const nextVersionNum = computed(() => {
  if (!bom.value?.current_version) return 2
  const m = /^T(\d+)$/i.exec(bom.value.current_version)
  return m && m[1] ? parseInt(m[1], 10) + 1 : 2
})

const filteredDifferences = computed(() => {
  if (!onlyDiff.value) return differences.value
  return differences.value.filter((d) => d.diff.length > 0)
})

async function loadBomOptions() {
  try {
    const res = await patternRoomApi.listBom({ per_page: 100 })
    bomOptions.value = res.items ?? []
  } catch (e) {
    // 静默失败
  }
}

async function onBomChange() {
  if (!selectedBomIdLocal.value) {
    bom.value = null
    versions.value = []
    differences.value = []
    return
  }
  await loadVersions()
  await loadBomDetail()
  await loadCompare()
}

async function loadBomDetail() {
  if (!selectedBomIdLocal.value) return
  try {
    const res = await patternRoomApi.getBom(selectedBomIdLocal.value)
    bom.value = res.bom
  } catch (e: any) {
    showToast(e?.detail || '加载 BOM 失败', 'error')
  }
}

async function loadVersions() {
  if (!selectedBomIdLocal.value) return
  try {
    const res = await patternRoomApi.listVersions(selectedBomIdLocal.value)
    versions.value = res.versions ?? []
    // 默认选中前两个版本
    if (versions.value.length >= 2 && !fromVersion.value && !toVersion.value) {
      fromVersion.value = versions.value[0]!
      toVersion.value = versions.value[versions.value.length - 1]!
    } else if (versions.value.length === 1) {
      fromVersion.value = versions.value[0]!
      toVersion.value = versions.value[0]!
    }
  } catch (e) {
    versions.value = []
  }
}

async function loadCompare() {
  if (!selectedBomIdLocal.value || !fromVersion.value || !toVersion.value) {
    differences.value = []
    return
  }
  if (fromVersion.value === toVersion.value) {
    differences.value = []
    return
  }
  isLoading.value = true
  try {
    const res = await patternRoomApi.compareVersions(
      selectedBomIdLocal.value,
      fromVersion.value,
      toVersion.value,
    )
    bom.value = res.bom
    differences.value = res.differences ?? []
  } catch (e: any) {
    showToast(e?.detail || '对比失败', 'error')
    differences.value = []
  } finally {
    isLoading.value = false
  }
}

function createNewVersion() {
  versionReason.value = ''
  createVersionOpen.value = true
}

async function submitCreateVersion() {
  if (!selectedBomIdLocal.value) return
  if (versionReason.value.trim().length < 10) {
    showToast('变更原因 必须 ≥ 10 字符', 'warning')
    return
  }
  submitting.value = true
  try {
    const res = await patternRoomApi.createVersion(selectedBomIdLocal.value, {
      reason: versionReason.value.trim(),
    })
    if (res.success) {
      showToast(`已创建版本 ${res.to_version}`, 'success')
      createVersionOpen.value = false
      await loadVersions()
      await loadBomDetail()
      // 自动切到新版本对比
      if (versions.value.length >= 2) {
        fromVersion.value = versions.value[versions.value.length - 2]!
        toVersion.value = versions.value[versions.value.length - 1]!
        await loadCompare()
      }
    }
  } catch (e: any) {
    showToast(e?.detail || '创建版本失败', 'error')
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.bomId,
  (newId) => {
    if (newId && newId !== selectedBomIdLocal.value) {
      selectedBomIdLocal.value = newId
      fromVersion.value = ''
      toVersion.value = ''
      onBomChange()
    }
  },
)

function statusVariant(status: string): 'default' | 'primary' | 'success' | 'warning' | 'info' {
  const map: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'info'> = {
    draft: 'default',
    sampling: 'info',
    confirmed: 'success',
    archived: 'warning',
  }
  return map[status] || 'default'
}

function categoryLabel(category: string): string {
  const map: Record<string, string> = {
    fabric: '面料',
    filling: '填充',
    accessory: '辅料',
    packaging: '包装',
  }
  return map[category] || category
}

function categoryVariant(category: string): 'primary' | 'warning' | 'info' | 'success' {
  const map: Record<string, 'primary' | 'warning' | 'info' | 'success'> = {
    fabric: 'primary',
    filling: 'warning',
    accessory: 'info',
    packaging: 'success',
  }
  return map[category] || 'primary'
}

function fieldLabel(field: string): string {
  const map: Record<string, string> = {
    supplier_name: '供应商',
    material_spec: '规格',
    unit_price: '单价',
    contact_person: '联系人',
    contact_phone: '电话',
    delivery_days: '交期',
  }
  return map[field] || field
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '-'
  if (typeof v === 'number') {
    if (fieldLabel('').includes('单价')) return `¥${v}`
    return String(v)
  }
  return String(v)
}

onMounted(async () => {
  await loadBomOptions()
  if (selectedBomIdLocal.value) {
    await onBomChange()
  }
})
</script>

<style scoped>
.pr-compare-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.pr-compare-toolbar {
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

.pr-toolbar-field select {
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 13px;
  background: white;
  min-width: 140px;
}

.pr-toolbar-arrow {
  color: var(--color-text-muted);
  font-size: 13px;
}

.pr-toggle-diff {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.pr-toggle-diff input {
  cursor: pointer;
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

.pr-bom-summary {
  display: flex;
  gap: 24px;
  padding: 12px 16px;
  background: var(--color-surface);
  border-radius: 10px;
  border: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

.pr-summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pr-summary-item label {
  font-size: 11px;
  color: var(--color-text-muted);
  font-weight: 600;
  text-transform: uppercase;
}

.pr-summary-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.pr-version-current {
  color: var(--color-purple-700);
  background: var(--color-purple-50);
  padding: 2px 10px;
  border-radius: 6px;
  display: inline-block;
}

.pr-diff-count {
  color: var(--color-warning-700);
  background: var(--color-warning-50);
  padding: 2px 10px;
  border-radius: 6px;
  display: inline-block;
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

.pr-tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pr-tbl th {
  background: var(--color-surface);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
}

.pr-tbl td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border-light);
  vertical-align: middle;
}

.pr-diff-row {
  border-left: 4px solid var(--color-warning-500);
}

.pr-td-bold {
  font-weight: 600;
}

.pr-td-supplier {
  font-size: 13px;
}

.pr-td-supplier-from {
  color: var(--color-text-muted);
}

.pr-changed {
  color: var(--color-warning-700);
  font-weight: 600;
}

.pr-changed small {
  color: var(--color-text-muted);
  font-weight: normal;
  font-size: 11px;
  display: block;
  margin-top: 2px;
}

.pr-diff-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pr-diff-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 3px 6px;
  background: var(--color-warning-50);
  border-radius: 4px;
}

.pr-diff-field {
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-diff-old {
  color: var(--color-danger-600);
  text-decoration: line-through;
}

.pr-diff-arrow {
  font-size: 9px;
  color: var(--color-text-muted);
}

.pr-diff-new {
  color: var(--color-success-700);
  font-weight: 600;
}

.pr-change-flag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: var(--color-warning-100);
  color: var(--color-warning-700);
  border-radius: 6px;
  font-size: 11px;
}

.pr-empty {
  text-align: center;
  padding: 40px 14px;
  color: var(--color-text-muted);
}

.pr-empty i {
  margin-right: 8px;
}

/* 创建版本对话框 */
.pr-create-version-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pr-form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
}

.pr-form-field label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-form-field textarea {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s;
  resize: vertical;
  min-height: 80px;
}

.pr-form-field textarea:focus {
  border-color: var(--color-primary-400);
}

.pr-char-count {
  font-size: 11px;
  color: var(--color-text-muted);
  text-align: right;
}

.pr-version-new {
  color: var(--color-success-700);
  background: var(--color-success-50);
  padding: 2px 10px;
  border-radius: 6px;
  display: inline-block;
  font-weight: 700;
}

.pr-req {
  color: var(--color-danger-500);
}

.pr-form-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-info-50);
  border: 1px solid var(--color-info-200);
  border-radius: 8px;
  font-size: 12px;
  color: var(--color-info-700);
}
</style>
