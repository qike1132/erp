import { describe, expect, it } from 'vitest'

// @ts-expect-error 脚本是无类型的 .mjs（纯函数由本用例锁定）
import { IGNORES, unwaivedVulnerabilities } from '../../scripts/audit-with-ignore.mjs'

/**
 * 回归锁（2026-11-18 CI 修复）：npm audit 的**具名豁免**闸门。
 *
 * 背景：`npm audit --omit=dev --audit-level=high` 没有 ignore 机制，一条「上游暂无
 * 修复版本」的高危公告就会让 CI 永久红（picomatch GHSA-fc5q-39xc-vjpf 即此情形：
 * 公告 range `<=4.0.7`，npm 的"修复"是把 vue-router 5.x 降回 4.6.5）。这里改用
 * 可追溯的豁免表：只放行名单内的 GHSA 及其传递来源，其余 high/critical 一律失败；
 * 豁免到期必须复核。
 */

type Vuln = { severity?: string, via?: unknown[] }

const picomatchAdvisory = {
  severity: 'high',
  via: [{
    name: 'picomatch',
    url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf',
    severity: 'high',
    range: '<=4.0.7',
  }],
}

/** 真实图的等价简化：picomatch 高危 → vue-router 经由它变成 high。 */
function graphWithTransitive(): Record<string, Vuln> {
  return {
    picomatch: picomatchAdvisory,
    'fdir': { severity: 'high', via: ['picomatch'] },
    'tinyglobby': { severity: 'high', via: ['fdir', 'picomatch'] },
    'vue-router': { severity: 'high', via: ['picomatch', 'tinyglobby'] },
  }
}

function now(): Date {
  return new Date('2026-11-18T00:00:00Z')
}

describe('npm audit 具名豁免闸门', () => {
  it('名单内的公告 + 其全部传递来源 → 不算失败', () => {
    const r = unwaivedVulnerabilities(graphWithTransitive(), IGNORES, now())
    expect(r.failing).toEqual([])
    expect(r.applied.map((i: { id: string }) => i.id)).toContain('GHSA-fc5q-39xc-vjpf')
  })

  it('传递链上多一条未豁免的 high → 必须失败（豁免不能顺带放过别的漏洞）', () => {
    const g = graphWithTransitive()
    g['lodash'] = {
      severity: 'high',
      via: [{ url: 'https://github.com/advisories/GHSA-xxxx-yyyy-zzzz' }],
    }
    const r = unwaivedVulnerabilities(g, IGNORES, now())
    expect(r.failing).toContain('lodash')
  })

  it('豁免已过 review_by → 直接判失败（不允许变成永久后门）', () => {
    const r = unwaivedVulnerabilities(
      graphWithTransitive(), IGNORES, new Date('2027-01-01T00:00:00Z'),
    )
    expect(r.expired.length).toBeGreaterThan(0)
  })

  it('moderate 不参与判定（本闸门只管 high/critical）', () => {
    const r = unwaivedVulnerabilities(
      { foo: { severity: 'moderate', via: [{ url: 'https://github.com/advisories/GHSA-a-b-c' }] } },
      IGNORES, now(),
    )
    expect(r.failing).toEqual([])
  })
})
