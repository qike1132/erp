<template>
  <div class="empty-state">
    <div class="empty-icon">
      <FontAwesomeIcon :icon="icon" aria-hidden="true" />
    </div>
    <h3 class="empty-title">{{ title }}</h3>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <slot />
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  icon?: string
  title?: string
  description?: string
}>(), {
  // 字符串会被 vue-fontawesome 解析为 {prefix:'fas', iconName}，
  // 只传图标名（由 fontAwesomeLoader 按需注册），不能带 "fas fa-" 类名前缀
  icon: 'inbox',
  title: '暂无数据',
  description: '',
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
  color: var(--color-text-secondary, #9ca3af);
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 8px;
  color: var(--color-text-primary, #374151);
}

.empty-desc {
  font-size: 13px;
  margin: 0 0 20px;
  max-width: 320px;
  line-height: 1.5;
}
</style>
