<template>
  <div class="sb-search">
    <span class="sb-search-icon" aria-hidden="true"></span>
    <input
      v-model="model"
      type="text"
      class="sb-search-input"
      placeholder="搜索菜单..."
      aria-label="搜索菜单"
    />
  </div>
</template>

<script setup lang="ts">
const model = defineModel<string>({ default: '' })
</script>

<style scoped>
.sb-search {
  position: relative;
  margin-bottom: 12px;
}

.sb-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px 8px 34px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  font-size: 13px;
  color: var(--color-text);
  background: var(--color-surface);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.sb-search-input::placeholder {
  color: var(--color-text-tertiary);
}

.sb-search-input:focus {
  border-color: var(--color-primary-300);
  box-shadow: 0 0 0 3px var(--color-primary-50);
}

.sb-search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 13px;
  height: 13px;
  border: 2px solid var(--color-text-secondary);
  border-radius: 50%;
  pointer-events: none;
}

.sb-search-icon::after {
  content: '';
  position: absolute;
  width: 7px;
  height: 2px;
  background: var(--color-text-secondary);
  right: -5px;
  bottom: -2px;
  transform: rotate(45deg);
  border-radius: 2px;
}
</style>