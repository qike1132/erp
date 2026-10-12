<template>
  <section class="pd-right">
    <template v-if="node">
      <header class="pd-right-head">
        <FontAwesomeIcon
          v-if="node.icon"
          :icon="node.icon.replace('fa-', '')"
          class="pd-right-icon"
          aria-hidden="true"
        />
        <h4>{{ node.name }}</h4>
        <span class="pd-right-cnt"> 已选 <b>{{ countOf(node) }}</b> / {{ moduleIds.length }} </span>
        <button v-if="hasChildren" type="button" class="pd-link" @click="togglePermNode(node.id)">
          {{ stateOf(node) === 'all' ? '清空' : '全选' }}
        </button>
      </header>
      <div class="pd-rows">
        <template v-for="row in rows" :key="row.item.id">
          <p v-if="row.group" class="pd-group">{{ row.group }}</p>
          <div
            class="pd-row"
            :class="{ on: isPermChecked(row.item.id) }"
            role="checkbox"
            :aria-checked="isPermChecked(row.item.id)"
            tabindex="0"
            @click="togglePermNode(row.item.id)"
            @keydown.enter.prevent="togglePermNode(row.item.id)"
            @keydown.space.prevent="togglePermNode(row.item.id)"
          >
            <PermissionCheckBox
              :state="isPermChecked(row.item.id) ? 'all' : 'none'"
              :label="row.item.name"
              :interactive="false"
            />
            <span class="pd-row-name">{{ row.item.name }}</span>
            <code class="pd-code">{{ row.item.code }}</code>
          </div>
        </template>
      </div>
    </template>
    <p v-else class="pd-empty">请选择左侧模块</p>
  </section>
</template>

<script setup lang="ts">
/**
 * PermissionDetailPanel.vue — 分配权限弹窗右栏：当前模块的权限清单
 *
 * 有子权限的模块先列「模块访问」（模块自身 = 可见/查看授权）再列「操作权限」；
 * 无子权限的模块只列自身一行。整行可点，勾选框为纯指示器（点击穿透给整行）。
 */
import { computed } from 'vue'
import type { PermissionItem } from '@/types'
import PermissionCheckBox from '@/views/user/components/PermissionCheckBox.vue'
import {
  collectModuleIds,
  countChecked,
  getPermissionCheckState,
  type PermissionCheckState,
} from '@/views/user/composables/useUserManagement'

const props = defineProps<{
  /** 当前模块；无选中时为 undefined */
  node?: PermissionItem
  /** 已勾选权限 id 列表 */
  permCheckedKeys: number[]
  /** 判断是否已勾选 */
  isPermChecked: (id: number) => boolean
  /** 切换勾选（父子级联） */
  togglePermNode: (id: number) => void
}>()

/** 权限行 + 其分组标签（标签为空串表示不渲染） */
interface DetailRow {
  group: string
  item: PermissionItem
}

/** 模块是否带操作权限 */
const hasChildren = computed(() => (props.node?.children?.length ?? 0) > 0)

/** 行列表：有子权限时 = 模块自身 + 各操作权限（各带分组标签），否则只有模块自身 */
const rows = computed<DetailRow[]>(() => {
  const n = props.node
  if (!n) return []
  if (!hasChildren.value) return [{ group: '', item: n }]
  const children = n.children ?? []
  return [
    { group: '模块访问', item: n },
    ...children.map((c, i) => ({ group: i === 0 ? '操作权限' : '', item: c })),
  ]
})

/** 模块（含子权限）的 id 集合大小 */
const moduleIds = computed(() => (props.node ? collectModuleIds(props.node) : []))

/** 模块的勾选状态 */
function stateOf(n: PermissionItem): PermissionCheckState {
  return getPermissionCheckState(collectModuleIds(n), props.permCheckedKeys)
}

/** 模块的「已选/总数」文本 */
function countOf(n: PermissionItem): string {
  const ids = collectModuleIds(n)
  return `${countChecked(ids, props.permCheckedKeys)}/${ids.length}`
}
</script>

<style scoped>
.pd-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  margin-left: 12px;
}
.pd-right-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 2px 12px;
  border-bottom: 1px solid var(--color-border-light, #e8ecf1);
}
.pd-right-icon {
  font-size: 14px;
  color: var(--color-primary-500);
}
.pd-right-head h4 {
  flex: 1;
  margin: 0;
  font-size: 15px;
  color: var(--color-text);
}
.pd-right-cnt {
  font-size: 12.5px;
  color: var(--color-text-muted);
}
.pd-right-cnt b {
  color: var(--color-primary-600);
}
.pd-rows {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 2px 4px;
}
.pd-group {
  margin: 4px 0 8px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--color-text-placeholder, #94a3b8);
}
.pd-row {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 7px;
  padding: 9px 12px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}
.pd-row:hover {
  border-color: var(--color-primary-200);
  background: var(--color-primary-50);
}
.pd-row.on {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}
.pd-row-name {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--color-text);
}
.pd-row.on .pd-row-name {
  color: var(--color-primary-700);
}
.pd-code {
  flex: none;
  padding: 3px 7px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 6px;
  background: var(--color-slate-50, #f8fafc);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  color: var(--color-text-placeholder, #94a3b8);
}
.pd-empty {
  margin: 24px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--color-text-placeholder, #94a3b8);
}
</style>
