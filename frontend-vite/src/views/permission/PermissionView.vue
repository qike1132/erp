<template>
  <div class="permission-page">
    <UiPageHeader>权限管理<template #description>查看系统权限树结构</template></UiPageHeader>

    <UiCard>
      <div v-if="isLoading" class="flex items-center justify-center py-10 text-gray-400 gap-2">
        <UiSpinner /> 加载中...
      </div>
      <template v-else-if="permissionTree.length === 0">
        <UiEmpty description="暂无权限数据" />
      </template>
      <div v-else class="py-2">
        <PermissionNode v-for="node in permissionTree" :key="node.id" :node="node" :depth="0" />
      </div>
    </UiCard>
  </div>
</template>

<script setup lang="ts">
import { computed, h, defineComponent, PropType } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { permissionApi } from '@/api'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const PermissionNode = defineComponent({
  name: 'PermissionNode',
  props: {
    node: { type: Object as PropType<any>, required: true },
    depth: { type: Number, default: 0 },
  },
  setup(props) {
    return () => {
      const children = props.node.children || []
      return h('div', { style: { paddingLeft: `${props.depth * 24}px` } }, [
        h(
          'div',
          {
            class: 'flex items-center gap-2 py-1.5 px-2 rounded hover:bg-gray-50',
          },
          [
            h('i', {
              class: children.length > 0 ? 'fas fa-folder text-amber-500' : 'fas fa-file text-gray-400',
              style: { fontSize: '14px', width: '18px', textAlign: 'center' },
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
        ...children.map((child: any) => h(PermissionNode, { node: child, depth: props.depth + 1, key: child.id })),
      ])
    }
  },
})

const { data: result, isLoading } = useQuery({
  queryKey: ['permissions-tree'],
  queryFn: () => permissionApi.tree() as Promise<any>,
  staleTime: 60_000,
})

const permissionTree = computed(() => result.value?.tree ?? result.value ?? [])
</script>
