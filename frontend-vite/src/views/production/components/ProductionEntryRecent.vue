<template>
  <aside class="pr-recent" data-test="qe-recent">
    <div class="pr-recent-head">
      <div class="pr-recent-title">
        <b>最近客户添加</b>
        <span :title="customerName">{{ customerId == null ? '未选客户' : customerName }}</span>
      </div>
      <span v-if="customerId != null" class="pr-recent-count">{{ items.length }}</span>
    </div>

    <div class="pr-recent-list">
      <div v-if="loading" class="pr-recent-state">加载中…</div>
      <div v-else-if="customerId == null" class="pr-recent-state">
        <span>先选择客户</span>
        <span class="sub">这里会显示该客户最近录入的 SKU，点一条直接加一行</span>
      </div>
      <template v-else-if="items.length">
        <button
          v-for="it in items"
          :key="it.product_id"
          type="button"
          class="pr-recent-item"
          :title="`${it.product_name}（点击加入清单）`"
          @click="emit('add', it)"
        >
          <span class="n">{{ it.product_name }}</span>
          <span class="m">
            <span v-if="it.barcode" class="code">{{ it.barcode }}</span>
            <span v-if="it.quantity" class="qty">上次 {{ it.quantity }}</span>
          </span>
        </button>
      </template>
      <div v-else class="pr-recent-state">
        <span>该客户近 90 天没有录入记录</span>
        <button type="button" class="browse" @click="emit('browse')">浏览该客户的产品</button>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * ProductionEntryRecent — 表格右侧「最近客户添加」。
 *
 * 固定占位的独立区域：没选客户时显示引导，选了客户后列出该客户近 90 天
 * 录入过的 SKU（由 useProductionEntry 拉生产记录去重而来），点一条直接加一行。
 */
import type { RecentSku } from '../composables/useProductionEntry'

defineProps<{
  customerId: number | null
  items: RecentSku[]
  loading: boolean
  customerName: string
}>()

const emit = defineEmits<{
  add: [item: RecentSku]
  browse: []
}>()
</script>

<style scoped>
.pr-recent { flex: 0 0 180px; width: 180px; min-height: 0; display: flex; flex-direction: column; border: 1px solid var(--color-border); border-radius: 12px; background: #fcfdff; overflow: hidden; }
.pr-recent-head { flex: 0 0 auto; padding: 10px 12px; border-bottom: 1px solid var(--color-border-light); display: flex; align-items: flex-start; gap: 8px; background: #fff; }
.pr-recent-title { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.pr-recent-title b { font-size: 13px; font-weight: 800; color: var(--color-text); }
.pr-recent-title span { font-size: 11.5px; color: var(--color-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pr-recent-count { margin-left: auto; min-width: 20px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--color-surface); color: var(--color-text-muted); font-size: 11px; font-weight: 700; display: grid; place-items: center; }
.pr-recent-list { flex: 1; min-height: 0; overflow-y: auto; padding: 6px; display: flex; flex-direction: column; gap: 2px; }
.pr-recent-item { display: flex; flex-direction: column; gap: 2px; width: 100%; padding: 8px 9px; border: 1px solid transparent; border-radius: 8px; background: transparent; text-align: left; cursor: pointer; font-family: inherit; transition: background 0.14s, border-color 0.14s; }
.pr-recent-item:hover { background: #fff; border-color: var(--color-primary-200); }
.pr-recent-item .n { font-size: 14px; font-weight: 700; color: var(--color-text); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.4; }
.pr-recent-item .m { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--color-text-placeholder); }
.pr-recent-item .code { font-family: 'SF Mono', Consolas, monospace; }
.pr-recent-item .qty { color: var(--color-text-muted); }
.pr-recent-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 18px 12px; font-size: 12px; line-height: 1.6; color: var(--color-text-placeholder); text-align: center; }
.pr-recent-state .sub { font-size: 11.5px; color: var(--color-text-4, var(--color-text-placeholder)); }
.pr-recent-state .browse { border: 1px solid var(--color-border); background: #fff; color: var(--color-text-secondary); font-size: 12px; font-weight: 600; border-radius: 7px; padding: 5px 10px; cursor: pointer; font-family: inherit; }
.pr-recent-state .browse:hover { border-color: var(--color-primary-400); color: var(--color-primary-700); }
</style>
