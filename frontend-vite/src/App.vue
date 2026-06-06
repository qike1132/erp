<template>
  <a href="#main-content" class="skip-link">跳到主内容</a>
  <router-view />
</template>

<style scoped>
.skip-link {
  position: absolute;
  top: -100%;
  left: 0;
  z-index: 99999;
  padding: 8px 16px;
  background: var(--color-ocean);
  color: white;
  font-weight: 700;
  font-size: 14px;
  border-radius: 0 0 8px 0;
  text-decoration: none;
  transition: top 0.2s ease;
}
.skip-link:focus-visible {
  top: 0;
}
</style>
