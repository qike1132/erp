import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const script = resolve(root, 'scripts/generate-api-types.mjs')

function run(args: string[]): { code: number; out: string } {
  try {
    const out = execFileSync(process.execPath, [script, ...args], { encoding: 'utf-8' })
    return { code: 0, out }
  } catch (e: any) {
    return { code: e.status ?? 1, out: String(e.stderr ?? '') + String(e.stdout ?? '') }
  }
}

describe('同步门禁检出漂移', () => {
  it('快照未变时通过', () => {
    const spec = resolve(root, 'openapi.json')
    const out = resolve(root, 'src/types/api.d.ts')
    expect(run([spec, '--out', out, '--check']).code).toBe(0)
  })

  it('改一个后端字段后判红', () => {
    const dir = mkdtempSync(join(tmpdir(), 'genapi-'))
    const spec = JSON.parse(readFileSync(resolve(root, 'openapi.json'), 'utf-8'))
    // noUncheckedIndexedAccess 下 [0] 为 string | undefined；此处必有元素，非空断言只修类型层。
    const first = Object.keys(spec.components.schemas)[0]!
    spec.components.schemas[first].properties = {
      ...(spec.components.schemas[first].properties ?? {}),
      __drift_probe__: { type: 'string' },
    }
    const mutated = join(dir, 'openapi.json')
    writeFileSync(mutated, JSON.stringify(spec), 'utf-8')
    const r = run([mutated, '--out', resolve(root, 'src/types/api.d.ts'), '--check'])
    expect(r.code).toBe(1)
    expect(r.out).toContain('不同步')
  })

  it('生成物缺失时判红', () => {
    const spec = resolve(root, 'openapi.json')
    const missing = resolve(root, 'src/types/__nope__.d.ts')
    expect(run([spec, '--out', missing, '--check']).code).toBe(1)
  })
})
