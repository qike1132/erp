<template>
  <div class="dre-roles">
    <div v-for="(role, idx) in modelValue" :key="idx" class="dre-role-row">
      <input
        v-model="modelValue[idx]"
        class="dre-role-input"
        placeholder="角色名称"
        maxlength="100"
      />
      <button
        v-if="modelValue.length > 1"
        type="button"
        class="dre-role-remove"
        title="移除"
        @click="modelValue.splice(idx, 1)"
      >
        <FontAwesomeIcon icon="times" aria-hidden="true" />
      </button>
    </div>
    <button type="button" class="dre-add-btn" aria-label="添加角色" @click="modelValue.push('')">
      <FontAwesomeIcon icon="plus" aria-hidden="true" />
      添加角色
    </button>
  </div>
</template>

<script setup lang="ts">
const modelValue = defineModel<string[]>({ default: () => [''] })
</script>

<style scoped>
.dre-roles {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dre-role-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dre-role-input {
  flex: 1;
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
.dre-role-input:focus {
  border-color: var(--color-primary-500);
}
.dre-role-remove {
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
.dre-role-remove:hover {
  background: var(--color-danger-50, #fef2f2);
  border-color: var(--color-danger-300, #fca5a5);
}
.dre-add-btn {
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
.dre-add-btn:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
</style>