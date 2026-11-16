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

    /**
     * 回退到兜底图标（'fas','circle'）。
     *
     * 必须先走 loadIcon('circle') 把 circle 注册进 library 再置 ready：vue-fontawesome
     * 渲染 ['prefix','iconName'] 时要查库，查不到就静默渲染成空 svg —— 那样「回退」等于
     * 换了个名字继续空白（首次进入未加载过 circle 的页面正是这种情形）。
     */
    function fallbackToCircle() {
      loadIcon('circle')
        .catch(() => null)
        .then(() => {
          resolvedIcon = ['fas', 'circle']
          ready.value = true
        })
    }

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
        .then((def) => {
          // P2（2026-10-24）+ 2026-11-16 审计：解析结果为 null 与「加载抛错」是同一处境的
          // 两种表现（未收录名走的是 loadIcon 的 `return Promise.resolve(null)` 分支，
          // 根本不会进 catch）——原先只挂 .catch 时，未收录图标会被当成「已就绪」渲染成
          // 空白 svg，页面静默缺图标且零报错。这里把 null 也归到回退分支。
          if (!def) throw new Error(`[FontAwesomeIconLazy] 图标不可用: ${canonical}`)
          resolvedIcon = [parsed.prefix, canonical]
          ready.value = true
        })
        .catch(() => {
          // P2（2026-10-24）：加载失败时回退到兜底图标，而不是用原值渲染（页面静默空白）。
          // 与 layouts/composables/useSidebarNav.ts 的 resolveIcon 兜底口径一致。
          fallbackToCircle()
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
