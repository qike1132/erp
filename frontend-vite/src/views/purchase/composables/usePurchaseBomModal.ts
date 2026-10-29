import { nextTick, ref, shallowRef, type Component, type Ref } from 'vue'
import type { ResumeProduct } from '@/utils/bomOrderResume'

interface BomEditorHandle {
  open: (product: { id: number; name: string }) => Promise<void> | void
}

/**
 * 采购页同页 BOM 弹窗的组件装载器。
 *
 * BomEditor 仍复用产品页实现，但通过点击时才动态 import，避免采购页首屏
 * 连带加载产品页的 BOM 数据层；组件卸载前一直复用同一个实例。
 */
export function usePurchaseBomModal() {
  const bomEditorRef = ref<BomEditorHandle | null>(null)
  const bomEditorComponent: Ref<Component | null> = shallowRef(null)

  async function openBomEditor(product: ResumeProduct): Promise<void> {
    if (!bomEditorComponent.value) {
      const module = await import('@/views/product/components/BomEditor.vue')
      bomEditorComponent.value = module.default
      await nextTick()
      if (!bomEditorRef.value) await nextTick()
    }
    if (!bomEditorRef.value) {
      throw new Error('BOM 编辑器加载失败，请重试')
    }
    await bomEditorRef.value.open({ id: product.product_id, name: product.product_name })
  }

  return { bomEditorRef, bomEditorComponent, openBomEditor }
}
