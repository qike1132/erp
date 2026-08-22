<template>
  <div class="permission-page">
    <UiPageHeader>权限管理<template #description>查看系统权限树结构</template></UiPageHeader>

    <UiCard>
      <div v-if="isLoading" class="flex items-center justify-center py-10 text-gray-400 gap-2">
        <UiSpinner /></div>
      <template v-else-if="permissionTree.length === 0">
        <UiEmpty text="暂无权限数据" />
      </template>
      <div v-else class="py-2">
        <PermissionNode v-for="node in permissionTree" :key="node.id" :node="node" :depth="0" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, h, defineComponent, PropType, type VNode } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import { permissionApi } from '@/api'
import type { PermissionItem } from '@/types'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const PermissionNode = defineComponent({
  name: 'PermissionNode',
  props: {
    node: { type: Object as PropType<PermissionItem>, required: true },
    depth: { type: Number, default: 0 },
  },
  setup(props) {
    // 显式标注渲染函数返回类型，避免 PermissionNode 自引用导致循环推断
    return (): VNode => {
      const children = props.node.children || []
      return h('div', { style: { paddingLeft: `${props.depth * 24}px` } }, [
        h(
          'div',
          {
            class: 'flex items-center gap-2 py-1.5 px-2 rounded hover:bg-gray-50',
          },
          [
            h(FontAwesomeIcon, {
              icon: children.length > 0 ? 'fas fa-folder' : 'fas fa-file',
              class: children.length > 0 ? 'text-amber-500' : 'text-gray-400',
              style: { fontSize: '14px', width: '18px', textAlign: 'center' },
              'aria-hidden': true,
            }),
            h('span', { class: 'text-sm text-gray-700' }, props.node.name),
            h(
              'span',
              {
                class: 'text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500',
              },
              props.node.code,
            ),
          ],
        ),
        ...children.map((child) => h(PermissionNode, { node: child, depth: props.depth + 1, key: child.id })),
      ])
    }
  },
})

const { data: result, isLoading } = useQuery({
  queryKey: ['permissions-tree'],
  queryFn: () => permissionApi.tree(),
  staleTime: 60_000,
})

const permissionTree = computed(() => {
  // 兼容历史 { tree: PermissionItem[] } 包裹结构；后端当前返回裸数组
  const wrapped = result.value as unknown as { tree?: PermissionItem[] } | null | undefined
  return wrapped?.tree ?? result.value ?? []
})
</script>
