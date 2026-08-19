import { reactive, ref, watch, type Ref } from 'vue'
import type { PartDetail } from '@/api/patternRoom'

export interface PartEditData {
  supplier_name: string
  fabric_name: string
  fabric_color_no: string
}

export function usePartInlineEdit(
  partsByVersion: Ref<PartDetail[]>,
  projectId: Ref<number | null | undefined>,
  currentRoleId: Ref<number | null>,
  onSave: (part: PartDetail, data: PartEditData) => void,
) {
  const editingPartId = ref<number | undefined>(undefined)
  const editForm = reactive({
    supplier_name: '',
    fabric_name: '',
    fabric_color_no: '',
  })

  function startEdit(part: PartDetail) {
    if (part.id == null) return
    editingPartId.value = part.id
    editForm.supplier_name = part.supplier_name || ''
    editForm.fabric_name = part.fabric_name || ''
    editForm.fabric_color_no = part.fabric_color_no || ''
  }

  function cancelEdit() {
    editingPartId.value = undefined
  }

  function saveEdit(part: PartDetail) {
    editingPartId.value = undefined
    onSave(part, { ...editForm })
  }

  watch(() => partsByVersion.value, () => { editingPartId.value = undefined })
  watch(
    [projectId, currentRoleId],
    () => { editingPartId.value = undefined },
  )

  return { editingPartId, editForm, startEdit, cancelEdit, saveEdit }
}