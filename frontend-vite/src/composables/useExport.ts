/**
 * 统一导出 composable
 *
 * 封装各视图重复的导出流程：开始提示 → 执行导出动作 → 成功/失败提示 → loading 态。
 * 导出动作由调用方以回调传入，内部通常调用 API 层的 download / postDownload
 * （已完成取 Blob 与触发下载），或 utils/csv.ts 的 downloadCsv（前端拼 CSV 场景）。
 */
import { ref } from 'vue'
import { toast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

/** 导出各阶段提示文案；传 false 表示该阶段不提示 */
export interface ExportMessages {
  /** 开始提示，默认 '正在导出...' */
  start?: string | false
  /** 成功提示，默认 '导出成功' */
  success?: string | false
  /** 失败提示兜底文案（优先展示接口返回的详细错误），默认 '导出失败' */
  error?: string | false
}

export function useExport(defaultMessages: ExportMessages = {}) {
  /** 导出进行中标记，可绑定到导出按钮的 disabled / loading */
  const exporting = ref(false)

  /**
   * 执行导出动作并统一处理提示与 loading
   *
   * @param action 导出动作（内部完成下载触发），抛出异常视为失败
   * @param messages 覆盖默认提示文案（与 useExport 的默认配置合并，后者优先级更低）
   * @returns 是否导出成功
   */
  async function runExport(
    action: () => unknown,
    messages: ExportMessages = {},
  ): Promise<boolean> {
    const m = { start: '正在导出...', success: '导出成功', error: '导出失败', ...defaultMessages, ...messages }
    // 防止重复点击触发并发导出
    if (exporting.value) return false
    exporting.value = true
    if (m.start !== false) toast.info(m.start)
    try {
      await action()
      if (m.success !== false) toast.success(m.success)
      return true
    } catch (e: unknown) {
      console.error('[useExport] 导出失败:', e)
      if (m.error !== false) toast.error(getErrorMessage(e, m.error))
      return false
    } finally {
      exporting.value = false
    }
  }

  return { exporting, runExport }
}
