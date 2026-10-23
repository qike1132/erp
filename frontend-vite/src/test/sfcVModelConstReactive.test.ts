/**
 * F2-6 门禁：`v-model` 绑到 `const` 的 `reactive()` 绑定 —— @vue/compiler-sfc 会静默把
 * `const` 改写成 `let` 才让 setter 成立，属于「能跑但语义靠编译器兜底」的隐患：
 * 子组件一旦整体替换模型对象，父侧变量被重新赋值，而父组件其它代码仍按原对象身份读写。
 *
 * 修法是「解构绑定」：父侧只 `:form="form"`，写回靠父子共享同一个 reactive proxy。
 * 这只在**子组件不整体替换模型**时成立，所以本门禁第二段把该前提钉住 —— 否则改成单向
 * prop 只是把「编译器暗改 const」换成「子组件整体赋值被父侧静默丢弃」。
 *
 * 编译期部分只做静态编译，不渲染组件：那条约束完全发生在编译期，运行期测试反而测不到。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { compileScript, parse } from '@vue/compiler-sfc'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { describe, expect, it } from 'vitest'

import ReportFilterBar from '@/views/report/components/ReportFilterBar.vue'

// 与 apiTypeAssertionBaseline.test.ts 同一取根方式（jsdom 下 new URL('.', ...) 不是 file: 协议）
const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
/** 编译器消息原文（不含文件路径），命中即视为本门禁要拦的用法 */
const CONST_REACTIVE_VMODEL = /`v-model` cannot update a `const` reactive binding/

function listSfcPaths(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (name !== 'test') listSfcPaths(p, out)
    } else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

/** 编译一个 SFC（script setup + 内联模板），收集编译器打到 console.warn 的消息。 */
function compileWarnings(source: string, filename: string): string[] {
  const found: string[] = []
  const original = console.warn
  console.warn = (...args: unknown[]) => {
    const msg = args.map((a) => (typeof a === 'string' ? a : '')).join(' ')
    if (CONST_REACTIVE_VMODEL.test(msg)) found.push(msg)
  }
  try {
    const { descriptor } = parse(source, { filename })
    if (!descriptor.script && !descriptor.scriptSetup) return found
    compileScript(descriptor, {
      id: filename,
      inlineTemplate: true,
      templateOptions: { compilerOptions: { whitespace: 'preserve' } },
    })
  } catch {
    // 无关的编译期硬错误（模板引用外部资源等）由 type-check / build 门禁负责，
    // 本门禁只认上面那条消息；这里吞掉异常是为了不因别的文件而误红。
    return found
  } finally {
    console.warn = original
  }
  return found
}

describe('SFC 编译期：v-model 不得绑 const reactive 绑定', () => {
  it('自检：探测链路真的能抓到这种用法（正向控制）', () => {
    // 两个易被忽略的坑：
    // 1) `reactive` 必须从 vue 导入 —— 编译器按绑定来源判定「这是 reactive 绑定」，
    //    少了这行 import，控制用例会在什么都没测到的情况下静默通过。
    // 2) 绑定名必须**不与真实文件重名** —— 该告警走 warnOnce，同进程内按消息全文去重，
    //    用 `form` 这类常见名会把随后真实文件的告警吞掉，让扫描假绿。
    const warnings = compileWarnings(
      `<template><Child v-model:selfProof="selfProofBinding" /></template>\n`
        + `<script setup lang="ts">\nimport { reactive } from 'vue'\nimport Child from './Child.vue'\nconst selfProofBinding = reactive({ a: 1 })\n</script>\n`,
      'SelfProof.vue'
    )
    expect(warnings.length).toBeGreaterThan(0)
  })

  it('src/ 下不再有 v-model 绑 const reactive 的组件', () => {
    const offenders: string[] = []
    for (const file of listSfcPaths(SRC_ROOT)) {
      const source = readFileSync(file, 'utf-8')
      // 便宜的预筛：告警成立必须同时有 const reactive 绑定和 v-model:xxx 用法
      if (!/v-model[:.]/.test(source)) continue
      if (!new RegExp(`const\\s+\\w+\\s*=\\s*reactive\\(`).test(source)) continue
      for (const w of compileWarnings(source, relative(SRC_ROOT, file))) {
        offenders.push(`${relative(SRC_ROOT, file)}: ${w.trim()}`)
      }
    }
    expect(offenders).toEqual([])
  })
})

/** 父侧省掉 `@update:xxx` 的绑定点，以及各自对应的子组件与模型变量名。 */
const ONE_WAY_MODEL_SITES = [
  { child: 'views/stock/components/StockOutInputForm.vue', model: 'form', parent: 'views/stock/StockOutTab.vue' },
  { child: 'views/stock/components/StockOutEditStagedDialog.vue', model: 'form', parent: 'views/stock/StockOutTab.vue' },
  { child: 'views/report/components/ReportFilterBar.vue', model: 'filters', parent: 'views/report/ReportView.vue' },
]

describe('SFC 编译期：单向绑定的子组件不得整体替换模型对象', () => {
  for (const { child, model, parent } of ONE_WAY_MODEL_SITES) {
    it(`${child} 只嵌套写 ${model}，父侧 ${parent} 才能省掉 @update:${model}`, () => {
      const source = readFileSync(join(SRC_ROOT, child), 'utf-8')
      // 拦 `form.value = ...`（含 += 等复合赋值），但 `form.value.productId =`（嵌套写）
      // 与 `form.value === x`（比较）都不许误伤：= 前必须是 .value 本体，且排除第二个 =。
      const wholesaleAssign = new RegExp(
        `(?<![.\\w])${model}\\.value\\s*(?:[-+*/%&|^]|\\?\\?)?=(?!=)`
      )
      expect(source, `${child} 出现了 ${model}.value = ... 整体替换`).not.toMatch(wholesaleAssign)
      // 模板里 `v-model="form"` 等价于整体替换；`v-model="form.date"` 是嵌套写，放过。
      expect(source, `${child} 模板里对 ${model} 整根 v-model`).not.toMatch(
        new RegExp(`v-model(:[\\w-]+)?\\s*=\\s*"${model}"`)
      )
    })
  }
})

/**
 * 上面只是源码层前提，这里跑真实写入：父侧不给 `update:filters` 监听器，
 * 子组件 `v-model="filters.product"` 的嵌套写仍必须落到父组件那个 reactive 对象上
 * —— 靠的是父子共享同一个 proxy，而不是 emit 回流。少了这条，「删掉 @update:xxx」
 * 只是读起来等价，没有当场证明。
 */
describe('单向 :prop 绑定的运行期等价性', () => {
  it('ReportFilterBar 无 update:filters 监听时，嵌套写仍落到父侧 reactive', async () => {
    const filters = reactive({ customer: '', product: '' })
    const wrapper = mount(ReportFilterBar, {
      props: { filters, customerOptions: [] },
      global: { stubs: { FontAwesomeIcon: true } },
    })
    // 走 UiInput 那条（v-model="filters.product"）；UiSelect 的 onInput 只更新组件内的
    // 搜索草稿、要选中才 emit，与本门禁要证的「共享 proxy」无关，不掺进来。
    await wrapper.find('.rp-field input').setValue('保温杯')
    expect(filters.product).toBe('保温杯')
    expect(wrapper.emitted('update:filters')).toBeUndefined()
  })
})
