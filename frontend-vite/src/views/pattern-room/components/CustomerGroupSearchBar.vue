<template>
  <!-- 搜索框 + 新建打样 -->
  <div class="cgl-search-row" role="search" aria-label="搜索打样项目">
    <div class="cgl-search">
      <FontAwesomeIcon icon="search" class="cgl-search-icon" aria-hidden="true" />
      <input
        class="cgl-search-input"
        type="text"
        placeholder="搜索版师或项目..."
        aria-label="搜索版师或项目"
        @input="onSearchInput"
      />
    </div>
    <button
      v-if="canManage"
      type="button"
      class="cgl-add-btn"
      @click="$emit('add-project')"
    >
      新建打样
    </button>
  </div>

  <!-- 状态筛选胶囊：互斥切换按钮组，选中态走 aria-pressed（见 useSelectionA11y） -->
  <div class="cgl-status-filter" role="group" aria-label="按项目状态筛选">
    <button
      v-for="opt in STATUS_OPTIONS"
      :key="opt.value"
      v-bind="itemAttrs(opt.value)"
      type="button"
      :class="['cgl-status-btn', { active: statusFilter === opt.value }]"
      @click="onStatusChange(opt.value)"
    >
      {{ opt.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { ProjectStatus } from '@/api/patternRoom'
import { useSelectionA11y } from '@/composables/useSelectionA11y'

const props = defineProps<{
  /** 当前状态筛选（受控：由父级 statusFilter 传入，避免父子状态漂移） */
  statusFilter: ProjectStatus
  /** 是否可新建打样（无权限时隐藏按钮） */
  canManage: boolean
}>()

/** 状态胶囊的选中态语义统一走 useSelectionA11y，勿手写 aria-pressed 字面量 */
const { itemAttrs } = useSelectionA11y(() => props.statusFilter)

const emit = defineEmits<{
  search: [keyword: string]
  'status-change': [value: ProjectStatus]
  'add-project': []
}>()

/** 状态胶囊选项（value 受 ProjectStatus 约束，标签改动集中在此处） */
const STATUS_OPTIONS: readonly { value: ProjectStatus; label: string }[] = [
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
]

function onStatusChange(value: ProjectStatus) {
  emit('status-change', value)
}

function onSearchInput(e: Event) {
  const target = e.target as HTMLInputElement
  emit('search', target.value)
}
</script>

<style scoped>
.cgl-search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid var(--color-border-light, #e5e7eb);
  flex-shrink: 0;
}
.cgl-search {
  position: relative;
  flex: 1;
  min-width: 0;
}
.cgl-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary, #9ca3af);
  font-size: 12px;
}
.cgl-search-input {
  width: 100%;
  padding: 8px 12px 8px 30px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text-primary);
  box-sizing: border-box;
}
/*
 * 不使用 outline: none —— 那会盖掉 app.css 的全局 :focus-visible 焦点环
 * （审查 A11Y-10）。这里只叠加边框强调，2px 轮廓由全局规则提供，
 * 满足 WCAG 2.4.11 对焦点指示面积的要求。
 */
.cgl-search-input:focus-visible {
  border-color: var(--color-primary-500, #5b8def);
}
.cgl-add-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-700);
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  cursor: pointer;
  white-space: nowrap;
  font-family: inherit;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}
.cgl-add-btn:hover {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  transform: translateY(-1px);
}
.cgl-status-filter {
  display: inline-flex;
  gap: 4px;
  padding: 4px 12px 0;
  flex-shrink: 0;
}
.cgl-status-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary, #6b7280);
  background: transparent;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.cgl-status-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.cgl-status-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  border-color: var(--color-primary-200);
  font-weight: 600;
}
</style>