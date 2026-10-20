#!/usr/bin/env node
/**
 * Vue Query 持久化缓存 buster 同步门禁。
 *
 * 背景（2026-10-17 审计 待核实 #20）：``src/main.ts`` 的 ``persistQueryClient``
 * 用 ``buster: 'binfa-erp-v1'`` 作为 sessionStorage 缓存的失效开关——buster 一变，
 * 旧缓存整体作废。但 buster 自 2026-08-20 引入后从未 bump，期间
 * ``src/types/api.d.ts``（后端契约生成物）改了 28 次。任何一次结构变更都可能让
 * 老客户端带着与新 API 不匹配的持久化缓存运行（陈旧 UI），只靠 maxAge=24h 兜底。
 *
 * 门禁规则（快照即「上次核对过的状态」，与 gate_baseline.json 同一思路）：
 * 1. main.ts 的 buster 与快照不一致 → 必须同步快照（bump 后跑 --update）；
 * 2. api.d.ts 的 sha256 与快照不一致，而 buster 没变 → **失败**：改了契约就要 bump；
 * 3. ``--update`` 也拒绝「只换 hash 不 bump」——否则门禁可被顺手绕过。
 *
 * 用法：``node scripts/check-query-cache-buster.mjs [--update]``（由 npm run check:api 调用）
 */
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const ROOT = join(SCRIPT_DIR, '..')
const MAIN_TS = join(ROOT, 'src', 'main.ts')
const API_TYPES = join(ROOT, 'src', 'types', 'api.d.ts')
const SNAPSHOT = join(SCRIPT_DIR, 'query-cache-buster.snapshot.json')

/** 从 main.ts 源码里取 buster 字面量；缺失即报错（防止改名后门禁空转） */
export function readBuster(source) {
  const match = source.match(/buster:\s*['"]([^'"]+)['"]/)
  return match ? match[1] : null
}

export function computeHash(source) {
  return createHash('sha256').update(source).digest('hex')
}

/**
 * 纯判定：返回 { ok, errors }。
 * @param {{currentBuster: string|null, currentHash: string, snapshot: {buster: string, apiTypesSha256: string}}} input
 */
export function evaluate({ currentBuster, currentHash, snapshot }) {
  const errors = []
  if (!currentBuster) {
    errors.push('main.ts 里找不到 persistQueryClient 的 buster 字面量（改名了？门禁不能空转）')
    return { ok: false, errors }
  }
  if (currentBuster !== snapshot.buster) {
    errors.push(
      `main.ts 的 buster (${currentBuster}) 与快照 (${snapshot.buster}) 不一致：` +
      'bump 之后请运行 node scripts/check-query-cache-buster.mjs --update 并提交快照',
    )
    return { ok: false, errors }
  }
  if (currentHash !== snapshot.apiTypesSha256) {
    errors.push(
      'src/types/api.d.ts 变了，但持久化缓存 buster 没 bump：' +
      "请修改 src/main.ts 的 buster（如 'binfa-erp-v1' → 'binfa-erp-v2'），" +
      '再运行 node scripts/check-query-cache-buster.mjs --update',
    )
  }
  return { ok: errors.length === 0, errors }
}

/** --update 的写入门槛：hash 变了就必须同时 bump buster，否则拒绝落盘 */
export function evaluateUpdate({ currentBuster, currentHash, snapshot }) {
  if (!currentBuster) {
    return { ok: false, errors: ['main.ts 里找不到 buster 字面量'] }
  }
  const hashChanged = currentHash !== snapshot.apiTypesSha256
  const busterChanged = currentBuster !== snapshot.buster
  if (hashChanged && !busterChanged) {
    return {
      ok: false,
      errors: [
        '拒绝更新快照：api.d.ts 变了但 buster 没 bump。' +
        '先改 src/main.ts 的 buster，再运行 --update（否则门禁形同虚设）',
      ],
    }
  }
  return { ok: true, errors: [] }
}

function main() {
  const update = process.argv.includes('--update')
  const mainSource = readFileSync(MAIN_TS, 'utf8')
  const currentBuster = readBuster(mainSource)
  const currentHash = computeHash(readFileSync(API_TYPES, 'utf8'))
  const snapshot = JSON.parse(readFileSync(SNAPSHOT, 'utf8'))

  if (update) {
    const result = evaluateUpdate({ currentBuster, currentHash, snapshot })
    if (!result.ok) {
      for (const error of result.errors) console.error(`[query-cache-buster] ${error}`)
      process.exit(1)
    }
    writeFileSync(
      SNAPSHOT,
      `${JSON.stringify({
        _comment: 'api.d.ts 变更后必须同步 bump main.ts 的 buster；由 check-query-cache-buster.mjs 维护',
        buster: currentBuster,
        apiTypesSha256: currentHash,
      }, null, 2)}\n`,
      'utf8',
    )
    console.log(`[query-cache-buster] 快照已更新：buster=${currentBuster} hash=${currentHash.slice(0, 12)}…`)
    return
  }

  const { ok, errors } = evaluate({ currentBuster, currentHash, snapshot })
  if (!ok) {
    for (const error of errors) console.error(`[query-cache-buster] FAIL ${error}`)
    process.exit(1)
  }
  console.log(`[query-cache-buster] PASS buster=${currentBuster} 与 api.d.ts 快照同步`)
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main()
}
