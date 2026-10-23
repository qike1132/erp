/**
 * StockOutImportSection 文件选择 input 重置回归（R30-L10，2026-10-20 OCR 提交前统一扫描）。
 *
 * 缺陷：onExcelFileSelect 读文件后不重置原生 input.value——浏览器对同一路径重选
 * 不触发 change，「冻结拒绝后/导入失败修正表格后重选同一文件」完全无反馈
 * （无文件名、无 toast、导入按钮保持禁用）。
 *
 * 修复：读完 files[0] 立即无条件清 input.value（守卫前），任何路径下一次选择
 * 同一路径都能重新触发 change。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
  download: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

import { stockApi } from '@/api'
import type { StagingImportResult } from '@/types'
import StockOutImportSection from '@/views/stock/components/StockOutImportSection.vue'
import { showToast } from '@/composables/useToast'

function mountImportSection(extra: { disabled?: boolean } = {}) {
  return mount(StockOutImportSection, {
    props: {
      customer: '表单客户',
      date: '2026-10-06',
      searchProducts: async () => [],
      ...extra,
    },
    global: {
      stubs: {
        OcrPasteImport: { template: '<div />' },
        FontAwesomeIcon: { template: '<i />' },
        UiLoadingIcon: { template: '<i />' },
      },
    },
  })
}

/** 模拟用户经原生 input 选择了文件：覆写 files/value。jsdom 对 file input 的 value
 * 只允许设空串（非空抛 NoModificationAllowedError），故用实例级 data property 遮蔽
 * 原型 accessor——既可注入「已选过文件」初值，又能断言组件是否将其清空。 */
function selectFileViaInput(wrapper: ReturnType<typeof mountImportSection>, file: File) {
  const input = wrapper.find('input[type="file"]').element as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  Object.defineProperty(input, 'value', { value: `C:\\fakepath\\${file.name}`, writable: true, configurable: true })
  return wrapper.find('input[type="file"]').trigger('change')
}

describe('StockOutImportSection — 文件选择 input 重置（R30-L10）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('L10-a: 选中合法 Excel 后 input.value 立即被清——同一路径重选仍能触发 change（Red：现状读后不清）', async () => {
    const wrapper = mountImportSection()
    await selectFileViaInput(wrapper, new File(['x'], 'a.xlsx'))
    await flushPromises()

    // excelFile 已生效（文件名渲染 + 导入按钮解禁）
    expect(wrapper.find('.so-file-inline').text()).toContain('a.xlsx')
    expect(wrapper.find('.so-inline-btn-success').attributes('disabled')).toBeUndefined()
    // 核心断言：处理完成后原生 input 已被重置（不清则重选同一路径不触发 change）
    expect((wrapper.find('input[type="file"]').element as HTMLInputElement).value).toBe('')
  })

  it('L10-b: 冻结拒绝路径同样先清再守卫：toast「正在处理」且 input.value 已清（Red：现状守卫先 return 不碰 input）', async () => {
    const wrapper = mountImportSection({ disabled: true })
    await selectFileViaInput(wrapper, new File(['x'], 'a.xlsx'))
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith('正在处理，请稍后再导入', 'warning')
    expect((wrapper.find('input[type="file"]').element as HTMLInputElement).value).toBe('')
    // excelFile 未被设置的旁证：导入按钮保持禁用
    expect(wrapper.find('.so-inline-btn-success').attributes('disabled')).toBeDefined()
  })
})

describe('StockOutImportSection — 导入在途冻结文件入口（R36 L-j）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  /** 挂起导入制造 importing=true 窗口：选 a.xlsx → 点「导入」→ importExcel 挂起不 resolve。
   *  返回 spy 与放行函数供用例收尾（imported=0 → 跳过 confirm，importing 复位）。 */
  async function mountWithPendingImport() {
    const importExcelSpy = vi.spyOn(stockApi.stagingStockouts, 'importExcel')
    let resolveImport!: (v: StagingImportResult) => void
    importExcelSpy.mockImplementation(() => new Promise((res) => { resolveImport = res }))
    const wrapper = mountImportSection()
    await selectFileViaInput(wrapper, new File(['x'], 'a.xlsx'))
    await flushPromises()
    expect(wrapper.find('.so-file-inline').text()).toContain('a.xlsx') // 前置：a.xlsx 已选
    await wrapper.find('.so-inline-btn-success').trigger('click')
    await flushPromises()
    expect(importExcelSpy).toHaveBeenCalledTimes(1) // 前置：导入在途（importing=true）
    return {
      wrapper,
      importExcelSpy,
      finishImport: async () => {
        resolveImport({ success: true, imported: 0 })
        await flushPromises()
      },
    }
  }

  it('L-j-a: 导入在途中经 input 选择新文件被拒——excelFile 保持原文件 + 「正在处理」toast（Red：现状 rejectIfFrozen 只看 props.disabled）', async () => {
    // 缺陷（Red）：导入在途时 props.disabled 仍 false（父级冻结链 addInFlight ||
    // submitting 不含 importBusy，R36-Lb 才补），rejectIfFrozen 又不看自身 importing
    // ——窗口内换选的文件被接受，待导入成功后 handleImportExcel 的 excelFile.value
    // = null 把它静默丢弃（无 toast、文件名直接消失）。修复（R36 L-j）：importing
    // 纳入冻结谓词，与其他入口同口径。
    const ctx = await mountWithPendingImport()
    try {
      await selectFileViaInput(ctx.wrapper, new File(['y'], 'b.xlsx'))
      await flushPromises()

      expect(showToast).toHaveBeenCalledWith('正在处理，请稍后再导入', 'warning')
      expect(ctx.wrapper.find('.so-file-inline').text()).toContain('a.xlsx') // 未被换成 b.xlsx
      expect(ctx.importExcelSpy).toHaveBeenCalledTimes(1) // 在途导入未被打断重发

      await ctx.finishImport() // 干净收尾：放行导入，importing 复位
    } finally {
      ctx.importExcelSpy.mockRestore()
    }
  })

  it('L-j-b: 导入在途中 drop 新文件同样被拒——与 input 入口同口径（Red）', async () => {
    const ctx = await mountWithPendingImport()
    try {
      await ctx.wrapper.find('.so-section-header').trigger('drop', {
        dataTransfer: { files: [new File(['y'], 'b.xlsx')] },
      })
      await flushPromises()

      expect(showToast).toHaveBeenCalledWith('正在处理，请稍后再导入', 'warning')
      expect(ctx.wrapper.find('.so-file-inline').text()).toContain('a.xlsx')

      await ctx.finishImport()
    } finally {
      ctx.importExcelSpy.mockRestore()
    }
  })
})
