import { describe, expect, it } from 'vitest'
import { plushCutePT } from '@/styles/primevue-pt'

describe('PrimeVue AutoComplete pass-through', () => {
  it('keeps the loading icon out of the input flow', () => {
    const autocomplete = plushCutePT.autocomplete!

    expect(autocomplete.root).toContain('relative')
    expect(autocomplete.loader).toContain('absolute')
  })
})
