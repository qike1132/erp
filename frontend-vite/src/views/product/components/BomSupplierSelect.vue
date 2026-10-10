<template>
  <div ref="rootRef" class="bss-root">
    <input
      ref="inputRef"
      :value="text"
      type="text"
      class="bss-input"
      :placeholder="placeholder"
      name="supplier-name"
      autocomplete="off"
      maxlength="100"
      role="combobox"
      :aria-expanded="open"
      @focus="handleOpen"
      @click="handleOpen"
      @input="onInput"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="chooseHighlighted"
      @keydown.esc="handleClose"
    />
    <Teleport to="body">
      <div v-if="open" ref="panelRef" class="bss-panel" :style="panelStyle" role="listbox">
        <div v-if="!filtered.length" class="bss-empty">
          未找到「<em>{{ text.trim() }}</em>」，保存 BOM 后将自动创建该供应商
        </div>
        <div
          v-for="(opt, i) in filtered"
          :key="opt.id"
          class="bss-option"
          :class="{ active: i === highlight }"
          role="option"
          :aria-selected="i === highlight"
          @mousedown.prevent="choose(opt)"
          @mouseenter="highlight = i"
        >{{ opt.name }}</div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/**
 * BomSupplierSelect — BOM 配置的供应商选择框
 *
 * 点击/聚焦即弹出全部供应商（来自 /suppliers/options，实时）；输入实时过滤（大小写不敏感）；
 * 既可选项回填，也可直接输入新名（保存 BOM 后由后端同事务自动建卡）。
 * 面板 Teleport 到 body + fixed 定位，避免被 BOM 表格的横向滚动容器裁剪。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

export interface SupplierOption {
  id: number
  name: string
}

const props = withDefaults(defineProps<{
  modelValue?: string
  options?: SupplierOption[]
  placeholder?: string
}>(), {
  modelValue: '',
  options: () => [],
  placeholder: '选择或输入供应商',
})

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const rootRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const text = ref(props.modelValue)
const open = ref(false)
const highlight = ref(0)
const panelStyle = ref<Record<string, string>>({})

watch(() => props.modelValue, (v) => {
  if ((v ?? '') !== text.value) text.value = v ?? ''
})

const filtered = computed<SupplierOption[]>(() => {
  const q = text.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter(o => o.name.toLowerCase().includes(q))
})

function onInput(e: Event) {
  text.value = (e.target as HTMLInputElement).value
  emit('update:modelValue', text.value)
  highlight.value = 0
  open.value = true
  positionPanel()
}

function handleOpen() {
  open.value = true
  highlight.value = 0
  nextTick(positionPanel)
}

function handleClose() {
  open.value = false
}

function choose(opt: SupplierOption) {
  text.value = opt.name
  emit('update:modelValue', opt.name)
  open.value = false
}

function chooseHighlighted() {
  if (!open.value || !filtered.value.length) return
  choose(filtered.value[highlight.value]!)
}

function move(delta: number) {
  if (!open.value) { handleOpen(); return }
  const n = filtered.value.length
  if (!n) return
  highlight.value = (highlight.value + delta + n) % n
}

function positionPanel() {
  const el = inputRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  panelStyle.value = {
    position: 'fixed',
    top: `${r.bottom + 4}px`,
    left: `${r.left}px`,
    width: `${r.width}px`,
  }
}

function onDocMouseDown(e: MouseEvent) {
  const t = e.target as Node
  if (rootRef.value?.contains(t) || panelRef.value?.contains(t)) return
  open.value = false
}

/** 位置会随滚动/缩放漂移：关闭面板（面板内自身的滚动不算）。 */
function onViewportChange(e?: Event) {
  if (!open.value) return
  const t = e?.target as Node | null
  if (t && panelRef.value?.contains(t)) return
  open.value = false
}

watch(open, (v) => {
  if (v) {
    document.addEventListener('mousedown', onDocMouseDown, true)
    window.addEventListener('scroll', onViewportChange, true)
    window.addEventListener('resize', onViewportChange)
  } else {
    document.removeEventListener('mousedown', onDocMouseDown, true)
    window.removeEventListener('scroll', onViewportChange, true)
    window.removeEventListener('resize', onViewportChange)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMouseDown, true)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<style scoped>
.bss-root { position: relative; width: 100%; }
.bss-input {
  width: 100%; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; outline: none; background: #fff;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.bss-input:focus { border-color: var(--color-primary-400, #7aa2f7); box-shadow: 0 0 0 3px rgba(0, 148, 191, .1); }
.bss-panel {
  z-index: 1500; max-height: 240px; overflow-y: auto; background: #fff;
  border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  box-shadow: 0 14px 34px rgba(15, 23, 42, .16); padding: 4px;
}
.bss-option {
  padding: 8px 10px; font-size: 13px; border-radius: 7px; cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.bss-option.active { background: var(--color-primary-50, #eef4ff); color: var(--color-primary-700, #2f6fdd); }
.bss-empty { padding: 10px 12px; font-size: 12.5px; color: var(--color-text-secondary, #6b7280); line-height: 1.6; }
.bss-empty em { font-style: normal; font-weight: 600; color: var(--color-primary-700, #2f6fdd); }
</style>
