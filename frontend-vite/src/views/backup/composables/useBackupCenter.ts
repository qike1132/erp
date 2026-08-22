/**
 * useBackupCenter — 备份中心编排 Hook（聚合器）
 *
 * 批次 2-3 拆分：实现按域迁移至
 *   useBackupTables（表信息/备份记录/完整性巡检）
 *   useBackupServerList（服务器备份列表/删除）
 *   useBackupActions（模式/导出/保存/增量/三类恢复/确认弹窗）
 * 本文件保持原返回形状不变，BackupView / ServerBackupList 零改动。
 */
import { useBackupTables } from './useBackupTables'
import { useBackupServerList } from './useBackupServerList'
import { useBackupActions } from './useBackupActions'

// 兼容 re-export：消费方此前自本模块导入这些类型（如 ServerBackupList.vue 的 ServerBackupItem）
export type { ServerBackupItem } from './useBackupServerList'
export type { BackupValidateSummary, RestoreSummary, BackupSaveResult } from './useBackupActions'

export function useBackupCenter() {
  const tablesView = useBackupTables()
  const serverList = useBackupServerList()
  const actions = useBackupActions({
    loadTables: tablesView.loadTables,
    loadServerBackups: serverList.loadServerBackups,
    serverBackups: serverList.serverBackups,
  })

  return {
    // 表信息
    ...tablesView,
    // 服务器备份
    ...serverList,
    // 动作域（覆盖 restoringFile 等恢复态）
    ...actions,
  }
}
