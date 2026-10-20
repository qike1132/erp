/**
 * check:dto 门禁的行为回归（2026-10-17 审计 F1-1 / F1-2）。
 *
 * 门禁本体：frontend-vite/scripts/check-mobile-dto.mjs（npm run check:dto，CI 跑）。
 * 本测试在**临时夹具**上跑同一支脚本（--root 指过去），验证三条规则真的会红：
 *
 * R1 src/mobile 重复声明 @/types 的 DTO → 判红；
 * R2 src/api/*.ts 重复声明生成层（api.d.ts）的同名类型 → 判红；
 * R3 src/types/index.ts 重复声明生成层的同名类型 → 判红；
 * 豁免表：登记过的重复放行；条目失效（对应声明已不存在）判红。
 *
 * 为什么要有这个测试：门禁脚本本身没被任何测试覆盖过——把判定写错（比如正则
 * 退化成只匹配 export interface）脚本仍会「绿」，CI 形同虚设。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url)) // frontend-vite/src/test
const script = resolve(here, '..', '..', 'scripts', 'check-mobile-dto.mjs')
const repoRoot = resolve(here, '..', '..')

let fixture: string

/** 造一套最小夹具：生成层 1 个类型，手写层默认干净 */
function buildFixture(opts: {
  apiTypes?: string
  indexTypes?: string
  generatedTypes?: string
  exemptions?: string[]
} = {}) {
  const apiTypes = opts.apiTypes ?? ''
  const indexTypes = opts.indexTypes ?? ''
  const generatedTypes = opts.generatedTypes ?? 'export interface Widget {\n  id: number\n}\n'
  const exemptions = opts.exemptions ?? []

  mkdirSync(join(fixture, 'src', 'types'), { recursive: true })
  mkdirSync(join(fixture, 'src', 'api'), { recursive: true })
  mkdirSync(join(fixture, 'src', 'mobile'), { recursive: true })
  mkdirSync(join(fixture, 'scripts'), { recursive: true })

  writeFileSync(join(fixture, 'src', 'types', 'api.d.ts'), generatedTypes, 'utf-8')
  writeFileSync(join(fixture, 'src', 'types', 'index.ts'), indexTypes, 'utf-8')
  writeFileSync(join(fixture, 'src', 'api', 'foo.ts'), apiTypes, 'utf-8')
  writeFileSync(
    join(fixture, 'scripts', 'dto-duplicate-exemptions.json'),
    JSON.stringify({ entries: exemptions }, null, 2),
    'utf-8',
  )
}

/** 跑门禁；返回 { code, stdout, stderr }（不抛） */
function runGate(): { code: number; output: string } {
  try {
    const stdout = execFileSync('node', [script, '--root', fixture], { encoding: 'utf-8' })
    return { code: 0, output: stdout }
  } catch (err) {
    const e = err as { status?: number; stdout?: string; stderr?: string }
    return { code: e.status ?? 1, output: `${e.stdout ?? ''}${e.stderr ?? ''}` }
  }
}

beforeEach(() => {
  fixture = mkdtempSync(join(tmpdir(), 'dto-gate-'))
})

afterEach(() => {
  rmSync(fixture, { recursive: true, force: true })
})

describe('check:dto 门禁：干净仓库放行', () => {
  it('手写层没有同名声明时判绿', () => {
    buildFixture({
      apiTypes: 'export interface LocalThing {\n  id: number\n}\n',
      indexTypes: 'export interface SharedThing {\n  id: number\n}\n',
    })
    const { code, output } = runGate()
    expect(code).toBe(0)
    expect(output).toContain('[PASS]')
  })
})

describe('check:dto 门禁：R1 移动端重复声明', () => {
  it('src/mobile 重复声明 @/types 已导出的 DTO → 判红并指名道姓', () => {
    buildFixture({ indexTypes: 'export interface SharedThing {\n  id: number\n}\n' })
    writeFileSync(
      join(fixture, 'src', 'mobile', 'MView.vue'),
      '<script setup lang="ts">\nimport { ref } from "vue"\ninterface SharedThing {\n  id: number\n}\n</script>\n',
      'utf-8',
    )
    const { code, output } = runGate()
    expect(code).toBe(1)
    expect(output).toContain('SharedThing')
    expect(output).toContain('src/mobile')
  })
})

describe('check:dto 门禁：R2 src/api 重复声明生成层同名类型', () => {
  it('未登记的同名类型 → 判红', () => {
    buildFixture({
      apiTypes: 'export interface Widget {\n  id: number\n}\n',
      generatedTypes: 'export interface Widget {\n  id: number\n}\n',
    })
    const { code, output } = runGate()
    expect(code).toBe(1)
    expect(output).toContain('Widget')
    expect(output).toContain('src/api/foo.ts')
  })

  it('登记在豁免表里的同名类型 → 放行', () => {
    buildFixture({
      apiTypes: 'export interface Widget {\n  id: number\n}\n',
      generatedTypes: 'export interface Widget {\n  id: number\n}\n',
      exemptions: ['src/api/foo.ts:Widget'],
    })
    const { code, output } = runGate()
    expect(code).toBe(0)
    expect(output).toContain('[PASS]')
  })

  it('豁免条目失效（对应声明已删）→ 判红，逼着清理豁免表', () => {
    buildFixture({
      apiTypes: 'export interface LocalThing {\n  id: number\n}\n',
      generatedTypes: 'export interface Widget {\n  id: number\n}\n',
      exemptions: ['src/api/foo.ts:Widget'],
    })
    const { code, output } = runGate()
    expect(code).toBe(1)
    expect(output).toContain('失效')
  })
})

describe('check:dto 门禁：R3 src/types/index.ts 重复声明生成层同名类型', () => {
  it('未登记的同名类型 → 判红', () => {
    buildFixture({
      indexTypes: 'export interface Widget {\n  id: number\n}\n',
      generatedTypes: 'export interface Widget {\n  id: number\n}\n',
    })
    const { code, output } = runGate()
    expect(code).toBe(1)
    expect(output).toContain('Widget')
    expect(output).toContain('src/types/index.ts')
  })

  it('登记在豁免表里的同名类型 → 放行', () => {
    buildFixture({
      indexTypes: 'export interface Widget {\n  id: number\n}\n',
      generatedTypes: 'export interface Widget {\n  id: number\n}\n',
      exemptions: ['src/types/index.ts:Widget'],
    })
    const { code, output } = runGate()
    expect(code, output).toBe(0)
  })
})

describe('check:dto 门禁：真实仓库当前状态', () => {
  it('本仓手写层与生成层的同名类型都在豁免表里（存量已登记）', () => {
    const { code, output } = (() => {
      try {
        const stdout = execFileSync('node', [script], { encoding: 'utf-8', cwd: repoRoot })
        return { code: 0, output: stdout }
      } catch (err) {
        const e = err as { status?: number; stdout?: string; stderr?: string }
        return { code: e.status ?? 1, output: `${e.stdout ?? ''}${e.stderr ?? ''}` }
      }
    })()
    expect(output).toBeTruthy()
    expect(code, output).toBe(0)
  })
})
