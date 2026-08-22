<template>
  <div class="pjf-maker-row">
    <div ref="makerDropdownRef" class="pjf-maker-dropdown">
      <button
        type="button"
        class="pjf-select pjf-maker-trigger"
        @click="makerDropdownOpen = !makerDropdownOpen"
      >
        <span>{{ selectedMakerName || '-- 请选择 --' }}</span>
        <FontAwesomeIcon :icon="makerDropdownOpen ? 'chevron-up' : 'chevron-down'" aria-hidden="true" />
      </button>
      <div v-if="makerDropdownOpen" class="pjf-maker-options">
        <button
          type="button"
          :class="['pjf-maker-option', { active: patternMakerId === null }]"
          @click="emit('select', null)"
        >
          <span>-- 请选择 --</span>
        </button>
        <div
          v-for="pm in patternMakers"
          :key="pm.id"
          :class="['pjf-maker-option', { active: patternMakerId === pm.id }]"
        >
          <button type="button" class="pjf-maker-option-name" :aria-label="pm.name" @click="emit('select', pm.id)">
            <span>{{ pm.name }}</span>
          </button>
          <button
            type="button"
            class="pjf-maker-del"
            title="删除"
            @click.stop="emit('delete', pm.id)"
          >
            <FontAwesomeIcon icon="times" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
    <button type="button" class="pjf-role-add" aria-label="添加版师" @click="addMakerInputOpen = true">
      <FontAwesomeIcon icon="plus" aria-hidden="true" />
      添加版师
    </button>
  </div>
  <div v-if="addMakerInputOpen" class="pjf-maker-add-row">
    <input
      v-model="addMakerName"
      class="pjf-input pjf-maker-add-input"
      placeholder="输入版师姓名"
      maxlength="100"
      @keyup.enter="confirmAddMaker"
    />
    <button type="button" class="pjf-role-add" aria-label="确定" @click="confirmAddMaker">
      确定
    </button>
    <button type="button" class="pjf-maker-cancel" aria-label="取消" @click="cancelAddMaker">
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
  select: [id: number | null]
  delete: [id: number]
  'add-maker': [name: string]
}>()

const makerDropdownOpen = ref(false)
const makerDropdownRef = ref<HTMLElement | null>(null)
const selectedMakerName = computed(() => {
  const pm = props.patternMakers.find((m) => m.id === props.patternMakerId)
  return pm?.name ?? ''
})

const addMakerInputOpen = ref(false)
const addMakerName = ref('')

function onDocClick(e: MouseEvent) {
  if (makerDropdownRef.value && !makerDropdownRef.value.contains(e.target as Node)) {
    makerDropdownOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})

function confirmAddMaker() {
  const name = addMakerName.value.trim()
  if (!name) {
    toast.warning('请输入版师姓名')
    return
  }
  emit('add-maker', name)
  addMakerName.value = ''
  addMakerInputOpen.value = false
}

function cancelAddMaker() {
  addMakerInputOpen.value = false
  addMakerName.value = ''
}
</script>

<style scoped>
.pjf-maker-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pjf-maker-select {
  flex: 1;
  min-width: 0;
}
.pjf-maker-add-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.pjf-maker-add-input {
  flex: 1;
  min-width: 0;
}
.pjf-maker-cancel {
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
.pjf-maker-cancel:hover {
  border-color: var(--color-danger-300, #fca5a5);
  color: var(--color-danger-500, #ef4444);
  background: var(--color-danger-50, #fef2f2);
}
.pjf-maker-dropdown {
  position: relative;
  flex: 1;
  min-width: 0;
}
.pjf-maker-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  cursor: pointer;
}
.pjf-maker-trigger i {
  font-size: 10px;
  color: var(--color-text-secondary, #94a3b8);
  flex-shrink: 0;
  margin-left: 8px;
}
.pjf-maker-options {
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
.pjf-maker-option {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 0;
  border: none;
  background: #fff;
  transition: background 0.15s;
}
.pjf-maker-option:hover {
  background: var(--color-primary-50, #eff6ff);
}
.pjf-maker-option.active {
  background: var(--color-primary-100, #dbeafe);
}
.pjf-maker-option-name {
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
.pjf-maker-del {
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
.pjf-maker-del:hover {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-500, #ef4444);
}
.pjf-role-add {
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
.pjf-role-add:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.pjf-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.pjf-input:focus {
  border-color: var(--color-primary-500);
}
.pjf-select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.pjf-select:focus {
  border-color: var(--color-primary-500);
}
</style>