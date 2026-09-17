<template>
  <div class="mc-search-wrapper">
    <div class="mc-search-input-group">
      <FontAwesomeIcon icon="search" class="mc-search-icon" aria-hidden="true" />
      <input
        v-model="model"
        type="text"
        placeholder="搜索产品名称或69码..."
        class="mc-search-input"
        @input="emit('search-input')"
        @focus="emit('search-focus')"
        @blur="emit('search-blur')"
      />
      <button
        v-if="model"
        class="mc-search-clear"
        aria-label="关闭"
        @click="model = ''; emit('search-input')"
      >
        <FontAwesomeIcon icon="times" aria-hidden="true" />
      </button>
    </div>
    <div v-if="suggestions.length" class="mc-search-dropdown">
      <div v-for="p in suggestions" :key="p.id" class="mc-dropdown-item" @mousedown.prevent="emit('select', p)">
        <div class="mc-dropdown-item-info">
          <span class="mc-dropdown-item-name">{{ p.name }}</span>
          <span v-if="p.barcode" class="mc-dropdown-item-meta">{{ p.barcode }}</span>
        </div>
        <span :class="['mc-bom-tag-mini', p.has_bom ? 'has-bom' : 'no-bom']">
          {{ p.has_bom ? '有BOM' : '无BOM' }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { MaterialCalcProduct } from '@/api'

const model = defineModel<string>({ default: '' })

defineProps<{
  suggestions: MaterialCalcProduct[]
}>()

const emit = defineEmits<{
  'search-input': []
  'search-focus': []
  'search-blur': []
  'select': [p: MaterialCalcProduct]
}>()
</script>

<style scoped>
/* 本组件现在位于 .mc-col-tools 工具行内，自身不再带外边距，只负责撑满剩余宽度 */
.mc-search-wrapper {
  position: relative;
  flex: 1;
  min-width: 0;
}

.mc-search-input-group {
  position: relative;
  display: flex;
  align-items: center;
}

.mc-search-icon {
  position: absolute;
  left: 8px;
  color: var(--color-text-muted);
  font-size: 12px;
  z-index: 2;
  pointer-events: none;
}

.mc-search-input {
  width: 100%;
  height: 30px;
  padding: 0 26px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 12px;
  color: var(--color-text);
  outline: none;
  background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.mc-search-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.mc-search-input::placeholder {
  color: var(--color-text-muted);
}

.mc-search-clear {
  position: absolute;
  right: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: none;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.mc-search-clear:hover {
  background: var(--color-slate-100);
  color: var(--color-text-secondary);
}

.mc-search-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: #fff;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 10px 32px rgba(16, 24, 40, 0.12);
  z-index: 1000;
  max-height: 300px;
  overflow-y: auto;
}

.mc-dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  cursor: pointer;
  border-bottom: 1px solid var(--color-border-light);
  transition: background 0.15s ease;
}

.mc-dropdown-item:last-child {
  border-bottom: none;
}

.mc-dropdown-item:hover {
  background: var(--color-primary-50);
}

.mc-dropdown-item-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.mc-dropdown-item-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-dropdown-item-meta {
  font-size: 11px;
  color: var(--color-text-muted);
}

.mc-bom-tag-mini {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid;
}

.mc-bom-tag-mini.has-bom {
  background: var(--color-success-50);
  color: var(--color-success-700);
  border-color: var(--color-success-200);
}

.mc-bom-tag-mini.no-bom {
  background: var(--color-slate-100);
  color: var(--color-text-muted);
  border-color: var(--color-border);
}
</style>