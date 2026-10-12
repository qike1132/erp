<template>
  <aside class="pd-left">
    <div class="pd-left-head">
      <label class="pd-search">
        <FontAwesomeIcon icon="search" aria-hidden="true" />
        <input
          v-model="query"
          type="search"
          autocomplete="off"
          placeholder="搜索模块或权限…"
          aria-label="搜索模块或权限"
        />
      </label>
      <button type="button" class="pd-link" @click="toggleAllPerms">
        {{ permIsAllChecked ? '清空' : '全选' }}
      </button>
    </div>
    <div class="pd-list">
      <template v-for="sec in sections" :key="sec.key">
        <p class="pd-sec">{{ sec.name }}</p>
        <div
          v-for="node in sec.items"
          :key="node.id"
          class="pd-mod"
          :class="{ act: node.id === activeModuleId }"
          :aria-current="node.id === activeModuleId ? 'true' : undefined"
          tabindex="0"
          @click="$emit('select', node.id)"
          @keydown.enter.prevent="$emit('select', node.id)"
        >
          <PermissionCheckBox
            :state="stateOf(node)"
            :label="node.name"
            @toggle="togglePermNode(node.id)"
          />
          <FontAwesomeIcon
            v-if="node.icon"
            :icon="node.icon.replace('fa-', '')"
            class="pd-mod-icon"
            aria-hidden="true"
          />
          <span class="pd-mod-name">{{ node.name }}</span>
          <span class="pd-pill" :class="{ all: stateOf(node) === 'all' }">{{ countOf(node) }}</span>
        </div>
      </template>
      <p v-if="sections.length === 0" class="pd-empty">
        {{ query.trim() ? '没有匹配的模块' : '暂无权限数据' }}
      </p>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * PermissionModuleList.vue — 分配权限弹窗左栏：分区 → 模块清单
 *
 * 每行一个模块：三态勾选框（级联）+ 图标 + 名称 + 「已选/总数」进度胶囊；
 * 点击行选中该模块（右栏随之切换），点勾选框只切权限、不切换选中。
 */
import type { PermissionItem } from '@/types'
import PermissionCheckBox from '@/views/user/components/PermissionCheckBox.vue'
import {
  collectModuleIds,
  countChecked,
  getPermissionCheckState,
  type PermissionCheckState,
  type PermissionSection,
} from '@/views/user/composables/useUserManagement'

const props = defineProps<{
  /** 过滤后的分区（顺序/命名与导航栏一致） */
  sections: PermissionSection[]
  /** 当前选中的模块 id */
  activeModuleId: number
  /** 已勾选权限 id 列表 */
  permCheckedKeys: number[]
  /** 是否全选 */
  permIsAllChecked: boolean
  /** 切换勾选（父子级联） */
  togglePermNode: (id: number) => void
  /** 全选/取消全选 */
  toggleAllPerms: () => void
}>()

/** 搜索词（父组件持有） */
const query = defineModel<string>('query', { required: true })

defineEmits<{ select: [id: number] }>()

/** 模块的勾选状态 */
function stateOf(node: PermissionItem): PermissionCheckState {
  return getPermissionCheckState(collectModuleIds(node), props.permCheckedKeys)
}

/** 模块的「已选/总数」文本 */
function countOf(node: PermissionItem): string {
  const ids = collectModuleIds(node)
  return `${countChecked(ids, props.permCheckedKeys)}/${ids.length}`
}
</script>

<style scoped>
.pd-left {
  width: 252px;
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--color-border-light, #e8ecf1);
  border-radius: 12px;
  background: #fbfcff;
  overflow: hidden;
}
.pd-left-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border-light, #e8ecf1);
}
.pd-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  padding: 5px 9px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: #fff;
  color: var(--color-text-placeholder, #94a3b8);
  font-size: 12px;
}
.pd-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 12.5px;
  color: var(--color-text);
}
.pd-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 8px 12px;
}
.pd-sec {
  margin: 0;
  padding: 10px 8px 5px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--color-text-placeholder, #94a3b8);
}
.pd-mod {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border-radius: 9px;
  cursor: pointer;
  color: var(--color-text-secondary);
}
.pd-mod:hover {
  background: var(--color-primary-50);
}
.pd-mod.act {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-weight: 700;
}
.pd-mod-icon {
  width: 17px;
  flex: none;
  text-align: center;
  font-size: 13px;
  color: var(--color-primary-400);
}
.pd-mod.act .pd-mod-icon {
  color: var(--color-primary-600);
}
.pd-mod-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pd-pill {
  flex: none;
  padding: 1px 8px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 999px;
  background: #fff;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted);
}
.pd-pill.all {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: #fff;
}
.pd-empty {
  margin: 24px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--color-text-placeholder, #94a3b8);
}
</style>
