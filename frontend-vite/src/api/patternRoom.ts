/**
 * 按客户分类打样信息模块 API 客户端
 *
 * 对应后端路由前缀: /api/v1/pattern-room（保持路径不变，用户无感切换）
 * 后端 endpoint: fastapi_app/api/v1/endpoints/customer_sampling.py
 * 后端 schema:   fastapi_app/schemas/customer_sampling.py
 *
 * 保持导出名 `patternRoomApi` 不变以兼容 `api/index.ts`。
 * 内部完全重写为面向"客户分组 + 部位布料 + 版本快照"扁平结构的 23 个 API 方法。
 */
import { get, post, put, del, upload } from './request'
import type { WithRequired, WithItems, ReplaceField, WithField } from '@/types'
import type { ChangeLogEntry as GenChangeLogEntry, FieldDiff as GenFieldDiff, RoleBrief as GenRoleBrief, VersionBrief as GenVersionBrief, BatchPartCreateRequest as GenBatchPartCreateRequest, PartCreateRequest as GenPartCreateRequest, PartUpdateRequest as GenPartUpdateRequest, ProjectUpdateRequest as GenProjectUpdateRequest, RoleCreateRequest as GenRoleCreateRequest, RoleUpdateRequest as GenRoleUpdateRequest, BatchPartItem as GenBatchPartItem, RoleListResponse as GenRoleListResponse, VersionListResponse as GenVersionListResponse, ChangeLogListResponse as GenChangeLogListResponse, GroupedListResponse as GenGroupedListResponse, PartDetail as GenPartDetail, PartListResponse as GenPartListResponse, PartsByVersionResponse as GenPartsByVersionResponse, PatternMakerGroup as GenPatternMakerGroup, ProjectCreateRequest as GenProjectCreateRequest, ProjectListResponse as GenProjectListResponse, ProjectSummary as GenProjectSummary, VersionDetailResponse as GenVersionDetailResponse } from '@/types/api'

// ==================== 类型别名 ====================

/** 变更类型：新增 / 修改 / 删除 */
export type ChangeType = 'add' | 'modify' | 'delete'

/** 打样项目状态（收敛裸字符串，避免各处字面量拼写漂移） */
export type ProjectStatus = 'in_progress' | 'completed' | 'cancelled'

// ==================== 通用响应 ====================

/** 操作响应（创建/更新/删除/上传）
 * version：带乐观锁的更新操作（部位/角色/项目）返回更新后的新版本号，
 * 供前端局部回写，避免第二次编辑携带旧 version 触发 409。
 */
export interface ActionResponse {
  success: boolean
  message: string
  id?: number
  sequence_no?: string
  version_id?: number
  version_no?: string
  version?: number
  file_id?: number
  url?: string
  thumbnail_url?: string
}

// ==================== 部位布料 ====================

/** 部位布料详情 */
export type PartDetail = WithRequired<GenPartDetail, 'part_name' | 'sort_order' | 'fabric_name' | 'fabric_spec' | 'fabric_color_no' | 'supplier_id' | 'supplier_name' | 'contact_person' | 'contact_phone' | 'unit_price' | 'delivery_days' | 'remark' | 'version' | 'id'> // version 是乐观锁版本号；version_no 仅跨版本查询时填充

/** 部位列表响应 */
export type PartListResponse = WithItems<Required<GenPartListResponse>, 'items', PartDetail>

/** 单个历史候选值（板房已录字段值 trim + 忽略大小写归并后的结果） */
export interface PartFieldCandidateValue {
  /** trim 后的展示值 */
  value: string
  /** 历史使用次数（归并后累加） */
  count: number
}

/** 部位字段历史候选查询参数（fields 缺省 supplier_name,fabric_name） */
export interface PartFieldCandidatesParams {
  fields?: string
  limit?: number
}

/** 部位字段历史候选响应（按字段名分组，只含请求的字段） */
export interface PartFieldCandidatesResponse {
  success: boolean
  fields: Record<string, PartFieldCandidateValue[]>
}

/** 部位跨版本汇总响应 */
export type PartsByVersionResponse = WithItems<Required<GenPartsByVersionResponse>, 'items', PartDetail>

// ==================== 角色 ====================

/** 角色简要信息 */
export type RoleBrief = Required<GenRoleBrief>
// version 是乐观锁版本号

/** 角色列表响应 */
export type RoleListResponse = WithItems<GenRoleListResponse, 'items', RoleBrief>

/** 新增角色请求 */
export type RoleCreateRequest = GenRoleCreateRequest

/** 编辑角色请求（乐观锁 version 必填） */
export type RoleUpdateRequest = GenRoleUpdateRequest

/** 批量新增部位单项 */
export type BatchPartItem = WithRequired<GenBatchPartItem, 'supplier_id' | 'fabric_name' | 'fabric_color_no'>

/** 批量新增部位请求 */
export type BatchPartCreateRequest = GenBatchPartCreateRequest

// ==================== 版本 ====================

/** 版本简要信息 */
export type VersionBrief = Required<GenVersionBrief>

/** 版本列表响应 */
export type VersionListResponse = WithItems<GenVersionListResponse, 'items', VersionBrief>

/** 字段级差异 */
export type FieldDiff = Required<GenFieldDiff>

/** 变更记录（版本 diff 元素） */
export interface ChangeRecord {
  change_type: ChangeType
  part_name: string
  new_value: PartDetail | null
  old_value: PartDetail | null
  field_diffs: FieldDiff[] | null
}

/** 版本详情响应
 *
 * - T1（is_baseline=true）：返回 full_snapshot，change_summary=null
 * - T2+ 正常：返回 change_summary（预计算 diff），full_snapshot=null
 * - 降级（degraded=true，前一版本缺失）：返回 full_snapshot + degraded=true
 *
 * 必须用 WithField 而不是 WithItems：WithItems<T,K,E> === WithField<T,K,E[]>，
 * 它把字段写成**非空**数组，正好抹掉上面这两条「其中一个恒为 null」的契约 ——
 * 于是 `res.full_snapshot.map(...)` 类型检查通过、运行时对每个非基线版本抛 TypeError。
 * 元素口径仍锁本地强类型（PartDetail / ChangeRecord），不落到生成层的全可选镜像。
 */
export type VersionDetailResponse = WithField<WithField<Required<GenVersionDetailResponse>, 'full_snapshot', PartDetail[] | null>, 'change_summary', ChangeRecord[] | null>

// ==================== 变更日志 ====================

/** 变更日志条目 */
export type ChangeLogEntry = Required<GenChangeLogEntry>

/** 变更日志列表响应（分页） */
export type ChangeLogListResponse = WithItems<GenChangeLogListResponse, 'items', ChangeLogEntry>

// ==================== 打样项目 ====================

/** 打样项目摘要（列表展示） */
export type ProjectSummary = WithField<Required<GenProjectSummary>, 'status', ProjectStatus> // completed_at 仅在 status=completed 时有值；status 口径由 ProjectStatus 本身表达

/** 版师分组 */
export type PatternMakerGroup = WithItems<Required<GenPatternMakerGroup>, 'projects', ProjectSummary>

/** 按版师分组聚合查询响应 */
export type GroupedListResponse = WithRequired<ReplaceField<GenGroupedListResponse, 'groups', PatternMakerGroup[]>, 'success' | 'total_projects' | 'total' | 'pages' | 'current_page'> // truncated=命中后端 5000 条分组截断上限（分组统计不含全部匹配项目）

/** 打样项目列表响应（分页） */
export type ProjectListResponse = WithItems<Required<GenProjectListResponse>, 'items', ProjectSummary>

/** 打样项目详情响应 */
export interface ProjectDetailResponse {
  id: number
  sequence_no: string
  product_name: string
  product_image_url: string | null
  product_image_thumbnail_url: string | null
  product_image_blur_url: string | null
  product_image_file_id: number | null
  pattern_maker_id: number | null
  pattern_maker_name: string
  current_version: string
  /** 状态：in_progress / completed / cancelled */
  status: ProjectStatus
  remark: string
  created_by_name: string | null
  created_at: string
  updated_at: string
  /** 乐观锁版本号 */
  version: number
  parts: PartDetail[]
  versions: VersionBrief[]
  roles: RoleBrief[]
}

// ==================== 请求 Schema ====================

/** 新增打样项目请求 */
export type ProjectCreateRequest = GenProjectCreateRequest

/** 编辑打样项目请求（version 为乐观锁版本号，必填）
 *  pattern_maker_id / product_image_file_id 三态语义：
 *  字段缺省（undefined，JSON 序列化时丢弃）= 不修改；显式 null = 清空；传值 = 设置 */
export type ProjectUpdateRequest = GenProjectUpdateRequest

/** 新增部位请求 */
export type PartCreateRequest = GenPartCreateRequest

/** 编辑部位请求（version 为乐观锁版本号，必填） */
export type PartUpdateRequest = GenPartUpdateRequest

// ==================== 查询参数 ====================

/** 分组列表查询参数 */
export interface GroupedListParams {
  keyword?: string
  customer_id?: number
  status?: string
  page?: number
  per_page?: number
}

/** 项目列表查询参数（分页） */
export interface ProjectListParams {
  page?: number
  per_page?: number
  keyword?: string
  customer_id?: number
}

/** 变更日志查询参数（分页） */
export interface ChangeLogListParams {
  page?: number
  per_page?: number
}

// ==================== API ====================

/**
 * 按客户分类打样信息模块 API
 *
 * 22 个方法对应后端 22 个端点，路径前缀 /pattern-room。
 * 命名遵循 camelCase（前端约定），API 路径使用 kebab-case。
 */
export const patternRoomApi = {
  // ---------- 1. 按客户分组聚合查询 ----------
  getGroupedList: (params?: GroupedListParams) =>
    get<GroupedListResponse>('/pattern-room/grouped-list', params as Record<string, unknown>),

  // ---------- 2. 打样项目列表 ----------
  listProjects: (params?: ProjectListParams) =>
    get<ProjectListResponse>('/pattern-room/projects', params as Record<string, unknown>),

  // ---------- 3. 打样项目详情 ----------
  getProject: (id: number) =>
    get<ProjectDetailResponse>(`/pattern-room/projects/${id}`),

  // ---------- 4. 新增打样项目 ----------
  createProject: (data: ProjectCreateRequest) =>
    post<ActionResponse>('/pattern-room/projects', data),

  // ---------- 5. 编辑打样项目 ----------
  updateProject: (id: number, data: ProjectUpdateRequest) =>
    put<ActionResponse>(`/pattern-room/projects/${id}`, data),

  // ---------- 5b. 更新项目状态（完成/进行中/取消） ----------
  updateProjectStatus: (id: number, status: ProjectStatus) =>
    put<ActionResponse>(`/pattern-room/projects/${id}/status`, { status }),

  // ---------- 6. 删除打样项目 ----------
  deleteProject: (id: number) =>
    del<ActionResponse>(`/pattern-room/projects/${id}`),

  // ---------- 7. 上传产品图片（multipart/form-data） ----------
  uploadProjectImage: (id: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return upload<ActionResponse>(`/pattern-room/projects/${id}/image`, formData)
  },

  // ---------- 8. 部位列表 ----------
  listParts: (projectId: number, roleId?: number) =>
    get<PartListResponse>(`/pattern-room/projects/${projectId}/parts`, roleId != null ? { role_id: roleId } : undefined),

  // ---------- 9. 新增部位 ----------
  createPart: (projectId: number, data: PartCreateRequest) =>
    post<ActionResponse>(`/pattern-room/projects/${projectId}/parts`, data),

  // ---------- 10. 编辑部位布料 ----------
  updatePart: (partId: number, data: PartUpdateRequest) =>
    put<ActionResponse>(`/pattern-room/parts/${partId}`, data),

  // ---------- 11. 删除部位 ----------
  deletePart: (partId: number) =>
    del<ActionResponse>(`/pattern-room/parts/${partId}`),

  // ---------- 12. 版本列表 ----------
  listVersions: (projectId: number) =>
    get<VersionListResponse>(`/pattern-room/projects/${projectId}/versions`),

  // ---------- 13. 版本详情 ----------
  getVersionDetail: (versionId: number) =>
    get<VersionDetailResponse>(`/pattern-room/versions/${versionId}`),

  // ---------- 14. 变更日志列表 ----------
  listChangeLogs: (projectId: number, params?: ChangeLogListParams) =>
    get<ChangeLogListResponse>(
      `/pattern-room/projects/${projectId}/change-logs`,
      params as Record<string, unknown>,
    ),

  // ---------- 15. 部位跨版本汇总 ----------
  getPartsByVersion: (projectId: number, roleId?: number, finalOnly?: boolean) =>
    get<PartsByVersionResponse>(
      `/pattern-room/projects/${projectId}/parts-by-version`,
      (roleId != null || finalOnly != null
        ? {
            ...(roleId != null ? { role_id: roleId } : {}),
            ...(finalOnly ? { final_only: true } : {}),
          }
        : undefined) as Record<string, unknown>,
    ),

  // ---------- 16. 批量新增部位 ----------
  batchCreateParts: (projectId: number, data: BatchPartCreateRequest, roleId?: number) =>
    post<ActionResponse>(
      `/pattern-room/projects/${projectId}/parts/batch${roleId != null ? `?role_id=${roleId}` : ''}`,
      data,
    ),

  // ---------- 17. 复制部位版本 ----------
  copyPartVersion: (partId: number) =>
    post<ActionResponse>(`/pattern-room/parts/${partId}/copy-version`),

  // ---------- 18. 角色列表 ----------
  listRoles: (projectId: number) =>
    get<RoleListResponse>(`/pattern-room/projects/${projectId}/roles`),

  // ---------- 19. 新增角色 ----------
  createRole: (projectId: number, data: RoleCreateRequest) =>
    post<ActionResponse>(`/pattern-room/projects/${projectId}/roles`, data),

  // ---------- 20. 编辑角色（改名 / 设置最终版本） ----------
  updateRole: (roleId: number, data: RoleUpdateRequest) =>
    put<ActionResponse>(`/pattern-room/roles/${roleId}`, data),

  // ---------- 21. 删除角色 ----------
  deleteRole: (roleId: number) =>
    del<ActionResponse>(`/pattern-room/roles/${roleId}`),

  // ---------- 22. 部位字段历史候选 ----------
  getPartFieldCandidates: (params?: PartFieldCandidatesParams) =>
    get<PartFieldCandidatesResponse>(
      '/pattern-room/part-field-candidates',
      params as Record<string, unknown> | undefined,
    ),
}
