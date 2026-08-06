import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { countryApi } from '@/api'

const STORAGE_KEY = 'erp_countries'

function loadFromStorage(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveToStorage(list: string[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
  } catch {
    // ignore quota errors
  }
}

export const useCountryStore = defineStore('country', () => {
  const countries = ref<string[]>(loadFromStorage())
  const loaded = ref(false)

  const countryOptions = computed(() =>
    countries.value.map((c) => ({ value: c, label: c })),
  )

  async function fetchCountries() {
    try {
      const res = await countryApi.list()
      const list = Array.isArray(res) ? res.map((c) => c.name) : []
      countries.value = list
      saveToStorage(list)
      loaded.value = true
    } catch {
      // keep localStorage fallback
      loaded.value = true
    }
  }

  async function addCountry(name: string): Promise<boolean> {
    const trimmed = name.trim()
    if (!trimmed) return false
    if (countries.value.includes(trimmed)) return false
    try {
      await countryApi.create(trimmed)
      countries.value.push(trimmed)
      saveToStorage(countries.value)
      return true
    } catch (err: any) {
      if (err.response?.status === 409) return false
      countries.value.push(trimmed)
      saveToStorage(countries.value)
      return true
    }
  }

  async function removeCountry(name: string): Promise<boolean> {
    const idx = countries.value.indexOf(name)
    if (idx === -1) return false
    try {
      const list = await countryApi.list()
      const match = Array.isArray(list) ? list.find((c) => c.name === name) : null
      if (match) await countryApi.delete(match.id)
    } catch {
      // proceed with local removal
    }
    countries.value.splice(idx, 1)
    saveToStorage(countries.value)
    return true
  }

  return { countries, countryOptions, loaded, fetchCountries, addCountry, removeCountry }
})
