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
        <template v-if="hasChildren">
          <p class="pd-group">模块访问</p>
          <PermissionRow
            :item="node"
            :checked="isPermChecked(node.id)"
            @toggle="togglePermNode(node.id)"
          />
          <p class="pd-group">操作权限</p>
          <!-- 子权限正好是 /report 的行内操作码时，一行一个 TAB（每个 TAB 一对 编辑/删除） -->
          <template v-if="rowActionGroups">
            <div v-for="g in rowActionGroups" :key="g.label" class="pd-trow">
              <span class="pd-tnm">{{ g.label }}</span>
              <PermissionChip
                v-if="g.edit"
                :checked="isPermChecked(g.edit.id)"
                :label="`编辑${g.label}`"
                @toggle="togglePermNode(g.edit.id)"
              >
                编辑
              </PermissionChip>
              <PermissionChip
                v-if="g.delete"
                :checked="isPermChecked(g.delete.id)"
                :label="`删除${g.label}`"
                @toggle="togglePermNode(g.delete.id)"
              >
                删除
              </PermissionChip>
            </div>
          </template>
          <!-- 其它模块：一行一项（权限名 + 开关胶囊） -->
          <template v-else>
            <PermissionRow
              v-for="row in childRows"
              :key="row.id"
              :item="row"
              :checked="isPermChecked(row.id)"
              @toggle="togglePermNode(row.id)"
            />
          </template>
        </template>
        <PermissionRow
          v-else
          :item="node"
          :checked="isPermChecked(node.id)"
          @toggle="togglePermNode(node.id)"
        />
      </div>
    </template>
    <p v-else class="pd-empty">请选择左侧模块</p>
  </section>
</template>

<script setup lang="ts">
/**
 * PermissionDetailPanel.vue — 分配权限弹窗右栏：当前模块的权限清单
 *
 * 有子权限的模块先列「模块访问」（模块自身 = 可见/查看授权），再列「操作权限」。
 * 「操作权限」有两种呈现：
 * - **按 TAB 归组**（一行一个 TAB，每个 TAB 一对 编辑/删除 胶囊）：当子权限正好是
 *   /report 的行内操作码时启用（见 @/constants/reportRowActions）。这样
 *   「订单流水」下 5 个 tab × 编辑/删除 一眼看全，不用猜哪个码属于哪个 tab。
 * - **一行一项**：其它模块一行一个权限（权限名 + 开关胶囊）。
 */
import { computed } from 'vue'
import type { PermissionItem } from '@/types'
import PermissionChip from '@/views/user/components/PermissionChip.vue'
import PermissionRow from '@/views/user/components/PermissionRow.vue'
import { ROW_ACTION_TABS } from '@/constants/reportRowActions'
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

/** 一个 TAB 的「编辑/删除」一对权限 */
interface RowActionGroup {
  label: string
  edit?: PermissionItem
  delete?: PermissionItem
}

/** 模块是否带操作权限 */
const hasChildren = computed(() => (props.node?.children?.length ?? 0) > 0)

/** 一行一项路径用的子权限行 */
const childRows = computed<PermissionItem[]>(() =>
  hasChildren.value ? (props.node?.children ?? []) : [],
)

/**
 * 子权限正好是 /report 的行内操作码（`${resource}_edit` / `_delete`）时按 TAB 归组；
 * 只要有一个子项不属于这套码，就返回 null 走「一行一项」（避免误把别的模块也当 TAB 结构）。
 */
const rowActionGroups = computed<RowActionGroup[] | null>(() => {
  const children = props.node?.children ?? []
  if (children.length === 0) return null
  const groups: RowActionGroup[] = []
  const matched = new Set<number>()
  for (const tab of ROW_ACTION_TABS) {
    const edit = children.find((c) => c.code === `${tab.resource}_edit`)
    const del = children.find((c) => c.code === `${tab.resource}_delete`)
    if (edit) matched.add(edit.id)
    if (del) matched.add(del.id)
    if (edit || del) groups.push({ label: tab.label, edit, delete: del })
  }
  return matched.size === children.length ? groups : null
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
.pd-link {
  flex: none;
  padding: 0;
  border: none;
  background: none;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-600);
  cursor: pointer;
}
.pd-link:hover {
  text-decoration: underline;
}
.pd-empty {
  margin: 24px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--color-text-placeholder, #94a3b8);
}

/* ===== TAB 归组行（一行一个 TAB） ===== */
.pd-trow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 10px;
  background: #fff;
}
.pd-trow:hover {
  border-color: var(--color-primary-200);
  background: #fcfdff;
}
.pd-tnm {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
}
</style>
