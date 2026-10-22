import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('editable row keys', () => {
  it('does not use array index as key', () => {
    for (const rel of [
      'src/views/pattern-room/components/DialogRoleEditor.vue',
      'src/views/customer-order/components/ShipmentPlanControl.vue',
    ]) {
      const src = readFileSync(resolve(process.cwd(), rel), 'utf-8')
      expect(src).not.toMatch(/:key="idx"/)
    }
  })
})
