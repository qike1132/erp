/**
 * useProjectForm — 打样项目新增/编辑表单业务逻辑
 *
 * 封装表单状态、角色列表、产品图片上传前压缩与本地预览、
 * 版师选择/删除联动、提交（创建/更新）。
 * 版师自定义下拉的 UI 状态（展开/外点关闭/内联新增）由 PatternMakerSelect 子组件自管。
 */
import { reactive, ref, computed, watch, onBeforeUnmount } from 'vue'
import { toast } from '@/composables/useToast'
import type { PatternMaker } from '@/api/patternMaker'
import type { ProjectDetailResponse, ProjectCreateRequest, ProjectUpdateRequest } from '@/api/patternRoom'

export interface ProjectFormDialogProps {
  visible: boolean
  project: ProjectDetailResponse | null
  patternMakers: PatternMaker[]
  patternMakerId: number | null
  submitting: boolean
}

export type ProjectFormDialogEmit = (
  event:
    | 'update:visible'
    | 'update:patternMakerId'
    | 'submit-create'
    | 'submit-update'
    | 'upload-image'
    | 'remove-image'
    | 'add-pattern-maker'
    | 'delete-pattern-maker',
  ...args: unknown[]
) => void

const UPLOAD_MAX_EDGE = 1600
const UPLOAD_QUALITY = 0.82

async function compressImageFile(file: File): Promise<File> {
  if (file.type === 'image/webp' && file.size <= 1.5 * 1024 * 1024) return file
  try {
    const bitmap = await createImageBitmap(file)
    const { width, height } = bitmap
    const scale = Math.min(1, UPLOAD_MAX_EDGE / Math.max(width, height))
    if (scale === 1 && file.type === 'image/jpeg' && file.size <= 2 * 1024 * 1024) {
      bitmap.close()
      return file
    }
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return file
    }
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close()
    const stem = file.name.replace(/\.(jpe?g|png|webp)$/i, '') || 'image'
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', UPLOAD_QUALITY))
    if (blob && blob.type === 'image/webp') {
      return new File([blob], `${stem}.webp`, { type: 'image/webp' })
    }
    const jpegBlob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', UPLOAD_QUALITY))
    if (jpegBlob) {
      return new File([jpegBlob], `${stem}.jpg`, { type: 'image/jpeg' })
    }
    return file
  } catch (e) {
    console.warn('[ProjectFormDialog] 图片压缩失败，使用原图:', e)
    return file
  }
}

export function useProjectForm(props: ProjectFormDialogProps, emit: ProjectFormDialogEmit) {
  const isEditing = computed(() => props.project != null)

  const form = reactive({
    product_name: '',
    remark: '',
  })

  const roleNames = ref<string[]>([''])

  function selectMaker(id: number | null) {
    emit('update:patternMakerId', id)
  }

  function onDeleteMaker(id: number, name: string) {
    emit('delete-pattern-maker', id)
    if (props.patternMakerId === id) {
      emit('update:patternMakerId', null)
    }
    void name
  }

  const previewUrl = ref<string | null>(null)
  const isDragOver = ref(false)

  function revokePreview() {
    if (previewUrl.value?.startsWith('blob:')) {
      URL.revokeObjectURL(previewUrl.value)
    }
  }

  watch(
    () => props.visible,
    (val) => {
      if (val) {
        if (props.project) {
          form.product_name = props.project.product_name ?? ''
          form.remark = props.project.remark ?? ''
          revokePreview()
          previewUrl.value = props.project.product_image_url ?? null
        } else {
          form.product_name = ''
          form.remark = ''
          roleNames.value = ['']
          revokePreview()
          previewUrl.value = null
        }
      }
    },
  )

  onBeforeUnmount(revokePreview)

  async function applyImageFile(file: File) {
    const allowed = ['image/jpeg', 'image/png', 'image/webp']
    if (!allowed.includes(file.type)) {
      toast.warning('仅支持 JPEG / PNG / WebP 格式')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.warning('图片大小不能超过 10MB')
      return
    }
    const finalFile = await compressImageFile(file)
    revokePreview()
    previewUrl.value = URL.createObjectURL(finalFile)
    emit('upload-image', finalFile)
  }

  function onFileChange(e: Event) {
    const target = e.target as HTMLInputElement
    const file = target.files?.[0]
    if (!file) return
    void applyImageFile(file)
    target.value = ''
  }

  function onDragOver(e: DragEvent) {
    if (Array.from(e.dataTransfer?.types ?? []).includes('Files')) {
      isDragOver.value = true
    }
  }

  function onDragLeave() {
    isDragOver.value = false
  }

  function onDrop(e: DragEvent) {
    isDragOver.value = false
    const file = e.dataTransfer?.files?.[0]
    if (!file) return
    void applyImageFile(file)
  }

  function removeImage() {
    revokePreview()
    previewUrl.value = null
    emit('remove-image')
  }

  function handleSubmit() {
    if (isEditing.value) {
      const data: ProjectUpdateRequest = {
        product_name: form.product_name || null,
        pattern_maker_id: props.patternMakerId,
        remark: form.remark || null,
        version: props.project!.version,
      }
      emit('submit-update', data)
    } else {
      const trimmed = roleNames.value.map((n) => n.trim()).filter((n) => n.length > 0)
      const uniqueRoles = Array.from(new Set(trimmed))
      const data: ProjectCreateRequest = {
        product_name: form.product_name,
        pattern_maker_id: props.patternMakerId,
        remark: form.remark || null,
        initial_roles: uniqueRoles.length > 0 ? uniqueRoles : null,
      }
      emit('submit-create', data)
    }
  }

  return {
    isEditing,
    form,
    roleNames,
    selectMaker,
    onDeleteMaker,
    previewUrl,
    isDragOver,
    onFileChange,
    onDragOver,
    onDragLeave,
    onDrop,
    removeImage,
    handleSubmit,
  }
}
