import { describe, expect, it } from 'vitest'
import { shouldSuppressConsoleError } from '@/utils/consoleFilter'

describe('console.error suppression scope', () => {
  it('suppresses exact known browser-extension noise', () => {
    expect(
      shouldSuppressConsoleError(['message port closed before a response was received']),
    ).toBe(true)
    expect(
      shouldSuppressConsoleError([
        'Could not establish connection. Receiving end does not exist',
      ]),
    ).toBe(true)
  })

  it('does not suppress substrings or Error objects', () => {
    expect(
      shouldSuppressConsoleError([
        'prefix: message port closed before a response was received',
      ]),
    ).toBe(false)
    expect(
      shouldSuppressConsoleError([
        new Error('message port closed before a response was received'),
      ]),
    ).toBe(false)
  })
})
