<template>
  <div ref="rootRef" class="pcs-root">
    <div
      class="pcs-field"
      :class="{ 'pcs-field-open': open }"
      role="button"
      tabindex="0"
      :aria-expanded="open"
      aria-label="所属客户"
      @click="togglePanel"
      @keydown.enter.prevent="togglePanel"
      @keydown.space.prevent="togglePanel"
    >
      <span v-for="c in selectedRefs" :key="c.id" class="pcs-chip">
        {{ c.name }}
        <button
          type="button"
          class="pcs-chip-x"
          :aria-label="`移除 ${c.name}`"
          @click.stop="toggleId(c.id)"
        >×</button>
      </span>
      <span v-if="!selectedRefs.length" class="pcs-placeholder">{{ placeholder }}</span>
      <span class="pcs-caret" aria-hidden="true">▾</span>
    </div>

    <div v-if="open" class="pcs-panel">
      <input
        v-model="filter"
        class="pcs-search"
        type="text"
        placeholder="搜索客户…"
        aria-label="搜索客户"
      />
      <div class="pcs-list">
        <button
          v-for="o in filteredOptions"
          :key="o.id"
          type="button"
          class="pcs-option"
          :class="{ 'pcs-option-on': isSelected(o.id) }"
          @click="toggleId(o.id)"
        >
          <span class="pcs-check" aria-hidden="true">{{ isSelected(o.id) ? '✓' : '' }}</span>
          <span class="pcs-option-name">{{ o.name }}</span>
        </button>
        <p v-if="!filteredOptions.length" class="pcs-empty">无匹配客户</p>
      </div>
      <p class="pcs-hint">留空 = 不限制客户（所有客户都能选到这个 SKU）</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import type { ProductCustomerRef } from '@/types'

const props = withDefaults(defineProps<{
  modelValue: number[]
  /** 候选客户（调用方应把「产品当前已挂的客户」并进来，否则停用客户的归属会显示成 #id） */
  options: ProductCustomerRef[]
  placeholder?: string
}>(), {
  placeholder: '未挂客户 · 所有客户可见',
})

const emit = defineEmits<{
  'update:modelValue': [value: number[]]
}>()

const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)
const filter = ref('')

/**
 * 已选项的展示对象。
 * 找不到时回退成「客户 #id」而不是跳过：归属里有一个不在选项里的 id（客户被停用或
 * 删除），跳过会让 chip 消失、用户以为没挂客户，保存时该 id 被抹掉 = 静默把 SKU
 * 放开给所有客户。宁可显示得难看，也不能悄悄丢数据。
 */
const selectedRefs = computed<ProductCustomerRef[]>(() =>
  props.modelValue.map((id) => props.options.find((o) => o.id === id) ?? { id, name: `客户 #${id}` }),
)

const filteredOptions = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => o.name.toLowerCase().includes(q))
})

function isSelected(id: number) {
  return props.modelValue.includes(id)
}

function toggleId(id: number) {
  emit('update:modelValue', isSelected(id)
    ? props.modelValue.filter((x) => x !== id)
    : [...props.modelValue, id])
}

function togglePanel() {
  open.value = !open.value
  if (open.value) filter.value = ''
}

function onDocumentMouseDown(e: MouseEvent) {
  if (open.value && rootRef.value && !rootRef.value.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocumentMouseDown))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentMouseDown))
</script>

<style scoped>
.pcs-root { position: relative; }

.pcs-field {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 40px;
  padding: 6px 32px 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  background: white;
  cursor: pointer;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  position: relative;
}
.pcs-field:hover { border-color: var(--color-primary-400); }
.pcs-field-open,
.pcs-field:focus-visible {
  outline: none;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.pcs-placeholder { font-size: 14px; color: var(--color-text-muted, #94a3b8); }
.pcs-caret {
  position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
  color: var(--color-text-secondary); font-size: 12px; pointer-events: none;
}

.pcs-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 6px 2px 10px;
  font-size: 12.5px; font-weight: 600;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-100);
  border-radius: 999px;
}
.pcs-chip-x {
  border: none; background: transparent; cursor: pointer;
  color: var(--color-primary-600); opacity: 0.65; font-size: 13px; line-height: 1;
  padding: 0 2px;
}
.pcs-chip-x:hover { opacity: 1; }

.pcs-panel {
  position: absolute; z-index: 20; left: 0; right: 0; top: calc(100% + 6px);
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.10);
  overflow: hidden;
}
.pcs-search {
  width: 100%; border: none; outline: none;
  padding: 9px 12px; font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  font-family: inherit;
}
.pcs-list { max-height: 220px; overflow-y: auto; }
.pcs-option {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 8px 12px; font-size: 13px; text-align: left;
  background: transparent; border: none; cursor: pointer;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.pcs-option:last-child { border-bottom: none; }
.pcs-option:hover { background: var(--color-surface, #f8fafc); }
.pcs-option-on { font-weight: 600; color: var(--color-primary-600); }
.pcs-check {
  width: 15px; height: 15px; flex: none;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; color: var(--color-primary-600);
}
.pcs-empty { margin: 0; padding: 10px 12px; font-size: 12.5px; color: var(--color-text-muted, #94a3b8); }
.pcs-hint {
  margin: 0; padding: 6px 12px; font-size: 11.5px;
  color: var(--color-text-muted, #94a3b8);
  background: var(--color-surface, #f8fafc);
}
</style>
