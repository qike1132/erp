<template>
  <div v-if="roles.length > 0" class="role-tabs">
    <div
      v-for="role in roles"
      :key="role.id"
      :class="['role-tab', { 'role-tab--active': role.id === currentRoleId }]"
      @click="$emit('select', role.id)"
    >
      <span class="role-tab-name">
        {{ role.role_name }}
        <i v-if="role.is_default" class="fas fa-thumbtack role-tab-pin" aria-label="默认角色" title="默认角色" />
      </span>
      <button
        v-if="canManage && !role.is_default"
        type="button"
        class="role-tab-close"
        title="删除角色"
        @click.stop="$emit('remove', role)"
      >
        <i class="fas fa-times" aria-hidden="true" />
      </button>
    </div>
    <button
      v-if="canManage"
      type="button"
      class="role-tab-add"
      title="新增角色"
      @click="onAddClick"
    >
      <i class="fas fa-plus" aria-hidden="true" />
    </button>

    <!-- 新增角色内联输入 -->
    <div v-if="adding" class="role-tab-input-wrap" @click.stop>
      <input
        ref="inputEl"
        v-model="newName"
        class="role-tab-input"
        placeholder="角色名称"
        maxlength="100"
        @keydown.enter="onAddConfirm"
        @keydown.esc="onAddCancel"
        @blur="onAddConfirm"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import type { RoleBrief } from '@/api/patternRoom'

const props = defineProps<{
  roles: RoleBrief[]
  currentRoleId: number | null
  canManage: boolean
}>()

const emit = defineEmits<{
  'select': [roleId: number]
  'add': [roleName: string]
  'remove': [role: RoleBrief]
}>()

const adding = ref(false)
const newName = ref('')
const inputEl = ref<HTMLInputElement | null>(null)

async function onAddClick() {
  adding.value = true
  newName.value = ''
  await nextTick()
  inputEl.value?.focus()
}

function onAddConfirm() {
  const name = newName.value.trim()
  if (name) {
    emit('add', name)
  }
  adding.value = false
  newName.value = ''
}

function onAddCancel() {
  adding.value = false
  newName.value = ''
}

// adding 关闭时清空输入（兜底）
watch(adding, (v) => {
  if (!v) newName.value = ''
})
</script>

<style scoped>
.role-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  flex-wrap: wrap;
}

.role-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}

.role-tab:hover {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}

.role-tab--active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #3b82f6), var(--color-primary-600, #2563eb));
  border-color: var(--color-primary-600, #2563eb);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.25);
}

.role-tab--active:hover {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-600, #2563eb), var(--color-primary-700, #1d4ed8));
}

.role-tab-name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.role-tab-pin {
  font-size: 9px;
  opacity: 0.7;
}

.role-tab-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  border-radius: 50%;
  font-size: 10px;
  opacity: 0.6;
  transition: all 0.15s ease;
}

.role-tab-close:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.25);
}

.role-tab--active .role-tab-close:hover {
  background: rgba(255, 255, 255, 0.3);
}

.role-tab-add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px dashed var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 11px;
}

.role-tab-add:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}

.role-tab-input-wrap {
  display: inline-flex;
  align-items: center;
}

.role-tab-input {
  width: 120px;
  padding: 6px 10px;
  border: 1px solid var(--color-primary-400, #60a5fa);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  box-shadow: 0 0 0 2px var(--color-primary-100, #dbeafe);
}
</style>
