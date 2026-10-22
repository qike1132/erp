import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { useCatalogStore } from '@/stores/catalog'

describe('catalog store surface', () => {
  it('only exposes the customer-name entry that is actually used', () => {
    setActivePinia(createPinia())
    const store = useCatalogStore() as unknown as Record<string, unknown>
    expect(store.ensureActiveCustomerNames).toBeTypeOf('function')
    expect(store.ensureProducts).toBeUndefined()
    expect(store.ensureCustomers).toBeUndefined()
    expect(store.ensureSuppliers).toBeUndefined()
  })
})
