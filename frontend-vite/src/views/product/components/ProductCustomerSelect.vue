<template>
  <div ref="rootRef" class="pcs-root">
    <div
      ref="fieldRef"
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

    <!--
      面板必须 teleport 到 body 并定位成 fixed。
      留在组件内会挂在弹窗内容区（.bom-modal-body 有 overflow-y:auto）之下被裁掉半截，
      左栏新增表单的 .pd-col 也是 overflow:hidden —— 两处都会把下拉切掉。
    -->
    <Teleport to="body">
      <div v-if="open" ref="panelRef" class="pcs-panel" :style="panelStyle">
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
            @click="selectOption(o.id)"
          >
            <span class="pcs-check" aria-hidden="true">{{ isSelected(o.id) ? '✓' : '' }}</span>
            <span class="pcs-option-name">{{ o.name }}</span>
          </button>
          <p v-if="!filteredOptions.length" class="pcs-empty">无匹配客户</p>
        </div>
        <p class="pcs-hint">留空 = 不限制客户（所有客户都能选到这个 SKU）</p>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import type { CSSProperties } from 'vue'
import type { ProductCustomerRef } from '@/types'

const props = withDefaults(defineProps<{
  modelValue: number[]
  /** 候选客户（调用方应把「产品当前已挂的客户」并进来，否则停用客户的归属会显示成 #id） */
  options: ProductCustomerRef[]
  placeholder?: string
  /** 勾一个客户就收起面板；要选多个就再点开一次。默认保持展开、连续勾选 */
  closeOnSelect?: boolean
}>(), {
  placeholder: '未挂客户 · 所有客户可见',
  closeOnSelect: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: number[]]
}>()

const rootRef = ref<HTMLElement | null>(null)
const fieldRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const open = ref(false)
const filter = ref('')

/** 面板上下留白；实际高度还要被视口剩余空间夹一次 */
const PANEL_GAP = 6
const PANEL_MAX_H = 320
const PANEL_MIN_H = 180

const panelStyle = ref<CSSProperties>({})

/**
 * 面板已 teleport 到 body，只能自己算坐标：贴着字段下沿，下方空间不够就翻到上方，
 * 并把高度夹在可用空间内 —— 否则窄视口下仍会被视口底边切掉。
 */
function placePanel() {
  const field = fieldRef.value
  if (!field) return
  const rect = field.getBoundingClientRect()
  const below = window.innerHeight - rect.bottom - PANEL_GAP
  const above = rect.top - PANEL_GAP
  const openUp = below < PANEL_MIN_H && above > below
  const maxHeight = Math.max(PANEL_MIN_H, Math.min(PANEL_MAX_H, openUp ? above : below))
  panelStyle.value = {
    left: `${Math.round(rect.left)}px`,
    width: `${Math.round(rect.width)}px`,
    top: openUp ? 'auto' : `${Math.round(rect.bottom + PANEL_GAP)}px`,
    bottom: openUp ? `${Math.round(window.innerHeight - rect.top + PANEL_GAP)}px` : 'auto',
    maxHeight: `${Math.round(maxHeight)}px`,
  }
}

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

/** 面板里点选项的入口：closeOnSelect 时选完就收起（多选靠再次点开字段） */
function selectOption(id: number) {
  toggleId(id)
  if (props.closeOnSelect) open.value = false
}

function togglePanel() {
  open.value = !open.value
  if (open.value) {
    filter.value = ''
    // 同一次微任务里定位，赶在浏览器绘制前完成，避免面板先闪一下再跳到正确位置
    nextTick(placePanel)
  }
}

function onDocumentMouseDown(e: MouseEvent) {
  if (!open.value) return
  const target = e.target as Node
  // 面板已 teleport 出 rootRef，必须单独判一次，否则点选项会被当成「点外部」关掉面板
  if (rootRef.value?.contains(target) || panelRef.value?.contains(target)) return
  open.value = false
}

/** 视口变化或任意祖先滚动都要跟着挪，否则面板会跟字段脱开 */
function onViewportChange() {
  if (open.value) placePanel()
}

onMounted(() => {
  document.addEventListener('mousedown', onDocumentMouseDown)
  window.addEventListener('resize', onViewportChange)
  // capture=true：弹窗内容区自身的滚动不会冒泡到 window，只能靠捕获阶段拿到
  window.addEventListener('scroll', onViewportChange, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocumentMouseDown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
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

/*
  坐标与最大高度由 placePanel() 内联给出；这里只管外观。
  z-index 2100 与 PrimeVue 浮层同档：项目自定义弹窗是 1050，
  低于 1050 的面板在弹窗里会「渲染了但看不见」。
*/
.pcs-panel {
  position: fixed;
  z-index: 2100;
  display: flex;
  flex-direction: column;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.10);
  overflow: hidden;
}
.pcs-search {
  flex: none;
  width: 100%; border: none; outline: none;
  padding: 9px 12px; font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  font-family: inherit;
}
.pcs-list { flex: 1; min-height: 0; overflow-y: auto; }
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
  flex: none;
  margin: 0; padding: 6px 12px; font-size: 11.5px;
  color: var(--color-text-muted, #94a3b8);
  background: var(--color-surface, #f8fafc);
}
</style>
