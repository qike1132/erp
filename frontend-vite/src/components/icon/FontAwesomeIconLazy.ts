import { defineComponent, h, ref, watch, type PropType } from 'vue'
import { FontAwesomeIcon, type IconProp } from '@fortawesome/vue-fontawesome'
import { parse, findIconDefinition, type IconLookup } from '@fortawesome/fontawesome-svg-core'
import { loadIcon, canonicalIconName } from '@/utils/fontAwesomeLoader'

/**
 * 懒加载版 FontAwesomeIcon：
 * 保持既有 name-based 用法（icon="plus" / :icon="tab.icon"）不变，
 * 首次遇到未注册图标时按需动态导入并注册，避免全部 solid 图标进入首屏。
 */
export const FontAwesomeIconLazy = defineComponent({
  name: 'FontAwesomeIcon',
  inheritAttrs: false,
  props: {
    icon: {
      type: [String, Array, Object] as PropType<IconProp>,
      required: true,
    },
  },
  setup(props, { attrs, slots }) {
    const ready = ref(false)
    let resolvedIcon: IconProp = props.icon

    function resolveIcon() {
      const raw = props.icon

      // 组件内局部导入的完整 IconDefinition 对象直接渲染，无需查库
      if (
        raw &&
        typeof raw === 'object' &&
        !Array.isArray(raw) &&
        'icon' in (raw as Record<string, unknown>)
      ) {
        resolvedIcon = raw
        ready.value = true
        return
      }

      const parsed = parse.icon(raw as string | IconLookup | [string, string]) as IconLookup | null
      if (!parsed) {
        ready.value = true
        return
      }

      const canonical = canonicalIconName(parsed.iconName)
      if (findIconDefinition({ prefix: parsed.prefix, iconName: canonical } as IconLookup)) {
        resolvedIcon = [parsed.prefix, canonical]
        ready.value = true
        return
      }

      ready.value = false
      loadIcon(canonical)
        .then(() => {
          resolvedIcon = [parsed.prefix, canonical]
          ready.value = true
        })
        .catch(() => {
          // P2（2026-10-24）：加载失败时回退到兜底图标，而不是用原值渲染（页面静默空白）。
          // 与 layouts/composables/useSidebarNav.ts 的 resolveIcon 兜底口径一致。
          resolvedIcon = ['fas', 'circle']
          ready.value = true
        })
    }

    resolveIcon()
    watch(() => props.icon, () => resolveIcon())

    return () => {
      if (!ready.value) return null
      return h(FontAwesomeIcon, { ...attrs, icon: resolvedIcon } as never, slots.default?.())
    }
  },
})
