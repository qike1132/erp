<template>
  <!-- 权限分配弹窗（双栏主从：左选模块 → 右配权限） -->
  <UiDialog
    :open="permDialogVisible"
    title="分配权限"
    max-width-class="max-w-[880px]"
    @update:open="permDialogVisible = $event"
  >
    <div class="pd-head">
      <span class="pd-head-label">目标用户</span>
      <span class="pd-head-name">{{ permTargetName }}</span>
      <span class="pd-head-total">已选 <b>{{ checkedTotal }}</b> / {{ totalIds }} 项</span>
    </div>

    <div class="pd-panes">
      <PermissionModuleList
        v-model:query="query"
        :sections="visibleSections"
        :active-module-id="activeModuleId"
        :perm-checked-keys="permCheckedKeys"
        :perm-is-all-checked="permIsAllChecked"
        :toggle-perm-node="togglePermNode"
        :toggle-all-perms="toggleAllPerms"
        @select="activeModuleId = $event"
      />
      <PermissionDetailPanel
        :node="activeNode"
        :perm-checked-keys="permCheckedKeys"
        :is-perm-checked="isPermChecked"
        :toggle-perm-node="togglePermNode"
      />
    </div>

    <template #footer>
      <span class="pd-foot-total">已选 <b>{{ checkedTotal }}</b> / {{ totalIds }} 项</span>
      <button class="pd-btn" aria-label="取消" @click="permDialogVisible = false">取消</button>
      <button
        class="pd-btn pd-btn-primary"
        :disabled="permSubmitting"
        :aria-label="permSubmitting ? '保存中…' : '保存'"
        @click="handleSavePermission"
      >
        {{ permSubmitting ? '保存中…' : '保存' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * UserPermissionDialog.vue — 权限分配弹窗（双栏主从的外壳）
 *
 * 本组件只负责：弹窗外壳、目标用户/全局计数，以及「搜索词 + 当前选中模块」这两个
 * 视图状态与它们的联动；左栏渲染在 PermissionModuleList、右栏在 PermissionDetailPanel。
 *
 * 分区顺序/命名由父组件（useUserManagement）以导航栏为权威源传入；勾选状态与级联
 * 逻辑由父组件经 props 传入。
 */
import { computed, ref, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { PermissionItem } from '@/types'
import PermissionModuleList from '@/views/user/components/PermissionModuleList.vue'
import PermissionDetailPanel from '@/views/user/components/PermissionDetailPanel.vue'
import {
  collectSectionIds,
  countChecked,
  filterPermissionSections,
  type PermissionSection,
} from '@/views/user/composables/useUserManagement'

const props = defineProps<{
  /** 权限分配目标用户名 */
  permTargetName: string
  /** 按模块分组的权限树（section 顺序/命名与导航栏一致） */
  permissionSections: PermissionSection[]
  /** 已勾选权限 id 列表 */
  permCheckedKeys: number[]
  /** 是否全选 */
  permIsAllChecked: boolean
  /** 保存进行中 */
  permSubmitting: boolean
  /** 判断是否已勾选 */
  isPermChecked: (id: number) => boolean
  /** 切换勾选（父子级联） */
  togglePermNode: (id: number) => void
  /** 全选/取消全选 */
  toggleAllPerms: () => void
  /** 保存权限分配 */
  handleSavePermission: () => void
}>()

/** 弹窗开关（父组件 v-model:open） */
const permDialogVisible = defineModel<boolean>('open', { default: false })

/** 左栏搜索词 */
const query = ref('')
/** 右栏当前展示的模块（顶层权限）id */
const activeModuleId = ref(0)

/** 过滤后的分区（左栏可见部分） */
const visibleSections = computed(() =>
  filterPermissionSections(props.permissionSections, query.value),
)

/** 右栏当前模块；无匹配时取首个可见模块 */
const activeNode = computed<PermissionItem | undefined>(() => {
  for (const sec of visibleSections.value) {
    const hit = sec.items.find((n) => n.id === activeModuleId.value)
    if (hit) return hit
  }
  return visibleSections.value[0]?.items[0]
})

/** 全部权限 id（含子权限），用于全局计数 */
const allIds = computed(() => props.permissionSections.flatMap(collectSectionIds))
const totalIds = computed(() => allIds.value.length)
const checkedTotal = computed(() => countChecked(allIds.value, props.permCheckedKeys))

// 打开弹窗 / 权限树变化时重置搜索与选中
watch(
  () => props.permissionSections,
  (secs) => {
    query.value = ''
    activeModuleId.value = secs[0]?.items[0]?.id ?? 0
  },
  { immediate: true },
)

// 搜索把当前模块过滤掉时，自动落到首个可见模块
watch(visibleSections, (secs) => {
  const ids = secs.flatMap((s) => s.items.map((i) => i.id))
  if (!ids.includes(activeModuleId.value)) activeModuleId.value = ids[0] ?? 0
})
</script>

<style scoped>
.pd-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border-light, #e8ecf1);
}
.pd-head-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}
.pd-head-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}
.pd-head-total {
  margin-left: auto;
  font-size: 12.5px;
  color: var(--color-text-muted);
}
.pd-head-total b,
.pd-foot-total b {
  color: var(--color-primary-600);
}
.pd-panes {
  display: flex;
  height: min(58vh, 520px);
  margin-top: 12px;
}
.pd-foot-total {
  margin-right: auto;
  font-size: 12.5px;
  color: var(--color-text-muted);
}
.pd-btn {
  padding: 7px 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.pd-btn-primary {
  border-color: var(--color-primary-500);
  background: var(--color-primary-500);
  color: #fff;
}
.pd-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
}
.pd-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
