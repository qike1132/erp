<template>
  <div class="login-container">
    <div class="brand-section">
      <div class="brand-content">
        <div class="logo-wrapper">
          <div class="logo-frame">
            <img src="/logo_plush.png" alt="东莞玩具" />
          </div>
        </div>

        <div class="brand-info">
          <h1 class="brand-title">东莞玩具协同系统</h1>
          <p class="brand-tagline">专业的毛绒玩具企业供应链管理平台<br />智能、高效、可靠的数字化管理解决方案</p>
        </div>

        <div class="feature-cards">
          <div class="feature-card">
            <div class="feature-icon-wrap">
              <FontAwesomeIcon icon="box" style="font-size: 28px" aria-hidden="true" />
            </div>
            <div class="feature-text">
              <div class="feature-title">智能库存管理</div>
              <div class="feature-desc">实时追踪库存动态，精准预测需求</div>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon-wrap">
              <FontAwesomeIcon icon="file-lines" style="font-size: 28px" aria-hidden="true" />
            </div>
            <div class="feature-text">
              <div class="feature-title">高效订单处理</div>
              <div class="feature-desc">自动化流程，提升运营效率</div>
            </div>
          </div>

          <div class="feature-card">
            <div class="feature-icon-wrap">
              <FontAwesomeIcon icon="chart-line" style="font-size: 28px" aria-hidden="true" />
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
              <FontAwesomeIcon icon="user" class="input-prefix-icon" aria-hidden="true" />
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
              <FontAwesomeIcon icon="lock" class="input-prefix-icon" aria-hidden="true" />
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                name="password"
                placeholder="请输入密码"
                autocomplete="current-password"
                required
                class="form-input with-prefix with-suffix"
                aria-describedby="login-error-msg"
              />
              <button type="button" class="input-suffix-btn" aria-label="切换密码可见性" @click="showPassword = !showPassword">
                <FontAwesomeIcon :icon="showPassword ? 'eye-slash' : 'eye'" aria-hidden="true" />
              </button>
            </div>
          </div>

          <div class="remember-row">
            <label class="remember-label">
              <UiCheckbox :checked="form.remember" @update:checked="form.remember = $event" />
              <span>记住我</span>
            </label>
          </div>

          <div v-if="errorMsg" id="login-error-msg" class="login-error-msg">{{ errorMsg }}</div>

          <button type="submit" class="btn-login" :disabled="loading">
            <FontAwesomeIcon v-if="!loading" icon="right-to-bracket" style="margin-right: 6px" aria-hidden="true" />
            {{ loading ? '登录中…' : '安全登录' }}
          </button>
        </form>

        <div class="login-footer">
          <p class="footer-text">东莞玩具供应链管理系统</p>
          <p class="footer-version">v2.0</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
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
  animation: fadeInDown 0.4s ease;
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
  animation: fadeInUp 0.4s ease 0.1s both;
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
  animation: fadeInUp 0.5s ease 0.15s both;
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
  animation: fadeInUp 0.3s ease both;
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
  color: var(--color-surface-card);
  border: none;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.btn-login:hover,
.btn-login:focus {
  background: color-mix(in srgb, var(--color-ocean-deep) 85%, black);
  border-color: color-mix(in srgb, var(--color-ocean-deep) 85%, black);
}

.btn-login:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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
.form-input:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}

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
