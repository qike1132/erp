import { inject, provide, reactive, ref, watch, type InjectionKey, type Ref } from 'vue'
import type { PartDetail } from '@/api/patternRoom'

/**
 * 部位可编辑字段元数据 —— 单一事实来源（CP-1）
 *
 * 背景：`supplier_name / fabric_name / fabric_color_no` 原先在 9 处被逐个枚举
 * （API 契约、内联编辑、编排 hook、二维表表头与单元格、打印表头、批量表单），
 * 导致新增字段必然漏改某处且类型检查不报错（最典型是打印表头少一列）。
 *
 * 本模块统一承载"显示 + 输入"元数据，由二维表列、打印表头、批量表单、
 * 行内编辑共同派生。新增字段只需改此处 + `api/patternRoom.ts` 的接口定义。
 */
export type PartEditableKey = 'supplier_name' | 'fabric_name' | 'fabric_color_no'

export interface PartFieldMeta {
  /** PartDetail 上的字段名 */
  key: PartEditableKey
  /** 表格表头 / 打印表头 / 表单标签 */
  label: string
  /** 输入框 placeholder */
  placeholder: string
  /** 批量新增表单输入框最大长度 */
  formMaxlength: number
  /** 行内编辑输入框最大长度 */
  inlineMaxlength: number
  /** 批量表单网格列修饰符（保持既有 CSS 类名不变） */
  modifier: 'supplier' | 'fabric' | 'color'
  /** 二维表 colgroup 列宽 */
  width: string
}

/** 部位可编辑字段，顺序即各表格/表单中的列顺序 */
export const PART_EDIT_FIELDS: readonly PartFieldMeta[] = [
  {
    key: 'supplier_name',
    label: '供应商',
    placeholder: '供应商',
    formMaxlength: 100,
    inlineMaxlength: 200,
    modifier: 'supplier',
    width: '110px',
  },
  {
    key: 'fabric_name',
    label: '布料名称',
    placeholder: '布料名称',
    formMaxlength: 200,
    inlineMaxlength: 200,
    modifier: 'fabric',
    width: '110px',
  },
  {
    key: 'fabric_color_no',
    label: '色号',
    placeholder: '色号',
    formMaxlength: 50,
    inlineMaxlength: 50,
    modifier: 'color',
    width: '110px',
  },
]

/** 内联编辑表单数据（由 PartEditableKey 派生，避免结构漂移） */
export type PartEditData = Record<PartEditableKey, string>

/** 空的部位编辑表单数据 */
export function createEmptyEditData(): PartEditData {
  const out = {} as PartEditData
  for (const field of PART_EDIT_FIELDS) out[field.key] = ''
  return out
}

/**
 * 部位内联编辑上下文（CP-3）
 *
 * 背景：编辑态原先由 PatternRoomView 经 ProjectDetailPanel → PartsVersionTableV2
 * 逐层下发到 PartsVersionRowV2，并原样回传 start-edit / save-edit / cancel-edit
 * 三个事件（共 4 层）。中间两层并不关心编辑态，只是转发；一旦漏绑某一层，
 * 「修改版本」按钮即失效（代码注释已记录该故障曾发生）。
 *
 * 改为 provide/inject 后，中间层无需再声明这些 props/emits，
 * 但编辑态的提供方仍是唯一入口，数据流依旧单向可追溯。
 */
export interface PartInlineEditContext {
  editingPartId: Ref<number | undefined>
  editForm: PartEditData
  startEdit: (part: PartDetail) => void
  saveEdit: (part: PartDetail) => void
  cancelEdit: () => void
}

export const PART_INLINE_EDIT_KEY: InjectionKey<PartInlineEditContext> = Symbol('partInlineEdit')

/** 由页面级组件提供编辑上下文（须在 setup 同步阶段调用） */
export function providePartInlineEdit(ctx: PartInlineEditContext): void {
  provide(PART_INLINE_EDIT_KEY, ctx)
}

/** 由行组件消费编辑上下文；缺失时明确报错而非静默失效 */
export function injectPartInlineEdit(): PartInlineEditContext {
  const ctx = inject(PART_INLINE_EDIT_KEY)
  if (!ctx) {
    throw new Error('部位内联编辑上下文未提供：请确认祖先组件已调用 providePartInlineEdit()')
  }
  return ctx
}

export function usePartInlineEdit(
  partsByVersion: Ref<PartDetail[]>,
  projectId: Ref<number | null | undefined>,
  currentRoleId: Ref<number | null>,
  onSave: (part: PartDetail, data: PartEditData) => void,
) {
  const editingPartId = ref<number | undefined>(undefined)
  const editForm = reactive<PartEditData>(createEmptyEditData())

  function startEdit(part: PartDetail) {
    if (part.id == null) return
    editingPartId.value = part.id
    for (const field of PART_EDIT_FIELDS) {
      editForm[field.key] = part[field.key] || ''
    }
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
