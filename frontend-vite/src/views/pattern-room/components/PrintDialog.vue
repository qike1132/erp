<template>
  <!-- 打样单打印内容：通过 Teleport 挂到 body，屏幕上隐藏，打印时（body.pd-printing）仅显示本内容 -->
  <Teleport to="body">
    <div class="pd-print-sheet">
      <div class="pd-head">
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

        <!-- 产品图片：表头右上角，与元信息顶部对齐 -->
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

      <div class="pd-rule" />

      <!-- 部位明细表格（按角色分组，通栏占满纸张宽度） -->
      <div class="pd-tables">
        <div v-for="group in groupedParts" :key="group.roleId ?? 'none'" class="pd-role-section">
          <div class="pd-role-head">
            <span class="pd-role-title">{{ group.roleName }}</span>
            <span v-if="group.items.length" class="pd-role-count">
              {{ group.items.length }} 个部位
            </span>
          </div>
          <table class="pd-table">
            <!-- 显式列宽：每个角色分段是独立 <table>，共用同一份 colgroup 才能保证列位置一致 -->
            <colgroup>
              <col style="width: 100px" />
              <col style="width: 60px" />
              <col v-for="field in PART_EDIT_FIELDS" :key="field.key" :style="{ width: field.width }" />
            </colgroup>
            <thead>
              <tr>
                <th class="pd-th-part">部位名称</th>
                <th>版本</th>
                <th v-for="field in PART_EDIT_FIELDS" :key="field.key">{{ field.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(part, idx) in group.items" :key="part.id ?? `${group.roleId}-${idx}`">
                <td class="pd-td-part">{{ part.part_name || '-' }}</td>
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

/**
 * 按角色分组的部位数据。
 *
 * 分段来源是「角色列表」而非「部位数据」：角色的最终版本可能没有数据
 * （current_version 指向空版本/已不存在的版本，或该角色尚未录入部位），
 * 若仅由部位数据推导分段，整个角色会从打样单上消失。
 * 同一角色下每个 part_name 只保留一行（版本由上游按最终版本/最新有数据版本选定）。
 */
const groupedParts = computed(() => {
  const groups = new Map<number | null, { roleId: number | null; roleName: string; items: PartDetail[] }>()
  // 先按角色列表顺序建段，保证每个角色都会出现在打样单上
  for (const r of props.roles) {
    groups.set(r.id, { roleId: r.id, roleName: r.role_name, items: [] })
  }

  const seenParts = new Map<number | null, Set<string>>()

  for (const part of props.parts) {
    const rid = part.role_id ?? null
    let group = groups.get(rid)
    if (!group) {
      // 角色列表外的数据（角色已被删除等）追加到末尾，避免内容丢失
      group = { roleId: rid, roleName: rid != null ? `角色${rid}` : '未分配角色', items: [] }
      groups.set(rid, group)
    }
    let seen = seenParts.get(rid)
    if (!seen) {
      seen = new Set<string>()
      seenParts.set(rid, seen)
    }
    if (seen.has(part.part_name)) continue
    seen.add(part.part_name)
    group.items.push(part)
  }

  return [...groups.values()]
})

defineExpose({ updatePrintTime })
</script>

<style scoped>
/* 屏幕上隐藏（仅打印时显示） */
.pd-print-sheet {
  display: none;
}

/* ============ 表头：左元信息，右上产品图片 ============ */
/* 顶部对齐：图片贴住内容顶端，元信息也不再垂直居中而上下各留一大段空白 */
.pd-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 28px;
}

/* wrap：产品名称可能很长，换行而不是横向撑破纸张 */
.pd-head-meta {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 44px;
}

/* 标签在上、值在下：值比标签醒目，编号/色号一类数字列竖向对齐 */
.pd-meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.pd-meta-label {
  font-size: 11px;
  color: #75808e;
  letter-spacing: 0.08em;
}

.pd-meta-value {
  font-size: 15px;
  font-weight: 700;
  color: #16202e;
  font-variant-numeric: tabular-nums;
}

/* 表头分割线：深墨 + 品牌橙拼接 */
.pd-rule {
  height: 3px;
  margin: 14px 0 18px;
  background: linear-gradient(to right, #16202e 0 92px, #ff9f43 92px 100%);
}

/* 产品图片 */
.pd-image-box {
  width: 180px;
  height: 180px;
  flex-shrink: 0;
  border: 1px solid #d5dbe3;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f6f8fa;
  page-break-inside: avoid;
}

.pd-image {
  width: 100%;
  height: 100%;
  /* contain：完整显示整张图片（cover 会按外框裁剪，非正方形图片内容被切掉） */
  object-fit: contain;
  display: block;
}

.pd-image-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #9aa4b1;
  font-size: 12px;
}

.pd-image-placeholder svg {
  width: 44px;
  height: 44px;
  opacity: 0.45;
}

/* ============ 部位明细表格 ============ */
/* 角色分组 */
.pd-role-section {
  margin-bottom: 22px;
  page-break-inside: avoid;
}

.pd-role-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding-left: 11px;
  border-left: 3px solid #ff9f43;
  margin-bottom: 7px;
}

.pd-role-title {
  font-size: 14.5px;
  font-weight: 700;
  color: #16202e;
  letter-spacing: 0.04em;
}

.pd-role-count {
  font-size: 11px;
  color: #75808e;
}

.pd-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  /* 固定列宽：每个角色分段是独立 <table>，auto 布局会各按自身内容算列宽，
     导致同一列在不同分段下左右漂移。用 colgroup + fixed 让全部分段共用列位置。 */
  table-layout: fixed;
}

.pd-table th,
.pd-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #eceff3;
  text-align: center;
  color: #16202e;
  /* 列宽固定后不再随内容变宽：允许换行，避免长供应商/布料名溢出到相邻列 */
  white-space: normal;
}

.pd-table th {
  font-size: 12px;
  font-weight: 700;
  color: #44515f;
  background: #f6f8fa;
  border-top: 1px solid #d5dbe3;
  border-bottom: 1px solid #d5dbe3;
}

.pd-th-part,
.pd-td-part {
  text-align: left;
}

.pd-table tr {
  page-break-inside: avoid;
}

.pd-empty {
  color: #75808e;
}

.pd-foot {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px dashed #d5dbe3;
  font-size: 12px;
  color: #75808e;
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
