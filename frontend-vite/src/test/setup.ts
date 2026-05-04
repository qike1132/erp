import '@testing-library/jest-dom/vitest'
import { config } from '@vue/test-utils'

config.global.stubs = {
  FontAwesomeIcon: true,
}
