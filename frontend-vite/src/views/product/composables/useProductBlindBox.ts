import { reactive } from 'vue'

/** 配比上限：与后端 schema 的 `le=1000000` 对齐，避免两处漂移 */
export const HIDDEN_CARTON_RATIO_MAX = 1_000_000

/** 校验失败提示（两个表单共用同一文案） */
export const HIDDEN_CARTON_RATIO_INVALID = '盲盒隐藏款装箱配比必须为正整数（不超过 1000000）'

/** 盲盒配置表单状态（新增与编辑共用） */
export interface BlindBoxForm {
  isBlindBox: boolean
  hasHiddenRole: boolean
  /** 输入框原值：空串与 null 同义（不额外配隐藏款） */
  hiddenCartonRatio: number | null | ''
}

/** 盲盒配置的来源行（产品列表行 / 详情） */
export interface ProductBlindBoxSource {
  is_blind_box?: boolean
  has_hidden_role?: boolean
  hidden_carton_ratio?: number | null
}

/** 配比是否合法：空 = 合法（不额外配隐藏款），否则必须是 1..上限 的整数 */
export function isValidHiddenCartonRatio(value: number | null | ''): boolean {
  if (value === '' || value === null) return true
  return Number.isInteger(value) && value >= 1 && value <= HIDDEN_CARTON_RATIO_MAX
}

/**
 * 盲盒配置表单状态（新增与编辑共用）。
 *
 * - ``blindBox``：绑定给 ProductBlindBoxFields 的 form（子组件就地改字段）；
 * - ``initial``：打开时的基线，编辑保存时用于判断哪些字段真的改动过；
 * - ``effectiveRatio``：生效配比——只有「盲盒 + 有隐藏款」才提交，空串归一为 null；
 * - ``changedPayload``：只返回改动过的字段（后端「未提交 = 不改动」）。
 */
export function useProductBlindBox() {
  const blindBox = reactive<BlindBoxForm>({
    isBlindBox: false, hasHiddenRole: false, hiddenCartonRatio: null,
  })
  const initial = { isBlindBox: false, hasHiddenRole: false, hiddenCartonRatio: null as number | null }

  /** 配比归一：空串 → null（'' 与 null 语义相同，都是「不额外配」） */
  function normalizeRatio(value: number | null | ''): number | null {
    return value === '' ? null : value
  }

  function loadFrom(row: ProductBlindBoxSource) {
    Object.assign(blindBox, {
      isBlindBox: row.is_blind_box === true,
      hasHiddenRole: row.has_hidden_role === true,
      hiddenCartonRatio: row.hidden_carton_ratio ?? null,
    })
    // 基线显式归一：不能把 '' 用 as 断言塞进 number | null，否则 effectiveRatio()
    // 归一成 null 后会与基线 '' 比较成「已改动」，白白提交一次 null（OCR low）。
    initial.isBlindBox = blindBox.isBlindBox
    initial.hasHiddenRole = blindBox.hasHiddenRole
    initial.hiddenCartonRatio = normalizeRatio(blindBox.hiddenCartonRatio)
  }

  /** 生效配比：只有「盲盒 + 有隐藏款」才提交，空串归一为 null */
  function effectiveRatio(): number | null {
    return blindBox.isBlindBox && blindBox.hasHiddenRole
      ? normalizeRatio(blindBox.hiddenCartonRatio)
      : null
  }

  /** 生效的「有隐藏款」开关（非盲盒时恒 false） */
  function effectiveHasHidden(): boolean {
    return blindBox.isBlindBox && blindBox.hasHiddenRole
  }

  /** 编辑保存用：只返回**改动过**的盲盒字段（后端未提交 = 不改动，避免覆盖别处改动） */
  function changedPayload(): {
    is_blind_box?: boolean
    has_hidden_role?: boolean
    hidden_carton_ratio?: number | null
  } {
    const payload: {
      is_blind_box?: boolean
      has_hidden_role?: boolean
      hidden_carton_ratio?: number | null
    } = {}
    if (blindBox.isBlindBox !== initial.isBlindBox) payload.is_blind_box = blindBox.isBlindBox
    const hasHidden = effectiveHasHidden()
    if (hasHidden !== initial.hasHiddenRole) payload.has_hidden_role = hasHidden
    const ratio = effectiveRatio()
    if (ratio !== initial.hiddenCartonRatio) payload.hidden_carton_ratio = ratio
    return payload
  }

  function reset() {
    Object.assign(blindBox, { isBlindBox: false, hasHiddenRole: false, hiddenCartonRatio: null })
  }

  return {
    blindBox, initial, loadFrom,
    effectiveRatio, effectiveHasHidden, changedPayload, reset,
  }
}
