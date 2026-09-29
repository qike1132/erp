<template>
  <div class="sp-dist">
    <div v-if="!rows.length" class="sp-dist-empty">暂无数据</div>
    <template v-else>
      <div v-for="row in rows" :key="row.name" class="sp-dist-row">
        <span class="sp-dist-name" :title="row.name">{{ row.name }}</span>
        <span class="sp-dist-track">
          <i :class="row.top ? 'sp-dist-top' : 'sp-dist-weak'" :style="{ width: row.w + '%' }" />
        </span>
        <span class="sp-dist-pct num">{{ row.w }}%</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// 客户出货分布 —— 从 PurchasePlanDailyTab 移入「月度汇总」Tab。
// 它是整月口径的视角，与汇总 Tab 同主题；留在日 Tab 只会和右栏抢位置。
import { computed } from 'vue'
import type { CustSumItem } from './types'

const props = defineProps<{
  customers: CustSumItem[]
}>()

/** 前 5 名客户占最大计划量的比例。取数顺序沿用原实现（传入的排序不许在此重排） */
const rows = computed(() => {
  const list = props.customers
  const max = Math.max(0, ...list.map(c => Number(c.plan_qty || 0)))
  return list.slice(0, 5).map((c, i) => ({
    name: c.customer_name,
    w: max > 0 ? Math.round(Number(c.plan_qty || 0) / max * 100) : 0,
    top: i === 0,
  }))
})
</script>

<style scoped lang="scss">
.sp-dist {
  padding: 14px 18px;
}

.sp-dist-empty {
  padding: 22px 0;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted, #8c96ad);
}

.sp-dist-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.sp-dist-row:first-child {
  margin-top: 0;
}

.sp-dist-name {
  width: 88px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--color-text-secondary, #5a6b8c);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sp-dist-track {
  flex: 1;
  min-width: 0;
  height: 8px;
  border-radius: 4px;
  background: #edf0f6;
  overflow: hidden;
}

.sp-dist-track > i {
  display: block;
  height: 100%;
  border-radius: 4px;
}

.sp-dist-top { background: var(--color-primary-500, #5b8def); }
.sp-dist-weak { background: #c4d0e8; }

.sp-dist-pct {
  width: 40px;
  flex-shrink: 0;
  text-align: right;
  font-size: 12px;
  color: var(--color-text-muted, #8c96ad);
}
</style>
