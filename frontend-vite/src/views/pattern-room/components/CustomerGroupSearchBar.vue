<template>
  <!-- 搜索框 -->
  <div class="cgl-search">
    <FontAwesomeIcon icon="search" class="cgl-search-icon" aria-hidden="true" />
    <input
      class="cgl-search-input"
      type="text"
      placeholder="搜索版师或项目..."
      @input="onSearchInput"
    />
  </div>

  <!-- 状态筛选胶囊 -->
  <div class="cgl-status-filter">
    <button
      v-for="opt in STATUS_OPTIONS"
      :key="opt.value"
      type="button"
      :class="['cgl-status-btn', { active: statusFilter === opt.value }]"
      @click="onStatusChange(opt.value)"
    >
      {{ opt.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  /** 当前状态筛选（受控：由父级 statusFilter 传入，避免父子状态漂移） */
  statusFilter: string
}>()

const emit = defineEmits<{
  search: [keyword: string]
  'status-change': [value: string]
}>()

const STATUS_OPTIONS = [
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
] as const

function onStatusChange(value: string) {
  emit('status-change', value)
}

function onSearchInput(e: Event) {
  const target = e.target as HTMLInputElement
  emit('search', target.value)
}
</script>

<style scoped>
.cgl-search {
  position: relative;
  padding: 12px;
  border-bottom: 1px solid var(--color-border-light, #e5e7eb);
  flex-shrink: 0;
}
.cgl-search-icon {
  position: absolute;
  left: 22px;
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
  outline: none;
  box-sizing: border-box;
}
.cgl-search-input:focus {
  border-color: var(--color-primary-400);
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