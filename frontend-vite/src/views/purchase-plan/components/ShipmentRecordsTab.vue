<template>
  <div v-if="loading" class="sp-modal-empty"><UiSpinner /></div>
  <div v-else-if="error" class="sp-modal-empty"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />加载失败</div>
  <div v-else-if="!records.length" class="sp-modal-empty"><FontAwesomeIcon icon="inbox" aria-hidden="true" />暂无出货记录</div>
  <div v-else class="sp-stockout-list">
    <div class="sp-stockout-header">
      <span class="sp-stockout-col-date">出货时间</span>
      <span class="sp-stockout-col-no">出货单号</span>
      <span class="sp-stockout-col-customer">客户</span>
      <span class="sp-stockout-col-product">产品</span>
      <span class="sp-stockout-col-qty">数量</span>
    </div>
    <VirtualList
      :items="records"
      :itemHeight="40"
      :containerHeight="460"
      :itemKey="(r) => r.shipment_no"
    >
      <template #default="{ item: rec }">
        <div class="sp-stockout-row">
          <span class="sp-stockout-col-date">{{ rec.shipment_date }}</span>
          <span class="sp-stockout-col-no">{{ rec.shipment_no }}</span>
          <span class="sp-stockout-col-customer">{{ rec.customer_name }}</span>
          <span class="sp-stockout-col-product">{{ rec.product_name }}</span>
          <span class="sp-stockout-col-qty">{{ rec.quantity }}</span>
        </div>
      </template>
    </VirtualList>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { planApi } from '@/api';
import VirtualList from '@/components/ui/VirtualList.vue';
import type { Plan } from './types';

const props = defineProps<{
  date: string;
  plans: Plan[];
}>();

const loading = ref(false);
const error = ref(false);
const records = ref<any[]>([]);

async function load() {
  if (!props.date) return;
  loading.value = true;
  error.value = false;
  records.value = [];
  try {
    const planIds = [...new Set(props.plans.map((p: Plan) => p.plan_id))];
    if (planIds.length === 0) {
      loading.value = false;
      return;
    }
    // 并行请求所有 plan 的出货记录，替代串行 N+1
    const chunkSize = 10;
    const allRecords: any[] = [];
    for (let i = 0; i < planIds.length; i += chunkSize) {
      const chunk = planIds.slice(i, i + chunkSize);
      const responses = await Promise.all(chunk.map(pid => planApi.shipmentRecords(pid)));
      for (const res of responses) {
        const recs = (res as any)?.records ?? res ?? [];
        allRecords.push(...recs);
      }
    }
    // 去重 by shipment_no（同一出货记录可能被多个计划匹配到）
    const seen = new Set<string>();
    records.value = allRecords.filter((r: any) => {
      if (!r.shipment_no || seen.has(r.shipment_no)) return false;
      seen.add(r.shipment_no);
      return true;
    });
  } catch (e) {
    error.value = true;
    console.error('Failed to load shipment records', e);
  } finally {
    loading.value = false;
  }
}

watch(() => props.date, () => { if (props.date) load(); }, { immediate: true });
</script>

<style scoped>
.sp-modal-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.sp-modal-empty i {
  font-size: 28px;
  opacity: 0.5;
}

.sp-stockout-list { display: flex; flex-direction: column; gap: 0; }
.sp-stockout-header {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  background: var(--color-surface, #f8fafc); border-radius: 10px 10px 0 0;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  font-size: 11px; font-weight: 700; color: var(--color-text-secondary);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.sp-stockout-col-date { flex: 1; }
.sp-stockout-col-no { flex: 1.2; }
.sp-stockout-col-customer { flex: 1.5; }
.sp-stockout-col-product { flex: 2; }
.sp-stockout-col-qty { flex: 0.8; text-align: center; }
.sp-stockout-row {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0); transition: background 0.15s; font-size: 13px;
}
.sp-stockout-row:last-child { border-bottom: none; }
.sp-stockout-row:hover { background: var(--color-primary-50, #eff6ff); }
.sp-stockout-col-no { flex: 1.2; font-family: var(--font-mono); font-size: 12px; color: var(--color-text-secondary); }
</style>
