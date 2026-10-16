<template>
  <div ref="rootRef" class="bss-root">
    <input
      ref="inputRef"
      :value="text"
      type="text"
      :class="['bss-input', inputClass]"
      :placeholder="placeholder"
      :name="inputName"
      autocomplete="off"
      :maxlength="maxlength"
      role="combobox"
      :aria-expanded="open"
      @focus="handleOpen"
      @click="handleOpen"
      @input="onInput"
      @blur="handleBlur"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="chooseHighlighted"
      @keydown.esc="handleEsc"
    />
    <Teleport to="body">
      <!--
        面板样式必须留在本组件的 <style scoped>：Teleport 到 body 后它不在宿主
        DOM 子树里，宿主 scoped 规则（含 :deep()）碰不到它，否则会退化成裸 div。
        宿主只能用 :deep() 注入上面的 input（如表格编辑态边框）。
      -->
      <div v-if="open" ref="panelRef" class="bss-panel" :style="panelStyle" role="listbox">
        <div v-if="!filtered.length" class="bss-empty">
          未找到「<em>{{ text.trim() }}</em>」，{{ emptyHint }}
        </div>
        <div
          v-for="(opt, i) in filtered"
          :key="opt.value + ':' + i"
          class="bss-option"
          :class="{ active: i === highlight }"
          role="option"
          :aria-selected="i === highlight"
          @mousedown.prevent="choose(opt)"
          @mouseenter="highlight = i"
        >{{ displayOf(opt) }}</div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/**
 * PartFieldCombobox —— 带历史候选的自由文本输入框
 *
 * 从 BomSupplierSelect 泛化而来（删除原组件、BomEditor 改指向本组件，避免双实现漂移）。
 * 行为与之一致：聚焦/点击即弹候选、输入实时过滤（大小写不敏感子串）、
 * 键盘上下 + Enter 选中、Esc 只关面板、Teleport + fixed 防滚动容器裁剪、
 * 无匹配时仍可自由输入。
 *
 * 与 BomSupplierSelect 的差异（为板房场景 + 通用化）：
 * - options 形状从 {id,name} 改为 {value,count}（板房历史候选无 id）
 * - 显示值 trim：不回把手输的首尾空格变体写回单元格
 * - 空态后半句经 emptyHint 传入（BOM「保存后将自动创建」/ 板房「保存后将自动记录」）
 * - Esc 加 .stop：宿主是 reka-ui DialogContent（带 Esc 关窗），防止关面板连带关弹窗
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

export interface CandidateOption {
  value: string
  count: number
}

const props = withDefaults(defineProps<{
  modelValue?: string
  options?: CandidateOption[]
  placeholder?: string
  maxlength?: number
  /** 空态后半句（前面固定为「未找到“xxx”，」） */
  emptyHint?: string
  /** 宿主注入 input 的额外类名（如表格编辑态 pvt-inline-input） */
  inputClass?: string
  /** 原生 input name，浏览器凭据自动填充需要 */
  inputName?: string
}>(), {
  modelValue: '',
  options: () => [],
  placeholder: '选择或输入',
  maxlength: 200,
  emptyHint: '保存后将自动记录',
  inputClass: '',
  inputName: undefined,
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

/** 展示值始终 trim，避免把首尾空格变体写回数据 */
function displayOf(opt: CandidateOption): string {
  return (opt.value ?? '').trim()
}

const filtered = computed<CandidateOption[]>(() => {
  const q = text.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter(o => displayOf(o).toLowerCase().includes(q))
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

/**
 * Esc 只在面板打开时由本组件消费并 stopPropagation。
 *
 * 面板已关时必须放行：宿主是 reka-ui UiDialog（PartFormDialog 等），它的
 * DismissableLayer 靠 Esc 关弹窗。若无条件 stop，面板关着时按 Esc 会被吞掉，
 * 弹窗就再也无法用键盘关闭。
 */
function handleEsc(e: KeyboardEvent) {
  if (!open.value) return
  e.stopPropagation()
  open.value = false
}

/** 焦点离开本组件（Tab / 程序化移焦）时关面板。选项已用 @mousedown.prevent 保焦点，
    所以点选不会走到这里；仅当焦点确实移到 root/panel 之外才关（relatedTarget 为 null
    说明没落到具体元素上，同样关）。 */
function handleBlur(e: FocusEvent) {
  const next = e.relatedTarget as Node | null
  if (next && (rootRef.value?.contains(next) || panelRef.value?.contains(next))) return
  open.value = false
}

function choose(opt: CandidateOption) {
  // 程序化赋值不受原生 maxlength 约束，须自己夹：后端 BatchPartItem.supplier_name
  // 上限 100 而 PartUpdateRequest 上限 200，行内编辑存下的长值会成为候选，不夹就会在
  // 批量弹窗里写入一个手输永远达不到的长度 → 后端 422。
  text.value = displayOf(opt).slice(0, props.maxlength)
  emit('update:modelValue', text.value)
  open.value = false
}

function chooseHighlighted() {
  if (!open.value || !filtered.value.length) return
  // highlight 可能在 filtered 缩短后越界（options 异步替换 / modelValue 回写重算）：
  // 用 min 夹住，别让 `!` 把真实的 undefined 藏起来（choose → displayOf 会抛）。
  const opt = filtered.value[Math.min(highlight.value, filtered.value.length - 1)]
  if (opt) choose(opt)
}

function move(delta: number) {
  if (!open.value) { handleOpen(); return }
  const n = filtered.value.length
  if (!n) return
  highlight.value = (highlight.value + delta + n) % n
}

/** 面板与输入框的间距、面板理想最大高度（与样式里的 max-height 保持一致） */
const PANEL_GAP = 4
const PANEL_MAX_H = 240

function positionPanel() {
  const el = inputRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const vw = window.innerWidth || document.documentElement.clientWidth
  const vh = window.innerHeight || document.documentElement.clientHeight

  const below = vh - r.bottom - PANEL_GAP
  const above = r.top - PANEL_GAP

  let top: number
  let maxH: number
  if (below >= PANEL_MAX_H || below >= above) {
    // 下方放得下，或下方仍比上方宽裕 → 正常展开在下方
    top = r.bottom + PANEL_GAP
    maxH = Math.min(PANEL_MAX_H, Math.max(below, 0))
  } else {
    // 下方不够（input 靠近视口底部）→ 翻到上方，底边贴 input 顶
    maxH = Math.min(PANEL_MAX_H, Math.max(above, 0))
    top = Math.max(PANEL_GAP, r.top - PANEL_GAP - maxH)
  }

  // 右侧溢出时向左收，避免宽面板（如长供应商名）被视口裁掉
  const width = Math.min(r.width, vw - r.left - PANEL_GAP)
  const left = Math.min(r.left, Math.max(PANEL_GAP, vw - width - PANEL_GAP))

  panelStyle.value = {
    position: 'fixed',
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(maxH)}px`,
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
  /* 宿主若是 modal 弹窗（reka-ui UiDialog），弹窗打开时 DismissableLayer 会把
     body 设为 pointer-events: none，且只对弹窗自身的 [data-dismissable-layer] 恢复 auto。
     本面板 Teleport 到 body，是弹窗 portal 的兄弟节点，会继承到那个 none —— 面板照常渲染
     （滚动条照样画出）却收不到任何鼠标事件，滚轮/拖动滚动条全部失灵。
     这里显式 auto 覆盖继承（与 reka-ui 自身对 layer 的做法同思路），恢复滚动与点选。 */
  pointer-events: auto;
}
.bss-option {
  padding: 8px 10px; font-size: 13px; border-radius: 7px; cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.bss-option.active { background: var(--color-primary-50, #eef4ff); color: var(--color-primary-700, #2f6fdd); }
.bss-empty { padding: 10px 12px; font-size: 12.5px; color: var(--color-text-secondary, #6b7280); line-height: 1.6; }
.bss-empty em { font-style: normal; font-weight: 600; color: var(--color-primary-700, #2f6fdd); }
</style>
