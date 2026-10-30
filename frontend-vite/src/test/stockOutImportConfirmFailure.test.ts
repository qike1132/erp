/**
 * StockOutImportSection 确认失败必须可见（2026-10-30 审计 A-H3）。
 *
 * 缺陷：导入成功但 /staging-stockouts/confirm 返回 success:false（库存不足等）时，
 * 旧实现只认 success 分支、catch 为空——用户看到「成功导入」而实际零出货，
 * 失败行随后被服务端物理删除。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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
import StockOutImportSection from '@/views/stock/components/StockOutImportSection.vue'
import { showToast } from '@/composables/useToast'

function mountSection() {
  return mount(StockOutImportSection, {
    props: {
      customer: '客户A',
      date: '2026-10-30',
      searchProducts: async () => [],
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

async function selectAndImport(wrapper: ReturnType<typeof mountSection>) {
  const input = wrapper.find('input[type="file"]').element as HTMLInputElement
  Object.defineProperty(input, 'files', {
    value: [new File(['x'], 'stockout.xlsx')],
    configurable: true,
  })
  await wrapper.find('input[type="file"]').trigger('change')
  await flushPromises()
  await wrapper.find('.so-inline-btn-success').trigger('click')
  await flushPromises()
}

describe('StockOutImportSection — 确认失败反馈（A-H3）', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.restoreAllMocks())

  it('confirm 返回 success:false 时提示错误并刷新，不能静默当成成功', async () => {
    vi.spyOn(stockApi.stagingStockouts, 'importExcel').mockResolvedValue({
      success: true,
      imported: 2,
    } as never)
    vi.spyOn(stockApi.stagingStockouts, 'confirm').mockResolvedValue({
      success: false,
      message: '库存不足',
      confirmed: 0,
      errors: ['第 1 行：库存不足'],
    } as never)

    const wrapper = mountSection()
    await selectAndImport(wrapper)

    expect(showToast).toHaveBeenCalledWith(
      expect.stringContaining('库存不足'),
      'error',
    )
    expect(wrapper.emitted('imported')).toHaveLength(1)
  })

  it('confirm 抛错时提示错误并刷新，暂存行仍可见', async () => {
    vi.spyOn(stockApi.stagingStockouts, 'importExcel').mockResolvedValue({
      success: true,
      imported: 1,
    } as never)
    vi.spyOn(stockApi.stagingStockouts, 'confirm').mockRejectedValue({
      response: { data: { detail: '确认接口超时' } },
    })

    const wrapper = mountSection()
    await selectAndImport(wrapper)

    expect(showToast).toHaveBeenCalledWith('确认接口超时', 'error')
    expect(wrapper.emitted('imported')).toHaveLength(1)
  })
})
