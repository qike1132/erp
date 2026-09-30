<template>
  <div class="pr-entry-dropdown">
    <div v-if="searchLoading" class="pr-entry-dropdown-state">
      <UiSpinner />
    </div>
    <div v-else-if="searchError" class="pr-entry-dropdown-state pr-entry-dropdown-error">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> {{ searchError }}
    </div>
    <div v-else-if="!searchResults.length" class="pr-entry-dropdown-state">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" /> 无匹配产品
    </div>
    <button
      v-for="(p, idx) in searchResults"
      :key="p.id"
      type="button"
      :class="['pr-entry-dropdown-item', { active: idx === searchActiveIndex }]"
      @mousedown.prevent="emit('select', p)"
    >
      <span class="pr-entry-dropdown-icon"><FontAwesomeIcon icon="box" aria-hidden="true" /></span>
      <span class="pr-entry-dropdown-content">
        <span class="pr-entry-dropdown-name">{{ p.name }}</span>
        <span class="pr-entry-dropdown-meta">
          <span v-if="p.barcode" class="pr-entry-dropdown-barcode"><FontAwesomeIcon icon="barcode" aria-hidden="true" /> {{ p.barcode }}</span>
          <span v-if="p.specification" class="pr-entry-dropdown-spec">{{ p.specification }}</span>
        </span>
      </span>
      <FontAwesomeIcon v-if="idx === searchActiveIndex" icon="arrow-right" class="pr-entry-dropdown-enter" aria-hidden="true" />
    </button>
  </div>
</template>

<script setup lang="ts">
import type { Product } from '@/types'
import UiSpinner from '@/components/ui/UiSpinner.vue'

defineProps<{
  searchLoading: boolean
  searchError: string
  searchResults: Product[]
  searchActiveIndex: number
}>()

const emit = defineEmits<{
  select: [product: Product]
}>()
</script>

<style scoped>
.pr-entry-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 6px;
  background: white;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.15);
  max-height: 260px;
  overflow-y: auto;
  z-index: 20;
  padding: 4px;
}
.pr-entry-dropdown-state {
  padding: 16px;
  font-size: 13px;
  color: var(--color-text-muted);
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.pr-entry-dropdown-state i {
  font-size: 14px;
}
.pr-entry-dropdown-error {
  color: var(--color-danger-600);
}
.pr-entry-dropdown-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  border-radius: 8px;
  font-family: inherit;
  color: inherit;
  transition: background 0.15s ease;
}
.pr-entry-dropdown-item:hover,
.pr-entry-dropdown-item.active {
  background: var(--color-primary-50);
}
.pr-entry-dropdown-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--color-border-light);
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  flex-shrink: 0;
}
.pr-entry-dropdown-item.active .pr-entry-dropdown-icon {
  background: var(--color-primary-100);
  color: var(--color-primary-700);
}
.pr-entry-dropdown-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pr-entry-dropdown-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pr-entry-dropdown-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--color-text-muted);
}
.pr-entry-dropdown-barcode {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.pr-entry-dropdown-barcode i {
  font-size: 10px;
}
.pr-entry-dropdown-enter {
  color: var(--color-primary-700);
  font-size: 12px;
}
</style>