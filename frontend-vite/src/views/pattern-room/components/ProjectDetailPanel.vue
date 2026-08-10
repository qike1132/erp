<template>
  <div class="pdp-container">
    <!-- 未选中项目 -->
    <EmptyState
      v-if="!project"
      icon="fas fa-hand-point-left"
      title="请选择一个打样项目"
      description="从左侧列表中选择项目查看详情"
    />

    <!-- 项目详情 -->
    <template v-else>
      <!-- 部位布料表格（跨版本二维表） -->
      <div class="pdp-section pdp-parts-section">
        <div class="pdp-section-header">
          <h3 class="pdp-section-title">
            <i class="fas fa-layer-group" aria-hidden="true" />
            部位布料
            <span class="pdp-count-badge">{{ partsByVersion.length }}</span>
          </h3>
        </div>

        <div v-if="partLoading" class="pdp-loading">
          <UiSpinner size="sm" />
          <span>加载部位数据...</span>
        </div>

        <div v-else-if="partsByVersion.length === 0" class="pdp-empty-parts">
          <i class="fas fa-cubes" aria-hidden="true" />
          <span>暂无部位布料信息</span>
        </div>

        <div v-else class="pdp-parts-table-wrap">
          <table class="pdp-parts-table pdp-parts-table--version">
            <colgroup>
              <col style="width: 100px">
              <col style="width: 60px">
              <col style="width: 110px">
              <col style="width: 110px">
              <col style="width: 110px">
              <col style="width: 110px">
            </colgroup>
            <thead>
              <tr>
                <th>部位名称</th>
                <th>版本</th>
                <th>供应商</th>
                <th>布料名称</th>
                <th>色号</th>
                <th class="pdp-actions-th">功能</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="group in groupedRows" :key="group.part_name">
                <tr
                  v-for="(part, idx) in group.items"
                  :key="part.id ?? `${group.part_name}-${idx}`"
                  :class="{ 'pdp-row--editing': editingPartId === part.id }"
                >
                  <td v-if="idx === 0" :rowspan="group.rowSpan" class="pdp-part-name-col">
                    <div class="pdp-part-name-cell">
                      <span>{{ group.part_name }}</span>
                      <button
                        v-if="selectedVersion[group.part_name]"
                        class="pdp-expand-btn"
                        :title="group.collapsed ? '展开所有版本' : '折叠其他版本'"
                        @click.stop="toggleExpand(group.part_name)"
                      >
                        <i
                          :class="['fas', group.collapsed ? 'fa-chevron-down' : 'fa-chevron-up']"
                          aria-hidden="true"
                        />
                      </button>
                    </div>
                  </td>
                  <td class="pdp-version-col">
                    <button
                      v-if="part.version_no"
                      class="pdp-vp-chip"
                      :class="{ 'pdp-vp-chip--active': selectedVersion[group.part_name] === part.version_no }"
                      :title="selectedVersion[group.part_name] === part.version_no ? '点击取消选择，显示所有版本' : '选择 ' + part.version_no + ' 为最终版本'"
                      @click.stop="toggleVersion(group.part_name, part.version_no!)"
                    >
                      {{ part.version_no }}
                    </button>
                    <span v-else>-</span>
                  </td>
                  <!-- 供应商 -->
                  <td>
                    <input
                      v-if="editingPartId === part.id"
                      v-model="editForm.supplier_name"
                      class="pdp-inline-input"
                      placeholder="供应商"
                    />
                    <template v-else>{{ part.supplier_name || '-' }}</template>
                  </td>
                  <!-- 布料名称 -->
                  <td>
                    <input
                      v-if="editingPartId === part.id"
                      v-model="editForm.fabric_name"
                      class="pdp-inline-input"
                      placeholder="布料名称"
                    />
                    <template v-else>{{ part.fabric_name || '-' }}</template>
                  </td>
                  <!-- 色号 -->
                  <td>
                    <input
                      v-if="editingPartId === part.id"
                      v-model="editForm.fabric_color_no"
                      class="pdp-inline-input"
                      placeholder="色号"
                    />
                    <template v-else>{{ part.fabric_color_no || '-' }}</template>
                  </td>
                  <!-- 功能列 -->
                  <td class="pdp-actions-col">
                    <div v-if="editingPartId === part.id" class="pdp-row-actions">
                      <button
                        type="button"
                        class="pdp-action-btn pdp-action-btn--success"
                        title="保存"
                        @click="saveEdit(part)"
                      >
                        <i class="fas fa-check" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        class="pdp-action-btn pdp-action-btn--muted"
                        title="取消"
                        @click="cancelEdit()"
                      >
                        <i class="fas fa-times" aria-hidden="true" />
                      </button>
                    </div>
                    <div v-else class="pdp-row-actions">
                      <button
                        v-if="part.version_no === group.latestVersionNo"
                        type="button"
                        class="pdp-action-btn pdp-action-btn--info"
                        title="复制版本"
                        @click="$emit('copy-version', part)"
                      >
                        <i class="fas fa-copy" aria-hidden="true" />
                      </button>
                      <span v-else class="pdp-action-placeholder" />
                      <button
                        type="button"
                        class="pdp-action-btn pdp-action-btn--warning"
                        :title="part.id == null ? '历史快照，无法编辑' : '修改版本'"
                        :disabled="!canManage || part.id == null"
                        @click="startEdit(part)"
                      >
                        <i class="fas fa-pen" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        class="pdp-action-btn pdp-action-btn--danger"
                        title="删除版本"
                        @click="$emit('delete-version', part)"
                      >
                        <i class="fas fa-trash-alt" aria-hidden="true" />
                      </button>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import UiSpinner from '@/components/ui/UiSpinner.vue'
import EmptyState from './EmptyState.vue'
import { computed, ref, reactive, watch } from 'vue'
import type { ProjectDetailResponse, PartDetail } from '@/api/patternRoom'

const props = defineProps<{
  project: ProjectDetailResponse | null
  partsByVersion: PartDetail[]
  versionList: string[]
  versionLoading: boolean
  partLoading: boolean
  canManage: boolean
}>()

const emit = defineEmits<{
  'copy-version': [part: PartDetail]
  'edit-version': [part: PartDetail]
  'delete-version': [part: PartDetail]
  'save-edit': [part: PartDetail, data: { supplier_name: string; fabric_name: string; fabric_color_no: string }]
}>()

/** 正在编辑的行 part_id（null = 无编辑中行）
 *  注意：必须用 undefined 而非 null 做哨兵，避免与快照行 part.id === null 误匹配 */
const editingPartId = ref<number | undefined>(undefined)

const editForm = reactive({
  supplier_name: '',
  fabric_name: '',
  fabric_color_no: '',
})

function startEdit(part: PartDetail) {
  if (part.id == null) return
  editingPartId.value = part.id
  editForm.supplier_name = part.supplier_name || ''
  editForm.fabric_name = part.fabric_name || ''
  editForm.fabric_color_no = part.fabric_color_no || ''
}

function saveEdit(part: PartDetail) {
  editingPartId.value = undefined
  emit('save-edit', part, { ...editForm })
}

function cancelEdit() {
  editingPartId.value = undefined
}

/** 数据刷新或切换项目时退出编辑状态（兜底防残留） */
watch(
  () => props.partsByVersion,
  () => { editingPartId.value = undefined },
)

/** 切换项目时强制退出编辑，并重置版本筛选 */
watch(
  () => props.project?.id ?? null,
  () => {
    editingPartId.value = undefined
    selectedVersion.value = {}
    expandedParts.value = new Set()
  },
)

// ==================== 版本筛选器 ====================

/** 每个部位名称 → 选中的版本号 */
const selectedVersion = ref<Record<string, string | null>>({})

/** 已手动展开的部位名称集合（展开后显示所有版本，但芯片保持高亮） */
const expandedParts = ref<Set<string>>(new Set())

/**
 * 切换某个部位名称的版本筛选：
 * - 点击未选中版本 → 设为选中，折叠只显示该版本
 * - 点击已选中版本 → 取消选中，恢复显示所有版本
 */
function toggleVersion(partName: string, versionNo: string) {
  if (selectedVersion.value[partName] === versionNo) {
    // 取消选中
    const { [partName]: _, ...rest } = selectedVersion.value
    selectedVersion.value = rest
    // 同时清除展开状态
    expandedParts.value.delete(partName)
  } else {
    selectedVersion.value = { ...selectedVersion.value, [partName]: versionNo }
    // 选择新版本时清除展开状态，重新折叠
    expandedParts.value.delete(partName)
  }
}

/** 切换展开/折叠（芯片保持高亮，不清除 selectedVersion） */
function toggleExpand(partName: string) {
  const next = new Set(expandedParts.value)
  if (next.has(partName)) {
    next.delete(partName)
  } else {
    next.add(partName)
  }
  expandedParts.value = next
}

/** 按 part_name 分组后的行数据，已计算 rowSpan，支持版本筛选 */
const groupedRows = computed(() => {
  const items = props.partsByVersion
  const result: { part_name: string; rowSpan: number; items: PartDetail[]; latestVersionNo: string | null; collapsed: boolean }[] = []
  const seen = new Map<string, PartDetail[]>()

  for (const item of items) {
    const key = item.part_name
    if (!seen.has(key)) seen.set(key, [])
    seen.get(key)!.push(item)
  }

  for (const [name, group] of seen) {
    // 计算该部位的最新版本号（T1/T2/T3 → 提取数字后取最大值）
    const versionNums = group
      .map(i => i.version_no)
      .filter(Boolean)
      .map(v => parseInt((v as string).replace(/^T/i, ''), 10))
      .filter(n => !isNaN(n))
    const maxNum = versionNums.length > 0 ? Math.max(...versionNums) : null
    const latestVersionNo = maxNum != null ? `T${maxNum}` : null

    // 版本筛选：如果选中了某个版本且未手动展开，只保留该版本的行
    const sel = selectedVersion.value[name]
    const versionExists = sel ? group.some(i => i.version_no === sel) : false
    const shouldFold = versionExists && !expandedParts.value.has(name)
    let filteredItems = shouldFold ? group.filter(i => i.version_no === sel) : group

    // 按版本号顺序排序（T1/T2/T3/.../T10 → 1,2,3,...,10）
    const versionNum = (v?: string | null) => {
      if (!v) return Number.MAX_SAFE_INTEGER
      const n = parseInt(v.replace(/^T/i, ''), 10)
      return isNaN(n) ? Number.MAX_SAFE_INTEGER : n
    }
    filteredItems = [...filteredItems].sort((a, b) => versionNum(a.version_no) - versionNum(b.version_no))

    result.push({
      part_name: name,
      rowSpan: filteredItems.length,
      items: filteredItems,
      latestVersionNo,
      collapsed: shouldFold,
    })
  }
  return result
})
</script>

<style scoped>
/* ============ 容器 ============ */
.pdp-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 12px;
  background: #fff;
}

/* ============ Section 通用 ============ */
.pdp-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
}

.pdp-section:last-child {
  border-bottom: none;
}

.pdp-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 8px;
}

.pdp-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary, #1a1a2e);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  line-height: 1.4;
}

.pdp-section-title i {
  font-size: 12px;
  color: var(--color-text-secondary, #475569);
}

.pdp-count-badge {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-muted, #94a3b8);
  font-weight: 500;
  line-height: 1.6;
}

/* ============ 加载 ============ */
.pdp-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-secondary, #475569);
  font-size: 13px;
}

/* ============ 空部位（系统原生） ============ */
.pdp-empty-parts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 13px;
}

.pdp-empty-parts i {
  font-size: 32px;
  opacity: 0.4;
  color: var(--color-text-secondary, #475569);
}

/* ============ 部位表格（系统原生风格） ============ */
.pdp-parts-section {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.pdp-parts-table-wrap {
  flex: 1;
  overflow: auto;
}

.pdp-parts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: fixed;
}

.pdp-parts-table th,
.pdp-parts-table td {
  padding: 10px 12px;
  text-align: left;
  border: 1px solid #d9dce3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
}

.pdp-parts-table th {
  font-weight: 500;
  color: var(--color-text-primary, #1a1a2e);
  background: #fff;
  position: sticky;
  top: 0;
  z-index: 1;
  font-size: 13px;
  text-align: center;
}

.pdp-parts-table tbody tr:hover {
  background: transparent;
}

/* ============ 跨版本表格专用样式 ============ */

/* 跨版本表格 th 左对齐（默认居中不适用） */
.pdp-parts-table--version th {
  text-align: center;
}

/* 跨版本表格数据列居中 */
.pdp-parts-table--version td {
  text-align: center;
}

/* 部位名称列 — rowSpan 合并后的左侧锚定列 */
.pdp-part-name-col {
  font-weight: 500;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
  text-align: center;
}

.pdp-part-name-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

/* 折叠时展开按钮 */
.pdp-expand-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  font-size: 9px;
  color: var(--color-warning-500, #ff9f43);
  background: #fff;
  border: 1px solid var(--color-warning-300, #fdba74);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.pdp-expand-btn:hover {
  color: #fff;
  background: var(--color-warning-500, #ff9f43);
  border-color: var(--color-warning-500, #ff9f43);
}

/* ============ 版本选择器芯片 ============ */
.pdp-vp-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 22px;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 500;
  font-family: inherit;
  color: var(--color-text-muted, #94a3b8);
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}

.pdp-vp-chip:hover {
  color: var(--color-warning-600, #ea580c);
  background: var(--color-warning-50, #fff7ed);
  border-color: var(--color-warning-300, #fdba74);
}

.pdp-vp-chip--active {
  color: #fff;
  background: linear-gradient(135deg, #ff9f43, #ff8c1f);
  border-color: #ff8c1f;
  box-shadow: 0 1px 4px rgba(255, 159, 67, 0.3);
}

.pdp-vp-chip--active:hover {
  color: #fff;
  background: linear-gradient(135deg, #ff8c1f, #e67e22);
  border-color: #e67e22;
}

/* 版本号列 */
.pdp-version-col {
  text-align: center;
  color: var(--color-text-primary, #1a1a2e);
}

/* ============ 功能按钮列 ============ */
.pdp-actions-col {
  padding: 6px 10px !important;
}

.pdp-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.pdp-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  font-size: 12px;
  font-family: inherit;
  border: 1px solid;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.pdp-action-btn i {
  font-size: 10px;
}

/* 复制版本 — 蓝色系 */
.pdp-action-btn--info {
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
  border-color: var(--color-primary-200, #bfdbfe);
}

.pdp-action-btn--info:hover {
  background: var(--color-primary-100, #dbeafe);
  border-color: var(--color-primary-400, #60a5fa);
}

/* 复制按钮占位，保持对齐 */
.pdp-action-placeholder {
  display: inline-flex;
  width: 26px;
  height: 26px;
  visibility: hidden;
}

/* 修改版本 — 橙色系 */
.pdp-action-btn--warning {
  color: var(--color-warning-600, #ea580c);
  background: var(--color-warning-50, #fff7ed);
  border-color: var(--color-warning-200, #fed7aa);
}

.pdp-action-btn--warning:hover {
  background: var(--color-warning-100, #ffedd5);
  border-color: var(--color-warning-400, #fb923c);
}

/* 删除版本 — 红色系 */
.pdp-action-btn--danger {
  color: var(--color-danger-600, #dc2626);
  background: var(--color-danger-50, #fef2f2);
  border-color: var(--color-danger-200, #fecaca);
}

.pdp-action-btn--danger:hover {
  background: var(--color-danger-100, #fee2e2);
  border-color: var(--color-danger-400, #f87171);
}

/* 保存 — 绿色系 */
.pdp-action-btn--success {
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
  border-color: var(--color-success-200, #bbf7d0);
}

.pdp-action-btn--success:hover {
  background: var(--color-success-100, #dcfce7);
  border-color: var(--color-success-400, #4ade80);
}

/* 取消 — 灰色系 */
.pdp-action-btn--muted {
  color: var(--color-text-secondary, #6b7280);
  background: #f9fafb;
  border-color: #d1d5db;
}

.pdp-action-btn--muted:hover {
  background: #f3f4f6;
  border-color: #9ca3af;
}

/* ============ 内联编辑 ============ */
.pdp-row--editing {
  background: #fefce8;
}

.pdp-inline-input {
  width: 100%;
  max-width: 100%;
  padding: 4px 6px;
  border: 1px solid var(--color-warning-400, #fb923c);
  border-radius: 4px;
  font-size: 12px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  background: #fff;
  color: var(--color-text-primary, #1a1a2e);
}

.pdp-inline-input:focus {
  border-color: var(--color-warning-500, #ff9f43);
  box-shadow: 0 0 0 2px var(--color-warning-100, #ffedd5);
}


</style>
