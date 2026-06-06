<template>
  <!-- ═══ Capacitor 移动端：Apple 极简登录 ═══ -->
  <div v-if="isCapacitor" class="m-login-page">
    <div class="m-login-logo-area">
      <img class="m-login-logo" src="/logo_plush.png" alt="滨发协同系统" />
      <div class="m-login-title">滨发协同系统</div>
      <div class="m-login-sub">Binfa Collaboration System</div>
    </div>

    <div class="m-login-form-area">
      <form @submit.prevent="handleLogin">
        <div class="m-login-field">
          <label>用户名</label>
          <input
            v-model="form.username"
            type="text"
            placeholder="请输入用户名"
            autocomplete="username"
            required
          />
        </div>
        <div class="m-login-field">
          <label>密码</label>
          <div class="m-login-pwd-wrapper">
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              placeholder="请输入密码"
              autocomplete="current-password"
              required
            />
            <button
              class="m-login-pwd-toggle"
              type="button"
              aria-label="切换密码可见性"
              @click="showPassword = !showPassword"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path v-if="!showPassword" d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle v-if="!showPassword" cx="12" cy="12" r="3" />
                <path v-if="showPassword" d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                <path v-if="showPassword" d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                <line v-if="showPassword" x1="1" y1="1" x2="23" y2="23" />
              </svg>
            </button>
          </div>
        </div>
        <div v-if="errorMsg" class="m-login-error-msg show">{{ errorMsg }}</div>
        <div class="m-login-btn-area">
          <button type="submit" class="m-login-btn" :disabled="loading">
            <span v-if="!loading">登录</span>
            <span v-else class="m-login-spinner"></span>
          </button>
        </div>
      </form>
    </div>

    <div class="m-login-footer">滨发玩具供应链管理系统</div>
  </div>

  <!-- ═══ PC 端：原有左右分栏登录 ═══ -->
  <div v-else class="login-container">
    <div class="brand-section">
      <div class="brand-content">
        <div class="logo-wrapper">
          <div class="logo-frame">
            <img src="/logo_plush.png" alt="滨发玩具" />
          </div>
        </div>

        <div class="brand-info">
          <h1 class="brand-title">滨发玩具协同系统</h1>
          <p class="brand-tagline">专业的毛绒玩具企业供应链管理平台<br />智能、高效、可靠的数字化管理解决方案</p>
        </div>

        <div class="feature-cards">
          <div class="feature-card">
            <div class="feature-icon-wrap">
              <i class="fas fa-box" style="font-size: 28px" aria-hidden="true" />
            </div>
            <div class="feature-text">
              <div class="feature-title">智能库存管理</div>
              <div class="feature-desc">实时追踪库存动态，精准预测需求</div>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon-wrap">
              <i class="fas fa-file-lines" style="font-size: 28px" aria-hidden="true" />
            </div>
            <div class="feature-text">
              <div class="feature-title">高效订单处理</div>
              <div class="feature-desc">自动化流程，提升运营效率</div>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon-wrap">
              <i class="fas fa-chart-line" style="font-size: 28px" aria-hidden="true" />
            </div>
            <div class="feature-text">
              <div class="feature-title">实时数据分析</div>
              <div class="feature-desc">可视化报表，洞察业务趋势</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="login-section">
      <div class="login-card">
        <div class="login-card-header">
          <h2 class="login-heading">欢迎登录</h2>
          <p class="login-subheading">请输入您的账号信息以访问系统</p>
        </div>

        <form class="login-form" @submit.prevent="handleLogin">
          <div class="form-group">
            <label class="form-label">用户名</label>
            <div class="input-wrapper">
              <i class="fas fa-user input-prefix-icon" aria-hidden="true" />
              <input
                v-model="form.username"
                type="text"
                name="username"
                placeholder="请输入用户名"
                autocomplete="username"
                required
                class="form-input with-prefix"
              />
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">密码</label>
            <div class="input-wrapper">
              <i class="fas fa-lock input-prefix-icon" aria-hidden="true" />
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                name="password"
                placeholder="请输入密码"
                autocomplete="current-password"
                required
                class="form-input with-prefix with-suffix"
              />
              <button type="button" class="input-suffix-btn" aria-label="切换密码可见性" @click="showPassword = !showPassword">
                <i :class="showPassword ? 'fas fa-eye-slash' : 'fas fa-eye'" aria-hidden="true" />
              </button>
            </div>
          </div>

          <div class="remember-row">
            <label class="remember-label">
              <UiCheckbox :checked="form.remember" @update:checked="form.remember = $event" />
              <span>记住我</span>
            </label>
          </div>

          <div v-if="errorMsg" class="login-error-msg">{{ errorMsg }}</div>

          <button type="submit" class="btn-login" :disabled="loading">
            <i v-if="!loading" class="fas fa-right-to-bracket" style="margin-right: 6px" aria-hidden="true" />
            {{ loading ? '登录中…' : '安全登录' }}
          </button>
        </form>

        <div class="login-footer">
          <p class="footer-text">滨发玩具供应链管理系统</p>
          <p class="footer-version">v2.0</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { usePerfMark } from '@/composables/usePerfMark'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'

const perf = usePerfMark('login')

const isCapacitor = !!import.meta.env.VITE_CAPACITOR
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loading = ref(false)
const showPassword = ref(false)
const errorMsg = ref('')
const form = reactive({ username: '', password: '', remember: false })

onMounted(() => {
  perf.markMountEnd()
  const saved = localStorage.getItem('remembered_username')
  if (saved) {
    form.username = saved
    form.remember = true
  }
})

async function handleLogin() {
  if (!form.username || !form.password) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  perf.mark('auth-start')
  try {
    if (form.remember) {
      localStorage.setItem('remembered_username', form.username)
    } else {
      localStorage.removeItem('remembered_username')
    }
    const res = await authApi.login({
      username: form.username,
      password: form.password,
      remember: isCapacitor ? true : form.remember,
    })
    perf.markEnd('auth-start')
    perf.measure('auth-api', 'auth-start')
    perf.mark('init-start')
    if (isCapacitor && res.access_token) {
      localStorage.setItem('access_token', res.access_token)
    }
    await authStore.init(true)
    perf.markEnd('init-start')
    perf.measure('auth-store-init', 'init-start')
    const defaultRedirect = isCapacitor ? '/' : '/dashboard'
    const redirect = (route.query.redirect as string) || defaultRedirect
    router.push(redirect)
  } catch (err: any) {
    perf.markEnd('auth-start')
    perf.measure('auth-api-failed', 'auth-start')
    const msg = err.response?.data?.detail || '登录失败，请检查用户名和密码'
    errorMsg.value = msg
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ═══════════════════════════════════════════════
   移动端 Apple 极简登录（严格复刻 dashboard-preview）
   ═══════════════════════════════════════════════ */
.m-login-page {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #FFFFFF;
  z-index: 100;
  padding: 0;
}

.m-login-logo-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 0;
  flex-shrink: 0;
}

.m-login-logo {
  width: 300px;
  max-width: 80vw;
  height: auto;
  object-fit: contain;
}

.m-login-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--m-text-primary, #1D1D1F);
  margin-top: 0;
  letter-spacing: -0.5px;
}

.m-login-sub {
  font-size: 15px;
  color: var(--m-text-secondary, #86868B);
  margin-top: 8px;
  letter-spacing: 0;
}

.m-login-form-area {
  width: 100%;
  padding: 20px 24px 0;
  flex-shrink: 0;
}

.m-login-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 16px;
}

.m-login-field label {
  font-size: 13px;
  font-weight: 500;
  color: var(--m-text-secondary, #86868B);
  margin-bottom: 2px;
}

.m-login-field input {
  width: 100%;
  padding: 14px 16px;
  border: none;
  border-radius: 12px;
  font-size: 16px;
  font-family: -apple-system, 'SF Pro Text', 'Inter', 'Noto Sans SC', sans-serif;
  outline: none;
  transition: box-shadow 0.3s var(--m-ease-smooth, cubic-bezier(0.25, 0.1, 0.25, 1)),
              background 0.3s var(--m-ease-smooth, cubic-bezier(0.25, 0.1, 0.25, 1));
  background: var(--m-bg-grouped, #F5F5F7);
  color: var(--m-text-primary, #1D1D1F);
  box-sizing: border-box;
}

.m-login-field input:focus {
  background: var(--m-bg-grouped, #F5F5F7);
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.2);
}

.m-login-field input::placeholder {
  color: var(--m-text-tertiary, #AEAEB2);
  font-size: 15px;
}

.m-login-pwd-wrapper {
  position: relative;
  width: 100%;
}

.m-login-pwd-wrapper input {
  padding-right: 48px;
}

.m-login-pwd-toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  padding: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.m-login-pwd-toggle svg {
  width: 22px;
  height: 22px;
  color: var(--m-text-tertiary, #AEAEB2);
}

.m-login-error-msg {
  color: #FF3B30;
  font-size: 13px;
  margin-top: 0;
  margin-bottom: 4px;
  display: none;
}

.m-login-error-msg.show {
  display: block;
}

.m-login-btn-area {
  width: 100%;
  padding: 32px 24px 0;
  flex-shrink: 0;
}

.m-login-btn {
  width: 100%;
  height: 52px;
  border: none;
  border-radius: 14px;
  background: var(--m-accent, #0071E3);
  color: white;
  font-size: 17px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.3s var(--m-ease-spring, cubic-bezier(0.175, 0.885, 0.32, 1.275)),
              box-shadow 0.3s var(--m-ease-smooth, cubic-bezier(0.25, 0.1, 0.25, 1));
  font-family: -apple-system, 'SF Pro Text', 'Inter', 'Noto Sans SC', sans-serif;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(0, 113, 227, 0.25);
}

.m-login-btn:active {
  transform: scale(0.97);
}

.m-login-btn:disabled {
  opacity: 1;
  cursor: not-allowed;
}

.m-login-spinner {
  width: 24px;
  height: 24px;
  border: 2.5px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: m-spin 0.7s linear infinite;
}

@keyframes m-spin {
  to { transform: rotate(360deg); }
}

.m-login-footer {
  flex: 1;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 24px;
  font-size: 14px;
  color: #999999;
  flex-shrink: 0;
}

/* ═══════════════════════════════════════════════
   PC 端原有样式（保持不变）
   ═══════════════════════════════════════════════ */
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

.brand-section {
  flex: 1.1;
  background: var(--color-surface-card);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 78px;
  position: relative;
  overflow: hidden;
}

.brand-section::before {
  content: '';
  position: absolute;
  top: -195px;
  right: -195px;
  width: 520px;
  height: 520px;
  background: radial-gradient(circle, var(--color-ocean-light) 0%, transparent 70%);
  opacity: 0.6;
  pointer-events: none;
}

.brand-section::after {
  content: '';
  position: absolute;
  bottom: -130px;
  left: -130px;
  width: 390px;
  height: 390px;
  background: radial-gradient(circle, var(--color-ocean) 0%, transparent 70%);
  opacity: 0.4;
  pointer-events: none;
}

.brand-content {
  position: relative;
  z-index: 1;
  text-align: center;
  max-width: 546px;
}

.logo-wrapper {
  margin-bottom: 62px;
  animation: fadeInDown 0.8s ease;
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.logo-frame {
  width: 182px;
  height: 182px;
  margin: 0 auto;
  background: var(--color-surface-card);
  border-radius: 50%;
  padding: 21px;
  box-shadow: var(--shadow-lg);
  border: 5px solid var(--color-ocean-light);
  transition:
    transform 0.4s ease,
    box-shadow 0.4s ease;
}

.logo-frame:hover {
  transform: scale(1.05);
  box-shadow: var(--shadow-xl);
}

.logo-frame img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: 50%;
}

.brand-info {
  animation: fadeInUp 0.8s ease 0.2s both;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.brand-title {
  font-size: 42px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 16px;
  letter-spacing: -0.5px;
}

.brand-tagline {
  font-size: 20px;
  color: var(--color-text-secondary);
  line-height: 1.7;
  margin-bottom: 62px;
}

.feature-cards {
  display: flex;
  flex-direction: column;
  gap: 21px;
  animation: fadeInUp 0.8s ease 0.4s both;
}

.feature-card {
  display: flex;
  align-items: center;
  gap: 21px;
  padding: 26px 31px;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  transition: border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

.feature-card:hover {
  background: var(--color-surface-card);
  border-color: var(--color-ocean);
  box-shadow: var(--shadow-md);
  transform: translateX(10px);
}

.feature-icon-wrap {
  width: 62px;
  height: 62px;
  background: linear-gradient(135deg, var(--color-ocean-deep) 0%, var(--color-ocean) 100%);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-surface-card);
  flex-shrink: 0;
}

.feature-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 4px;
}

.feature-desc {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.login-section {
  flex: 0.9;
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 78px;
}

.login-card {
  width: 100%;
  max-width: 460px;
  background: var(--color-surface-card);
  border-radius: var(--radius-xl);
  padding: 52px 48px;
  box-shadow: var(--shadow-lg);
  animation: fadeInUp 0.8s ease 0.3s both;
}

.login-card-header {
  margin-bottom: 40px;
}

.login-heading {
  font-size: 30px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 10px;
}

.login-subheading {
  font-size: 16px;
  color: var(--color-text-secondary);
}

.form-label {
  display: block;
  font-size: 15px;
  font-weight: 500;
  color: var(--color-text);
  margin-bottom: 8px;
}

.remember-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.btn-login {
  width: 100%;
  height: 48px;
  font-size: 17px;
  font-weight: 600;
  border-radius: var(--radius-md);
  background: var(--color-ocean-deep);
  border-color: var(--color-ocean-deep);
}

.btn-login:hover,
.btn-login:focus {
  background: color-mix(in srgb, var(--color-ocean-deep) 85%, black);
  border-color: color-mix(in srgb, var(--color-ocean-deep) 85%, black);
}

.login-footer {
  text-align: center;
  margin-top: 40px;
  padding-top: 32px;
  border-top: 1px solid var(--color-border);
}

.footer-text {
  font-size: 16px;
  color: var(--color-text-muted);
}

.footer-version {
  font-size: 14px;
  color: var(--color-text-muted);
  margin-top: 5px;
}

.login-form .form-group {
  margin-bottom: 22px;
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.input-prefix-icon {
  position: absolute;
  left: 12px;
  color: var(--color-text-muted);
  font-size: 14px;
  pointer-events: none;
}

.input-suffix-btn {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px 8px;
  font-size: 14px;
}

.input-suffix-btn:hover {
  color: var(--color-text-secondary);
}

.form-input {
  width: 100%;
  padding: 12px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 15px;
  color: var(--color-text);
  background: var(--color-surface-card);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-ocean-deep) 20%, transparent);
}
.form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.form-input::placeholder {
  color: var(--color-text-muted);
}

.form-input.with-prefix {
  padding-left: 40px;
}

.form-input.with-suffix {
  padding-right: 40px;
}

.remember-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.login-error-msg {
  color: var(--color-danger-600);
  font-size: 13px;
  margin-bottom: 8px;
  padding: 8px 12px;
  background: var(--color-danger-50);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-danger-200);
}

@media (max-width: 1024px) {
  .brand-section {
    padding: 48px;
  }

  .logo-frame {
    width: 120px;
    height: 120px;
  }

  .brand-title {
    font-size: 28px;
  }

  .login-section {
    padding: 48px;
  }

  .login-card {
    padding: 40px 36px;
  }
}

@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
  }

  .brand-section {
    padding: 40px 32px;
    min-height: auto;
  }

  .brand-content {
    max-width: 100%;
  }

  .logo-frame {
    width: 100px;
    height: 100px;
  }

  .brand-tagline {
    margin-bottom: 32px;
  }

  .feature-cards {
    display: none;
  }

  .login-section {
    padding: 40px 24px;
    flex: 1;
  }

  .login-card {
    padding: 36px 28px;
  }
}

@media (max-width: 480px) {
  .brand-section {
    padding: 32px 24px;
  }

  .logo-frame {
    width: 90px;
    height: 90px;
  }

  .brand-title {
    font-size: 24px;
  }

  .login-card {
    padding: 32px 24px;
    border-radius: var(--radius-xl);
  }

  .login-heading {
    font-size: 22px;
  }
}
</style>
