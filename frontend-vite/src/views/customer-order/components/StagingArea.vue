<template>
  <div class="co-col">
    <div class="co-col-title">
      <span><FontAwesomeIcon icon="layer-group" aria-hidden="true" /> 暂存列表</span>
      <span v-if="stagedItems.length" class="count-badge-subtle" role="status" aria-live="polite">共 {{ stagedItems.length }} 个</span>
    </div>
    <div class="co-col-scroll" :aria-label="`暂存列表，共 ${stagedItems.length} 条`">
      <template v-if="stagedItems.length">
        <div
          v-for="(item, idx) in stagedItems"
          :key="item.type + '-' + item.productId + '-' + idx"
          class="co-staged-card"
          :style="{ borderColor: item.type === 'order' ? 'var(--color-ocean-light)' : 'var(--color-success-200)' }"
        >
          <div class="co-staged-main">
            <div class="co-staged-info">
              <span :class="['co-type-badge', item.type]">{{ item.type === 'order' ? '订单' : '备货' }}</span>
              <span class="co-staged-tag"><FontAwesomeIcon icon="user" aria-hidden="true" />{{ item.customer }}</span>
              <span class="co-staged-tag"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" />{{ item.date }}</span>
              <span class="co-staged-product">
                <FontAwesomeIcon :icon="item.type === 'order' ? 'shopping-cart' : 'cubes'" :style="{ color: item.type === 'order' ? 'var(--color-ocean-text)' : 'var(--color-success-700)' }" />
                {{ item.productName }}

                <span class="count-badge-subtle">数量: {{ item.quantity }}</span>
                <span v-if="item.deductQuantity > 0" class="count-badge-subtle">抵扣: {{ item.deductQuantity }}</span>
                <span v-if="item.note" class="count-badge-subtle">备注: {{ item.note }}</span>
                <!-- 分批出货徽标（2026-10-06 v2）：每批一枚，超 2 批折叠；中性 chip 群中唯一的彩色信号点 -->
                <template v-if="item.type === 'order' && item.shipmentPlans.length">
                  <span v-for="(plan, pIdx) in item.shipmentPlans.slice(0, 2)" :key="pIdx" class="count-badge-subtle co-plan-chip">
                    <FontAwesomeIcon icon="truck" aria-hidden="true" />出货: {{ plan.date.slice(5) }}×{{ plan.quantity }}
                  </span>
                  <span v-if="item.shipmentPlans.length > 2" class="count-badge-subtle co-plan-chip">
                    +{{ item.shipmentPlans.length - 2 }}批
                  </span>
                </template>
              </span>
            </div>
            <div class="co-staged-actions">
              <button
                class="co-btn-icon co-btn-warn"
                :aria-label="`编辑 ${item.customer} 的 ${item.productName}`"
                @click="emit('edit-staged', item.uid)"
              >
                <FontAwesomeIcon icon="edit" aria-hidden="true" />
              </button>
              <button
                class="co-btn-icon co-btn-danger"
                :aria-label="`删除 ${item.customer} 的 ${item.productName}`"
                @click="emit('remove-staged', item.uid)"
              >
                <FontAwesomeIcon icon="trash" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="co-empty-state">
        <FontAwesomeIcon icon="box-open" class="co-empty-icon" aria-hidden="true" />
        <p>暂无暂存记录</p>
      </div>
    </div>

    <!-- 提交按钮 -->
    <div v-if="stagedItems.length" class="co-submit-bar">
      <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap">
        <UiButton
          variant="primary"
          size="lg"
          :disabled="submitting"
          style="min-width: 200px"
          @click="emit('submit-all')"
        >
          <FontAwesomeIcon icon="paper-plane" aria-hidden="true" />{{ submitLabel }}
        </UiButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import type { StagedItem } from '../composables/types'

const props = defineProps<{
  stagedItems: StagedItem[]
  submitting: boolean
}>()

const emit = defineEmits<{
  'edit-staged': [uid: string]
  'remove-staged': [uid: string]
  'submit-all': []
}>()

const orderCount = computed(() => props.stagedItems.filter((i) => i.type === 'order').length)
const stockinCount = computed(() => props.stagedItems.length - orderCount.value)

/** 按钮文案必须如实区分订单/备货：混着备货时「提交订单 (N)」会让人以为全是订单，
 * 而备货是要写库存的（2026-10-06 出库"凭空库存"事故的可见性缺口之一） */
const submitLabel = computed(() => {
  if (props.submitting) return '提交中…'
  if (orderCount.value && stockinCount.value) return `提交：订单 ${orderCount.value} + 备货 ${stockinCount.value}`
  if (stockinCount.value) return `提交备货 (${stockinCount.value})`
  return `提交订单 (${orderCount.value})`
})
</script>

<style scoped>
/* ===== 栏目 ===== */
.co-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.co-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

.co-col-scroll {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

/* ===== 暂存列表 ===== */
.co-staged-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  transition: border-color 0.2s ease, background 0.2s ease;
}
/* hover 用描边/底色表达，不做位移（列表扫读时位移会造成抖动与重排） */
.co-staged-card:hover {
  border-color: var(--color-primary-300);
  background: var(--color-surface, #f8fafc);
}
.co-staged-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.co-staged-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.co-staged-tag {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}
.co-staged-tag i {
  font-size: 11px;
}
.co-staged-product {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
}
/* 出货计划 chip：primary 色调，与中性 chip 形成对比 */
.co-plan-chip {
  color: var(--color-primary-600);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.co-plan-chip i {
  font-size: 11px;
}
.co-staged-actions {
  display: flex;
  gap: 4px;
  margin-left: 8px;
  flex-shrink: 0;
}

/* ===== 类型徽章 ===== */
.co-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.co-type-badge.order {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-type-badge.stockin {
  background: var(--color-success-100);
  color: var(--color-success-600);
}
.co-type-badge.custom {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}

/* ===== 操作按钮 ===== */
.co-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.co-btn-warn {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.co-btn-warn:hover {
  background: var(--color-warning-100);
}
.co-btn-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.co-btn-danger:hover {
  background: var(--color-danger-100);
}
.co-btn-danger:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== 提交栏 ===== */
.co-submit-bar {
  text-align: center;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border, #cbd5e1);
}

/* ===== 空状态 ===== */
.co-empty-state {
  text-align: center;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
}
.co-empty-icon {
  font-size: 28px;
  opacity: 0.5;
}
.co-empty-state p {
  margin: 0;
  font-size: 14px;
}
</style>
