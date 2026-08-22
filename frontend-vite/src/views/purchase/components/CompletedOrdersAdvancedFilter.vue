<template>
  <transition name="coq-slide">
    <div v-show="filterExpanded" class="coq-advanced">
      <div class="coq-advanced-row">
        <div class="coq-advanced-cell">
          <label class="coq-advanced-label">供应商</label>
          <input
            type="text"
            class="coq-advanced-input"
            placeholder="输入供应商名称"
            :value="filters.supplier_name"
            @input="$emit('updateFilter', { key: 'supplier_name', value: ($event.target as HTMLInputElement).value })"
          />
        </div>
        <div class="coq-advanced-cell">
          <label class="coq-advanced-label">69码</label>
          <input
            type="text"
            class="coq-advanced-input"
            placeholder="输入69码"
            :value="filters.barcode"
            @input="$emit('updateFilter', { key: 'barcode', value: ($event.target as HTMLInputElement).value })"
          />
        </div>
        <div class="coq-advanced-cell">
          <label class="coq-advanced-label">物料名称</label>
          <input
            type="text"
            class="coq-advanced-input"
            placeholder="输入物料名称"
            :value="filters.material_name"
            @input="$emit('updateFilter', { key: 'material_name', value: ($event.target as HTMLInputElement).value })"
          />
        </div>
        <button class="coq-btn coq-btn-ghost coq-advanced-reset" aria-label="重置" @click="$emit('resetFilters')">
          <FontAwesomeIcon icon="undo" aria-hidden="true" />
          <span>重置</span>
        </button>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
defineProps<{
  filters: Record<string, string>
  filterExpanded: boolean
}>()

defineEmits<{
  updateFilter: [payload: { key: string; value: string }]
  resetFilters: []
}>()
</script>

<style scoped>
.coq-advanced {
  padding: 12px 24px;
  background: var(--coq-bg-soft);
  border-bottom: 1px solid var(--coq-border);
}

.coq-advanced-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.coq-advanced-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 160px;
  flex: 1;
}

.coq-advanced-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--coq-slate);
  letter-spacing: 0.02em;
}

.coq-advanced-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  background: var(--coq-bg);
  font-family: inherit;
  color: var(--coq-text);
  box-sizing: border-box;
}

.coq-advanced-input::placeholder {
  color: var(--coq-text-muted);
}

.coq-advanced-input:focus {
  border-color: var(--coq-blue);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12);
}

.coq-advanced-reset {
  flex: 0 0 auto;
}

.coq-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--coq-bg);
  color: var(--coq-text-secondary);
  white-space: nowrap;
  font-family: inherit;
  line-height: 1.4;
}

.coq-btn i {
  font-size: 11px;
}

.coq-btn:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
  background: var(--coq-blue-light);
}

.coq-btn-ghost {
  border-color: transparent;
  background: transparent;
}

.coq-btn-ghost:hover {
  border-color: var(--coq-border);
  background: var(--coq-bg-soft);
}

.coq-slide-enter-active,
.coq-slide-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
  max-height: 200px;
}

.coq-slide-enter-from,
.coq-slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

@media (max-width: 1024px) {
  .coq-advanced-row {
    flex-direction: column;
    align-items: stretch;
  }

  .coq-advanced-reset {
    align-self: flex-start;
  }
}
</style>