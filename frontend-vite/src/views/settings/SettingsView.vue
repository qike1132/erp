<template>
  <div class="settings-page">
    <UiPageHeader>系统设置<template #description>系统参数与偏好设置</template></UiPageHeader>
    <UiCard>
      <template #header>
        <span class="font-semibold">系统信息</span>
      </template>
      <UiDescriptions
        :rows="[
          { label: '系统版本', key: 'version', value: APP_VERSION },
          { label: '前端框架', key: 'framework', value: 'Vue 3 + Vite' },
          { label: 'UI 组件库', key: 'ui', value: 'Reka UI + Tailwind CSS 4' },
          { label: '后端框架', key: 'backend', value: 'FastAPI' },
        ]"
      />
      <p class="settings-empty">
        本页暂无可配置项。备份路径与计划在「数据备份」页维护。
      </p>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import UiCard from '@/components/ui/UiCard.vue'
import UiDescriptions from '@/components/ui/UiDescriptions.vue'
import { APP_VERSION } from '@/constants/brand'
</script>

<style scoped>
/* 说明文案：此前整页只有硬编码版本号，用户进来找不到任何可改项也无任何说明 */
.settings-empty {
  margin: 16px 0 0;
  color: var(--color-text-secondary, #64748b);
  font-size: 13px;
}
</style>
