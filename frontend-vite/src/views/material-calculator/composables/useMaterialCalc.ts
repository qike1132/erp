// 物料计算器产品列表：产品查询 / 搜索建议 / BOM 过滤（从 MaterialCalculatorView.vue 抽出，行为不变）
import { ref, computed, onUnmounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { purchaseApi, type MaterialCalcProduct } from '@/api'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'

export function useMaterialCalc() {
  const searchQuery = ref('')
  const searchSuggestions = ref<MaterialCalcProduct[]>([])
  const bomFilter = ref<'all' | 'true' | 'false'>('all')

  // 搜索建议防抖（250ms）；hideSuggestionsTimer 为建议列表隐藏延迟，独立保留
  const { debounceSearch } = useDebouncedSearch(250)
  let hideSuggestionsTimer: ReturnType<typeof setTimeout> | null = null

  onUnmounted(() => {
    if (hideSuggestionsTimer) clearTimeout(hideSuggestionsTimer)
  })

  const { data: productsQueryData, isLoading: loadingProducts } = useQuery({
    queryKey: ['material-calculator-products'],
    queryFn: async () => {
      const res = await purchaseApi.products({ per_page: 200, simple: true })
      return (res.products ?? []).map((p) => ({
        id: p.id,
        name: p.name,
        barcode: p.barcode ?? undefined,
        has_bom: !!p.has_bom,
      })) as MaterialCalcProduct[]
    },
    staleTime: 30_000,
  })

  const allProducts = computed<MaterialCalcProduct[]>(() => productsQueryData.value ?? [])

  // S5: 加载达到 200 上限时提示用户用搜索定位
  const productCapHint = computed(() =>
    allProducts.value.length >= 200 ? '已加载前 200 个产品，如未找到请使用上方搜索' : '',
  )

  const filteredProducts = computed(() => {
    let list = allProducts.value
    if (bomFilter.value === 'true') list = list.filter((p) => p.has_bom)
    else if (bomFilter.value === 'false') list = list.filter((p) => !p.has_bom)
    return list
  })

  function onSearchInput() {
    debounceSearch(async () => {
      if (!searchQuery.value.trim()) {
        searchSuggestions.value = []
        return
      }
      try {
        const res = await purchaseApi.searchSuggestions(searchQuery.value.trim())
        searchSuggestions.value = res.suggestions ?? []
      } catch {
        searchSuggestions.value = []
      }
    })
  }

  function onMcSearchFocus() {
    if (searchQuery.value.trim() && searchSuggestions.value.length === 0) {
      onSearchInput()
    }
  }
  function hideMcSuggestions() {
    if (hideSuggestionsTimer) clearTimeout(hideSuggestionsTimer)
    hideSuggestionsTimer = setTimeout(() => { searchSuggestions.value = [] }, 150)
  }

  return {
    searchQuery,
    searchSuggestions,
    bomFilter,
    loadingProducts,
    productCapHint,
    filteredProducts,

    onSearchInput,
    onMcSearchFocus,
    hideMcSuggestions,
  }
}
