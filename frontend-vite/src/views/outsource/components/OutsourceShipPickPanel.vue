<template>
  <aside class="osw-left">
    <div class="osw-l-toolbar">
      <label class="osw-search">
        <FontAwesomeIcon icon="search" aria-hidden="true" />
        <input
          v-model="keyword"
          type="text"
          placeholder="搜索产品名称"
          aria-label="搜索产品名称"
        />
      </label>
    </div>
    <div class="osw-l-meta">
      <span>待发货产品 <b>{{ filtered.length }}</b> 项</span>
      <button type="button" class="osw-link" @click="emit('select-all')">全选</button>
    </div>
    <!-- 列表（表头 sticky 在滚动容器内，保证与卡片同宽、右列精确对齐） -->
    <div class="osw-l-list">
      <div class="osw-l-head" aria-hidden="true">
        <span class="osw-l-head-cbx" />
        <span class="osw-l-head-prod">产品名称</span>
        <span />
      </div>
      <div v-if="!filtered.length" class="osw-l-empty">没有匹配的产品</div>
      <div
        v-for="g in filtered"
        :key="g.key"
        :class="['osw-card', { 'is-on': isPickOn(g) }]"
        @click="emit('toggle', g)"
      >
        <input
          type="checkbox"
          class="osw-cbx"
          :checked="isPickOn(g)"
          :aria-label="`勾选 ${g.productName}`"
          @click.stop="emit('toggle', g)"
        />
        <!-- 单行：产品名称 + 跨订单角标 -->
        <span class="osw-prod-name" :title="g.productName">{{ g.productName }}</span>
        <span v-if="g.orderCount > 1" class="osw-prod-orders" :title="`该产品分布在 ${g.orderCount} 张订单`">{{ g.orderCount }}单</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * OutsourceShipPickPanel.vue — 批量发货弹窗左栏「待发货产品」
 *
 * 只管浏览挑选：点卡片任意处 = 勾选/取消（emit toggle），全选只作用于当前筛选结果；
 * 挑选状态（是否已在清单）由父组件经 selectedNames 下发，本组件不持有清单状态。
 * 关键字状态由父组件持有（手机端 Tab 的待选计数依赖它），经 v-model:keyword 双向绑定。
 */
import { computed } from 'vue'
import type { PickGroup } from './shipCartModel'

const props = defineProps<{
  /** 全量挑选项（未过滤；过滤在本组件内按 keyword 进行） */
  groups: PickGroup[]
  /** 已加入清单的产品名列表（用于卡片选中态） */
  selectedNames: string[]
}>()

const emit = defineEmits<{
  (e: 'toggle', g: PickGroup): void
  (e: 'select-all'): void
}>()

const keyword = defineModel<string>('keyword', { default: '' })

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return props.groups.filter((g) => !kw || g.productName.includes(kw))
})

/** 挑选项是否已在清单中 */
function isPickOn(g: PickGroup): boolean {
  return props.selectedNames.includes(g.productName)
}
</script>

<style scoped>
/* ---- 左栏 ---- */
.osw-left {
  width: 360px; flex-shrink: 0; display: flex; flex-direction: column; min-height: 0;
  border-right: 1px solid var(--color-border-light, #e2e8f0); background: #fff;
}
.osw-l-toolbar { display: flex; gap: 8px; padding: 12px 12px 8px; flex-shrink: 0; }
.osw-search {
  flex: 1; display: flex; align-items: center; gap: 7px;
  border: 1px solid #cbd5e1; border-radius: 9px; padding: 0 10px; background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.osw-search:focus-within { border-color: var(--color-primary-300, #93c5fd); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }
.osw-search svg { color: var(--color-text-muted, #94a3b8); font-size: 12px; flex-shrink: 0; }
.osw-search input {
  flex: 1; min-width: 0; border: none; outline: none; background: transparent;
  font: inherit; font-size: 13px; padding: 8px 0; color: var(--color-text, #1e293b);
}
.osw-search input::placeholder { color: var(--color-text-muted, #94a3b8); }

.osw-l-meta {
  display: flex; align-items: center; padding: 2px 16px 8px;
  font-size: 12px; color: var(--color-text-muted, #64748b); flex-shrink: 0;
}
.osw-l-meta b { color: var(--color-text, #1e293b); margin: 0 2px; }
.osw-l-meta .osw-link { margin-left: auto; }

/* 两栏共用类：scoped 样式不跨组件，在两个子组件内各持一份 */
.osw-link {
  border: none; background: transparent; color: var(--color-primary-600, #2563eb);
  font: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer;
  padding: 4px 6px; border-radius: 6px; transition: background 0.15s ease;
}
.osw-link:hover:not(:disabled) { background: var(--color-primary-50, #eff6ff); }
.osw-link:disabled { color: #b6c2d2; cursor: not-allowed; }

.osw-l-list { flex: 1; overflow-y: auto; padding: 2px 12px 12px; scrollbar-gutter: stable; }
.osw-l-empty { padding: 36px 16px; text-align: center; color: var(--color-text-muted, #94a3b8); font-size: 12.5px; }

/* 列表表头：sticky 在滚动容器内；内边距/列宽与 .osw-card 逐列对齐 */
/* 表头与卡片共用 grid 列定义：勾选 | 产品 | 角标 */
.osw-l-head,
.osw-card {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.osw-l-head {
  position: sticky; top: 0; z-index: 1;
  margin-bottom: 6px; padding: 6px 12px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 11px; font-weight: 700; letter-spacing: 0.03em;
  color: var(--color-text-muted, #94a3b8);
  background: #fff;
}
.osw-l-head-prod { min-width: 0; }

.osw-card {
  padding: 10px 12px; margin-bottom: 6px;
  background: #fff; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  cursor: pointer; user-select: none;
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.osw-card:hover { border-color: var(--color-primary-300, #93c5fd); background: #fbfdff; }
.osw-card.is-on {
  border-color: var(--color-primary-300, #93c5fd); background: var(--color-primary-50, #eff6ff);
  box-shadow: inset 3px 0 0 var(--color-primary-600, #2563eb);
}
.osw-cbx { width: 16px; height: 16px; accent-color: var(--color-primary-600, #2563eb); cursor: pointer; margin: 0; }

/* 单行布局：产品名（完整展示） + 跨订单角标 */
.osw-prod-name {
  min-width: 0; font-size: 13.5px; font-weight: 600; color: var(--color-text, #1e293b);
  /* 产品名完整展示：允许折行，不使用省略号截断 */
  overflow-wrap: anywhere; line-height: 1.45;
}
/* 跨订单角标：同一产品分布在多张订单 */
.osw-prod-orders {
  justify-self: start;
  font-size: 10.5px; font-weight: 700; color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb); border: 1px solid var(--color-warning-200, #fde68a);
  border-radius: 5px; padding: 0 5px; line-height: 1.5; white-space: nowrap;
}

/* 移动端左栏规则：从父组件响应式块迁入（根元素带父作用域属性，父级显隐切换仍生效） */
@media (max-width: 768px) {
  .osw-left { width: 100%; border-right: none; }
}
</style>
