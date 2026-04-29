<template>
  <div class="settings-page">
    <UiPageHeader>系统设置<template #description>系统参数与偏好设置</template></UiPageHeader>
    <UiCard>
      <template #header>
        <span class="font-semibold">系统信息</span>
      </template>
      <UiDescriptions
        :rows="[
          { label: '系统版本', key: 'version', value: '1.4.91' },
          { label: '前端框架', key: 'framework', value: 'Vue 3 + Vite' },
          { label: 'UI 组件库', key: 'ui', value: 'Reka UI + Tailwind CSS 4' },
          { label: '后端框架', key: 'backend', value: 'FastAPI' },
        ]"
      />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import UiCard from '@/components/ui/UiCard.vue'
import UiDescriptions from '@/components/ui/UiDescriptions.vue'
</script>
