<template>
  <div class="mc-search-wrapper">
    <div class="mc-search-input-group">
      <FontAwesomeIcon icon="search" class="mc-search-icon" aria-hidden="true" />
      <input
        :value="searchQuery"
        type="text"
        placeholder="搜索产品名称或69码..."
        class="mc-search-input"
        @input="$emit('update:searchQuery', ($event.target as HTMLInputElement).value); $emit('search-input')"
        @focus="$emit('focus')"
        @blur="$emit('blur')"
      />
      <button
        v-if="searchQuery"
        class="mc-search-clear"
        aria-label="关闭"
        @click="$emit('update:searchQuery', ''); $emit('search-input')"
      >
        <FontAwesomeIcon icon="times" aria-hidden="true" />
      </button>
    </div>
    <div v-if="searchSuggestions.length" class="mc-search-dropdown">
      <div v-for="p in searchSuggestions" :key="p.id" class="mc-dropdown-item" @mousedown.prevent="$emit('select', p)">
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

defineProps<{
  searchQuery: string
  searchSuggestions: MaterialCalcProduct[]
}>()

defineEmits<{
  'update:searchQuery': [value: string]
  'search-input': []
  focus: []
  blur: []
  select: [p: MaterialCalcProduct]
}>()
</script>

<style scoped>
.mc-search-wrapper {
  position: relative;
  padding: 12px 16px;
}
.mc-search-input-group {
  position: relative;
  display: flex;
  align-items: center;
}
.mc-search-icon {
  position: absolute;
  left: 14px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
  z-index: 2;
}
.mc-search-input {
  width: 100%;
  padding: 12px 40px 12px 42px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 11px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
}
.mc-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.mc-search-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.mc-search-clear {
  position: absolute;
  right: 10px;
  background: none;
  border: none;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  padding: 6px;
  border-radius: 50%;
  transition: background 0.2s ease, color 0.2s ease;
}
.mc-search-clear:hover {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-secondary);
}
.mc-search-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 16px;
  right: 16px;
  background: white;
  border: 2px solid var(--color-primary-200);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  z-index: 1000;
  max-height: 320px;
  overflow-y: auto;
}
.mc-dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.mc-dropdown-item:last-child { border-bottom: none; }
.mc-dropdown-item:hover { background: var(--color-primary-50); }
.mc-dropdown-item-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.mc-dropdown-item-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text);
}
.mc-dropdown-item-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.mc-bom-tag-mini {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.mc-bom-tag-mini.has-bom {
  background: var(--color-success-100);
  color: var(--color-success-700);
}
.mc-bom-tag-mini.no-bom {
  background: var(--color-danger-100);
  color: var(--color-danger-800);
}
</style>