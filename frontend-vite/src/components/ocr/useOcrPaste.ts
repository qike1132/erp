/**
 * useOcrPaste — 粘贴图片识别的动作域（客户订单 / 出货两页共用）
 *
 * 链路：粘贴/选图 → 上传预览端点（**不写库**）→ 弹窗人工确认 → buildStaged 回调
 * 把草稿映射成各自域的暂存条目。
 *
 * 这里只负责「识别 + 三道校验闸门」；条目长什么样由消费方在 buildStaged 里决定，
 * 因此这里没有对应的写接口——识别错了用户可以在弹窗或暂存区里改、删。
 */
import { computed, ref } from 'vue'
import { ocrApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { QUANTITY_MIN, QUANTITY_MAX } from '@/utils/quantity'
import { genUid } from '@/utils/uid'
import type { OcrDraftItem, OcrOrderPreviewResult, OcrStagingContext } from './types'

/** 与后端 MAX_OCR_FILE_SIZE 保持一致 */
const MAX_MB = 10

/**
 * 导入前的数量校验（比实时输入框的「越界」判定更严）。
 *
 * 实时输入把「空值」当作「还没开始填」而不算越界——那对输入框是对的（一进
 * 页面就标红是噪音）。但导入时没有「还没填」这一说：空数量进暂存区会让整批
 * 提交 422。
 */
function isImportableQuantity(value: unknown): boolean {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return false
  return n >= QUANTITY_MIN && n <= QUANTITY_MAX
}

export interface OcrPasteOptions {
  /**
   * 三道闸门全过后：把草稿映射成各自域的暂存条目并入列，返回 false 视为未导入。
   * 用回调而不是约定数据形状——订单（StagedItem）与出货（StagedStockout）各自决定落点。
   */
  buildStaged: (drafts: OcrDraftItem[], ctx: OcrStagingContext) => boolean
  /** 表单当前选中的客户：图上没有客户信息时兜底 */
  getDefaultCustomer: () => string
  /** 表单当前选中的时间：图上本来就没有日期 */
  getDefaultDate: () => string
}

export function useOcrPaste({ buildStaged, getDefaultCustomer, getDefaultDate }: OcrPasteOptions) {
  const recognizing = ref(false)
  const dialogOpen = ref(false)
  const draftItems = ref<OcrDraftItem[]>([])
  const rawText = ref('')
  const warnings = ref<string[]>([])
  const sourceName = ref('')

  /**
   * 本次识别**一条都没解析出来** —— 弹窗据此进「指引态」。
   *
   * 刻意不用 `draftItems.length === 0` 代替：那样用户把误识别的行逐条删光后，
   * 界面会变成「没有识别到可导入的条目」，把他自己的删除动作报成识别失败。
   */
  const emptyResult = ref(false)

  /** 是否有候选条目（决定弹窗展示确认表还是指引态） */
  const hasDrafts = computed(() => !emptyResult.value)

  /** 产品未匹配的行数。未匹配必须先手选，否则不允许导入 */
  const unmatchedCount = computed(() => draftItems.value.filter((i) => !i.product_id).length)

  /** 数量缺失或越界的行数。空数量同样不能导入（见 isImportableQuantity） */
  const invalidQuantityCount = computed(
    () => draftItems.value.filter((i) => !isImportableQuantity(i.quantity)).length,
  )

  /** 落不到客户的条数（图上没有 + 表单也没选） */
  const missingCustomerCount = computed(
    () => draftItems.value.filter((i) => !(i.customer || getDefaultCustomer())).length,
  )

  function acceptFile(file: File): boolean {
    const isImage = file.type.startsWith('image/')
    const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
    if (!isImage && !isPdf) {
      showToast('请粘贴图片，或选择图片 / PDF 文件', 'warning')
      return false
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      showToast(`文件不能超过 ${MAX_MB}MB，当前 ${(file.size / 1024 / 1024).toFixed(1)}MB`, 'warning')
      return false
    }
    return true
  }

  function reset() {
    draftItems.value = []
    rawText.value = ''
    warnings.value = []
    sourceName.value = ''
    emptyResult.value = false
  }

  async function recognize(file: File) {
    if (recognizing.value) return
    if (!acceptFile(file)) return
    recognizing.value = true
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await ocrApi.previewOrder(fd, getDefaultCustomer()) as unknown as OcrOrderPreviewResult
      // 先清空再按本次结果重建，避免上一次的条目残留
      reset()
      rawText.value = res.raw_text || ''
      warnings.value = res.warnings || []
      sourceName.value = res.filename || file.name
      if (!res.success || !res.items?.length) {
        emptyResult.value = true // 一条都没解析出来 → 指引态
      } else {
        draftItems.value = res.items.map((item) => ({ ...item, uid: genUid() }))
      }
      dialogOpen.value = true
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '图片识别失败'), 'error')
    } finally {
      recognizing.value = false
    }
  }

  function closeDialog() {
    dialogOpen.value = false
  }

  /**
   * 确认导入：三道闸门都过才调 buildStaged，否则会把注定提交失败的数据放进暂存区：
   * 未匹配产品（没有 product_id）、数量非法（空/0/越界）、没客户。
   * 手工录入路径有对应的必填校验，这里与它对齐。
   */
  function confirmImport(): boolean {
    if (!draftItems.value.length) return false
    if (unmatchedCount.value > 0) {
      showToast(`还有 ${unmatchedCount.value} 项没有选择产品，请先选择或删除该行`, 'warning')
      return false
    }
    if (invalidQuantityCount.value > 0) {
      showToast(`还有 ${invalidQuantityCount.value} 项数量不合法，请填写 1 以上的整数`, 'warning')
      return false
    }
    if (missingCustomerCount.value > 0) {
      showToast(`还有 ${missingCustomerCount.value} 项没有客户，请先在表单选择客户`, 'warning')
      return false
    }
    const ok = buildStaged(draftItems.value, {
      date: getDefaultDate(),
      fallbackCustomer: getDefaultCustomer(),
    })
    if (!ok) return false
    showToast(`已加入 ${draftItems.value.length} 条到暂存区，确认无误后提交`, 'success')
    dialogOpen.value = false
    reset()
    return true
  }

  return {
    recognizing,
    dialogOpen,
    draftItems,
    rawText,
    warnings,
    sourceName,
    hasDrafts,
    emptyResult,
    unmatchedCount,
    invalidQuantityCount,
    missingCustomerCount,
    recognize,
    confirmImport,
    closeDialog,
  }
}
