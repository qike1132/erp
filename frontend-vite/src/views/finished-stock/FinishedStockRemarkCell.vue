<template>
  <!-- 备注行内编辑：默认显示文本（空则虚位），点击变输入框，回车/保存按钮提交，Esc 取消 -->
  <div class="fr-cell">
    <template v-if="editing">
      <input
        ref="inputRef"
        v-model="draft"
        class="fr-input"
        placeholder="点击填写备注"
        autocomplete="off"
        @keydown.enter="onEnter"
        @keydown.esc="onEsc"
      />
      <span v-if="saving" class="fr-saving">保存中…</span>
      <template v-else>
        <button class="fr-ok" @click="emit('save', draft)">保存</button>
        <button class="fr-cancel" @click="cancel">取消</button>
      </template>
    </template>
    <button v-else class="fr-view" @click="startEdit">{{ remark || '点击填写' }}</button>
  </div>
</template>

<script setup lang="ts">
/**
 * FinishedStockRemarkCell.vue — 成品库存页「备注」单元格（行内可编辑）。
 *
 * 从 FinishedStockView 抽出：编辑态/草稿/保存中都在本组件内维护，父级只关心
 * save 事件（拿到最终文本）。父级按 row-key 控制哪一行在编辑（editing）。
 */
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  /** 当前行备注（已保存值） */
  remark: string
  /** 本行是否处于编辑态（父级按 row-key 控制，保证同时只有一行在编辑） */
  editing: boolean
  /** 保存中（禁用重复提交） */
  saving: boolean
}>()

const emit = defineEmits<{
  /** 开始编辑（父级据此把 editingKey 指向本行） */
  'start': []
  /** 取消编辑（父级清 editingKey） */
  'cancel': []
  /** 保存：参数为最终文本 */
  'save': [text: string]
}>()

const draft = ref(props.remark || '')
const inputRef = ref<HTMLInputElement | null>(null)

// 进入编辑态时用最新已存值重置草稿；退出时丢弃（取消语义）。
watch(() => props.editing, (on) => {
  if (on) {
    draft.value = props.remark || ''
    // 自动聚焦：原按钮被移除后焦点会落回文档，不聚焦的话用户得再点一次输入框
    nextTick(() => inputRef.value?.focus())
  }
})

function startEdit() {
  emit('start')
}

function cancel() {
  emit('cancel')
}

/**
 * 2026-10-17 审计 AUD-17：中文输入法选词回车会触发 keyup.enter ——
 * Vue 的按键修饰符不过滤 IME 组合态，导致备注被存成半截拼音串。
 * keydown 在组合期 isComposing=true（部分浏览器 keyCode=229），此时必须忽略。
 */
function onEnter(e: KeyboardEvent) {
  if (e.isComposing || e.keyCode === 229) return
  emit('save', draft.value)
}

function onEsc(e: KeyboardEvent) {
  if (e.isComposing || e.keyCode === 229) return
  cancel()
}
</script>

<style scoped>
.fr-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fr-view {
  flex: 1; min-width: 0; text-align: left; padding: 4px 8px; border: 1px solid transparent;
  border-radius: 8px; background: transparent; font-family: inherit; font-size: 12.5px;
  color: var(--color-text); cursor: text; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.fr-view:hover { border-color: var(--color-border); background: var(--color-surface); }
.fr-input {
  flex: 1; min-width: 0; padding: 4px 8px; border: 1.5px solid var(--color-primary-500);
  border-radius: 8px; font-family: inherit; font-size: 12.5px; color: var(--color-text);
  background: var(--color-surface-card); outline: none;
}
.fr-input::placeholder { color: var(--color-text-placeholder); }
.fr-ok, .fr-cancel {
  flex-shrink: 0; padding: 4px 10px; border-radius: 8px; font-size: 12px; font-weight: 600;
  font-family: inherit; cursor: pointer; white-space: nowrap;
}
.fr-ok { border: 1.5px solid var(--color-primary-600); background: var(--color-primary-600); color: var(--color-text-inverse); }
.fr-cancel { border: 1.5px solid var(--color-border); background: var(--color-surface-card); color: var(--color-text-secondary); }
.fr-saving { flex-shrink: 0; font-size: 12px; color: var(--color-text-muted); white-space: nowrap; }
</style>
