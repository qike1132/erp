/**
 * 按客户分类打样信息模块 API 客户端
 *
 * 对应后端路由前缀: /api/v1/pattern-room（保持路径不变，用户无感切换）
 * 后端 endpoint: fastapi_app/api/v1/endpoints/customer_sampling.py
 * 后端 schema:   fastapi_app/schemas/customer_sampling.py
 *
 * 保持导出名 `patternRoomApi` 不变以兼容 `api/index.ts`。
 * 内部完全重写为面向"客户分组 + 部位布料 + 版本快照"扁平结构的 22 个 API 方法。
 */
import { get, post, put, del, upload } from './request'

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
export interface PartDetail {
  id: number | null
  project_id?: number
  role_id?: number | null
  part_name: string
  sort_order: number
  fabric_name: string
  fabric_spec: string
  fabric_color_no: string
  supplier_id: number | null
  supplier_name: string
  contact_person: string
  contact_phone: string
  unit_price: number | null
  delivery_days: number | null
  remark: string
  created_at?: string
  updated_at?: string
  /** 乐观锁版本号 */
  version: number
  /** 所属版本号（跨版本查询时填充） */
  version_no?: string | null
}

/** 部位列表响应 */
export interface PartListResponse {
  success: boolean
  items: PartDetail[]
}

/** 部位跨版本汇总响应 */
export interface PartsByVersionResponse {
  success: boolean
  items: PartDetail[]
  versions: string[]
  final_version: string
}

// ==================== 角色 ====================

/** 角色简要信息 */
export interface RoleBrief {
  id: number
  project_id: number
  role_name: string
  sort_order: number
  is_default: boolean
  current_version: string
  created_at: string
  updated_at: string
  /** 乐观锁版本号 */
  version: number
}

/** 角色列表响应 */
export interface RoleListResponse {
  success: boolean
  items: RoleBrief[]
}

/** 新增角色请求 */
export interface RoleCreateRequest {
  role_name: string
}

/** 编辑角色请求（乐观锁 version 必填） */
export interface RoleUpdateRequest {
  role_name?: string | null
  current_version?: string | null
  version: number
}

/** 批量新增部位单项 */
export interface BatchPartItem {
  part_name: string
  supplier_id: number | null
  supplier_name?: string | null
  fabric_name: string | null
  fabric_color_no: string | null
  version_no?: string
}

/** 批量新增部位请求 */
export interface BatchPartCreateRequest {
  items: BatchPartItem[]
}

// ==================== 版本 ====================

/** 版本简要信息 */
export interface VersionBrief {
  id: number
  version_no: string
  created_at: string
  reason: string
}

/** 版本列表响应 */
export interface VersionListResponse {
  success: boolean
  items: VersionBrief[]
}

/** 字段级差异 */
export interface FieldDiff {
  field: string
  old: unknown
  new: unknown
}

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
 */
export interface VersionDetailResponse {
  id: number
  project_id: number
  version_no: string
  created_at: string
  is_baseline: boolean
  degraded: boolean
  full_snapshot: PartDetail[] | null
  change_summary: ChangeRecord[] | null
}

// ==================== 变更日志 ====================

/** 变更日志条目 */
export interface ChangeLogEntry {
  id: number
  project_id: number
  target_version: string
  action: string
  action_label: string
  change_type: string
  change_type_label: string
  part_name: string
  field_diffs: unknown[]
  operator_id: number | null
  operator_name: string
  created_at: string
}

/** 变更日志列表响应（分页） */
export interface ChangeLogListResponse {
  success: boolean
  items: ChangeLogEntry[]
  total: number
  pages: number
  current_page: number
}

// ==================== 打样项目 ====================

/** 打样项目摘要（列表展示） */
export interface ProjectSummary {
  id: number
  sequence_no: string
  product_name: string
  product_image_url: string | null
  product_image_thumbnail_url: string | null
  product_image_blur_url: string | null
  current_version: string
  /** 状态：in_progress / completed / cancelled */
  status: ProjectStatus
  /** 完成时间（状态为 completed 时有值） */
  completed_at: string | null
  /** 部位数量 */
  parts_count: number
  updated_at: string
}

/** 版师分组 */
export interface PatternMakerGroup {
  pattern_maker_id: number | null
  pattern_maker_name: string
  project_count: number
  latest_update_time: string
  projects: ProjectSummary[]
}

/** 按版师分组聚合查询响应 */
export interface GroupedListResponse {
  success: boolean
  groups: PatternMakerGroup[]
  total_projects: number
  total: number
  pages: number
  current_page: number
}

/** 打样项目列表响应（分页） */
export interface ProjectListResponse {
  success: boolean
  items: ProjectSummary[]
  total: number
  pages: number
  current_page: number
}

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
export interface ProjectCreateRequest {
  product_name: string
  pattern_maker_id?: number | null
  remark?: string | null
  initial_roles?: string[] | null
}

/** 编辑打样项目请求（version 为乐观锁版本号，必填） */
export interface ProjectUpdateRequest {
  product_name?: string | null
  pattern_maker_id?: number | null
  remark?: string | null
  product_image_file_id?: number | null
  /** 移除已有产品图片（后端清除 product_image_file_id） */
  clear_image?: boolean
  current_version?: string | null
  version: number
}

/** 新增部位请求 */
export interface PartCreateRequest {
  part_name: string
  sort_order?: number
  fabric_name?: string | null
  fabric_spec?: string | null
  /** 色号 */
  fabric_color_no?: string | null
  supplier_id?: number | null
  contact_person?: string | null
  contact_phone?: string | null
  unit_price?: number | null
  delivery_days?: number | null
  remark?: string | null
}

/** 编辑部位请求（version 为乐观锁版本号，必填） */
export interface PartUpdateRequest {
  part_name?: string | null
  sort_order?: number | null
  fabric_name?: string | null
  fabric_spec?: string | null
  fabric_color_no?: string | null
  supplier_id?: number | null
  supplier_name?: string | null
  contact_person?: string | null
  contact_phone?: string | null
  unit_price?: number | null
  delivery_days?: number | null
  remark?: string | null
  version: number
}

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
}
