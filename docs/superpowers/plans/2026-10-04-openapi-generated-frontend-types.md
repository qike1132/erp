# OpenAPI 生成前端 DTO 类型 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 FastAPI 的 OpenAPI schema 生成 `frontend-vite/src/types/api.d.ts`，并用门禁锁住它与后端契约同步。

**Architecture:** 三段解耦。① 后端侧：`check_openapi_frontend_alignment.py --export` 产出快照 `frontend-vite/openapi.json` 并校验它没过期（python job，有 fastapi_app、无 node）。② 前端侧：`generate-api-types.mjs` 读快照生成 `api.d.ts`，`--check` 模式校验同步（frontend job，有 node、无 fastapi_app）。两个检查各在拥有对应运行时的 job 里跑，互不依赖。

**Tech Stack:** Python 3.13（FastAPI 离线 `app.openapi()`）、Node 22（ESM `.mjs`）、vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-10-04-openapi-generated-frontend-types-design.md`

**范围说明：** 本计划覆盖 spec 的 ①导出 ②生成 ③门禁 ④收敛——但 ④ 只做「建立基线 + 用一个域证明收敛方法可行」。全仓 130 处 `as unknown as` 跨 51 个文件的收敛是独立的一轮工作，需单独立计划（见 Task 5 结尾）。

## Global Constraints

- Node >= 22（仓库 engines 硬约束）；前端脚本用 ESM `.mjs`，与现有 `check-*.mjs` 同栈。
- **本机既是生产也是运维主机**：计划内所有命令都是只读的生成/校验，不触碰生产库、不重启服务。
- 生成物 `src/types/api.d.ts` **必须入库**且为只读产物；`check:types` 逐字节校验同步。
- **不得**改动任何 `list[dict]` 响应 schema（会剥掉 handler 注入字段，前端立刻坏）。
- **不得**让生成物覆盖 8 个前端视图模型：`NavItem`/`NavSection`（`useSidebarNav.ts` 与 `index.ts` 两份）、`MonthlySummary`、`FabricItem`、`ProductListResponse`（purchase.ts）、`AvailableStockinItem`。
- 提交信息写**为什么**；一个提交做一件事。
- 本机**未装 pre-commit**，`.githooks/pre-commit` 第 3 层会降级为「暂存含 .py/.vue 时直接跑 quality_gate.py」。

## Review Focus

以下输入/失败模式最可能让使用者踩坑，各自在所属任务的测试里钉住：

1. **生成物被 prettier 重排 → 同步检查假红。** 仓库无 `.prettierignore`，`lint-staged` 会对 `*.ts` 跑 prettier。漏配一个忽略路径就复发。（Task 2）
2. **尾段撞名的 schema 被静默合并。** 实测 10 组撞名（`StagingListResponse`、`TrendResponse`、`ActionResponse` 等），名字相同但结构不同，合并会让前端拿到错的类型。（Task 1）
3. **`list[dict]` 响应被当成有类型。** `OrderListResponse.data` 生成 `Array<Record<string, unknown>>` 却可能被误当真实类型用，掩盖注入字段。（Task 2）
4. **后端改字段但没人重导快照 → 假绿。** 生成器只读快照，快照过期则全链路无声通过。（Task 4）
5. **前端视图模型被生成物覆盖 → 运行时 undefined。** 如 `NavItem.title` 是 store 适配层产物，后端 schema 里没有。（Task 2）

---

### Task 1: 生成器映射核心 + 单测

**Files:**
- Create: `frontend-vite/scripts/generate-api-types.mjs`
- Create: `frontend-vite/scripts/generate-api-types.d.mts`
- Test: `frontend-vite/src/test/generateApiTypes.test.ts`

**Interfaces:**
- Produces:
  - `generateTypes(spec: object): string` — 由 OpenAPI 文档产出完整 `.d.ts` 文本
  - `tsTypeOf(node: object, nameMap: Map<string,string>): string` — 单个 schema 节点 → TS 类型串
  - `buildNameMap(schemaKeys: string[]): Map<string,string>` — schema 原始键 → 唯一 TS 标识符
  - `sanitizeIdent(name: string): string` — 非法标识符/保留字消毒

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/generateApiTypes.test.ts`：

```ts
import { describe, it, expect } from 'vitest'
import { generateTypes, tsTypeOf, buildNameMap, sanitizeIdent } from '../../scripts/generate-api-types.mjs'

describe('tsTypeOf 映射规则', () => {
  it('基础类型与 required/optional', () => {
    const map = new Map<string, string>()
    const spec = {
      components: {
        schemas: {
          Foo: {
            type: 'object',
            required: ['a'],
            properties: { a: { type: 'integer' }, b: { type: 'string' } },
          },
        },
      },
    }
    const out = generateTypes(spec)
    expect(out).toContain('export interface Foo {')
    expect(out).toMatch(/^\s+a: number$/m)
    expect(out).toMatch(/^\s+b\?: string$/m)
  })

  it('anyOf [X, null] 塌成 X | null', () => {
    const out = tsTypeOf({ anyOf: [{ type: 'string' }, { type: 'null' }] }, new Map())
    expect(out).toBe('string | null')
  })

  it('$ref 解析为名字映射结果', () => {
    const map = new Map([['Bar', 'Bar']])
    expect(tsTypeOf({ $ref: '#/components/schemas/Bar' }, map)).toBe('Bar')
  })

  it('enum 字面量联合', () => {
    expect(tsTypeOf({ enum: ['a', 'b'] }, new Map())).toBe('"a" | "b"')
  })

  it('数组：items 是 $ref 则 Array<Ref>', () => {
    const map = new Map([['Bar', 'Bar']])
    expect(tsTypeOf({ type: 'array', items: { $ref: '#/components/schemas/Bar' } }, map)).toBe('Array<Bar>')
  })

  it('数组：items 是裸 object（list[dict]）则 Array<Record<string, unknown>>', () => {
    expect(tsTypeOf({ type: 'array', items: { type: 'object', additionalProperties: true } }, new Map())).toBe('Array<Record<string, unknown>>')
  })

  it('数组：items 无 schema 则 Array<unknown>', () => {
    expect(tsTypeOf({ type: 'array' }, new Map())).toBe('Array<unknown>')
  })

  it('非标识符字段名加引号', () => {
    const spec = {
      components: {
        schemas: {
          Odd: { type: 'object', required: ['kebab-key'], properties: { 'kebab-key': { type: 'string' } } },
        },
      },
    }
    expect(generateTypes(spec)).toMatch(/^\s+"kebab-key": string$/m)
  })
})

describe('buildNameMap 撞名消歧', () => {
  it('尾段唯一时用尾段', () => {
    const m = buildNameMap(['fastapi_app__schemas__order__OrderListResponse'])
    expect(m.get('fastapi_app__schemas__order__OrderListResponse')).toBe('OrderListResponse')
  })

  it('尾段撞名时用最短唯一后缀，不静默合并', () => {
    const keys = [
      'fastapi_app__schemas__staging__StagingListResponse',
      'fastapi_app__schemas__production_plan__StagingListResponse',
    ]
    const m = buildNameMap(keys)
    const a = m.get(keys[0])!
    const b = m.get(keys[1])!
    expect(a).not.toBe(b)
    expect(a).toBe('staging_StagingListResponse')
    expect(b).toBe('production_plan_StagingListResponse')
  })
})

describe('sanitizeIdent', () => {
  it('保留字与首字符非法时加前缀', () => {
    expect(sanitizeIdent('default')).toBe('_default')
    expect(sanitizeIdent('1x')).toBe('_1x')
    expect(sanitizeIdent('Normal')).toBe('Normal')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/generateApiTypes.test.ts`
Expected: FAIL —— `Failed to resolve import "../../scripts/generate-api-types.mjs"`

- [ ] **Step 3: 写生成器核心**

创建 `frontend-vite/scripts/generate-api-types.mjs`：

```js
// 由 FastAPI OpenAPI schema 生成前端 DTO 类型。
// 只读脚本，不连数据库、不依赖运行中的服务。
import { readFileSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const HEADER = [
  '// @generated by scripts/generate-api-types.mjs — DO NOT EDIT',
  '// 源: frontend-vite/openapi.json（由 python scripts/check_openapi_frontend_alignment.py --export 产出）',
  '/* eslint-disable */',
  '',
].join('\n')

const PRIMITIVE = { integer: 'number', number: 'number', string: 'string', boolean: 'boolean', null: 'null' }
const IDENT = /^[A-Za-z_$][A-Za-z0-9_$]*$/
const RESERVED = new Set(['interface','type','enum','class','function','new','delete','import','export','default','extends','implements','in','instanceof','return','this','typeof','void','with','yield','null','true','false','const','let','var','if','else','for','while','do','switch','case','break','continue','try','catch','finally','throw','super','await','async','static','public','private','protected','readonly','declare','namespace','module','abstract','as','is','keyof','infer','never','unknown','any','number','string','boolean','symbol','object','undefined'])

export function sanitizeIdent(name) {
  let s = String(name).replace(/[^A-Za-z0-9_$]/g, '_')
  if (!/^[A-Za-z_$]/.test(s)) s = '_' + s
  if (RESERVED.has(s)) s = '_' + s
  return s
}

export function buildNameMap(schemaKeys) {
  const segs = (k) => k.split('__')
  const map = new Map()
  for (const key of schemaKeys) {
    const parts = segs(key)
    let chosen = parts[parts.length - 1]
    for (let n = 1; n <= parts.length; n++) {
      const cand = parts.slice(parts.length - n).join('_')
      const clash = schemaKeys.some((o) => o !== key && segs(o).slice(-n).join('_') === cand)
      if (!clash) { chosen = cand; break }
      if (n === parts.length) chosen = parts.join('_')
    }
    map.set(key, sanitizeIdent(chosen))
  }
  return map
}

function propKey(name) { return IDENT.test(name) ? name : JSON.stringify(name) }

function unionOf(nodes, nameMap) {
  return [...new Set(nodes.map((n) => tsTypeOf(n, nameMap)))].join(' | ')
}

function objectBody(schema, nameMap, indent = '  ') {
  const required = new Set(schema.required ?? [])
  return Object.entries(schema.properties)
    .map(([name, node]) => `${indent}${propKey(name)}${required.has(name) ? '' : '?'}: ${tsTypeOf(node, nameMap)}`)
    .join('\n')
}

export function tsTypeOf(node, nameMap) {
  if (!node || typeof node !== 'object') return 'unknown'
  if (typeof node.$ref === 'string') {
    const raw = node.$ref.split('/').pop()
    return nameMap.get(raw) ?? sanitizeIdent(raw)
  }
  if (Array.isArray(node.anyOf)) return unionOf(node.anyOf, nameMap)
  if (Array.isArray(node.oneOf)) return unionOf(node.oneOf, nameMap)
  if (Array.isArray(node.allOf)) return node.allOf.map((n) => tsTypeOf(n, nameMap)).join(' & ')
  if (Array.isArray(node.enum)) return node.enum.map((v) => JSON.stringify(v)).join(' | ')
  if (node.type === 'array') return `Array<${node.items ? tsTypeOf(node.items, nameMap) : 'unknown'}>`
  if (node.type === 'object') {
    if (node.properties) return '{\n' + objectBody(node, nameMap) + '\n}'
    // 裸 dict / list[dict] 的 items：additionalProperties 为 true 或 schema
    const ap = node.additionalProperties
    if (ap && typeof ap === 'object') return `Record<string, ${tsTypeOf(ap, nameMap)}>`
    return 'Record<string, unknown>'
  }
  return PRIMITIVE[node.type] ?? 'unknown'
}

export function generateTypes(spec) {
  const schemas = (spec.components && spec.components.schemas) || {}
  const keys = Object.keys(schemas).sort()
  const nameMap = buildNameMap(keys)
  const blocks = keys.map((key) => {
    const schema = schemas[key]
    const name = nameMap.get(key)
    if (!schema.properties) return `export type ${name} = ${tsTypeOf(schema, nameMap)}`
    return `export interface ${name} {\n${objectBody(schema, nameMap)}\n}`
  })
  return HEADER + blocks.join('\n\n') + '\n'
}
```

同时创建 `frontend-vite/scripts/generate-api-types.d.mts`（让 TS 能解析 `.mjs` 的导出，无需改 tsconfig）：

```ts
export declare function sanitizeIdent(name: string): string
export declare function buildNameMap(schemaKeys: string[]): Map<string, string>
export declare function tsTypeOf(node: unknown, nameMap: Map<string, string>): string
export declare function generateTypes(spec: unknown): string
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/generateApiTypes.test.ts`
Expected: PASS（全部用例）

- [ ] **Step 5: 确认类型检查不被破坏**

Run: `cd frontend-vite && npm run type-check`
Expected: 退出码 0（`.d.mts` 生效，测试文件不报「找不到声明文件」）

- [ ] **Step 6: 提交**

```bash
git add frontend-vite/scripts/generate-api-types.mjs frontend-vite/scripts/generate-api-types.d.mts frontend-vite/src/test/generateApiTypes.test.ts
git commit -m "feat(前端): OpenAPI→TS 生成器核心，撞名 schema 用最短唯一后缀消歧"
```

---

### Task 2: 生成 api.d.ts + 免疫 lint/format + npm 接线

**Files:**
- Modify: `frontend-vite/scripts/generate-api-types.mjs`（追加 CLI）
- Create: `frontend-vite/openapi.json`（快照）
- Create: `frontend-vite/src/types/api.d.ts`（生成物）
- Create: `frontend-vite/.prettierignore`
- Modify: `frontend-vite/eslint.config.js:79`
- Modify: `frontend-vite/package.json`（scripts）
- Test: `frontend-vite/src/test/generateApiTypes.honesty.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `generateTypes`
- Produces: npm 脚本 `gen:api`、`check:types`；CLI 契约 `node scripts/generate-api-types.mjs <spec.json> --out <file> [--check]`，退出码 0=同步 / 1=漂移 / 2=环境错误

- [ ] **Step 1: 写诚实性守卫测试（失败）**

创建 `frontend-vite/src/test/generateApiTypes.honesty.test.ts`：

```ts
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')

describe('生成物诚实性', () => {
  const dts = readFileSync(resolve(root, 'src/types/api.d.ts'), 'utf-8')

  it('list[dict] 响应产出 Record<string, unknown> 而非伪装的具体字段', () => {
    // OrderListResponse.data: list[dict]，实测 handler 注入 5 个字段 schema 看不见。
    // required=["data"] 已实测，故 data 必填、不带 ?。
    const m = /export interface OrderListResponse \{([\s\S]*?)\n\}/.exec(dts)
    expect(m).not.toBeNull()
    expect(m![1]).toMatch(/^\s+data: Array<Record<string, unknown>>$/m)
  })

  it('注入字段不出现在生成物里（生成层不假装覆盖）', () => {
    const item = /export interface OrderItemSchema \{([\s\S]*?)\n\}/.exec(dts)
    expect(item).not.toBeNull()
    for (const f of ['product_image', 'purchase_order_qty', 'spare_quantity', 'is_ordered', 'has_processes']) {
      expect(item![1]).not.toContain(f)
    }
  })

  it('撞名的 schema 产出两个不同的标识符，未静默合并', () => {
    // staging 与 production_plan 各有一个 StagingListResponse（结构不同）
    expect(dts).toMatch(/export interface staging_StagingListResponse \{/)
    expect(dts).toMatch(/export interface production_plan_StagingListResponse \{/)
  })
})

describe('前端视图模型未被删（生成物不覆盖它们）', () => {
  const handwritten = readFileSync(resolve(root, 'src/types/index.ts'), 'utf-8')

  it('会丢字段的前端视图模型仍在手写层', () => {
    // 这批名字与后端 schema 同名但结构不同（含前端自加字段），必须保留手写
    for (const name of ['MonthlySummary', 'NavSection', 'NavItem']) {
      expect(handwritten).toMatch(new RegExp(`export interface ${name}\\b`))
    }
    expect(handwritten).toMatch(/daily_data/) // MonthlySummary 的前端聚合字段
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/generateApiTypes.honesty.test.ts`
Expected: FAIL —— `ENOENT: no such file ... src/types/api.d.ts`

- [ ] **Step 3: 给生成器追加 CLI**

在 `frontend-vite/scripts/generate-api-types.mjs` 末尾追加：

```js
function main() {
  const args = process.argv.slice(2)
  const check = args.includes('--check')
  const outI = args.indexOf('--out')
  const out = outI >= 0 ? args[outI + 1] : null
  const input = args.find((a, i) => !a.startsWith('--') && i !== outI + 1)
  if (!input || !out) {
    console.error('用法: node scripts/generate-api-types.mjs <openapi.json> --out <file> [--check]')
    process.exit(2)
  }
  let spec
  try { spec = JSON.parse(readFileSync(input, 'utf8')) }
  catch (e) { console.error('[ERROR] 无法读取/解析 ' + input + ': ' + e.message); process.exit(2) }

  const generated = generateTypes(spec)
  if (check) {
    let current
    try { current = readFileSync(out, 'utf8') }
    catch { console.error('[FAIL] 生成物不存在: ' + out + '（跑 `npm run gen:api` 生成）'); process.exit(1) }
    if (current.replace(/\r\n/g, '\n') !== generated) {
      console.error('[FAIL] ' + out + ' 与 openapi.json 不同步。跑 `npm run gen:api` 后提交。')
      process.exit(1)
    }
    console.log('[PASS] ' + out + ' 与 openapi.json 同步。')
    process.exit(0)
  }
  writeFileSync(out, generated, 'utf8')
  console.log('[OK] 已生成 ' + out + '（' + generated.split('\n').length + ' 行）')
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
```

- [ ] **Step 4: 产出快照并生成 api.d.ts**

Run（仓库根）: `python scripts/check_openapi_frontend_alignment.py --export frontend-vite/openapi.json`
Expected: 退出码 0，打印契约检查结果，并写出 `frontend-vite/openapi.json`

Run: `cd frontend-vite && node scripts/generate-api-types.mjs openapi.json --out src/types/api.d.ts`
Expected: `[OK] 已生成 src/types/api.d.ts（约 3000+ 行）`

- [ ] **Step 5: 免疫 prettier 与 eslint**

创建 `frontend-vite/.prettierignore`：

```
dist/**
dist-new/**
node_modules/**
src/auto-imports.d.ts
src/components.d.ts
src/env.d.ts
src/types/api.d.ts
```

修改 `frontend-vite/eslint.config.js:79`，把生成物加入 ignores（与现有三个 `.d.ts` 同一套约定）：

```js
    ignores: ['dist/**', 'node_modules/**', 'src/auto-imports.d.ts', 'src/components.d.ts', 'src/env.d.ts', 'src/types/api.d.ts'],
```

- [ ] **Step 6: npm 接线**

在 `frontend-vite/package.json` 的 `scripts` 里，`check:api` 那行之后插入：

```json
    "gen:api": "node scripts/generate-api-types.mjs openapi.json --out src/types/api.d.ts",
    "check:types": "node scripts/generate-api-types.mjs openapi.json --out src/types/api.d.ts --check",
```

- [ ] **Step 7: 跑测试确认通过 + 确认门禁不被误伤**

Run: `cd frontend-vite && npx vitest run src/test/generateApiTypes.honesty.test.ts`
Expected: PASS

Run: `cd frontend-vite && npm run lint && npm run check:types`
Expected: 两者均退出码 0。`check:types` 打印 `[PASS] ... 同步`

- [ ] **Step 8: 提交**

```bash
git add frontend-vite/scripts/generate-api-types.mjs frontend-vite/openapi.json frontend-vite/src/types/api.d.ts frontend-vite/.prettierignore frontend-vite/eslint.config.js frontend-vite/package.json frontend-vite/src/test/generateApiTypes.honesty.test.ts
git commit -m "feat(前端): 生成 api.d.ts 并接上门禁 —— 生成物对 lint/format 免疫，避免同步检查假红"
```

---

### Task 3: 同步门禁的漂移回归 + CI 接线

**Files:**
- Test: `frontend-vite/src/test/generateApiTypes.sync.test.ts`
- Modify: `.github/workflows/ci-cd.yml:290-295`

**Interfaces:**
- Consumes: Task 2 的 CLI 契约（`--check`，退出码语义）

- [ ] **Step 1: 写漂移回归测试（失败）**

创建 `frontend-vite/src/test/generateApiTypes.sync.test.ts`：

```ts
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
    const first = Object.keys(spec.components.schemas)[0]
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/generateApiTypes.sync.test.ts`
Expected: 若 Task 2 的 `--check` 未接线则 FAIL；接线后应 PASS。若已 PASS 说明 Task 2 已就绪，继续。

- [ ] **Step 3: CI 接线（frontend job）**

修改 `.github/workflows/ci-cd.yml` 第 290-295 行的对齐检查块，加入 `check:types`：

```yaml
    - name: Run frontend cross-layer alignment checks
      run: |
        npm run check:api
        npm run check:api:pc
        npm run check:routes
        npm run check:dto
        npm run check:types
```

- [ ] **Step 4: 本地验证整块门禁**

Run: `cd frontend-vite && npm run check:api && npm run check:api:pc && npm run check:routes && npm run check:dto && npm run check:types`
Expected: 全部退出码 0

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/test/generateApiTypes.sync.test.ts .github/workflows/ci-cd.yml
git commit -m "test(前端): 钉住 api.d.ts 同步门禁能检出漂移，并接入 CI 对齐检查块"
```

---

### Task 4: 后端快照新鲜度门禁 + 测试

**Files:**
- Modify: `scripts/check_openapi_frontend_alignment.py`（加 `--snapshot` 与比对函数）
- Modify: `.github/workflows/ci-cd.yml:102-103`（test job 那一步加参数）
- Test: `tests/test_openapi_snapshot_freshness.py`

**Interfaces:**
- Produces: `spec_fingerprint(spec: dict) -> str`；CLI 新参数 `--snapshot PATH`
- Consumes: Task 2 产出的 `frontend-vite/openapi.json`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_openapi_snapshot_freshness.py`：

```python
# tests/test_openapi_snapshot_freshness.py
"""回归锁: openapi.json 快照过期时，契约门禁必须判红。

背景: 生成器只读 frontend-vite/openapi.json。若后端改了 schema 而没人重导快照，
前端类型会无声地停留在旧契约上（假绿）。本测试钉住 --snapshot 能检出这种过期。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_openapi_frontend_alignment.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
    )


def test_snapshot_fresh_passes(tmp_path: Path) -> None:
    live = _run(["--export", str(tmp_path / "live.json")])
    assert live.returncode == 0, live.stderr
    r = _run(["--openapi", str(tmp_path / "live.json"), "--snapshot", str(tmp_path / "live.json")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "一致" in r.stdout


def test_snapshot_stale_fails(tmp_path: Path) -> None:
    live = _run(["--export", str(tmp_path / "live.json")])
    assert live.returncode == 0, live.stderr
    stale = json.loads((tmp_path / "live.json").read_text(encoding="utf-8"))
    stale["paths"]["/__drift_probe__"] = {"get": {"responses": {"200": {"description": "x"}}}}
    (tmp_path / "stale.json").write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    r = _run(["--openapi", str(tmp_path / "live.json"), "--snapshot", str(tmp_path / "stale.json")])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "过期" in r.stdout or "不一致" in r.stdout
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_openapi_snapshot_freshness.py -v`
Expected: FAIL —— `unrecognized arguments: --snapshot`

- [ ] **Step 3: 实现 --snapshot**

在 `scripts/check_openapi_frontend_alignment.py` 中，`spec_paths` 函数之后插入：

```python
def spec_fingerprint(spec: dict) -> str:
    """结构化指纹：键序无关，用于比较两份规范是否等价。"""
    return json.dumps(spec, sort_keys=True, ensure_ascii=False)


def check_snapshot(live: dict, snapshot: dict) -> int:
    """比较现算规范与已提交快照；返回 0=一致，1=过期。"""
    if spec_fingerprint(live) == spec_fingerprint(snapshot):
        print("[PASS] openapi.json 快照与后端 app.openapi() 一致。")
        return 0
    live_paths = spec_paths(live)
    snap_paths = {str(p) for p in (snapshot.get("paths") or {})}
    added = sorted(live_paths - snap_paths)
    removed = sorted(snap_paths - live_paths)
    print("[FAIL] openapi.json 快照已过期 —— 后端 schema 变了但没人重导。")
    if added:
        print("  后端新增路径 " + str(len(added)) + " 条，例如: " + ", ".join(added[:5]))
    if removed:
        print("  后端删除路径 " + str(len(removed)) + " 条，例如: " + ", ".join(removed[:5]))
    if not added and not removed:
        print("  路径集合相同，差异在 schema 定义内部（字段/类型）。")
    print("  修复: python scripts/check_openapi_frontend_alignment.py --export frontend-vite/openapi.json")
    print("        然后 cd frontend-vite && npm run gen:api，一并提交。")
    return 1
```

在 `main()` 里 `--api-dir` 参数之后加入：

```python
    parser.add_argument("--snapshot", type=Path, default=None, help="比较该已提交快照与现算规范是否一致（过期即判失败）")
```

在 `main()` 中 `spec` 求值之后（`backend = spec_paths(spec)` 之后）插入：

```python
    if args.snapshot is not None:
        try:
            snapshot = load_spec_file(args.snapshot)
        except SpecError as exc:
            print("[ERROR] " + str(exc), file=sys.stderr)
            return 2
        rc = check_snapshot(spec, snapshot)
        if rc != 0:
            return rc
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_openapi_snapshot_freshness.py -v`
Expected: PASS（两个用例）

- [ ] **Step 5: CI 接线（test job）**

修改 `.github/workflows/ci-cd.yml` 第 102-103 行那一步：

```yaml
    - name: Check frontend endpoints against backend OpenAPI
      run: python scripts/check_openapi_frontend_alignment.py --verbose --snapshot frontend-vite/openapi.json
```

- [ ] **Step 6: 端到端验证**

Run: `python scripts/check_openapi_frontend_alignment.py --verbose --snapshot frontend-vite/openapi.json`
Expected: 退出码 0，打印契约检查与快照一致性

- [ ] **Step 7: 提交**

```bash
git add scripts/check_openapi_frontend_alignment.py tests/test_openapi_snapshot_freshness.py .github/workflows/ci-cd.yml
git commit -m "feat(门禁): OpenAPI 快照过期即判红 —— 堵住信号生成器只读快照引入的假绿"
```

---

### Task 5: 断言收敛首批 + 基线回归

**Files:**
- Test: `frontend-vite/src/test/apiTypeAssertionBaseline.test.ts`
- Modify: `frontend-vite/src/api/stock.ts:40`（首个收敛样例）
- Modify: `frontend-vite/src/types/index.ts`（如需，导出 `InventoryResponse` 等已在生成物的类型）

**Interfaces:**
- Consumes: Task 2 的 `src/types/api.d.ts`

**说明：** 实测 130 处 `as unknown as` 里，**api 层只有 2 处**（`stock.ts:40`、`request.ts:247`），其余 **128 处全在 views/stores 层**。本任务只做两件事：① 建立防回潮的基线回归；② 收敛 `stock.ts:40` 作为方法样例。视图层 128 处的收敛需单独立计划（spec ④ 明确要求逐个判断、发现存量 bug 就停下报告，不能批量 sed）。`request.ts:247` 的 `as unknown as Blob` 涉及 axios `responseType:'blob'` 的响应类型，收敛需单独核实，本任务不动它。

- [ ] **Step 1: 写基线测试（记录当前断言数）**

创建 `frontend-vite/src/test/apiTypeAssertionBaseline.test.ts`：

```ts
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const src = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function walk(dir: string, acc: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const full = join(dir, e)
    if (statSync(full).isDirectory()) { if (e !== 'test') walk(full, acc) }
    else if (/\.(ts|vue)$/.test(e)) acc.push(full)
  }
  return acc
}

export function countAssertions(): number {
  let n = 0
  for (const f of walk(src)) {
    const text = readFileSync(f, 'utf-8')
    n += (text.match(/as unknown as/g) ?? []).length
  }
  return n
}

describe('as unknown as 断言基线', () => {
  it('断言总数不超过基线（防回潮）', () => {
    const total = countAssertions()
    // 基线在执行本任务时实测填入；只允许下调，清理后同步收紧此值
    expect(total).toBeLessThanOrEqual(130)
  })

  it('收敛样例：stockApi.stats 的断言已消除', () => {
    const text = readFileSync(resolve(src, 'api/stock.ts'), 'utf-8')
    expect(text).not.toContain('as unknown as typeof resp.data')
  })
})
```

- [ ] **Step 2: 跑测试确认第二条失败**

Run: `cd frontend-vite && npx vitest run src/test/apiTypeAssertionBaseline.test.ts`
Expected: FAIL —— `stockApi.stats 的断言已消除` 用例失败（该断言仍在）

- [ ] **Step 3: 收敛 stock.ts 的断言**

`frontend-vite/src/api/stock.ts:37-41` 当前为：

```ts
export const stockApi = {
  stats: async () => {
    const resp = await get<{ success: boolean; data: { order_quantity: number; order_regular_quantity: number; order_custom_quantity: number; stockin_quantity: number } }>('/stock/stats');
    return resp.data ?? resp as unknown as typeof resp.data;
  },
```

改为（用一个具名类型替代自引用断言；`unknown` 分支本就不可能命中，显式写出返回类型即可）：

```ts
export interface StockStats {
  order_quantity: number
  order_regular_quantity: number
  order_custom_quantity: number
  stockin_quantity: number
}

export const stockApi = {
  stats: async (): Promise<StockStats> => {
    const resp = await get<{ success?: boolean; data?: StockStats }>('/stock/stats')
    return resp.data ?? (resp as StockStats)
  },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/apiTypeAssertionBaseline.test.ts`
Expected: PASS

- [ ] **Step 5: 类型检查与既有测试不回归**

Run: `cd frontend-vite && npm run type-check && npx vitest run`
Expected: 退出码 0；全量前端测试通过

- [ ] **Step 6: 提交**

```bash
git add frontend-vite/src/test/apiTypeAssertionBaseline.test.ts frontend-vite/src/api/stock.ts
git commit -m "test(前端): 钉住 as unknown as 基线，并收敛 stock 域断言作为方法样例"
```

---

## 已知遗留（不在本计划范围）

1. **全仓 130 处 `as unknown as` 的完整收敛**——跨 51 个文件，需逐个判断用哪个生成类型、哪些是 store 适配层必须保留。单独立计划。
2. **77 个 `list[dict]` 响应的类型化**——需先给 schema 补注入字段，否则 `response_model` 会剥字段。独立且高风险，触碰生产响应契约。
3. **schema 名展平的根因**——22 个 schema 被展平是因模块级同名类冲突（如两处 `ActionResponse`）。根治要改后端类名或模块结构，非前端范畴。
