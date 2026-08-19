<template>
  <div class="pjf-roles">
    <div v-for="(_, idx) in roleNames" :key="idx" class="pjf-role-row">
      <input
        v-model="roleNames[idx]"
        class="pjf-input pjf-role-input"
        placeholder="角色名称"
        maxlength="100"
      />
      <button
        v-if="roleNames.length > 1"
        type="button"
        class="pjf-role-remove"
        title="移除"
        @click="roleNames.splice(idx, 1)"
      >
        <i class="fas fa-times" aria-hidden="true" />
      </button>
    </div>
    <button type="button" class="pjf-role-add" @click="roleNames.push('')" aria-label="添加角色">
      <i class="fas fa-plus" aria-hidden="true" />
      添加角色
    </button>
  </div>
</template>

<script setup lang="ts">
const roleNames = defineModel<string[]>('roleNames', { required: true })
</script>

<style scoped>
.pjf-roles {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pjf-role-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pjf-role-input {
  flex: 1;
}
.pjf-role-remove {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  color: var(--color-danger-500, #ef4444);
  cursor: pointer;
  font-size: 11px;
  transition: all 0.15s ease;
}
.pjf-role-remove:hover {
  background: var(--color-danger-50, #fef2f2);
  border-color: var(--color-danger-300, #fca5a5);
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
</style>