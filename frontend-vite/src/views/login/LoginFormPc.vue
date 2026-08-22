<template>
  <div class="login-container">
    <LoginBrandSection />
    <LoginFormCard
      v-model:show-password="showPassword"
      :loading="loading"
      :error-msg="errorMsg"
      v-model:form="form"
      :handle-login="handleLogin"
    />
  </div>
</template>

<script setup lang="ts">
import LoginBrandSection from './components/LoginBrandSection.vue'
import LoginFormCard from './components/LoginFormCard.vue'
import { useLogin } from './useLogin'

const { loading, showPassword, errorMsg, form, handleLogin } = useLogin()
</script>

<style scoped>
.login-container {
  --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.06);
  --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.08);
  --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.1);
  --shadow-xl: 0 16px 48px rgba(0, 0, 0, 0.12);

  display: flex;
  width: 100%;
  min-height: 100vh;
  background: var(--color-surface);
  overflow-x: hidden;
}

@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
  }
}
</style>
