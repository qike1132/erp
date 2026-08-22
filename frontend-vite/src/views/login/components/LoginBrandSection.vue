<template>
  <div class="brand-section">
    <div class="brand-content">
      <div class="logo-wrapper">
        <div class="logo-frame">
          <img loading="lazy" src="/logo_plush.png" alt="东莞玩具" />
        </div>
      </div>

      <div class="brand-info">
        <h1 class="brand-title">滨发玩具协同系统</h1>
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
</template>

<script setup lang="ts">
</script>

<style scoped>
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
  from { opacity: 0; transform: translateY(-30px); }
  to { opacity: 1; transform: translateY(0); }
}

.logo-frame {
  width: 182px;
  height: 182px;
  margin: 0 auto;
  background: var(--color-surface-card);
  border-radius: 50%;
  padding: 21px;
  box-shadow: var(--shadow-lg, 0 8px 32px rgba(0, 0, 0, 0.1));
  border: 5px solid var(--color-ocean-light);
  transition: transform 0.4s ease, box-shadow 0.4s ease;
}

.logo-frame:hover {
  transform: scale(1.05);
  box-shadow: var(--shadow-xl, 0 16px 48px rgba(0, 0, 0, 0.12));
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
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
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
  box-shadow: var(--shadow-md, 0 4px 16px rgba(0, 0, 0, 0.08));
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

@media (max-width: 1024px) {
  .brand-section { padding: 48px; }
  .logo-frame { width: 120px; height: 120px; }
  .brand-title { font-size: 28px; }
}

@media (max-width: 768px) {
  .brand-section { padding: 40px 32px; min-height: auto; }
  .brand-content { max-width: 100%; }
  .logo-frame { width: 100px; height: 100px; }
  .brand-tagline { margin-bottom: 32px; }
  .feature-cards { display: none; }
}

@media (max-width: 480px) {
  .brand-section { padding: 32px 24px; }
  .logo-frame { width: 90px; height: 90px; }
  .brand-title { font-size: 24px; }
}
</style>