/**
 * 回归守卫：产品批量导入必须如实播报后端结果。
 *
 * 缺陷背景（2026-10-12 用户反馈「上传成功后没有客户和价格」）：`handleBatchImport`
 * 只 `await` 了请求、没看返回值，任何 200 都播报「导入成功」。后端把「产品都已存在、
 * 一条都没更新」表达为 `success=false` + `message`，于是用户看到「导入成功」却没有任何
 * 变化，据此以为「客户和价格识别不了」—— 谎报成功把「已存在→跳过」掩盖成了功能故障。
 *
 * 锁死的不变量：播报内容与类型 ⇔ 后端返回的 `success` / `message`。
 *
 * 2026-10-12 起导入改为两步（预览 → 确认导入）：播报发生在「确认导入」之后，本文件
 * 相应地先走预览、再点确认；不变量本身不变。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  importProducts: vi.fn(),
  previewProducts: vi.fn(),
  invalidateQueries: vi.fn(),
}))

vi.mock('@/api', () => ({
  batchApi: {
    importProducts: mocks.importProducts,
    previewProducts: mocks.previewProducts,
    downloadTemplate: vi.fn(),
  },
}))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
}))

import { showToast } from '@/composables/useToast'
import ProductBatchImport from '@/views/product/components/ProductBatchImport.vue'

const stubs = {
  FontAwesomeIcon: true,
  // 预览弹窗只负责「展示 + 抛 confirm」；它自己的渲染契约在
  // productImportPreviewModal.test.ts 里单独覆盖，这里 stub 掉以便直驱确认。
  ProductImportPreviewModal: {
    props: ['open', 'result', 'importing'],
    emits: ['confirm'],
    template: '<button class="stub-confirm" @click="$emit(\'confirm\')">确认导入</button>',
  },
}

const PREVIEW_OK = {
  success: true,
  message: '',
  filename: '新品录入.xlsx',
  row_count: 2,
  summary: { create: 2, backfill: 0, skip: 0, error: 0 },
  rows: [{ row_no: 2, action: 'create', name: '新品A', changes: ['新建产品'] }],
}

async function mountWithSelectedFile() {
  const wrapper = mount(ProductBatchImport, { global: { stubs } })
  const file = new File(['x'], '新品录入.xlsx', { type: 'application/vnd.ms-excel' })
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  return wrapper
}

/** 走完「预览 → 确认导入」，返回 wrapper（播报发生在确认之后） */
async function clickImport(wrapper: Awaited<ReturnType<typeof mountWithSelectedFile>>) {
  await wrapper.find('.pd-inline-btn-preview').trigger('click')
  await flushPromises()
  await wrapper.find('.stub-confirm').trigger('click')
  await flushPromises()
}

describe('产品批量导入的结果播报', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.previewProducts.mockResolvedValue(PREVIEW_OK)
  })

  it('success=false：播报后端 message 且用 error 类型，不谎报「导入成功」', async () => {
    const message = '没有找到需要导入的产品数据（可能都已存在）'
    mocks.importProducts.mockResolvedValue({ success: false, message, imported: 0, skipped: 0 })

    await clickImport(await mountWithSelectedFile())

    expect(showToast).toHaveBeenCalledWith(message, 'error')
    expect(showToast).not.toHaveBeenCalledWith('导入成功', 'success')
  })

  it('success=true：播报后端 message（含行级提示）且用 success 类型', async () => {
    const message = '成功导入产品 2 条。错误: 行3: 客户\'查无此客户\'不存在于客户主数据，未挂客户归属'
    mocks.importProducts.mockResolvedValue({ success: true, message, imported: 2, skipped: 0 })

    await clickImport(await mountWithSelectedFile())

    expect(showToast).toHaveBeenCalledWith(message, 'success')
  })

  it('导入失败时保留已选文件，让用户能直接重试', async () => {
    mocks.importProducts.mockResolvedValue({ success: false, message: '导入失败', imported: 0, skipped: 0 })
    const wrapper = await mountWithSelectedFile()

    await clickImport(wrapper)

    expect(wrapper.find('.pd-file-inline').exists()).toBe(true)
  })

  it('导入成功时清空已选文件', async () => {
    mocks.importProducts.mockResolvedValue({ success: true, message: '成功导入产品 2 条', imported: 2, skipped: 0 })
    const wrapper = await mountWithSelectedFile()

    await clickImport(wrapper)

    expect(wrapper.find('.pd-file-inline').exists()).toBe(false)
  })
})
