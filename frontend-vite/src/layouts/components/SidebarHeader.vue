<template>
  <div class="sb-header">
    <router-link to="/dashboard" class="sb-logo">
      <img loading="lazy" src="/logo_plush.png" alt="东莞玩具" width="70" height="70" />
      <div v-if="!collapsed" class="sb-logo-text">
        <div class="sb-logo-title">滨发协同系统</div>
        <div class="sb-logo-subtitle">供应链管理平台 v2.0</div>
      </div>
    </router-link>
  </div>
</template>

<script setup lang="ts">
defineProps<{ collapsed: boolean }>()
</script>

<style scoped>
.sb-header {
  padding: 24px 20px 18px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.sb-logo {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 0;
  text-decoration: none;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.sb-logo:hover {
  opacity: 0.8;
}

.sb-logo img {
  width: 70px;
  height: 70px;
  border-radius: 13px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.sb-logo-text {
  min-width: 0;
}

.sb-logo-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.3;
}

.sb-logo-subtitle {
  font-size: 11px;
  color: var(--color-text-secondary);
  font-weight: 500;
  line-height: 1.4;
}
</style>