import { ref, reactive, computed } from 'vue'
import { productApi, supplierApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { BomItem, BomCategory, Role, ConfirmDialogLike } from './bomTypes'
import { buildRolePayload } from './bomTypes'
import { useBomQuickCopy } from './useBomQuickCopy'
import { useBomCopyDialog } from './useBomCopyDialog'
import { queryClient } from '@/utils/queryClient'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'

interface ProductLike {
  id: number
  name: string
}

/** loadBom 返回的物料原始记录 */
interface BomMaterialRecord {
  id?: number
  category?: string
  material_name?: string
  name?: string
  specification?: string
  unit?: string
  supplier_id?: number | null
  supplier_name?: string
  unit_usage?: number
  quantity?: number
  remark?: string
  role_id?: number | null
}

/** 单个作用域（某角色或产品级默认）的物料 */
type BomScope = Record<BomCategory, BomItem[]>

/**
 * 产品列表中 BOM 相关操作的统一入口。
 *
 * 本 composable 负责 BOM 编辑模态框的状态管理（含角色字段：
 * 一个 SKU 可关联多个角色，每个角色拥有独立物料清单，点击角色标签切换 BOM）；
 * 快速复制（useBomQuickCopy）与复制对话框（useBomCopyDialog）已抽离为独立 composable。
 */
export function useProductListActions(confirmDialog: ConfirmDialogLike) {
  // ===== BOM模态框 =====
  const bomDialogVisible = ref(false)
  const bomProductName = ref('')
  const currentProductId = ref<number | null>(null)
  const currentBomCategory = ref<BomCategory>('fabric')
  // 2026-10-17 审计 F-FE-WS-A-01：读失败时编辑基线被清成空集，若仍允许保存，
  // 后端「全量替换」语义会把该 SKU 整张 BOM 删光。此标记禁止在未加载成功时保存。
  const bomLoadFailed = ref(false)
  // 2026-10-17 审计 P2-51：保存防重复提交（双击会并发发起两次全量替换）
  const bomSaving = ref(false)

  const bomTabs = [
    { key: 'fabric' as const, label: '面料类', icon: 'fas fa-scroll' },
    { key: 'filling' as const, label: '填充类', icon: 'fas fa-cloud' },
    { key: 'accessory' as const, label: '辅料类', icon: 'fas fa-puzzle-piece' },
  ]

  // ===== 供应商下拉选项（打开 BOM 弹窗时实时拉取，供供应商选择框使用） =====
  const bomSupplierOptions = ref<{ id: number; name: string }[]>([])

  async function loadSupplierOptions() {
    try {
      const res = await supplierApi.options()
      bomSupplierOptions.value = res?.suppliers ?? []
    } catch (error) {
      console.error('加载供应商列表失败:', error)
      bomSupplierOptions.value = []
    }
  }

  // ===== 角色状态（一对多：SKU -> 角色列表） =====
  const bomRoles = ref<Role[]>([])
  /** 当前选中的角色；null = 产品级默认 BOM（无角色或未选角色） */
  const selectedRole = ref<Role | null>(null)
  let roleKeyCounter = 0

  // 按作用域分组的物料：'default' = 产品级默认 BOM；'role-<id>' / 'role-key-<key>' = 角色
  const bomByScope = reactive<Record<string, BomScope>>({})

  function scopeKeyOf(role: Role | null | undefined): string {
    if (!role) return 'default'
    if (role.id != null) return `role-${role.id}`
    return `role-key-${role.role_key}`
  }

  function ensureScope(key: string): BomScope {
    if (!bomByScope[key]) bomByScope[key] = { fabric: [], filling: [], accessory: [] }
    return bomByScope[key]
  }

  const currentScopeKey = computed(() => scopeKeyOf(selectedRole.value))
  /** 产品级默认 BOM 自定义名称（可双击改名并持久化，默认"默认BOM"） */
  const defaultScopeName = ref('默认BOM')
  /** 产品级默认 BOM 是否存在物料（存在时角色栏展示"默认BOM"标签，保证存量数据可编辑） */
  const defaultScopeHasItems = computed(() => {
    const scope = bomByScope['default']
    return !!scope && (scope.fabric.length + scope.filling.length + scope.accessory.length) > 0
  })
  const currentBomItems = computed(() => {
    const scope = bomByScope[currentScopeKey.value]
    return scope ? scope[currentBomCategory.value] : []
  })
  const currentBomTabLabel = computed(() => bomTabs.find(tab => tab.key === currentBomCategory.value)?.label || '')
  /** 汇总栏标题后缀：当前角色名或默认 BOM 名称 */
  const currentScopeLabel = computed(() => (selectedRole.value ? selectedRole.value.name : defaultScopeName.value))
  /** 当前作用域物料总数 */
  const currentScopeCount = computed(() => {
    const scope = bomByScope[currentScopeKey.value]
    if (!scope) return 0
    return scope.fabric.length + scope.filling.length + scope.accessory.length
  })

  function switchBomTab(category: BomCategory) {
    currentBomCategory.value = category
  }

  async function openBomModal(row: ProductLike) {
    currentProductId.value = row.id
    bomProductName.value = row.name
    bomDialogVisible.value = true
    currentBomCategory.value = 'fabric'
    // BOM 数据与供应商列表并行拉取：供应商列表每次打开都刷新（实时）
    await Promise.all([loadBomData(row.id), loadSupplierOptions()])
  }

  // 2026-10-17 审计 P2-58：加载序号防竞态——快速切换产品时旧响应可能覆盖新数据
  let bomLoadSeq = 0

  async function loadBomData(productId: number) {
    const seq = ++bomLoadSeq
    bomRoles.value = []
    selectedRole.value = null
    defaultScopeName.value = '默认BOM'
    Object.keys(bomByScope).forEach(key => delete bomByScope[key])
    bomLoadFailed.value = true // 进入加载即置失败态，成功路径末尾解除
    try {
      const res = (await productApi.loadBom(productId)) as {
        success: boolean
        product?: { roles?: { id: number; name: string }[]; default_bom_label?: string | null }
        materials?: BomMaterialRecord[]
      }
      if (seq !== bomLoadSeq) return // 已被更新的加载取代，丢弃旧响应
      if (!res.success) {
        // success=false 同样不能当编辑基线（空基线 + 保存 = 全删）
        bomLoadFailed.value = true
        showToast('加载BOM数据失败，禁止保存', 'error')
        return
      }
      bomRoles.value = (res.product?.roles || []).map(r => ({
        id: r.id,
        name: r.name,
      }))
      defaultScopeName.value = res.product?.default_bom_label?.trim() || '默认BOM'
      const materialsList = res.materials || []
      materialsList.forEach((item) => {
        const category = item.category || 'accessory'
        if (category === 'packaging') return // 包装类不在BOM配置中管理
        const key = item.role_id != null ? `role-${item.role_id}` : 'default'
        ensureScope(key)[category as BomCategory].push({
          id: item.id,
          name: item.material_name || item.name || '',
          specification: item.specification || '',
          unit: item.unit || '码',
          supplier_id: item.supplier_id || null,
          supplier_name: item.supplier_name || '',
          usage: item.unit_usage || item.quantity || 1,
          remark: item.remark || '',
          role_id: item.role_id ?? null,
          category: category,
        })
      })
      // 缺陷①（A-3）：打开弹窗默认停靠「默认BOM」——保持 selectedRole === null，
      // 不再默认落 bomRoles[0]，避免用户误在某个角色作用域下编辑。
      selectedRole.value = null
      bomLoadFailed.value = false // 数据完整落地，解除保存禁令
    } catch (error) {
      if (seq !== bomLoadSeq) return
      console.error('加载BOM数据失败:', error)
      bomLoadFailed.value = true
      showToast('加载BOM数据失败，禁止保存', 'error')
    }
  }

  function addBomItem() {
    const scope = ensureScope(currentScopeKey.value)
    // 填充类每作用域仅支持一条，已有数据时禁止再添加
    if (currentBomCategory.value === 'filling' && scope.filling.length >= 1) {
      showToast('填充类物料每产品（每角色）仅支持一条', 'warning')
      return
    }
    scope[currentBomCategory.value].push({
      name: '',
      specification: '',
      unit: currentBomCategory.value === 'filling' ? '克' : '码',
      supplier_name: '',
      usage: 1,
      remark: '',
      role_id: selectedRole.value?.id ?? null,
      category: currentBomCategory.value,
    })
    // P1-04：明确告知新物料的归属作用域，避免「加错角色」。
    showToast(`已在「${currentScopeLabel.value}」作用域添加物料`, 'info')
  }

  async function deleteBomItem(index: number) {
    const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
    if (!ok) return
    const scope = ensureScope(currentScopeKey.value)
    scope[currentBomCategory.value].splice(index, 1)
  }

  // ===== 角色操作 =====
  function selectRole(role: Role | null) {
    selectedRole.value = role
  }

  /**
   * 按 id 选中角色（复制完成后回选目标角色用）。
   * 找不到时保持当前选中不变，避免影响既有行为。
   */
  function selectRoleById(roleId: number) {
    const role = bomRoles.value.find(r => r.id === roleId)
    if (role) selectedRole.value = role
  }

  function addRole(name: string) {
    const trimmed = (name || '').trim()
    if (!trimmed) return
    const role: Role = { role_key: `rk-${++roleKeyCounter}`, name: trimmed }
    bomRoles.value.push(role)
    ensureScope(scopeKeyOf(role))
    selectedRole.value = role
  }

  /**
   * 重命名角色（**本地改**，保存 BOM 时随 payload 落库）。
   *
   * 角色为**产品私有**（迁移 088/089）：改名只作用于本 SKU，不再即时调后端
   * （原经 `PUT /purchase-center/roles/{id}` 会跨产品同步）。物料按 role_id 归属不变。
   *
   * @returns 重命名成功返回 `true`
   */
  function renameRole(role: Role, newName: string): boolean {
    const trimmed = (newName || '').trim()
    if (!trimmed || role.name === trimmed) return false
    role.name = trimmed
    return true
  }

  /** 重命名默认 BOM（空名/同名忽略，保持原名称） */
  function renameDefaultScope(newName: string) {
    const trimmed = (newName || '').trim()
    if (!trimmed || defaultScopeName.value === trimmed) return
    defaultScopeName.value = trimmed
  }

  async function removeRole(role: Role) {
    const ok = await confirmDialog.confirm(
      `删除角色"${role.name}"？`,
      '该角色的全部物料将一并删除',
      'danger',
    )
    if (!ok) return
    const idx = bomRoles.value.indexOf(role)
    if (idx >= 0) bomRoles.value.splice(idx, 1)
    delete bomByScope[scopeKeyOf(role)]
    // A-3：删除后回落到「默认BOM」作用域（与打开弹窗的默认停靠一致）
    if (selectedRole.value === role) selectedRole.value = null
  }

  async function saveBom() {
    if (bomSaving.value) return
    // 2026-10-17 审计 F-FE-WS-A-01：BOM 未加载成功时基线是空集，
    // 提交会按「全量替换」语义删光该 SKU 整张 BOM —— 禁止保存。
    if (bomLoadFailed.value) {
      showToast('BOM 未加载成功，禁止保存。请关闭弹窗后重试', 'error')
      return
    }
    // 校验：角色名必填
    const invalidRole = bomRoles.value.find(r => !(r.name || '').trim())
    if (invalidRole) {
      showToast('请填写角色名称', 'warning')
      return
    }
    // 校验：所有作用域物料必填项
    const allItems: BomItem[] = []
    Object.values(bomByScope).forEach(scope => allItems.push(...scope.fabric, ...scope.filling, ...scope.accessory))
    const invalidItems = allItems.filter(item => !item.name || !item.specification || !item.unit || !item.supplier_name)
    if (invalidItems.length > 0) {
      showToast('请填写所有必填项（物料名称、规格型号、计量单位、默认供应商）', 'warning')
      return
    }

    // 空基线覆盖非空 BOM 的二次确认（防误清空整张 BOM）
    if (allItems.length === 0 && currentProductId.value != null) {
      // 2026-10-18 OCR 评审：进入异步确认前就上锁，否则双击会并发走完确认；
      // loadBom 失败时必须解锁，否则 bomSaving 永久为 true、后续保存全部被吞。
      bomSaving.value = true
      let existing: { success: boolean; materials?: BomMaterialRecord[] }
      try {
        existing = await productApi.loadBom(currentProductId.value) as { success: boolean; materials?: BomMaterialRecord[] }
      } catch {
        bomSaving.value = false
        showToast('读取现有 BOM 失败，已取消保存', 'error')
        return
      }
      // 2026-10-18 OCR 评审：复查失败（异常 / success=false / 返回体异常）都必须解锁。
      // 此前只 catch 了异常，success=false 时 nonEmpty 恒为 false → 直接跳过确认，
      // 等于「无法确认是否在删数据」的情况下把空 BOM 存了进去。
      if (!existing.success) {
        bomSaving.value = false
        showToast('读取现有 BOM 失败，已取消保存', 'error')
        return
      }
      const nonEmpty = (existing.materials || []).some(m => (m.category || 'accessory') !== 'packaging')
      if (nonEmpty) {
        const ok = await confirmDialog.confirm(
          '当前 BOM 为空，但该产品已存在物料清单。保存将删除全部物料，确定继续吗？',
          '危险操作确认',
          'danger',
        )
        if (!ok) {
          bomSaving.value = false
          return
        }
      }
    }

    // 角色负载：id（既有行）/ role_key（新建）两条路径（角色为产品私有）
    const rolesPayload = buildRolePayload(bomRoles.value)

    const fabrics: unknown[] = []
    const accessories: unknown[] = []
    const fillings: unknown[] = []

    for (const [key, scope] of Object.entries(bomByScope)) {
      const role = bomRoles.value.find(r => scopeKeyOf(r) === key) ?? null
      const roleRef = role
        ? (role.id != null ? { role_id: role.id } : { role_key: role.role_key })
        : {}
      scope.fabric.forEach(item => fabrics.push({
        id: item.id,
        fabric_name: item.name,
        specification: item.specification,
        unit: item.unit,
        quantity: item.usage,
        supplier_id: item.supplier_id,
        supplier_name: item.supplier_name,
        remark: item.remark,
        category: 'fabric',
        ...roleRef,
      }))
      scope.accessory.forEach(item => accessories.push({
        id: item.id,
        accessory_name: item.name,
        specification: item.specification,
        unit: item.unit,
        quantity: item.usage,
        supplier_id: item.supplier_id,
        supplier_name: item.supplier_name,
        remark: item.remark,
        category: 'accessory',
        ...roleRef,
      }))
      if (scope.filling.length > 0) {
        const filling = scope.filling[0]!
        fillings.push({
          id: filling.id,
          cotton_usage: filling.usage,
          specification: filling.specification,
          supplier_id: filling.supplier_id,
          supplier_name: filling.supplier_name,
          unit: filling.unit,
          remark: filling.remark,
          ...roleRef,
        })
      }
    }

    try {
      bomSaving.value = true
      const payload = {
        fabrics,
        accessories,
        fillings,
        roles: rolesPayload,
        packagings: [],
        default_bom_label: defaultScopeName.value === '默认BOM' ? null : defaultScopeName.value,
      }
      const res = (await productApi.saveBom(currentProductId.value!, payload)) as { success: boolean; error?: string }
      if (res.success) {
        showToast('保存成功', 'success')
        bomDialogVisible.value = false
        // BOM 一改，「待生成」列表的 has_bom 与后续采购单生成都变了；采购相关查询
        // 被 persistQueryClient 持久化到 sessionStorage，不失效就会命中旧快照。
        invalidateOrderDerivedQueries(queryClient)
      } else {
        showToast(res.error || '保存失败', 'error')
      }
    } catch {
      showToast('保存BOM失败', 'error')
    } finally {
      bomSaving.value = false
    }
  }

  // ===== 快速复制 BOM（抽离至 useBomQuickCopy） =====
  // 注入 selectedRole：复制物料归属到当前选中的角色（null = 默认 BOM 作用域）
  // 注入 selectRoleById：复制成功后回选目标角色（新建角色落库后 id 会变）
  const quickCopy = useBomQuickCopy({
    currentProductId,
    currentProductName: bomProductName,
    reloadBom: loadBomData,
    selectedRole,
    selectRoleById,
    // 2026-10-18 OCR 评审：bomSaving 只拦「再次点保存」，而同工具栏的「复制BOM」
    // 也是 overwrite=true 的破坏性操作（复制成功后 reloadBom 会把编辑基线整份重载，
    // 与在途保存的全量替换互相覆盖）。保存进行中一律拒绝发起复制。
    isBusy: () => bomSaving.value,
    // 2026-10-17 审计 AUD-18：默认作用域覆盖前二次确认，避免误点清空目标 BOM
    confirmOverwrite: (productName: string) => confirmDialog.confirm(
      `目标产品「${productName}」已有 BOM，快速复制将删除其全部角色/面料/辅料/填充物并替换为源产品 BOM。确定继续吗？`,
      '此操作不可从界面恢复',
      'danger',
    ),
    // 2026-10-18 OCR 评审：角色作用域同样 overwrite=true —— 后端 _copy_bom_into_role
    // 会 delete 该 role_id 名下的面料/辅料/填充（bom_service.py:665-678）。
    // 作用域窄（不碰默认 BOM 与其他角色）但同样是不可逆清空，文案必须与产品级区分。
    confirmRoleOverwrite: (roleName: string) => confirmDialog.confirm(
      `角色「${roleName}」已有 BOM，快速复制将删除该角色名下的全部物料并替换为源产品 BOM。确定继续吗？`,
      '此操作不可从界面恢复',
      'danger',
    ),
  })

  // ===== 复制 BOM 对话框（抽离至 useBomCopyDialog） =====
  const copyDialog = useBomCopyDialog({
    currentProductId,
    reloadBom: loadBomData,
    selectedRole,
    selectRoleById,
    // 与快速复制同一口径：保存进行中拒绝发起复制（两者都会重载编辑基线）
    isBusy: () => bomSaving.value,
  })

  return {
    // BOM modal
    bomDialogVisible,
    bomProductName,
    currentProductId,
    currentBomCategory,
    bomTabs,
    currentBomItems,
    currentBomTabLabel,
    currentScopeLabel,
    currentScopeCount,
    switchBomTab,
    openBomModal,
    addBomItem,
    deleteBomItem,
    saveBom,
    // 供应商下拉选项
    bomSupplierOptions,
    // 角色
    bomRoles,
    selectedRole,
    defaultScopeName,
    defaultScopeHasItems,
    selectRole,
    selectRoleById,
    addRole,
    renameRole,
    renameDefaultScope,
    removeRole,
    // Quick copy
    ...quickCopy,
    // Copy BOM dialog
    ...copyDialog,
  }
}
