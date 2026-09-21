<template>
  <!-- 打样单打印内容：通过 Teleport 挂到 body，屏幕上隐藏，打印时（body.pd-printing）仅显示本内容 -->
  <Teleport to="body">
    <div class="pd-print-sheet">
      <div class="pd-head">
        <div class="pd-head-title">打 样 单</div>
        <div class="pd-head-meta">
          <div class="pd-meta-item">
            <span class="pd-meta-label">产品名称</span>
            <span class="pd-meta-value">{{ project?.product_name || '-' }}</span>
          </div>
          <div class="pd-meta-item">
            <span class="pd-meta-label">编号</span>
            <span class="pd-meta-value">{{ displayNumber }}</span>
          </div>
          <div class="pd-meta-item">
            <span class="pd-meta-label">版师</span>
            <span class="pd-meta-value">{{ project?.pattern_maker_name || '-' }}</span>
          </div>
        </div>
      </div>

      <div class="pd-body">
        <!-- 产品图片 -->
        <div class="pd-image-col">
          <div class="pd-image-box">
            <img
              v-if="project?.product_image_url"
              :src="project.product_image_url"
              alt="产品图片"
              class="pd-image"
            />
            <div v-else class="pd-image-placeholder">
              <FontAwesomeIcon icon="tshirt" aria-hidden="true" />
              <span>暂无图片</span>
            </div>
          </div>
        </div>

        <!-- 部位明细表格（按角色分组） -->
        <div class="pd-table-col">
          <div v-for="group in groupedParts" :key="group.roleId ?? 'none'" class="pd-role-section">
            <div class="pd-role-title">{{ group.roleName }}</div>
            <table class="pd-table">
              <thead>
                <tr>
                  <th class="pd-th-part">部位名称</th>
                  <th>版本</th>
                  <th v-for="field in PART_EDIT_FIELDS" :key="field.key">{{ field.label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(part, idx) in group.items" :key="part.id ?? `${group.roleId}-${idx}`">
                  <td>{{ part.part_name || '-' }}</td>
                  <td>{{ part.version_no || '-' }}</td>
                  <td v-for="field in PART_EDIT_FIELDS" :key="field.key">{{ part[field.key] || '-' }}</td>
                </tr>
                <tr v-if="group.items.length === 0">
                  <td :colspan="2 + PART_EDIT_FIELDS.length" class="pd-empty">暂无部位数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="pd-foot">
        <span>打印时间：{{ printTime }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ProjectDetailResponse, PartDetail, RoleBrief } from '@/api/patternRoom'
import { PART_EDIT_FIELDS } from '../composables/usePartInlineEdit'

const props = defineProps<{
  project: ProjectDetailResponse | null
  parts: PartDetail[]
  roles: RoleBrief[]
}>()

const printTime = ref('')

/** 按更新日期生成编号：YYYYMMDD + 01（单项目打印，序号固定 01） */
const displayNumber = computed(() => {
  const dateStr = props.project?.updated_at?.slice(0, 10) || ''
  if (!dateStr) return '-'
  return `${dateStr.replace(/-/g, '')}01`
})

/** 打印前更新打印时间 */
function updatePrintTime() {
  printTime.value = new Date().toLocaleString()
}

/** 按角色分组的部位数据，每个部位只保留最终版本 */
const groupedParts = computed(() => {
  const roleMap = new Map<number, string>()
  const roleFinalVersion = new Map<number, string>()
  for (const r of props.roles) {
    roleMap.set(r.id, r.role_name)
    roleFinalVersion.set(r.id, r.current_version)
  }

  const groups = new Map<number | null, { roleId: number | null; roleName: string; items: PartDetail[] }>()
  // 每个角色下每个 part_name 只保留最终版本那一行
  const seenParts = new Map<number | null, Set<string>>()

  for (const part of props.parts) {
    const rid = part.role_id ?? null
    if (!groups.has(rid)) {
      groups.set(rid, {
        roleId: rid,
        roleName: rid != null ? (roleMap.get(rid) ?? `角色${rid}`) : '未分配角色',
        items: [],
      })
      seenParts.set(rid, new Set())
    }
    const seen = seenParts.get(rid)!
    // 该部位已输出过最终版本行，跳过其他版本
    if (seen.has(part.part_name)) continue
    // 只保留该角色的最终版本
    const finalVersion = rid != null ? (roleFinalVersion.get(rid) ?? '') : ''
    if (finalVersion && part.version_no !== finalVersion) continue
    seen.add(part.part_name)
    groups.get(rid)!.items.push(part)
  }

  // 按角色 sort_order 排序
  const roleOrder = new Map<number, number>()
  props.roles.forEach((r, i) => roleOrder.set(r.id, i))

  return [...groups.values()].sort((a, b) => {
    const oa = a.roleId != null ? (roleOrder.get(a.roleId) ?? 999) : 999
    const ob = b.roleId != null ? (roleOrder.get(b.roleId) ?? 999) : 999
    return oa - ob
  })
})

defineExpose({ updatePrintTime })
</script>

<style scoped>
/* 屏幕上隐藏（仅打印时显示） */
.pd-print-sheet {
  display: none;
}

/* ============ 打样单纸张 ============ */
.pd-head {
  border-bottom: 2px solid #1a1a2e;
  padding-bottom: 12px;
  margin-bottom: 16px;
}

.pd-head-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  color: #1a1a2e;
  letter-spacing: 8px;
  margin-bottom: 12px;
}

.pd-head-meta {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
}

.pd-meta-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 13px;
}

.pd-meta-label {
  color: #6b7280;
  flex-shrink: 0;
}

.pd-meta-value {
  color: #1a1a2e;
  font-weight: 600;
}

.pd-body {
  display: flex;
  gap: 20px;
}

/* 产品图片 */
.pd-image-col {
  flex-shrink: 0;
}

.pd-image-box {
  width: 220px;
  height: 220px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  page-break-inside: avoid;
}

.pd-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.pd-image-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 13px;
}

.pd-image-placeholder i {
  font-size: 40px;
  opacity: 0.5;
}

/* 部位明细表格 */
.pd-table-col {
  flex: 1;
  min-width: 0;
}

/* 角色分组 */
.pd-role-section {
  margin-bottom: 16px;
  page-break-inside: avoid;
}

.pd-role-title {
  font-size: 14px;
  font-weight: 700;
  color: #1a1a2e;
  padding: 6px 10px;
  background: #f1f5f9;
  border-left: 4px solid #ff9f43;
  border-radius: 4px;
  margin-bottom: 6px;
}

.pd-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pd-table th,
.pd-table td {
  padding: 8px 10px;
  border: 1px solid #d9dce3;
  text-align: center;
  color: #1a1a2e;
  white-space: nowrap;
}

.pd-table th {
  background: #f8fafc;
  font-weight: 600;
}

.pd-th-part {
  text-align: left;
}

.pd-table tr {
  page-break-inside: avoid;
}

.pd-empty {
  color: #94a3b8;
}

.pd-foot {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px dashed #d9dce3;
  font-size: 12px;
  color: #6b7280;
  display: flex;
  justify-content: flex-end;
}

/* ============ 打印隔离：body 添加 pd-printing 后仅显示打样单 ============ */
:global(body.pd-printing > *) {
  display: none !important;
}

:global(body.pd-printing > .pd-print-sheet) {
  display: block !important;
  padding: 20px;
}

/* 打印时隐藏浏览器自带的页眉页脚（URL/日期/标题） */
@media print {
  @page {
    margin: 0;
  }
}

</style>
