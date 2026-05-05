<template>
  <div class="dashboard">
    <!-- Hero 欢迎区 -->
    <div class="home-hero p-[32px_24px] md:p-[48px_40px]">
      <h1 class="flex items-center gap-3 md:gap-5 text-2xl md:text-[36px] font-extrabold text-text mb-4 relative z-[1]">
        <img src="/logo_plush.png" alt="滨发玩具" class="w-14 h-14 md:w-20 md:h-20 rounded-[20px]" />
        滨发玩具协同系统
      </h1>
      <p class="lead text-sm md:text-[17px] text-text-secondary leading-relaxed max-w-[650px] relative z-[1] m-0">专业的毛绒玩具企业供应链管理平台 — 智能、高效、可靠的数字化管理解决方案</p>
    </div>


  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import UiStatCard from '@/components/ui/UiStatCard.vue';
import { dashboardApi } from '@/api';

const stats = ref<any>(null);

async function loadStats() {
  try {
    const data = await dashboardApi.stats();
    stats.value = data;
  } catch (e) {
    console.error('Failed to load stats:', e);
    // 使用默认数据
    stats.value = {
      order_today: 0,
      order_yesterday: 0,
      stockin_today: 0,
      stockin_yesterday: 0,
      stockout_today: 0,
      stockout_yesterday: 0,
      pending_approvals: 0,
      low_stock_count: 0,
      pending_purchases: 0,
      pending_materials: 0
    };
  }
}

onMounted(() => {
  loadStats();
});
</script>

<style scoped>
.home-hero {
  background: linear-gradient(135deg, var(--color-surface-card) 0%, var(--color-primary-50) 100%);
  border-radius: 24px;
  border: 2px solid var(--color-primary-50);
  box-shadow:
    0 8px 32px var(--shadow-md),
    0 4px 16px rgba(0, 0, 0, 0.06);
  position: relative;
  overflow: hidden;
}

.home-hero::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -10%;
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, var(--color-primary-100) 0%, transparent 70%);
  opacity: 0.15;
  border-radius: 50%;
}

.home-hero h1 img {
  box-shadow:
    0 6px 20px var(--shadow-sm),
    inset 0 2px 4px rgba(255, 255, 255, 0.9);
  animation: floatLogo 3s ease-in-out infinite;
}

@keyframes floatLogo {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-8px);
  }
}
</style>
