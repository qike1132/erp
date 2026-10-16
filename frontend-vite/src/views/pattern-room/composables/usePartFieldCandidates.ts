import { ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type { PartFieldCandidateValue } from '@/api/patternRoom'

/**
 * usePartFieldCandidates —— 板房「供应商 / 布料名称」历史候选的页面级缓存
 *
 * 背景：候选值只存在于后端 DB，前端必须拉取。但录入入口有两处（批量新增弹窗 +
 * 二维表行内编辑），且行内编辑是「每行一个 combobox」。故缓存的宿主必须是页面级
 * （PatternRoomView 调一次，provide 下发），行组件只消费 get() 不调 load()，
 * 否则 N 行就是 N 个请求。
 *
 * 设计要点：
 * - inflight 去重：并发 load() 共享同一个 Promise，只发一次请求
 * - settled 复用：请求成功后缓存结果，后续 load() 直接返回缓存
 * - fail-open：请求失败只 warn，get() 返回空数组，不阻塞录入
 *   （下拉会退化成纯文本框，用户仍可自由输入新值）
 *
 * 注意：缓存的只有候选数组（只读）。每个 combobox 的 open/highlight/text 是
 * 各自组件内的 ref，不会因共享缓存而串行。
 */

export type CandidateField = 'supplier_name' | 'fabric_name'

export function usePartFieldCandidates() {
  const cache = ref<Record<string, PartFieldCandidateValue[]>>({})
  const inflight = ref<Promise<void> | null>(null)
  /** 已成功拉取过（用于「失败后可重试」：失败不清 settled，成功才置位） */
  let settled = false

  /**
   * 拉取候选值（幂等）。已 settled 直接返回；进行中则复用 inflight Promise。
   * 失败静默（fail-open），不抛出，避免一个辅助下拉拖垮录入流程。
   */
  async function load(): Promise<void> {
    if (settled) return
    if (inflight.value) return inflight.value

    const p = (async () => {
      try {
        const res = await patternRoomApi.getPartFieldCandidates()
        cache.value = res?.fields ?? {}
        settled = true
      } catch (e) {
        console.warn('[usePartFieldCandidates] 历史候选加载失败，降级为纯文本输入:', e)
      } finally {
        inflight.value = null
      }
    })()
    inflight.value = p
    return p
  }

  /** 取某字段的候选数组；未加载 / 加载失败 / 字段无候采访时均返回空数组 */
  function get(field: string): PartFieldCandidateValue[] {
    return cache.value[field] ?? []
  }

  return { load, get }
}
