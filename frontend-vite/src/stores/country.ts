import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useCountryStore = defineStore('country', () => {
  const countries = ref<string[]>([])

  const countryOptions = computed(() =>
    countries.value.map((c) => ({ value: c, label: c })),
  )

  function addCountry(name: string) {
    const trimmed = name.trim()
    if (!trimmed) return false
    if (countries.value.includes(trimmed)) return false
    countries.value.push(trimmed)
    return true
  }

  return { countries, countryOptions, addCountry }
})
