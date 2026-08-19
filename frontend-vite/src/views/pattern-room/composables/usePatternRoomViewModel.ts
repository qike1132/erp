import { ref, computed, watch, onMounted } from 'vue'
import { useCustomerSampling } from './useCustomerSampling'
import { useSamplingProject } from './useSamplingProject'
import { useSamplingPart } from './useSamplingPart'
import { useSamplingVersion } from './useSamplingVersion'
import { useSamplingRole } from './useSamplingRole'
import { usePatternRoomPrint } from './usePatternRoomPrint'
import { usePatternRoomPatternMakers } from './usePatternRoomPatternMakers'
import { usePatternRoomProjectActions } from './usePatternRoomProjectActions'
import { usePatternRoomPartActions } from './usePatternRoomPartActions'
import { usePatternRoomLayout } from './usePatternRoomLayout'
import { usePatternRoomGroupFilter } from './usePatternRoomGroupFilter'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePermission } from '@/composables/usePermission'

export function usePatternRoomViewModel() {
  const { hasPermission } = usePermission()
  const canManage = computed(() => hasPermission('customer_sampling_manage'))

  const groupHook = useCustomerSampling()
  const projectHook = useSamplingProject()

  const selectedProjectId = ref<number | null>(null)
  const roleHook = useSamplingRole(selectedProjectId)
  const partHook = useSamplingPart(selectedProjectId, roleHook.currentRoleId)
  const versionHook = useSamplingVersion(selectedProjectId, roleHook.currentRoleId)

  const {
    statusFilter,
    searchKeyword,
    onStatusChange,
    onGroupPageChange,
    onSearch,
  } = usePatternRoomGroupFilter(groupHook)

  const confirmDialog = useConfirmDialog()

  const {
    patternMakers,
    formPatternMakerId,
    loadPatternMakers,
    handleAddPatternMaker,
    handleDeletePatternMaker,
  } = usePatternRoomPatternMakers(canManage, confirmDialog)

  const { isNarrow, drawerOpen } = usePatternRoomLayout()

  onMounted(() => {
    groupHook.loadGrouped(searchKeyword.value || undefined, 'in_progress', 1)
    loadPatternMakers()
  })

  function onSelectProject(id: number) {
    selectedProjectId.value = id
    projectHook.fetchDetail(id)
    if (isNarrow.value) drawerOpen.value = false
  }

  function onSelectProjectFromDrawer(id: number) {
    onSelectProject(id)
  }

  const {
    printDialogRef,
    printParts,
    printRoles,
    canPrint,
    handlePrint,
  } = usePatternRoomPrint({
    selectedProjectId,
    partsByVersion: partHook.partsByVersion,
    roles: roleHook.roles,
  })

  const {
    projectFormVisible,
    projectFormMode,
    pendingProjectImage,
    openCreateProjectDialog,
    onEditProjectFromCard,
    onCompleteProjectFromCard,
    onCancelProjectFromCard,
    onProjectUploadImage,
    onProjectSubmitCreate,
    onProjectSubmitUpdate,
  } = usePatternRoomProjectActions({
    canManage,
    confirmDialog,
    groupHook,
    projectHook,
    selectedProjectId,
    searchKeyword,
    statusFilter,
    isNarrow,
    drawerOpen,
    formPatternMakerId,
    onSelectProject,
  })

  const {
    partFormVisible,
    versionCreateVisible,
    openCreatePartDialog,
    onPartSubmitBatch,
    onSetFinalVersion,
    onCopyPartVersion,
    onSaveEdit,
    onDeleteVersion,
    onVersionCreateConfirm,
    onSelectRole,
    onAddRole,
    onRemoveRole,
  } = usePatternRoomPartActions({
    canManage,
    confirmDialog,
    selectedProjectId,
    projectHook,
    partHook,
    versionHook,
    roleHook,
  })

  watch(selectedProjectId, (newId) => {
    if (newId == null) {
      projectHook.clearCurrent()
    }
  })

  return {
    canManage,
    canPrint,
    groupHook,
    projectHook,
    partHook,
    versionHook,
    roleHook,
    selectedProjectId,
    isNarrow,
    drawerOpen,
    confirmDialog,
    patternMakers,
    formPatternMakerId,
    projectFormVisible,
    projectFormMode,
    pendingProjectImage,
    partFormVisible,
    versionCreateVisible,
    printDialogRef,
    printParts,
    printRoles,
    onSelectProject,
    onSelectProjectFromDrawer,
    onSearch,
    onStatusChange,
    onGroupPageChange,
    handleAddPatternMaker,
    handleDeletePatternMaker,
    openCreateProjectDialog,
    onEditProjectFromCard,
    onCompleteProjectFromCard,
    onCancelProjectFromCard,
    onProjectUploadImage,
    onProjectSubmitCreate,
    onProjectSubmitUpdate,
    openCreatePartDialog,
    onPartSubmitBatch,
    onSetFinalVersion,
    onCopyPartVersion,
    onSaveEdit,
    onDeleteVersion,
    onVersionCreateConfirm,
    onSelectRole,
    onAddRole,
    onRemoveRole,
    handlePrint,
  }
}