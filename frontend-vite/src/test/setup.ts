import '@testing-library/jest-dom/vitest'
import { config } from '@vue/test-utils'

config.global.stubs = {
  FontAwesomeIcon: true,
}

// jsdom 没有 ResizeObserver；PrimeVue VirtualScroller（AutoComplete 虚拟滚动）
// 在 mounted 时会绑定它，缺失会抛 ReferenceError。
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}
