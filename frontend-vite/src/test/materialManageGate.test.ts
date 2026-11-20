/** 来料登记按钮门控必须与后端 any-of 同形（审计 M-17）。 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync('src/views/material/MaterialView.vue', 'utf-8')

describe('来料登记权限门控', () => {
  it('canManage 同时接受 product_manage 与 material_registration', () => {
    expect(source).toMatch(
      /canManage\s*=\s*computed\(\(\)\s*=>\s*authStore\.hasAnyPermission\(\s*\[[^\]]*'product_manage'[^\]]*'material_registration'/,
    )
    expect(source).not.toMatch(
      /canManage\s*=\s*computed\(\(\)\s*=>\s*authStore\.hasPermission\('product_manage'\)\)/,
    )
  })
})
