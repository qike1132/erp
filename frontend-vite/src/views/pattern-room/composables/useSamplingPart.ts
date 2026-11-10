/**
 * useSamplingPart — 部位布料数据 Hook
 *
 * 封装跨版本部位汇总（parts-by-version）的查询与局部更新（patch/append/remove/setFinalVersion）。
 * 部位写操作（批量新增/编辑/删除/复制）由 usePatternRoomPartActions 直接调用 API 并回到本 hook 局部更新。
 * 接收响应式 projectId，watch 自动重新加载部位列表。
 * 对应 design.md 2.4.6 E3。
 *
 * 性能优化：
 * - 当前版本部位列表从 partsByVersion 派生，无冗余请求
 * - watch 仅在 currentRoleId 非 null 时加载，避免 projectId 变化时重复触发
 * - 引入 _requestId 竞态保护，快速切换项目时忽略旧响应
 */
import { ref, computed, watch, type Ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type { PartDetail } from '@/api/patternRoom'
import { resolveSamplingErrorMessage } from './useSamplingErrors'

export function useSamplingPart(
  projectId: Ref<number | null>,
  currentRoleId: Ref<number | null>,
) {
  /** 跨版本部位汇总（所有版本扁平列表，带 version_no） */
  const partsByVersion = ref<PartDetail[]>([])
  /** 版本号列表 */
  const versionList = ref<string[]>([])
  /** 最终版本号（角色级默认；部位未单独选择时沿用） */
  const finalVersion = ref<string>('T1')
  /** 部位级最终版本覆盖（部位名称 → 版本号），优先于 finalVersion */
  const finalVersions = ref<Record<string, string>>({})
  /** 加载中 */
  const loading = ref(false)
  /** 提交中（新增/编辑/删除） */
  const submitting = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 竞态保护：每次发请求递增，响应回来时若不匹配则忽略 */
  let _requestId = 0

  /**
   * 当前版本的部位列表（从 partsByVersion 派生，不再单独请求）。
   * 取 finalVersion 对应的部位；无 finalVersion 时返回全部。
   */
  const parts = computed<PartDetail[]>(() => {
    const fv = finalVersion.value
    if (!fv) return partsByVersion.value
    return partsByVersion.value.filter((p) => p.version_no === fv)
  })

  /**
   * 加载跨版本部位汇总（部位+版本二维表数据源）
   * 内置竞态保护：快速切换项目/角色时旧响应被忽略。
   */
  async function fetchPartsByVersion(id: number, roleId?: number): Promise<void> {
    const reqId = ++_requestId
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.getPartsByVersion(id, roleId)
      if (reqId !== _requestId) return
      partsByVersion.value = res.items ?? []
      versionList.value = res.versions ?? []
      finalVersion.value = res.final_version ?? 'T1'
      finalVersions.value = res.final_versions ?? {}
    } catch (e) {
      if (reqId !== _requestId) return
      console.error('[useSamplingPart] 查询跨版本部位数据失败:', e)
      // 与 Project/Version/Role hook 一致：失败必须可见，
      // 否则用户只看到空表，会误判为"该项目没有部位"
      const message = resolveSamplingErrorMessage(e, '加载部位数据失败')
      error.value = message
      partsByVersion.value = []
      versionList.value = []
      finalVersion.value = 'T1'
      finalVersions.value = {}
    } finally {
      if (reqId === _requestId) loading.value = false
    }
  }

  /** 解析某部位当前生效的最终版本：部位级覆盖优先，否则角色级默认 */
  function resolveFinalVersion(partName: string): string {
    return finalVersions.value[partName] ?? finalVersion.value
  }

  /** 本地写入某部位的最终版本覆盖（设置成功后调用，避免全量重拉闪烁） */
  function setPartFinalVersionLocal(partName: string, versionNo: string): void {
    finalVersions.value = { ...finalVersions.value, [partName]: versionNo }
  }

  /**
   * 本地局部 patch：更新单个部位数据，避免全量 fetchPartsByVersion。
   * 写操作成功后调用，保持数据引用稳定，仅触发对应行重渲染。
   */
  function patchPart(partId: number, patch: Partial<PartDetail>): void {
    const idx = partsByVersion.value.findIndex((p) => p.id === partId)
    if (idx > -1) {
      partsByVersion.value[idx] = { ...partsByVersion.value[idx]!, ...patch }
    }
  }

  /**
   * 本地局部删除：移除单个部位，避免全量 fetchPartsByVersion。
   */
  function removePartLocal(partId: number): void {
    partsByVersion.value = partsByVersion.value.filter((p) => p.id !== partId)
  }

  /**
   * 本地追加部位：新增部位后追加到列表尾部，避免全量 fetchPartsByVersion。
   */
  function appendPart(part: PartDetail): void {
    partsByVersion.value = [...partsByVersion.value, part]
  }

  /** 清空部位状态 */
  function clearParts() {
    partsByVersion.value = []
    versionList.value = []
    finalVersion.value = 'T1'
    finalVersions.value = {}
    error.value = null
  }

  // watch projectId + currentRoleId 自动重新加载跨版本汇总
  // 优化：currentRoleId 为 null 时跳过（等待 roleHook 设置当前角色后再加载），
  // 避免 projectId 变化时 currentRoleId 先被置 null 导致无效请求
  watch(
    [projectId, currentRoleId],
    ([newId, newRoleId]) => {
      if (newId == null) {
        clearParts()
        return
      }
      if (newRoleId == null) return
      fetchPartsByVersion(newId, newRoleId)
    },
    { immediate: true },
  )

  return {
    parts,
    partsByVersion,
    versionList,
    loading,
    submitting,
    error,
    fetchPartsByVersion,
    setPartFinalVersionLocal,
    resolveFinalVersion,
    patchPart,
    removePartLocal,
    appendPart,
    finalVersion,
    finalVersions,
    clearParts,
  }
}
