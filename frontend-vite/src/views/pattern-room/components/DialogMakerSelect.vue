<template>
  <div class="dms-row">
    <div ref="dropdownRef" class="dms-dropdown">
      <button
        type="button"
        class="dms-trigger"
        @click="dropdownOpen = !dropdownOpen"
      >
        <span>{{ selectedName || '-- 请选择 --' }}</span>
        <FontAwesomeIcon :icon="dropdownOpen ? 'chevron-up' : 'chevron-down'" aria-hidden="true" />
      </button>
      <div v-if="dropdownOpen" class="dms-options">
        <button
          type="button"
          :class="['dms-option', { active: patternMakerId === null }]"
          @click="selectMaker(null)"
        >
          <span>-- 请选择 --</span>
        </button>
        <div
          v-for="pm in patternMakers"
          :key="pm.id"
          :class="['dms-option', { active: patternMakerId === pm.id }]"
        >
          <button type="button" class="dms-option-name" :aria-label="pm.name" @click="selectMaker(pm.id)">
            <span>{{ pm.name }}</span>
          </button>
          <button
            type="button"
            class="dms-del"
            title="删除"
            @click.stop="onDeleteMaker(pm.id)"
          >
            <FontAwesomeIcon icon="times" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
    <button type="button" class="dms-add-btn" aria-label="添加版师" @click="addInputOpen = true">
      <FontAwesomeIcon icon="plus" aria-hidden="true" />
      添加版师
    </button>
  </div>
  <div v-if="addInputOpen" class="dms-add-row">
    <input
      v-model="addName"
      class="dms-add-input"
      placeholder="输入版师姓名"
      maxlength="100"
      @keyup.enter="confirmAdd"
    />
    <button type="button" class="dms-add-btn" aria-label="确定" @click="confirmAdd">
      确定
    </button>
    <button type="button" class="dms-cancel" aria-label="取消" @click="cancelAdd">
      取消
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { toast } from '@/composables/useToast'
import type { PatternMaker } from '@/api/patternMaker'

const props = defineProps<{
  patternMakers: PatternMaker[]
  patternMakerId: number | null
}>()

const emit = defineEmits<{
  'update:patternMakerId': [value: number | null]
  'add-pattern-maker': [name: string]
  'delete-pattern-maker': [id: number]
}>()

const dropdownOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)
const addInputOpen = ref(false)
const addName = ref('')

const selectedName = computed(() => {
  const pm = props.patternMakers.find((m) => m.id === props.patternMakerId)
  return pm?.name ?? ''
})

function selectMaker(id: number | null) {
  emit('update:patternMakerId', id)
  dropdownOpen.value = false
}

function onDeleteMaker(id: number) {
  emit('delete-pattern-maker', id)
  if (props.patternMakerId === id) {
    emit('update:patternMakerId', null)
  }
}

function onDocClick(e: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    dropdownOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})

function confirmAdd() {
  const name = addName.value.trim()
  if (!name) {
    toast.warning('请输入版师姓名')
    return
  }
  emit('add-pattern-maker', name)
  addName.value = ''
  addInputOpen.value = false
}

function cancelAdd() {
  addInputOpen.value = false
  addName.value = ''
}
</script>

<style scoped>
.dms-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dms-dropdown {
  position: relative;
  flex: 1;
  min-width: 0;
}
.dms-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  cursor: pointer;
  box-sizing: border-box;
}
.dms-trigger i {
  font-size: 10px;
  color: var(--color-text-secondary, #94a3b8);
  flex-shrink: 0;
  margin-left: 8px;
}
.dms-options {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  z-index: 50;
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
.dms-option {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0;
  border: none;
  background: #fff;
  transition: background 0.15s;
}
.dms-option:hover {
  background: var(--color-primary-50, #eff6ff);
}
.dms-option.active {
  background: var(--color-primary-100, #dbeafe);
}
.dms-option-name {
  flex: 1;
  min-width: 0;
  padding: 8px 12px;
  border: none;
  background: transparent;
  text-align: left;
  font-size: 13px;
  font-family: inherit;
  color: var(--color-text-primary);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dms-del {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: 4px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.15s ease;
}
.dms-del:hover {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-500, #ef4444);
}
.dms-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px dashed var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  align-self: flex-start;
  transition: all 0.15s ease;
}
.dms-add-btn:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.dms-add-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.dms-add-input {
  flex: 1;
  min-width: 0;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  box-sizing: border-box;
}
.dms-add-input:focus {
  border-color: var(--color-primary-500);
}
.dms-cancel {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  transition: all 0.15s ease;
}
.dms-cancel:hover {
  border-color: var(--color-danger-300, #fca5a5);
  color: var(--color-danger-500, #ef4444);
  background: var(--color-danger-50, #fef2f2);
}
</style>