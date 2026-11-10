/**
 * 部位级最终版本选择回归（/pattern-room）
 *
 * 背景：最终版本原先只能按角色存一个 current_version，点选 A 部位的 T2 会
 * 连带把 B 部位也切成 T2，B 无法保留 T1。修复后由 finalVersions 按部位覆盖，
 * 未覆盖的部位继续沿用角色默认。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick, ref } from 'vue'
import { usePartsVersionFilter } from '@/views/pattern-room/composables/usePartsVersionFilter'
import type { PartDetail } from '@/api/patternRoom'

function makePart(partName: string, versionNo: string, id: number): PartDetail {
  return {
    id,
    project_id: 1,
    role_id: 1,
    part_name: partName,
    sort_order: 1,
    fabric_name: '',
    fabric_spec: '',
    fabric_color_no: '',
    supplier_id: null,
    supplier_name: '',
    contact_person: '',
    contact_phone: '',
    unit_price: null,
    delivery_days: null,
    remark: '',
    version: 1,
    version_no: versionNo,
  }
}

function setup(defaultVersion = 'T2') {
  const partsByVersion = ref<PartDetail[]>([
    makePart('主料', 'T1', 1),
    makePart('主料', 'T2', 2),
    makePart('花结', 'T1', 3),
    makePart('花结', 'T2', 4),
  ])
  const finalVersion = ref(defaultVersion)
  const finalVersions = ref<Record<string, string>>({})
  const onSetFinalVersion = vi.fn()
  const filter = usePartsVersionFilter(
    partsByVersion,
    finalVersion,
    finalVersions,
    ref(1),
    ref(1),
    onSetFinalVersion,
  )
  return { partsByVersion, finalVersion, finalVersions, onSetFinalVersion, ...filter }
}

describe('usePartsVersionFilter — 部位级最终版本', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('未单独选择时所有部位沿用角色默认最终版本', () => {
    const { selectedVersion } = setup('T2')
    expect(selectedVersion.value).toEqual({ 主料: 'T2', 花结: 'T2' })
  })

  it('给一个部位改选版本，不影响其他部位', () => {
    const { selectedVersion, onSetFinalVersion, toggleVersion } = setup('T2')

    toggleVersion('花结', 'T1')

    expect(onSetFinalVersion).toHaveBeenCalledWith('花结', 'T1')
    expect(selectedVersion.value).toEqual({ 主料: 'T2', 花结: 'T1' })
  })

  it('落库后的部位级覆盖回填后，各部位保持各自选择', async () => {
    const { selectedVersion, finalVersions } = setup('T2')

    finalVersions.value = { 主料: 'T1', 花结: 'T2' }
    await nextTick()

    expect(selectedVersion.value).toEqual({ 主料: 'T1', 花结: 'T2' })
  })

  it('折叠态按各部件的最终版本各自展示对应行', async () => {
    const { groupedRows, finalVersions } = setup('T2')
    finalVersions.value = { 主料: 'T1', 花结: 'T2' }
    await nextTick()

    const byName = Object.fromEntries(groupedRows.value.map((g) => [g.part_name, g]))
    expect(byName['主料']!.items.map((i) => i.version_no)).toEqual(['T1'])
    expect(byName['花结']!.items.map((i) => i.version_no)).toEqual(['T2'])
    expect(byName['主料']!.collapsed).toBe(true)
    expect(byName['花结']!.collapsed).toBe(true)
  })

  it('部位没有默认最终版本行时保持未选中（展开全部版本）', () => {
    const { groupedRows } = setup('T3')
    const byName = Object.fromEntries(groupedRows.value.map((g) => [g.part_name, g]))
    expect(byName['主料']!.items.map((i) => i.version_no)).toEqual(['T1', 'T2'])
    expect(byName['主料']!.collapsed).toBe(false)
  })
})
