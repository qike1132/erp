<template>
  <div class="bk-section">
    <div class="bk-section-label">备份方式</div>
    <div class="bk-mode-switch">
      <button
        :class="['bk-mode-btn', modelValue === 'custom' ? 'bk-mode-active' : '']"
        @click="emit('change', 'custom')"
      >
        <FontAwesomeIcon icon="file-download" />
        <span>自定义路径</span>
        <small>下载到本地</small>
      </button>
      <button
        :class="['bk-mode-btn', modelValue === 'default' ? 'bk-mode-active' : '']"
        @click="emit('change', 'default')"
      >
        <FontAwesomeIcon icon="server" />
        <span>默认路径</span>
        <small>保存到服务器</small>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ modelValue: 'custom' | 'default' }>()

const emit = defineEmits<{ 'change': [mode: 'custom' | 'default'] }>()
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }
.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.bk-mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.bk-mode-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 12px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: white;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
}
.bk-mode-btn span {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}
.bk-mode-btn small {
  font-size: 11px;
  color: var(--color-text-muted);
}
.bk-mode-btn i {
  font-size: 18px;
  color: var(--color-text-muted);
  transition: color 0.3s ease;
}
.bk-mode-btn:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}
.bk-mode-btn:hover i {
  color: var(--color-primary-500);
}
.bk-mode-active {
  border-color: var(--color-primary-400);
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  box-shadow: var(--shadow-sm);
}
.bk-mode-active i {
  color: var(--color-primary-600);
}
.bk-mode-active span {
  color: var(--color-primary-700);
}
</style>