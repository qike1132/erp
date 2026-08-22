/**
 * usePatternRoomPartActions — 部位/版本/角色动作编排 Hook（聚合器）
 *
 * 批次 2-3 拆分：实现按动作域迁移至
 *   usePartActions（部位批量创建/内联编辑/复制删除版本/设最终版本）
 *   useVersionActions（版本弹窗/切换/当前版本判定）
 *   useRoleActions（角色切换与增删）
 * 本文件保持原公共 API 与返回形状不变，PatternRoomView 等消费方零改动。
 */
import type { Ref } from 'vue'
import type { PatternRoomActionContext } from './usePartActions'
import { usePartActions } from './usePartActions'
import { useVersionActions } from './useVersionActions'
import { useRoleActions } from './useRoleActions'
export type { RoleRemovePayload } from './useRoleActions'

/** 兼容原导出名：与 PatternRoomActionContext 同构 */
export interface UsePatternRoomPartActionsOptions extends PatternRoomActionContext {
  canManage: Ref<boolean>
}

export function usePatternRoomPartActions(options: UsePatternRoomPartActionsOptions) {
  const partActions = usePartActions(options)
  const versionActions = useVersionActions(options)
  const roleActions = useRoleActions(options)

  return {
    ...partActions,
    ...versionActions,
    ...roleActions,
  }
}
