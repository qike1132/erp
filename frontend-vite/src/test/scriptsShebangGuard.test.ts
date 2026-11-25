/**
 * scripts/*.mjs 首行禁 shebang（V-01 防回归守卫，2026-11-23 审计）。
 *
 * 根因：`#!/usr/bin/env node` 写在被 vitest import 的 .mjs 首行时，**Node 24 的
 * 模块执行通道不剥 shebang**，加载即 SyntaxError，整个测试文件 0 条被收集
 * （auditIgnoreGate 实测：1 failed | 286 passed，0 collected）；CI 钉的是 Node 22
 * （ci-cd.yml 三处 node-version: '22'），不受影响——shebang 一旦回归，CI 全绿
 * 看不见，只炸本地 Node 24。b67aae46 已删掉 audit-with-ignore.mjs 的一处，本
 * 守卫把整个 scripts/ 目录锁死。
 *
 * 为什么是 fs 扫描守卫而不是 eslint 规则：`npm run lint` 只扫 `src/`（不覆盖
 * scripts/），且 eslint 的 AST 遍历看不见 comment 节点（shebang 被 espree 归为
 * comment，no-restricted-syntax 选择器实测不触发）。本守卫与 Node 版本无关，
 * CI（Node 22）与本地（Node 24）的 vitest 都会执行。
 *
 * 为什么全域禁（不只锁被测试 import 的 4 个脚本）：全部脚本都只经
 * `node scripts/...` 调用（package.json 16 处 + CI + 各脚本的用法注释），shebang
 * 从未被当可执行标记用，纯残留；全域禁最简单，新增文件自动纳入。
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url)) // frontend-vite/src/test
const scriptsDir = join(here, '..', '..', 'scripts') // frontend-vite/scripts

describe('scripts/*.mjs 禁 shebang', () => {
  it('任何 .mjs 首行不得以 #! 开头（Node 24 vitest 加载即 SyntaxError）', () => {
    const files = readdirSync(scriptsDir).filter((f) => f.endsWith('.mjs'))
    // 目录定位错了就别静默全绿：扫不到文件本身就该红
    expect(files.length).toBeGreaterThan(0)

    const offenders: string[] = []
    for (const file of files) {
      // 剥 U+FEFF（BOM）：BOM 后跟 #! 时 shebang 早已失效且是 SyntaxError，同样违规
      const head = readFileSync(join(scriptsDir, file), 'utf-8').replace(/^\uFEFF/, '')
      if (head.startsWith('#!')) offenders.push(file)
    }
    expect(offenders).toEqual([])
  })
})
