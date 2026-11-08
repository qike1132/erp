import { reactive } from 'vue'
import type { BlindBoxForm } from '../components/ProductBlindBoxFields.vue'

/** 盲盒配置的来源行（产品列表行 / 详情） */
export interface ProductBlindBoxSource {
  is_blind_box?: boolean
  has_hidden_role?: boolean
  hidden_carton_ratio?: number | null
}

/**
 * 盲盒配置表单状态（新增与编辑共用）。
 *
 * - ``blindBox``：绑定给 ProductBlindBoxFields 的 v-model；
 * - ``initial``：打开时的基线（编辑保存时用于判断「配比是否改动」）；
 * - ``effectiveRatio``：生效配比——只有「盲盒 + 有隐藏款」才提交，空串归一为 null。
 */
export function useProductBlindBox() {
  const blindBox = reactive<BlindBoxForm>({
    isBlindBox: false, hasHiddenRole: false, hiddenCartonRatio: null,
  })
  const initial = { isBlindBox: false, hasHiddenRole: false, hiddenCartonRatio: null as number | null }

  function loadFrom(row: ProductBlindBoxSource) {
    Object.assign(blindBox, {
      isBlindBox: row.is_blind_box === true,
      hasHiddenRole: row.has_hidden_role === true,
      hiddenCartonRatio: row.hidden_carton_ratio ?? null,
    })
    Object.assign(initial, blindBox, { hiddenCartonRatio: blindBox.hiddenCartonRatio as number | null })
  }

  function effectiveRatio(): number | null {
    const raw = blindBox.isBlindBox && blindBox.hasHiddenRole ? blindBox.hiddenCartonRatio : null
    return raw === '' ? null : raw
  }

  function reset() {
    Object.assign(blindBox, { isBlindBox: false, hasHiddenRole: false, hiddenCartonRatio: null })
  }

  return { blindBox, initial, loadFrom, effectiveRatio, reset }
}
