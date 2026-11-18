#!/usr/bin/env node
/**
 * npm audit 的「具名豁免」闸门（CI 用）。
 *
 * 为什么不用裸 `npm audit --omit=dev --audit-level=high`：
 * npm audit **没有 ignore 机制**。只要有一条「上游暂无修复版本」的高危公告，
 * 整个 CI 就永久红；而 npm 给出的"修复"往往是降级大版本依赖（例如把
 * vue-router 5.x 降回 4.6.5），风险远大于收益。于是这里只允许**逐条具名**豁免：
 * 一条豁免 = 一个 GHSA id + 为什么可接受 + 复核日期，其余 high/critical 一律失败。
 *
 * 与仓里 `pyproject.toml` 的 `[[tool.code-quality.pip-audit-ignores]]` 同口径：
 * 豁免必须可检索、可追溯、有到期复核日，不能靠「降低阈值」或「跳过步骤」过门禁。
 *
 * 判定：某包及其全部传递来源（`via` 里的字符串项）都落在豁免名单里 ⇒ 不算失败。
 */
import { spawnSync } from 'node:child_process'

/**
 * 具名豁免表。每条必须写清：哪个公告、为什么现在可接受、什么时候复核。
 * `review_by` 到期后本脚本直接失败（强制复核，避免豁免变成永久后门）。
 */
export const IGNORES = [
  {
    id: 'GHSA-fc5q-39xc-vjpf',
    pkg: 'picomatch',
    reason:
      'ReDoS（CWE-1333，CVSS 7.5）。公告 range 为 <=4.0.7（含最新 4.0.7），上游尚未发布'
      + '修复版本；npm 给的“修复”是把 vue-router 5.x 降回 4.6.5（semver-major），'
      + '属框架回退，不在本 CL 范围。本项目的 picomatch 只用于构建期 glob（vite/vitest/'
      + 'unplugin 链路），不经手不可信的运行时输入。',
    review_by: '2026-12-18',
  },
]

const HIGH = new Set(['high', 'critical'])

function ghsaFromUrl(url) {
  const m = /advisories\/(GHSA-[a-z0-9-]+)/i.exec(String(url || ''))
  return m ? m[1] : null
}

/**
 * 计算「未被豁免的 high/critical 包」。纯函数，便于单测。
 * @param {Record<string, {severity?: string, via?: Array<string|{url?: string}>}>} vulns
 * @param {{id: string, review_by?: string}[]} ignores
 * @param {Date} today
 */
export function unwaivedVulnerabilities(vulns, ignores = IGNORES, today = new Date()) {
  const active = []
  const expired = []
  for (const item of ignores) {
    const due = item.review_by ? new Date(`${item.review_by}T00:00:00Z`) : null
    if (due && today > due) expired.push(item)
    else active.push(item)
  }
  const ids = new Set(active.map((i) => i.id))

  const memo = new Map()
  const ignoredOnly = (name, seen = new Set()) => {
    const v = vulns?.[name]
    if (!v) return true
    if (!HIGH.has(String(v.severity))) return true
    if (memo.has(name)) return memo.get(name)
    if (seen.has(name)) return true // 环，按已豁免处理
    seen.add(name)
    let ok = true
    for (const via of v.via ?? []) {
      if (typeof via === 'string') {
        if (!ignoredOnly(via, seen)) { ok = false; break }
      } else {
        const id = ghsaFromUrl(via?.url)
        if (!id || !ids.has(id)) { ok = false; break }
      }
    }
    memo.set(name, ok)
    return ok
  }

  const failing = Object.keys(vulns ?? {}).filter(
    (name) => HIGH.has(String(vulns[name]?.severity)) && !ignoredOnly(name),
  )
  const applied = active.filter((i) => Object.keys(vulns ?? {}).some(
    (name) => (vulns[name]?.via ?? []).some((via) => typeof via !== 'string' && ghsaFromUrl(via?.url) === i.id),
  ))
  return { failing: failing.sort(), applied, expired }
}

function runAudit() {
  // 用「整条命令 + shell」而不是「可执行文件 + 参数 + shell」：后者在 Node 里已弃用
  // （DEP0190，参数不转义），而 Windows 上 `npm` 是 .cmd，不起 shell 又找不到可执行文件。
  const res = spawnSync('npm audit --omit=dev --json', {
    encoding: 'utf8',
    shell: true,
    maxBuffer: 32 * 1024 * 1024,
  })
  // 有漏洞时 npm 退出码非 0，JSON 仍在 stdout —— 我们只要报告，不要退出码。
  const raw = (res.stdout || '').trim()
  if (!raw) {
    return { error: `npm audit 未返回 JSON（stderr: ${(res.stderr || '').slice(0, 400)}）` }
  }
  try {
    return { report: JSON.parse(raw) }
  } catch (e) {
    return { error: `npm audit 输出无法解析为 JSON: ${e.message}` }
  }
}

function main() {
  const { report, error } = runAudit()
  if (error) {
    console.error(`[FAIL] ${error}`)
    process.exit(2)
  }
  const { failing, applied, expired } = unwaivedVulnerabilities(report.vulnerabilities ?? {})

  if (expired.length > 0) {
    console.error('[FAIL] 以下 npm audit 豁免已到期，必须复核后再放行：')
    for (const i of expired) console.error(`  - ${i.id}（${i.pkg}，复核日 ${i.review_by}）`)
    process.exit(1)
  }
  for (const i of applied) {
    console.log(`[豁免] ${i.id}（${i.pkg}）— ${i.reason}（复核日 ${i.review_by}）`)
  }
  if (failing.length > 0) {
    console.error(`[FAIL] 存在未豁免的 high/critical 漏洞（${failing.length} 个）：${failing.join(', ')}`)
    console.error('  处置：升级依赖，或在 scripts/audit-with-ignore.mjs 的 IGNORES 里逐条具名豁免'
      + '（必须写理由与复核日期）。')
    process.exit(1)
  }
  console.log('[PASS] npm audit：无未豁免的 high/critical 漏洞')
}

if (import.meta.url === `file://${process.argv[1]?.replace(/\\/g, '/')}`
  || process.argv[1]?.endsWith('audit-with-ignore.mjs')) {
  main()
}
