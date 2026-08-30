/**
 * usePatternRoomPrint — 打样单打印 Hook
 *
 * 封装打印数据准备（逐角色加载全部部位）与浏览器打印流程
 * （打印时间刷新、body 打印隔离类、临时清空页面标题）。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, computed, onScopeDispose, type Ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type { PartDetail, RoleBrief } from '@/api/patternRoom'

/** 打印内容组件所需句柄（用于打印前刷新打印时间） */
export interface PrintDialogExpose {
  updatePrintTime: () => void
}

interface UsePatternRoomPrintOptions {
  /** 当前选中项目 ID */
  selectedProjectId: Ref<number | null>
  /** 当前角色的跨版本部位数据（降级用） */
  partsByVersion: Ref<PartDetail[]>
  /** 角色列表（打印需逐角色加载全部部位） */
  roles: Ref<RoleBrief[]>
}

export function usePatternRoomPrint(options: UsePatternRoomPrintOptions) {
  const { selectedProjectId, partsByVersion, roles } = options

  /** 打印内容组件引用（用于打印前刷新打印时间） */
  const printDialogRef = ref<PrintDialogExpose | null>(null)
  /** 打印用部位数据（全部角色，点击打印时才加载） */
  const printParts = ref<PartDetail[]>([])
  /** 打印用角色分组（role_id → role_name 映射） */
  const printRoles = ref<RoleBrief[]>([])
  /** 可打印：已选中产品且有部位数据 */
  const canPrint = computed(
    () => selectedProjectId.value != null && partsByVersion.value.length > 0,
  )

  /** 打印前页面标题（afterprint 时恢复，避免硬编码覆盖 SPA 动态标题） */
  let titleBeforePrint = typeof document !== 'undefined' ? document.title : ''
  const onAfterPrint = () => {
    document.body.classList.remove('pd-printing')
    document.title = titleBeforePrint
  }

  async function handlePrint() {
    if (!canPrint.value || !selectedProjectId.value) return
    const projectId = selectedProjectId.value
    const allRoles = roles.value
    printRoles.value = allRoles
    // 后端不支持不传 role_id 返回全部角色，需逐个角色加载（并行请求，避免多角色串行等待）
    try {
      const results = await Promise.all(
        allRoles.map((role) => patternRoomApi.getPartsByVersion(projectId, role.id)),
      )
      const allParts: PartDetail[] = []
      results.forEach((res, idx) => {
        const role = allRoles[idx]!
        const items = res.items ?? []
        // 确保每条数据带 role_id（用于 PrintDialog 按角色分组）
        for (const item of items) {
          if (item.role_id == null) item.role_id = role.id
          allParts.push(item)
        }
      })
      printParts.value = allParts
    } catch {
      // 降级：使用当前角色的数据
      printParts.value = partsByVersion.value
    }
    // 打印前刷新打印时间
    printDialogRef.value?.updatePrintTime()
    // 给 body 加打印隔离类，仅显示打样单内容
    document.body.classList.remove('pd-printing')
    document.body.classList.add('pd-printing')
    // 临时清空页面标题，避免浏览器打印预览页眉显示"滨发协同系统"
    titleBeforePrint = document.title
    document.title = ''
    // 等待打印内容渲染后，直接调出浏览器打印预览
    requestAnimationFrame(() => {
      window.print()
    })
  }

  // 打印结束后移除隔离类并恢复打印前页面标题
  // （具名 handler + onScopeDispose 注销，避免多次调用累积监听器）
  if (typeof window !== 'undefined') {
    window.addEventListener('afterprint', onAfterPrint)
    onScopeDispose(() => window.removeEventListener('afterprint', onAfterPrint))
  }

  return {
    printDialogRef,
    printParts,
    printRoles,
    canPrint,
    handlePrint,
  }
}
