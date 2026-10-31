import { onBeforeRouteLeave } from 'vue-router'

/**
 * useSummaryLeaveGuard — 汇总下单整页视图的「编辑态离开确认」守卫。
 *
 * 2026-10-31 随弹窗整页化引入：弹窗时代遮罩盖住侧边栏、天然拦住导航；整页化后
 * 侧边栏可点，需要显式把守「未保存内容」。守卫逻辑整体放在本 composable
 * （PurchaseView.vue 已在 400 行门禁边缘，接线必须一行化）。
 *
 * 判定口径（与弹窗时代「遮罩不关闭」的防误触意图一致，只拦有未保存内容的态）：
 * - `editMode`：自定义编辑态（数量/损耗率改动未保存）；
 * - `lossRateTouched`：损耗率已交互但尚未落库完成（自动落库在途/失败残留）；
 * - `lossRateSaveState === 'saving'`：落库请求在途，直接离开会丢回写。
 * 其余状态（非编辑态且损耗率已同步/未动过）直接放行——损耗率是自动落库的，
 * 没有传统意义的「未保存内容」。
 *
 * confirm 返回 Promise<boolean>（复用 PurchaseView 的 useConfirmDialog），
 * 语义即「用户是否确认离开」；守卫不关心 UI 如何呈现。
 */

interface SummaryGuardTarget {
  open: boolean
  editMode: boolean
  lossRateTouched: boolean
  lossRateSaveState: 'idle' | 'saving' | 'saved' | 'error'
  close: () => void
}

interface ConfirmFn {
  (msg: string, sub?: string, type?: 'danger' | 'warning'): Promise<boolean>
}

/** 「有未保存内容」的统一判定：路由守卫与返回按钮共用同一口径 */
function isSummaryDirty(summary: SummaryGuardTarget): boolean {
  return summary.editMode || summary.lossRateTouched || summary.lossRateSaveState === 'saving'
}

/** 守卫 + 返回按钮的一体化接线：挂路由守卫，返回 handleSummaryClose 给模板用 */
export function useSummaryLeaveGuard(summary: SummaryGuardTarget, confirm: ConfirmFn) {
  async function confirmLeaveSummary(): Promise<boolean> {
    const allowed = await confirm(
      '离开汇总下单？',
      '当前有未保存的编辑（数量/损耗率），离开将丢弃这些改动。',
      'warning',
    )
    if (allowed) summary.close()
    return allowed
  }

  onBeforeRouteLeave(async () => {
    if (!summary.open || !isSummaryDirty(summary)) return true
    return confirmLeaveSummary()
  })

  /** 「返回订单列表」按钮（及页签底部的返回）：编辑态先确认，非编辑态直接返回 */
  async function handleSummaryClose() {
    if (isSummaryDirty(summary)) {
      const allowed = await confirmLeaveSummary()
      if (!allowed) return
    }
    summary.close()
  }

  return { handleSummaryClose }
}
