/**
 * useOrderImport — Excel 批量导入动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载模板下载、文件选择/拖拽、暂存导入。
 *
 * 导入语义（与服务端一致）：`POST /staging-{orders,stockins}/import` 会**先清空**
 * 当前用户会话（`u{id}:default`）的暂存区，再写入本次 Excel 的全部行。
 * 因此导入后必须回读服务端暂存列表，用它**替换**上一次导入的条目。
 */
import { ref, type Ref, type ComputedRef } from 'vue'
import { orderApi, stockApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { StagingImportResult, StagingListResponse } from '@/types'
import type { StagedItem } from './types'
import { genUid } from './useStagedItems'

/** 下载统一导入模板（后端 /batch/download-template 是订单/备货共用的统一模板） */
function downloadTemplateFile() {
  void stockApi.downloadTemplate()
}

/** 暂存订单条目（/staging-orders 返回的原始结构） */
interface StagingOrderItem {
  order_type?: string
  customer: string
  product_id: number
  product_name: string
  quantity: number
  order_date: string
  note: string
  deduct_stock: boolean
  deduct_quantity?: number
  country?: string
}

/** 暂存备货条目（/staging-stockins 返回的原始结构） */
interface StagingStockinItem {
  order_type?: string
  customer: string
  product_id: number
  product_name: string
  quantity: number
  stockin_date: string
  note: string
  country?: string
}

/**
 * 暂存列表接口响应，权威形状见 `@/types::StagingListResponse`
 * （后端 `schemas/staging.py::StagingListResponse`）。
 *
 * ⚠️ 契约点：条目挂在 **`data`** 上。历史实现读的是 `staging_orders` / `items`
 * （两个键在真实响应里都不存在），于是「导入成功」toast 照常弹出、`items` 却是 `[]`，
 * 暂存列表恒空（2026-09-18 缺陷）。下方三个旧键仅作降级兼容，不作为主判据。
 */
interface StagingListPayload<T> extends Partial<StagingListResponse<T>> {
  /** @deprecated 真实响应不含此键，仅历史兼容 */
  staging_orders?: T[]
  /** @deprecated 真实响应不含此键，仅历史兼容 */
  staging_stockins?: T[]
  /** @deprecated 真实响应不含此键，仅历史兼容 */
  items?: T[]
}

/** 列表端点单页上限（后端 per_page 上限 500） */
const STAGING_PAGE_SIZE = 500
/** 分页护栏：最多 20 页（= 10000 条），防止异常响应导致死循环 */
const STAGING_MAX_PAGES = 20

/** 从任意一种响应包装中取出条目数组（data 为准，旧键兜底） */
function pickStagedItems<T>(res: StagingListPayload<T> | null | undefined): T[] {
  if (!res) return []
  const candidate = res.data ?? res.staging_orders ?? res.staging_stockins ?? res.items
  return Array.isArray(candidate) ? candidate : []
}

/**
 * 拉全当前会话的暂存条目。
 * 后端默认只返回 100 条（`per_page` 默认值），大文件导入必须分页取全，
 * 否则「导入成功但列表只显示前 100 条」会成为一个更隐蔽的同类缺陷。
 */
async function fetchAllStaged<T>(
  fetchPage: (params: { page: number; per_page: number }) => Promise<StagingListPayload<T>>,
): Promise<T[]> {
  const all: T[] = []
  for (let page = 1; page <= STAGING_MAX_PAGES; page += 1) {
    const res = await fetchPage({ page, per_page: STAGING_PAGE_SIZE })
    const items = pickStagedItems(res)
    all.push(...items)
    if (items.length < STAGING_PAGE_SIZE) break
  }
  return all
}

function toStagedOrder(i: StagingOrderItem): StagedItem {
  return {
    uid: genUid(),
    origin: 'import',
    type: 'order',
    orderType: i.order_type === 'custom' ? 'custom' : 'normal',
    customer: i.customer,
    productId: i.product_id,
    productName: i.product_name,
    quantity: i.quantity,
    date: i.order_date,
    note: i.note,
    deductStock: i.deduct_stock,
    deductQuantity: i.deduct_quantity || 0,
    country: i.country || '',
  }
}

function toStagedStockin(i: StagingStockinItem): StagedItem {
  return {
    uid: genUid(),
    origin: 'import',
    type: 'stockin',
    orderType: i.order_type === 'custom' ? 'custom' : 'normal',
    customer: i.customer,
    productId: i.product_id,
    productName: i.product_name,
    quantity: i.quantity,
    date: i.stockin_date,
    note: i.note,
    deductStock: false,
    deductQuantity: 0,
    country: i.country || '',
  }
}

export function useOrderImport(stagedItems: Ref<StagedItem[]>, isOrder: ComputedRef<boolean>) {
  const excelFile = ref<File | null>(null)
  const importing = ref(false)
  const isDragOver = ref(false)
  const excelInputRef = ref<HTMLInputElement | null>(null)

  /** 允许的模板后缀与体积上限（拖拽路径不会经过 input 的 accept 过滤，必须自行校验） */
  const OK_EXT = /\.(xlsx|xls)$/i
  const MAX_MB = 10

  /** 统一入口校验：文件对话框与拖拽两条路径共用，避免校验规则分叉 */
  function acceptFile(f: File | null | undefined): boolean {
    if (!f) return false
    if (!OK_EXT.test(f.name)) {
      showToast('仅支持 .xlsx / .xls 文件，请重新选择', 'warning')
      return false
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      showToast(`文件不能超过 ${MAX_MB}MB，当前 ${(f.size / 1024 / 1024).toFixed(1)}MB`, 'warning')
      return false
    }
    return true
  }

  function handleExcelSelect(e: Event) {
    const input = e.target as HTMLInputElement
    const f = input.files?.[0] ?? null
    if (f && !acceptFile(f)) {
      input.value = ''      // 拒绝后复位，允许用户重选同一个文件
      excelFile.value = null
      return
    }
    excelFile.value = f
  }

  function onDrop(e: DragEvent) {
    isDragOver.value = false
    const f = e.dataTransfer?.files?.[0]
    if (acceptFile(f)) excelFile.value = f ?? null
  }
  function downloadTemplate() {
    // 走 API 层统一端点，避免视图层硬编码 URL（原为 window.open 直连）
    downloadTemplateFile()
  }

  /**
   * 上报导入结果。原实现无条件弹「导入成功」——即使后端返回
   * `{success:false, message:'没有找到"订单管理"Sheet', imported:0}`（HTTP 200），
   * 也会误报成功，掩盖真实失败原因。此处改为按后端真实结果播报。
   */
  function reportImportResult(res: StagingImportResult | null, label: string): number {
    if (res?.success === false) {
      showToast(res.message || `${label}导入失败`, 'error')
      return 0
    }
    const imported = res?.imported ?? 0
    const errors = res?.errors ?? []
    if (imported === 0) {
      showToast(res?.message || `没有可导入的${label}，请检查模板`, 'warning')
    } else if (errors.length) {
      showToast(
        `成功导入 ${imported} 个${label}，另有 ${errors.length} 行有问题：${errors.slice(0, 2).join('；')}`,
        'warning',
      )
    } else {
      showToast(`成功导入 ${imported} 个${label}到暂存区`, 'success')
    }
    return imported
  }

  async function handleImport() {
    if (!excelFile.value || importing.value) return
    importing.value = true
    try {
      const fd = new FormData()
      fd.append('file', excelFile.value)

      let imported: StagedItem[]
      if (isOrder.value) {
        const res = await orderApi.staging.importExcel(fd)
        reportImportResult(res, '订单')
        imported = (await fetchAllStaged<StagingOrderItem>(
          (params) => orderApi.staging.list<StagingOrderItem>(undefined, params),
        )).map(toStagedOrder)
      } else {
        const res = await stockApi.stagingStockins.importExcel(fd)
        reportImportResult(res, '备货')
        imported = (await fetchAllStaged<StagingStockinItem>(
          (params) => stockApi.stagingStockins.list<StagingStockinItem>(undefined, params),
        )).map(toStagedStockin)
      }

      // 服务端已按「本次文件」重建暂存区：用它替换上次导入的条目，
      // 同时保留本页手工新增的条目（手工条目只存在于前端，服务端不会清）。
      stagedItems.value = [
        ...stagedItems.value.filter((i) => i.origin !== 'import'),
        ...imported,
      ]
      excelFile.value = null
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '导入失败'), 'error')
    } finally {
      importing.value = false
    }
  }

  return {
    excelFile,
    importing,
    isDragOver,
    excelInputRef,
    handleExcelSelect,
    onDrop,
    downloadTemplate,
    handleImport,
  }
}
