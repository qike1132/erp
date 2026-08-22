<template>
  <div class="nc-header">
    <div class="nc-header-left">
      <button class="nc-back-btn" :aria-label="'返回上一页'" @click="goBack">
        <FontAwesomeIcon icon="arrow-left" aria-hidden="true" />
      </button>
      <div class="nc-title-group">
        <h1 class="nc-title">通知中心</h1>
        <span v-if="unreadCount > 0" class="nc-title-badge">{{ unreadCount }} 条未读</span>
      </div>
    </div>
    <div class="nc-header-right">
      <button
        class="nc-btn nc-btn--ghost"
        :disabled="marking || unreadCount === 0"
        @click="handleMarkAll"
      >
        <FontAwesomeIcon icon="check-double" aria-hidden="true" />
        <span>全部已读</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * NotificationHeaderBar.vue — 通知中心页头
 *
 * 从 NotificationCenterView.vue 拆出：返回按钮 + 标题 + 未读徽章 + 全部已读按钮。
 */
defineProps<{
  /** 未读通知数（标题徽章 + 全部已读按钮可用态） */
  unreadCount: number
  /** 批量已读操作进行中（禁用全部已读按钮） */
  marking: boolean
}>()

const emit = defineEmits<{
  /** 返回上一页 */
  back: []
  /** 全部已读 */
  markAll: []
}>()

/** 返回上一页：交给父组件处理导航 */
function goBack() {
  emit('back')
}

/** 全部已读：交给父组件执行 */
function handleMarkAll() {
  emit('markAll')
}
</script>

<style scoped>
/* ============ 头部 ============ */
.nc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 24px;
  background: linear-gradient(135deg, rgba(91, 141, 239, 0.04) 0%, rgba(176, 224, 230, 0.06) 100%);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.nc-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.nc-back-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-button);
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-card);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 15px;
  transition: all var(--transition-fast, 0.2s ease);
  flex-shrink: 0;
}

.nc-back-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
  transform: translateX(-2px);
}

.nc-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.nc-title {
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--color-heading);
  letter-spacing: -0.01em;
  white-space: nowrap;
  margin: 0;
}

.nc-title-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-danger-600);
  background: var(--color-danger-50);
  border: 1px solid var(--color-danger-200);
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.nc-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ============ 按钮 ============ */
.nc-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius-button);
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  white-space: nowrap;
}

.nc-btn--ghost {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border: 1px solid var(--color-primary-100);
}

.nc-btn--ghost:hover:not(:disabled) {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

.nc-btn--ghost:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  background: transparent;
  border-color: transparent;
}

/* ============ 响应式：移动端 ============ */
@media (max-width: 767px) {
  .nc-header {
    padding: 14px 16px;
  }

  .nc-title {
    font-size: 1.1rem;
  }

  .nc-btn--ghost span {
    display: none;
  }

  .nc-btn--ghost {
    padding: 8px 12px;
  }
}

@media (max-width: 480px) {
  .nc-header {
    padding: 10px 12px;
  }

  .nc-title {
    font-size: 1rem;
  }

  .nc-back-btn {
    width: 36px;
    height: 36px;
  }
}
</style>
