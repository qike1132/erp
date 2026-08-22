<template>
  <div class="m-login">
    <!-- 顶部环境光 -->
    <div class="m-login-ambient" aria-hidden="true" />

    <!-- 品牌区 -->
    <header class="m-login-brand">
      <div class="m-login-logo">
        <img loading="lazy" src="/logo_plush.png" alt="滨发协同" width="96" height="96" />
      </div>
      <h1 class="m-login-title">滨发协同</h1>
      <p class="m-login-sub">Binfa Collaboration System</p>
      <p class="m-login-tagline">专业的毛绒玩具供应链协同平台</p>
    </header>

    <!-- 表单卡片 -->
    <form class="m-login-card" @submit.prevent="handleLogin">
      <div class="m-field">
        <label class="m-field-label" for="m-username">用户名</label>
        <div class="m-field-control">
          <input
            id="m-username"
            v-model.trim="form.username"
            type="text"
            placeholder="请输入用户名"
            autocomplete="username"
            inputmode="text"
            :disabled="loading"
          />
        </div>
      </div>

      <div class="m-field">
        <label class="m-field-label" for="m-password">密码</label>
        <div class="m-field-control">
          <input
            id="m-password"
            v-model="form.password"
            :type="showPassword ? 'text' : 'password'"
            class="m-input-password"
            placeholder="请输入密码"
            autocomplete="current-password"
            :disabled="loading"
          />
          <button
            type="button"
            class="m-eye"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <svg v-if="showPassword" viewBox="0 0 24 24" width="20" height="20" fill="none">
              <path d="M3 3l18 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
              <path
                d="M10.6 5.1A10.9 10.9 0 0 1 12 5c5 0 8.6 4.1 9.6 5.6.3.4.3.9 0 1.3-.5.7-1.6 2-3.1 3M6.6 6.6C4.3 8 2.9 9.9 2.4 10.6c-.3.4-.3.9 0 1.3C3.4 13.4 7 17.5 12 17.5c1.4 0 2.6-.3 3.7-.8"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
              />
              <path
                d="M9.9 9.9a2.8 2.8 0 0 0 4 4"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
              />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="none">
              <path
                d="M2.4 11.6C3.4 10.1 7 6 12 6s8.6 4.1 9.6 5.6c.3.4.3.9 0 1.3C20.6 14.4 17 18.5 12 18.5S3.4 14.4 2.4 12.9a.9.9 0 0 1 0-1.3Z"
                stroke="currentColor"
                stroke-width="1.8"
              />
              <circle cx="12" cy="12" r="2.8" stroke="currentColor" stroke-width="1.8" />
            </svg>
          </button>
        </div>
      </div>

      <label class="m-remember">
        <input v-model="form.remember" type="checkbox" class="m-remember-input" />
        <span class="m-switch" aria-hidden="true" />
        <span class="m-remember-text">记住账号</span>
      </label>

      <p v-if="errorMsg" class="m-error" role="alert">{{ errorMsg }}</p>

      <button type="submit" class="m-submit" :disabled="loading || !form.username || !form.password">
        <template v-if="loading">
          <span class="m-spinner" aria-hidden="true" />
          登录中…
        </template>
        <template v-else>登 录</template>
      </button>
    </form>

    <!-- 底部信息 -->
    <footer class="m-login-footer">
      <span>v2.0</span>
      <span class="m-dot">·</span>
      <span>内部系统</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useLogin } from '@/views/login/useLogin'

const { loading, showPassword, errorMsg, form, handleLogin } = useLogin()
</script>

<style scoped>
.m-login {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 100vh;
  min-height: 100dvh;
  padding: calc(var(--m-safe-top) + 32px) 24px calc(var(--m-safe-bottom) + 24px);
  overflow: hidden;
  background: var(--m-bg-deep);
  box-sizing: border-box;
}

/* 顶部环境光：Apple 式极淡蓝白氛围 */
.m-login-ambient {
  position: absolute;
  top: -200px;
  left: 50%;
  transform: translateX(-50%);
  width: 520px;
  height: 420px;
  background: radial-gradient(
    closest-side,
    rgba(0, 113, 227, 0.10),
    rgba(41, 151, 255, 0.05) 55%,
    transparent 100%
  );
  pointer-events: none;
}

/* ========== 品牌区 ========== */
.m-login-brand {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 36px;
  animation: m-login-rise 0.6s var(--m-ease-out) both;
}

.m-login-logo {
  animation: m-login-scale 0.5s var(--m-ease-out) both;
}

.m-login-logo img {
  display: block;
  width: 96px;
  height: 96px;
  border-radius: 24px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.10), 0 2px 6px rgba(0, 0, 0, 0.06);
}

.m-login-title {
  margin: 20px 0 0;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.8px;
  color: var(--m-text-primary);
}

.m-login-sub {
  margin: 6px 0 0;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.2px;
  color: var(--m-text-tertiary);
}

.m-login-tagline {
  margin: 14px 0 0;
  font-size: 14px;
  color: var(--m-text-secondary);
}

/* ========== 表单卡片（毛玻璃） ========== */
.m-login-card {
  position: relative;
  padding: 24px 20px 20px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: var(--m-shadow-card-hover);
  backdrop-filter: var(--m-blur-card);
  -webkit-backdrop-filter: var(--m-blur-card);
  animation: m-login-rise 0.6s var(--m-ease-out) 0.08s both;
}

.m-field {
  margin-bottom: 16px;
}

.m-field-label {
  display: block;
  margin: 0 0 8px 4px;
  font-size: var(--m-font-label-sm);
  font-weight: var(--m-font-weight-semibold);
  color: var(--m-text-secondary);
}

.m-field-control {
  position: relative;
}

.m-field-control input {
  width: 100%;
  height: 52px;
  padding: 0 16px;
  font-size: var(--m-font-body-lg);
  font-family: inherit;
  color: var(--m-text-primary);
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 14px;
  outline: none;
  box-sizing: border-box;
  -webkit-appearance: none;
  transition: border-color 0.2s var(--m-ease-smooth), box-shadow 0.2s var(--m-ease-smooth);
}

.m-field-control input:focus {
  border-color: var(--m-accent);
  box-shadow: 0 0 0 4px var(--m-accent-glow);
}

.m-field-control input:disabled {
  opacity: 0.6;
}

.m-field-control input.m-input-password {
  padding-right: 52px;
}

.m-eye {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: 12px;
  color: var(--m-text-tertiary);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.m-eye:active {
  background: var(--m-bg-card-alt);
}

/* ========== 记住账号（iOS 开关） ========== */
.m-remember {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 2px 18px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
}

.m-remember-input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.m-switch {
  position: relative;
  width: 44px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 13px;
  background: #e9e9eb;
  transition: background 0.25s var(--m-ease-out);
}

.m-switch::after {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  transition: transform 0.25s var(--m-ease-out);
}

.m-remember-input:checked + .m-switch {
  background: var(--m-accent);
}

.m-remember-input:checked + .m-switch::after {
  transform: translateX(18px);
}

.m-remember-text {
  font-size: var(--m-font-title-sm);
  color: var(--m-text-secondary);
}

/* ========== 错误提示 ========== */
.m-error {
  margin: 0 0 14px;
  padding: 10px 14px;
  font-size: var(--m-font-body-sm);
  color: var(--m-accent-red);
  background: var(--m-error-light);
  border-radius: 12px;
  text-align: center;
}

/* ========== 登录按钮 ========== */
.m-submit {
  width: 100%;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 17px;
  font-weight: var(--m-font-weight-semibold);
  font-family: inherit;
  color: #ffffff;
  background: linear-gradient(180deg, #0077ed 0%, #0066d6 100%);
  border: none;
  border-radius: 16px;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(0, 113, 227, 0.28);
  transition: transform 0.12s var(--m-ease-smooth), opacity 0.2s var(--m-ease-smooth);
}

.m-submit:active:not(:disabled) {
  transform: scale(0.98);
}

.m-submit:disabled {
  opacity: 0.5;
  cursor: default;
}

.m-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: m-spin 0.7s linear infinite;
}

@keyframes m-spin {
  to { transform: rotate(360deg); }
}

/* ========== 底部信息 ========== */
.m-login-footer {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  margin-top: 28px;
  font-size: var(--m-font-label-sm);
  color: var(--m-text-tertiary);
  animation: m-login-rise 0.6s var(--m-ease-out) 0.16s both;
}

.m-dot {
  opacity: 0.5;
}

/* ========== 入场动效 ========== */
@keyframes m-login-rise {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes m-login-scale {
  from { opacity: 0; transform: scale(0.85); }
  to { opacity: 1; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .m-login-brand,
  .m-login-logo,
  .m-login-card,
  .m-login-footer {
    animation: none;
  }
}
</style>
