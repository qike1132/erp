import { describe, it, expect } from 'vitest'
import { generateTypes, tsTypeOf, buildNameMap, sanitizeIdent } from '../../scripts/generate-api-types.mjs'

describe('tsTypeOf 映射规则', () => {
  it('基础类型与 required/optional', () => {
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
    const a = m.get(keys[0]!)!
    const b = m.get(keys[1]!)!
    expect(a).not.toBe(b)
    expect(a).toBe('staging_StagingListResponse')
    expect(b).toBe('production_plan_StagingListResponse')
  })

  it('三处同名也能全部消歧', () => {
    const keys = [
      'fastapi_app__schemas__customer_sampling__ActionResponse',
      'fastapi_app__schemas__material_registration__ActionResponse',
      'fastapi_app__schemas__purchase_center__ActionResponse',
    ]
    const names = keys.map((k) => buildNameMap(keys).get(k)!)
    expect(new Set(names).size).toBe(3)
  })

  it('sanitize 后仍同名则抛错，不产出非法重复 interface', () => {
    expect(() => buildNameMap(['a__b_x', 'a__b-x'])).toThrow(/schema 名冲突/)
  })
})

describe('sanitizeIdent', () => {
  it('保留字与首字符非法时加前缀', () => {
    expect(sanitizeIdent('default')).toBe('_default')
    expect(sanitizeIdent('1x')).toBe('_1x')
    expect(sanitizeIdent('Normal')).toBe('Normal')
  })
})
