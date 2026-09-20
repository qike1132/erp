<template>
  <div class="osw-result-wrap">
    <div v-if="result.ok" class="osw-result osw-result--ok">
      <div class="osw-result-head">
        <FontAwesomeIcon icon="circle-check" aria-hidden="true" />
        <strong>发货完成：已生成 {{ result.shipments.length }} 张发货单</strong>
      </div>
      <div v-for="s in result.shipments" :key="s.id" class="osw-result-row">
        <span class="osw-mono">{{ s.shipment_no }}</span>
        <span>{{ s.customer || '-' }}</span>
        <span class="osw-mono">{{ s.item_count }} 道工序 · {{ s.total_shipped.toLocaleString() }} 件</span>
        <span class="osw-badge">待贝乐收货</span>
      </div>
    </div>

    <div v-else class="osw-result osw-result--fail">
      <div class="osw-result-head">
        <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />
        <strong>发货失败（整批已回滚，数据未变更）</strong>
      </div>
      <div class="osw-result-detail">{{ result.error }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourceShipResultView.vue — 批量发货结果态（成功=发货单清单 / 失败=错误明细）
 * 纯展示：结果对象由父组件传入；底栏按钮（完成并关闭/返回修改）仍归父组件编排。
 */
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import type { ShipResult } from './shipCartModel'

defineProps<{ result: ShipResult }>()
</script>

<style scoped>
/* ===== 结果态 ===== */
.osw-result-wrap { flex: 1; overflow-y: auto; }
.osw-result { border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.osw-result--ok { background: var(--color-success-50, #f0fdf4); border: 1px solid var(--color-success-200, #bbf7d0); }
.osw-result--fail { background: var(--color-danger-50, #fef2f2); border: 1px solid #fecaca; }
.osw-result-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.osw-result--ok .osw-result-head { color: var(--color-success-700, #15803d); }
.osw-result--fail .osw-result-head { color: #b91c1c; }
.osw-result-row {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  background: #fff; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px; padding: 9px 12px; font-size: 12.5px;
}
.osw-mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; }
.osw-badge {
  margin-left: auto; font-size: 11px; font-weight: 700; color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb); border: 1px solid var(--color-warning-200, #fde68a);
  border-radius: 7px; padding: 2px 9px;
}
.osw-result-detail {
  background: #fff; border: 1px solid #fecaca; border-radius: 10px;
  padding: 10px 12px; font-size: 12.5px; color: #b91c1c;
}
</style>
