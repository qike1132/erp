/**
 * useProjectGrouping — 版师分组选择与项目编号 Hook
 *
 * 封装左侧版师列表的选中状态、当前分组计算，
 * 以及项目卡片的按日期递增编号（YYYYMMDD + 两位序号）。
 * 选中项目变化时自动切换到包含该项目的版师分组。
 * 逻辑自 CustomerGroupList.vue 原样搬移。
 */
import { ref, computed, watch, type Ref } from 'vue'
import type { PatternMakerGroup } from '@/api/patternRoom'

/** 分组 key：未分配版师使用固定占位 key */
function groupKey(makerId: number | null): string {
  return makerId != null ? String(makerId) : '_unassigned'
}

export function useProjectGrouping(
  groups: Ref<PatternMakerGroup[]>,
  selectedProjectId: Ref<number | null>,
) {
  /** 当前选中的版师 key */
  const selectedMakerKey = ref<string | null>(null)

  function isMakerSelected(makerId: number | null): boolean {
    return selectedMakerKey.value === groupKey(makerId)
  }

  function selectMaker(makerId: number | null) {
    selectedMakerKey.value = groupKey(makerId)
  }

  /** 当前选中的分组 */
  const selectedGroup = computed(() => {
    if (!selectedMakerKey.value) return null
    return groups.value.find((g) => groupKey(g.pattern_maker_id) === selectedMakerKey.value) ?? null
  })

  /** 按日期生成递增编号：YYYYMMDD + 两位序号（同天内按 updated_at 顺序递增） */
  const projectDisplayNumbers = computed(() => {
    const group = selectedGroup.value
    if (!group) return new Map<number, string>()

    const sorted = [...group.projects].sort((a, b) => {
      const ta = new Date(a.updated_at).getTime()
      const tb = new Date(b.updated_at).getTime()
      if (ta !== tb) return ta - tb
      return a.id - b.id
    })

    const counter = new Map<string, number>()
    const result = new Map<number, string>()

    for (const proj of sorted) {
      const dateKey = proj.updated_at.slice(0, 10)
      const dateNum = dateKey.replace(/-/g, '')
      const next = (counter.get(dateKey) ?? 0) + 1
      counter.set(dateKey, next)
      result.set(proj.id, `${dateNum}${String(next).padStart(2, '0')}`)
    }

    return result
  })

  // 默认选中第一个分组
  watch(
    groups,
    (g) => {
      if (g && g.length > 0 && selectedMakerKey.value === null) {
        selectedMakerKey.value = groupKey(g[0]!.pattern_maker_id)
      }
    },
    { immediate: true },
  )

  // 选中项目变化时，自动切换到包含该项目的版师分组
  // 场景：新增项目后选中新项目，但新项目所属版师与当前选中分组不同，
  // 若不切换分组，右侧卡片区域看不到新项目。
  watch(
    selectedProjectId,
    (newId) => {
      if (newId == null) return
      // 当前分组已包含该项目，无需切换
      if (selectedGroup.value?.projects.some((p) => p.id === newId)) return
      // 查找包含该项目的分组并切换
      const targetGroup = groups.value.find((g) => g.projects.some((p) => p.id === newId))
      if (targetGroup) {
        selectedMakerKey.value = groupKey(targetGroup.pattern_maker_id)
      }
    },
  )

  return {
    selectedMakerKey,
    isMakerSelected,
    selectMaker,
    selectedGroup,
    projectDisplayNumbers,
  }
}
