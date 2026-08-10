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
      <!-- 头部信息 -->
      <div class="pdp-header">
        <div class="pdp-header-left">
          <div class="pdp-thumb">
            <img v-if="project.product_image_url" :src="project.product_image_url" alt="" />
            <i v-else class="fas fa-tshirt" aria-hidden="true" />
          </div>
          <div class="pdp-header-info">
            <h2 class="pdp-title">{{ project.product_name }}</h2>
            <div class="pdp-meta">
              <span class="pdp-seq">{{ project.sequence_no }}</span>
              <span class="pdp-customer" v-if="project.customer_name">
                <i class="fas fa-building" aria-hidden="true" />
                {{ project.customer_name }}
              </span>
              <span class="pdp-version-badge">{{ project.current_version }}</span>
            </div>
            <div class="pdp-header-dates">
              <span>创建：{{ formatTime(project.created_at) }}</span>
              <span>更新：{{ formatTime(project.updated_at) }}</span>
              <span v-if="project.created_by_name">操作人：{{ project.created_by_name }}</span>
            </div>
          </div>
        </div>
        <div v-if="canManage" class="pdp-header-actions">
          <button class="pdp-action-btn" title="编辑" @click="$emit('edit')">
            <i class="fas fa-pen" aria-hidden="true" />
          </button>
          <button class="pdp-action-btn pdp-action-danger" title="删除" @click="$emit('delete')">
            <i class="fas fa-trash" aria-hidden="true" />
          </button>
        </div>
      </div>

      <!-- 版本切换 -->
      <div class="pdp-section pdp-version-bar">
        <div class="pdp-section-header">
          <h3 class="pdp-section-title">
            <i class="fas fa-code-branch" aria-hidden="true" />
            版本
          </h3>
          <button
            v-if="canManage"
            class="pdp-add-btn"
            @click="$emit('create-version')"
          >
            <i class="fas fa-plus" aria-hidden="true" />
            新版本
          </button>
        </div>
        <div class="pdp-version-list">
          <button
            v-for="v in versions"
            :key="v.id"
            :class="['pdp-version-chip', { active: currentVersionId === v.id }]"
            @click="$emit('switch-version', v.id)"
          >
            {{ v.version_no }}
          </button>
          <span v-if="versionLoading" class="pdp-version-loading">
            <UiSpinner size="xs" />
          </span>
        </div>
      </div>

      <!-- 版本详情（diff 信息） -->
      <div v-if="versionDetail && !isBaseline && versionDetail.change_summary" class="pdp-section pdp-diff-section">
        <div class="pdp-section-header">
          <h3 class="pdp-section-title">
            <i class="fas fa-arrow-right-arrow-left" aria-hidden="true" />
            变更摘要
          </h3>
          <span v-if="isDegraded" class="pdp-degraded-badge">降级展示</span>
        </div>
        <div class="pdp-diff-list">
          <div
            v-for="(change, idx) in versionDetail.change_summary"
            :key="idx"
            :class="['pdp-diff-item', `pdp-diff-${change.change_type}`]"
          >
            <span class="pdp-diff-type">
              <i v-if="change.change_type === 'add'" class="fas fa-plus-circle" aria-hidden="true" />
              <i v-else-if="change.change_type === 'modify'" class="fas fa-pen-circle" aria-hidden="true" />
              <i v-else class="fas fa-minus-circle" aria-hidden="true" />
            </span>
            <span class="pdp-diff-part">{{ change.part_name }}</span>
          </div>
        </div>
      </div>

      <!-- 部位布料表格 -->
      <div class="pdp-section pdp-parts-section">
        <div class="pdp-section-header">
          <h3 class="pdp-section-title">
            <i class="fas fa-layer-group" aria-hidden="true" />
            部位布料
            <span class="pdp-count-badge">{{ currentParts.length }}</span>
          </h3>
          <button
            v-if="canManage"
            class="pdp-add-btn"
            @click="$emit('add-part')"
          >
            <i class="fas fa-plus" aria-hidden="true" />
            新增部位
          </button>
        </div>

        <div v-if="partLoading" class="pdp-loading">
          <UiSpinner size="sm" />
          <span>加载部位数据...</span>
        </div>

        <div v-else-if="currentParts.length === 0" class="pdp-empty-parts">
          <i class="fas fa-cubes" aria-hidden="true" />
          <span>暂无部位布料信息</span>
        </div>

        <div v-else class="pdp-parts-table-wrap">
          <table class="pdp-parts-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>部位名称</th>
                <th>布料名称</th>
                <th>规格</th>
                <th>供应商</th>
                <th>联系人</th>
                <th>单价</th>
                <th>交期(天)</th>
                <th>备注</th>
                <th v-if="canManage">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="part in currentParts" :key="part.id">
                <td>{{ part.sort_order }}</td>
                <td class="pdp-part-name">{{ part.part_name }}</td>
                <td>{{ part.fabric_name || '-' }}</td>
                <td>{{ part.fabric_spec || '-' }}</td>
                <td>{{ part.supplier_name || '-' }}</td>
                <td>{{ part.contact_person || '-' }}</td>
                <td class="pdp-num">{{ part.unit_price != null ? '¥' + part.unit_price.toFixed(2) : '-' }}</td>
                <td class="pdp-num">{{ part.delivery_days ?? '-' }}</td>
                <td class="pdp-remark">{{ part.remark || '-' }}</td>
                <td v-if="canManage" class="pdp-actions">
                  <button class="pdp-row-btn" title="编辑" @click="$emit('edit-part', part)">
                    <i class="fas fa-pen" aria-hidden="true" />
                  </button>
                  <button class="pdp-row-btn pdp-row-btn-danger" title="删除" @click="$emit('delete-part', part)">
                    <i class="fas fa-trash" aria-hidden="true" />
                  </button>
                </td>
              </tr>
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
import type { ProjectDetailResponse, VersionBrief, VersionDetailResponse, PartDetail } from '@/api/patternRoom'

defineProps<{
  project: ProjectDetailResponse | null
  versions: VersionBrief[]
  currentVersionId: number | null
  versionDetail: VersionDetailResponse | null
  isBaseline: boolean
  isDegraded: boolean
  isCurrentVersion: boolean
  currentParts: PartDetail[]
  versionLoading: boolean
  partLoading: boolean
  canManage: boolean
}>()

defineEmits<{
  edit: []
  delete: []
  'switch-version': [versionId: number]
  'create-version': []
  'add-part': []
  'edit-part': [part: PartDetail]
  'delete-part': [part: PartDetail]
}>()

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.pdp-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 12px;
  background: #fff;
}

/* 头部 */
.pdp-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.pdp-header-left {
  display: flex;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.pdp-thumb {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--color-surface, #f3f4f6);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pdp-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pdp-thumb i {
  font-size: 24px;
  color: var(--color-text-secondary);
  opacity: 0.5;
}

.pdp-header-info {
  flex: 1;
  min-width: 0;
}

.pdp-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 4px;
  color: var(--color-text-primary);
}

.pdp-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.pdp-seq {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.pdp-customer {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}

.pdp-version-badge {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 6px;
  background: #3b82f620;
  color: #3b82f6;
  font-weight: 600;
}

.pdp-header-dates {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--color-text-secondary);
  opacity: 0.7;
  flex-wrap: wrap;
}

.pdp-header-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.pdp-action-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  transition: all 0.15s;
}

.pdp-action-btn:hover {
  border-color: #ff9f43;
  color: #ff9f43;
}

.pdp-action-danger:hover {
  border-color: #ef4444;
  color: #ef4444;
}

/* Section 通用 */
.pdp-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.pdp-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.pdp-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
}

.pdp-count-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 8px;
  background: var(--color-surface, #f3f4f6);
  color: var(--color-text-secondary);
  font-weight: 500;
}

.pdp-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #ff9f43;
  background: #ff9f4310;
  border: 1px solid #ff9f4340;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.pdp-add-btn:hover {
  background: #ff9f4320;
}

/* 版本列表 */
.pdp-version-list {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.pdp-version-chip {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  background: #fff;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.pdp-version-chip:hover {
  border-color: #3b82f6;
  color: #3b82f6;
}

.pdp-version-chip.active {
  border-color: #3b82f6;
  background: #3b82f610;
  color: #3b82f6;
}

.pdp-version-loading {
  margin-left: 4px;
}

/* 降级 badge */
.pdp-degraded-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #fbbf2420;
  color: #d97706;
  font-weight: 600;
}

/* Diff */
.pdp-diff-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pdp-diff-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.pdp-diff-add {
  background: #22c55e15;
  color: #16a34a;
}

.pdp-diff-modify {
  background: #f59e0b15;
  color: #d97706;
}

.pdp-diff-delete {
  background: #ef444415;
  color: #dc2626;
}

.pdp-diff-type {
  font-size: 11px;
}

/* 加载 */
.pdp-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

/* 空部位 */
.pdp-empty-parts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.pdp-empty-parts i {
  font-size: 28px;
  opacity: 0.4;
}

/* 部位表格 */
.pdp-parts-section {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-bottom: none;
}

.pdp-parts-table-wrap {
  flex: 1;
  overflow: auto;
}

.pdp-parts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.pdp-parts-table th,
.pdp-parts-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid var(--color-border-light, #f3f4f6);
  white-space: nowrap;
}

.pdp-parts-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  background: var(--color-surface, #fafafa);
  position: sticky;
  top: 0;
  z-index: 1;
}

.pdp-parts-table tbody tr:hover {
  background: #ff9f4305;
}

.pdp-part-name {
  font-weight: 600;
  color: var(--color-text-primary);
}

.pdp-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.pdp-remark {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pdp-actions {
  display: flex;
  gap: 4px;
}

.pdp-row-btn {
  width: 26px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  transition: all 0.15s;
}

.pdp-row-btn:hover {
  background: #ff9f4315;
  color: #ff9f43;
  border-color: #ff9f4330;
}

.pdp-row-btn-danger:hover {
  background: #ef444415;
  color: #ef4444;
  border-color: #ef444430;
}
</style>
