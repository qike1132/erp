/**
 * 三支前端门禁的「扫描集合为空即失败」回归（2026-10-17 审计 F2-1）。
 *
 * 被保护的门禁：`check:api`(check-api-alignment.mjs)、`check:api:pc`(check-pc-api-bypass.mjs)、
 * `check:routes`(check-route-alignment.mjs)。三个脚本原先都只看「命中了多少违规」，
 * 不看「扫到了多少文件」：
 *   - `walkDir`/`walk` 用 try/catch 吞掉 readdir 异常返回 `[]` → 空集也打 ✓；
 *   - 配对集合由「移动端 name = M + PC name」推导，命名约定一变 → 0 对也打 ✓。
 * 于是目录改名/整体挪层时门禁静默退化成空转，而 CI 仍是绿的。
 *
 * 本测试在**临时夹具**上跑同一支脚本（api/pc 用 `--root`，routes 用 `--router`），锁三件事：
 *   1. 正常夹具 → exit 0；
 *   2. 有违规夹具 → exit 1（门禁本体仍然有牙）；
 *   3. 扫描集合异常缩小 → exit 2 且给出可读原因（不是 0，也不是 1）。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const scriptsDir = resolve(here, '..', '..', 'scripts')

interface RunResult {
  code: number
  out: string
}

function runScript(script: string, args: string[]): RunResult {
  try {
    const out = execFileSync(process.execPath, [join(scriptsDir, script), ...args], {
      encoding: 'utf-8',
      stdio: 'pipe',
    })
    return { code: 0, out }
  } catch (err) {
    const e = err as { status?: number; stdout?: string; stderr?: string }
    return { code: e.status ?? -1, out: `${e.stdout ?? ''}${e.stderr ?? ''}` }
  }
}

/** 造 count 个占位文件（.vue 用最小模板，其余空） */
function fillFiles(dir: string, count: number, ext: string, body = '<template><div /></template>\n') {
  mkdirSync(dir, { recursive: true })
  for (let i = 0; i < count; i += 1) {
    writeFileSync(join(dir, `f${i}.${ext}`), ext === 'vue' ? body : '', 'utf-8')
  }
}

let fixture: string

beforeEach(() => {
  fixture = mkdtempSync(join(tmpdir(), 'gate-floor-'))
})

afterEach(() => {
  rmSync(fixture, { recursive: true, force: true })
})

describe('check-api-alignment（check:api）', () => {
  function buildCleanRoot(): string {
    // 2026-11-18 评审 M1：`src/api` 现在也有下限（MIN_API_FILES=22），
    // 夹具必须同步扩到下限之上，否则「达标 → exit 0」用例会假红。
    fillFiles(join(fixture, 'src', 'api'), 22, 'ts', '')
    writeFileSync(
      join(fixture, 'src', 'api', 'widget.ts'),
      "export const widgetApi = { get: () => get<Widget>('/api/v1/widget') }\n",
      'utf-8',
    )
    fillFiles(join(fixture, 'src', 'mobile'), 28, 'vue')
    fillFiles(join(fixture, 'src', 'views'), 160, 'vue')
    return fixture
  }

  it('src/api 缺失 → exit 2（评审 M1：判定基准必须有下限）', () => {
    // 只有 mobile 达标、api 为 0：旧实现会打印「✓ 移动端所有 API 调用均
    // 通过共享 API 层」并 exit 0 —— 而被比对的 api 层其实是空的。
    fillFiles(join(fixture, 'src', 'mobile'), 28, 'vue')
    const result = runScript('check-api-alignment.mjs', ['--root', fixture])
    expect(result.code).toBe(2)
    expect(result.out).toContain('src/api=0')
  })

  it('扫描量达标且无违规 → exit 0', () => {
    const root = buildCleanRoot()
    const result = runScript('check-api-alignment.mjs', ['--root', root])
    expect(result.code).toBe(0)
    expect(result.out).toContain('✓')
  })

  it('扫描集合异常缩小 → exit 2（不是「空集也通过」）', () => {
    mkdirSync(join(fixture, 'src', 'api'), { recursive: true })
    const result = runScript('check-api-alignment.mjs', ['--root', fixture])
    expect(result.code).toBe(2)
    expect(result.out).toContain('扫描集合异常缩小')
  })

  it('移动端自拼端点且 API 层没有 → exit 1（门禁本体仍有牙）', () => {
    const root = buildCleanRoot()
    writeFileSync(
      join(root, 'src', 'mobile', 'rogue.vue'),
      '<script setup>\nconst x = await get("/api/v1/not-in-layer")\n</script>\n',
      'utf-8',
    )
    const result = runScript('check-api-alignment.mjs', ['--root', root])
    expect(result.code).toBe(1)
  })
})

describe('check-pc-api-bypass（check:api:pc）', () => {
  it('扫描量达标且无违规 → exit 0', () => {
    fillFiles(join(fixture, 'src', 'views'), 250, 'vue')
    const result = runScript('check-pc-api-bypass.mjs', ['--root', fixture])
    expect(result.code).toBe(0)
    expect(result.out).toContain('✓')
  })

  it('扫描集合异常缩小 → exit 2', () => {
    mkdirSync(join(fixture, 'src', 'views'), { recursive: true })
    const result = runScript('check-pc-api-bypass.mjs', ['--root', fixture])
    expect(result.code).toBe(2)
    expect(result.out).toContain('扫描集合异常缩小')
  })
})

describe('check-route-alignment（check:routes）', () => {
  function buildRouter(opts: { pc: number; mobile: number; drift?: boolean }): string {
    const pcRows = Array.from(
      { length: opts.pc },
      (_, i) => `  { path: '/p${i}', name: 'P${i}', component: View }`,
    ).join(',\n')
    const mobileRows = Array.from({ length: opts.mobile }, (_, i) => {
      const path = opts.drift && i === 0 ? '/drifted' : `/p${i}`
      return `  { path: '${path}', name: 'MP${i}', component: MView }`
    }).join(',\n')
    const file = join(fixture, 'router.ts')
    writeFileSync(
      file,
      `const pcRoutes: RouteRecordRaw[] = [\n${pcRows}\n]\n`
      + `const mobileRoutes: RouteRecordRaw[] = [\n${mobileRows}\n]\n`,
      'utf-8',
    )
    return file
  }

  it('配对数量达标且路径一致 → exit 0', () => {
    const router = buildRouter({ pc: 26, mobile: 11 })
    const result = runScript('check-route-alignment.mjs', ['--router', router])
    expect(result.code).toBe(0)
  })

  it('同名路由路径漂移 → exit 1', () => {
    const router = buildRouter({ pc: 26, mobile: 11, drift: true })
    const result = runScript('check-route-alignment.mjs', ['--router', router])
    expect(result.code).toBe(1)
  })

  it('路由集合异常缩小 → exit 2', () => {
    const router = buildRouter({ pc: 3, mobile: 2 })
    const result = runScript('check-route-alignment.mjs', ['--router', router])
    expect(result.code).toBe(2)
    expect(result.out).toContain('路由集合异常缩小')
  })

  it('配对集合归零（移动端不再按 M<PCName> 命名）→ exit 2', () => {
    // 路由数量达标（26/11），但移动端 name 全不带 M 前缀 → pairs 恒为空
    const pcRows = Array.from(
      { length: 26 },
      (_, i) => `  { path: '/p${i}', name: 'P${i}', component: View }`,
    ).join(',\n')
    const mobileRows = Array.from(
      { length: 11 },
      (_, i) => `  { path: '/m${i}', name: 'X${i}', component: MView }`,
    ).join(',\n')
    const file = join(fixture, 'router-flat.ts')
    writeFileSync(
      file,
      `const pcRoutes: RouteRecordRaw[] = [\n${pcRows}\n]\n`
      + `const mobileRoutes: RouteRecordRaw[] = [\n${mobileRows}\n]\n`,
      'utf-8',
    )
    const result = runScript('check-route-alignment.mjs', ['--router', file])
    expect(result.code).toBe(2)
    expect(result.out).toContain('配对集合为空')
  })
})

describe('check-pc-api-bypass：移动端也在扫描面内（2026-10-17 审计 P2-2）', () => {
  it('src/mobile 直接 import 传输层 → exit 1（扩面前该文件完全不扫描）', () => {
    fillFiles(join(fixture, 'src', 'views'), 250, 'vue')
    mkdirSync(join(fixture, 'src', 'mobile'), { recursive: true })
    writeFileSync(
      join(fixture, 'src', 'mobile', 'Rogue.vue'),
      '<script setup>\nimport { post } from "@/api/request"\n</script>\n',
      'utf-8',
    )
    const result = runScript('check-pc-api-bypass.mjs', ['--root', fixture])
    expect(result.code).toBe(1)
    expect(result.out).toContain('src/mobile')
  })
})
