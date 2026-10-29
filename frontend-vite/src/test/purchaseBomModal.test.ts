import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { usePurchaseBomModal } from '@/views/purchase/composables/usePurchaseBomModal'

const { openMock } = vi.hoisted(() => ({ openMock: vi.fn() }))

vi.mock('@/views/product/components/BomEditor.vue', async () => {
  const { defineComponent: dc, h: render } = await import('vue')
  return {
    default: dc({
      setup(_props, { expose }) {
        expose({ open: openMock })
        return () => render('div', { class: 'bom-editor-stub' })
      },
    }),
  }
})

describe('采购页同页 BOM 弹窗装载器', () => {
  it('动态加载 BomEditor 后 ref 已就绪，并用产品 id/name 打开', async () => {
    openMock.mockResolvedValue(undefined)
    const Host = defineComponent({
      setup() {
        const { bomEditorComponent, bomEditorRef, openBomEditor } = usePurchaseBomModal()
        return {
          bomEditorComponent,
          openBomEditor,
          setEditor: (el: unknown) => {
            bomEditorRef.value = el as { open: (p: { id: number; name: string }) => Promise<void> } | null
          },
        }
      },
      template: '<component :is="bomEditorComponent" v-if="bomEditorComponent" :ref="setEditor" />',
    })
    const wrapper = mount(Host)
    await (wrapper.vm as unknown as {
      openBomEditor: (p: { product_id: number; product_name: string; product_barcode: null }) => Promise<void>
    }).openBomEditor({ product_id: 5, product_name: '产品五', product_barcode: null })

    expect(openMock).toHaveBeenCalledWith({ id: 5, name: '产品五' })
    wrapper.unmount()
  })
})
