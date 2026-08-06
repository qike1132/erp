<template>
  <div class="pr-breakdown-tab">
    <!-- 顶部工具栏 -->
    <div class="pr-toolbar">
      <div class="pr-toolbar-left">
        <label>BOM 选择</label>
        <select v-model="selectedBomIdLocal" @change="onBomChange">
          <option :value="null">请选择 BOM</option>
          <option v-for="b in bomOptions" :key="b.id" :value="b.id">
            {{ b.bom_no }} - {{ b.product_name }}
          </option>
        </select>
      </div>
      <div class="pr-toolbar-right">
        <div class="pr-view-toggle">
          <button :class="['pr-toggle-btn', { active: viewMode === 'tree' }]" @click="viewMode = 'tree'">
            <i class="fas fa-sitemap" /> 树形图
          </button>
          <button :class="['pr-toggle-btn', { active: viewMode === 'table' }]" @click="viewMode = 'table'">
            <i class="fas fa-table" /> 表格视图
          </button>
        </div>
        <template v-if="viewMode === 'tree'">
          <button class="pr-btn pr-btn-ghost" @click="zoomIn" title="放大"><i class="fas fa-search-plus" /></button>
          <button class="pr-btn pr-btn-ghost" @click="zoomOut" title="缩小"><i class="fas fa-search-minus" /></button>
          <button class="pr-btn pr-btn-ghost" @click="resetZoom" title="重置"><i class="fas fa-undo" /></button>
          <span class="pr-zoom-label">{{ Math.round(zoom * 100) }}%</span>
        </template>
      </div>
    </div>

    <!-- 内容区 -->
    <div class="pr-breakdown-content">
      <div v-if="!bom" class="pr-empty-state">
        <i class="fas fa-sitemap" />
        <p>请选择一个 BOM 查看拆分图</p>
      </div>
      <div v-else-if="isLoading" class="pr-empty-state">
        <UiSpinner />
        <p>加载中...</p>
      </div>
      <template v-else>
        <!-- 树形图视图 -->
        <div v-if="viewMode === 'tree'" class="pr-tree-view" ref="treeViewRef">
          <div class="pr-tree-canvas" :style="{ transform: `scale(${zoom})` }">
            <BreakdownNode
              v-for="(node, idx) in treeNodes"
              :key="idx"
              :node="node"
              :x="nodePositions[idx]?.x || 0"
              :y="nodePositions[idx]?.y || 0"
              @select="onNodeSelect"
            />
            <svg class="pr-tree-lines" :width="canvasWidth" :height="canvasHeight">
              <path
                v-for="(line, idx) in treeLines"
                :key="idx"
                :d="line.path"
                stroke="var(--color-border)"
                stroke-width="1.5"
                fill="none"
              />
            </svg>
          </div>
        </div>

        <!-- 表格视图 -->
        <div v-else class="pr-table-view">
          <table class="pr-tbl">
            <thead>
              <tr>
                <th style="width: 40px;">层级</th>
                <th>物料名称</th>
                <th style="width: 100px;">类别</th>
                <th style="width: 100px;">用量</th>
                <th style="width: 140px;">规格</th>
                <th style="width: 160px;">当前供应商</th>
                <th style="width: 80px;">版本</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in flatNodes" :key="row.id || row.path">
                <td>
                  <span class="pr-level-indicator" :style="{ paddingLeft: row.depth * 16 + 'px' }">
                    <i v-if="row.depth > 0" class="fas fa-arrow-right pr-level-arrow" />
                  </span>
                </td>
                <td class="pr-td-bold">
                  <i :class="categoryIcon(row.category)" :style="{ color: categoryColor(row.category) }" />
                  {{ row.material_name }}
                </td>
                <td>
                  <UiStatusBadge :variant="categoryVariant(row.category)">{{ categoryLabel(row.category) }}</UiStatusBadge>
                </td>
                <td>{{ row.quantity }} {{ row.unit }}</td>
                <td>{{ row.spec || '-' }}</td>
                <td>{{ row.current_supplier_name || '-' }}</td>
                <td>
                  <span class="pr-version-badge">{{ row.current_version }}</span>
                </td>
              </tr>
              <tr v-if="!flatNodes.length">
                <td colspan="7" class="pr-empty"><i class="fas fa-inbox" /><span>暂无节点</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- 节点详情抽屉 -->
    <UiDialog v-model:open="detailOpen" title="节点详情" max-width-class="max-w-[600px]">
      <template #title-icon>
        <i class="fas fa-circle-info" style="color: var(--color-primary-500);"></i>
      </template>
      <div v-if="selectedNode" class="pr-node-detail">
        <div class="pr-detail-grid">
          <div class="pr-detail-field">
            <label>物料名称</label>
            <span class="pr-detail-value">{{ selectedNode.material_name }}</span>
          </div>
          <div class="pr-detail-field">
            <label>类别</label>
            <span class="pr-detail-value">{{ categoryLabel(selectedNode.category) }}</span>
          </div>
          <div class="pr-detail-field">
            <label>用量</label>
            <span class="pr-detail-value">{{ selectedNode.quantity }} {{ selectedNode.unit }}</span>
          </div>
          <div class="pr-detail-field">
            <label>规格</label>
            <span class="pr-detail-value">{{ selectedNode.spec || '-' }}</span>
          </div>
        </div>

        <div class="pr-versions-section">
          <h5><i class="fas fa-code-branch" /> 版本快照</h5>
          <div v-if="selectedNode.versions?.length" class="pr-versions-list">
            <div v-for="v in selectedNode.versions" :key="v.id" class="pr-version-card">
              <div class="pr-version-card-header">
                <span class="pr-version-badge">{{ v.version }}</span>
                <span class="pr-version-time">{{ v.snapshot_at }}</span>
              </div>
              <div class="pr-version-card-body">
                <div><label>供应商：</label><span>{{ v.supplier_name || '-' }}</span></div>
                <div><label>规格：</label><span>{{ v.material_spec || '-' }}</span></div>
                <div v-if="v.unit_price"><label>单价：</label><span>¥{{ v.unit_price }}</span></div>
                <div v-if="v.contact_person"><label>联系人：</label><span>{{ v.contact_person }}</span></div>
                <div v-if="v.contact_phone"><label>电话：</label><span>{{ v.contact_phone }}</span></div>
                <div v-if="v.delivery_days"><label>交期：</label><span>{{ v.delivery_days }} 天</span></div>
                <div v-if="v.remark"><label>备注：</label><span>{{ v.remark }}</span></div>
              </div>
            </div>
          </div>
          <div v-else class="pr-versions-empty">暂无版本快照</div>
        </div>
      </div>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
/**
 * BreakdownTab.vue — 产品拆分图 Tab
 *
 * 职责：
 * - 提供 SVG 树形图 + 表格视图两种模式
 * - 节点点击展示详情对话框（含版本快照）
 */
import { ref, computed, watch, onMounted } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiStatusBadge from '@/components/ui/UiStatusBadge.vue'
import { showToast } from '@/composables/useToast'
import { patternRoomApi } from '@/api/patternRoom'
import type { PatternRoomBom, BomItem } from '@/api/patternRoom'
import BreakdownNode from './components/BreakdownNode.vue'

interface FlatNode extends BomItem {
  depth: number
  path: string
}

interface TreeNode {
  item: BomItem
  children: TreeNode[]
  x: number
  y: number
  width: number
  height: number
}

interface TreeLine {
  path: string
}

const props = defineProps<{ bomId: number | null }>()

const selectedBomIdLocal = ref<number | null>(props.bomId)
const bom = ref<PatternRoomBom | null>(null)
const isLoading = ref(false)
const viewMode = ref<'tree' | 'table'>('tree')
const zoom = ref(1)
const treeViewRef = ref<HTMLElement | null>(null)
const detailOpen = ref(false)
const selectedNode = ref<BomItem | null>(null)

// BOM 选项列表
const bomOptions = ref<PatternRoomBom[]>([])
async function loadBomOptions() {
  try {
    const res = await patternRoomApi.listBom({ per_page: 100 })
    bomOptions.value = res.items ?? []
  } catch (e) {
    // 静默失败
  }
}

async function loadBomDetail() {
  if (!selectedBomIdLocal.value) {
    bom.value = null
    return
  }
  isLoading.value = true
  try {
    const res = await patternRoomApi.getBom(selectedBomIdLocal.value)
    bom.value = res.bom
  } catch (e: any) {
    showToast(e?.detail || '加载 BOM 详情失败', 'error')
    bom.value = null
  } finally {
    isLoading.value = false
  }
}

function onBomChange() {
  loadBomDetail()
}

watch(
  () => props.bomId,
  (newId) => {
    if (newId && newId !== selectedBomIdLocal.value) {
      selectedBomIdLocal.value = newId
      loadBomDetail()
    }
  },
)

// 表格视图扁平化
const flatNodes = computed<FlatNode[]>(() => {
  if (!bom.value?.items) return []
  const result: FlatNode[] = []
  const walk = (items: BomItem[], depth: number, parentPath: string) => {
    items.forEach((item, idx) => {
      const path = `${parentPath}-${idx}`
      result.push({ ...item, depth, path })
      if (item.children?.length) {
        walk(item.children, depth + 1, path)
      }
    })
  }
  walk(bom.value.items, 0, '')
  return result
})

// 树形布局计算
const treeNodes = computed<TreeNode[]>(() => {
  if (!bom.value?.items) return []
  const NODE_W = 180
  const NODE_H = 70
  const H_GAP = 40
  const V_GAP = 60
  const nodes: TreeNode[] = []
  const lines: TreeLine[] = []

  let currentY = 0
  const layout = (items: BomItem[], depth: number, parentX?: number, parentY?: number): number => {
    if (!items.length) return 0
    const startY = currentY
    const childYs: number[] = []
    items.forEach((item) => {
      const y = currentY
      const node: TreeNode = {
        item,
        children: [],
        x: depth * (NODE_W + H_GAP),
        y,
        width: NODE_W,
        height: NODE_H,
      }
      if (item.children?.length) {
        const childCenterY = layout(item.children, depth + 1, node.x + NODE_W, node.y + NODE_H / 2)
        node.y = childCenterY - NODE_H / 2
      }
      nodes.push(node)
      childYs.push(node.y + NODE_H / 2)
      currentY += NODE_H + V_GAP
    })
    // 绘制连接线
    if (parentX !== undefined && parentY !== undefined) {
      childYs.forEach((cy) => {
        const midX = parentX + H_GAP / 2
        lines.push({
          path: `M ${parentX} ${parentY} C ${midX} ${parentY}, ${midX} ${cy}, ${parentX + H_GAP} ${cy}`,
        })
      })
    }
    const centerY = childYs.length
      ? (childYs[0]! + childYs[childYs.length - 1]!) / 2
      : 0
    return centerY
  }
  layout(bom.value.items, 0)
  _treeLines.value = lines
  return nodes
})

const _treeLines = ref<TreeLine[]>([])
const treeLines = computed(() => _treeLines.value)

const canvasWidth = computed(() => {
  const maxDepth = Math.max(0, ...treeNodes.value.map((n) => Math.floor(n.x / 220) + 1))
  return maxDepth * 220 + 40
})

const canvasHeight = computed(() => {
  return treeNodes.value.length * 130 + 40
})

function zoomIn() {
  zoom.value = Math.min(2, zoom.value + 0.1)
}
function zoomOut() {
  zoom.value = Math.max(0.4, zoom.value - 0.1)
}
function resetZoom() {
  zoom.value = 1
}

function onNodeSelect(item: BomItem) {
  selectedNode.value = item
  detailOpen.value = true
}

// 类别辅助
function categoryIcon(category: string): string {
  const map: Record<string, string> = {
    fabric: 'fas fa-square',
    filling: 'fas fa-cube',
    accessory: 'fas fa-link',
    packaging: 'fas fa-tag',
  }
  return map[category] || 'fas fa-circle'
}
function categoryColor(category: string): string {
  const map: Record<string, string> = {
    fabric: 'var(--color-purple-600)',
    filling: 'var(--color-warning-600)',
    accessory: 'var(--color-info-600)',
    packaging: 'var(--color-success-600)',
  }
  return map[category] || 'var(--color-text-muted)'
}
function categoryLabel(category: string): string {
  const map: Record<string, string> = {
    fabric: '面料',
    filling: '填充',
    accessory: '辅料',
    packaging: '包装',
  }
  return map[category] || category
}
function categoryVariant(category: string): 'primary' | 'warning' | 'info' | 'success' {
  const map: Record<string, 'primary' | 'warning' | 'info' | 'success'> = {
    fabric: 'primary',
    filling: 'warning',
    accessory: 'info',
    packaging: 'success',
  }
  return map[category] || 'primary'
}

// nodePositions for v-for binding
const nodePositions = computed(() => treeNodes.value.map((n) => ({ x: n.x, y: n.y })))

onMounted(() => {
  loadBomOptions()
  if (selectedBomIdLocal.value) loadBomDetail()
})
</script>

<style scoped>
.pr-breakdown-tab {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

.pr-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.pr-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pr-toolbar-left label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-toolbar-left select {
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 13px;
  background: white;
  min-width: 240px;
}

.pr-toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pr-view-toggle {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border-radius: 9px;
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
}

.pr-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.pr-toggle-btn.active {
  background: white;
  color: var(--color-primary-700);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.pr-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 10px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.pr-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-700);
}

.pr-btn-ghost {
  background: transparent;
}

.pr-zoom-label {
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 600;
  min-width: 40px;
  text-align: right;
}

.pr-breakdown-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--color-surface);
  border-radius: 12px;
  border: 1px solid var(--color-border-light);
  padding: 20px;
  position: relative;
}

.pr-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
  color: var(--color-text-muted);
  gap: 12px;
}

.pr-empty-state i {
  font-size: 48px;
  opacity: 0.4;
}

.pr-empty-state p {
  margin: 0;
  font-size: 14px;
}

.pr-tree-view {
  width: 100%;
  height: 100%;
  overflow: auto;
  position: relative;
}

.pr-tree-canvas {
  position: relative;
  transform-origin: top left;
  transition: transform 0.2s;
  min-width: fit-content;
  min-height: fit-content;
}

.pr-tree-lines {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 0;
}

.pr-table-view {
  background: white;
  border-radius: 8px;
  overflow: auto;
}

.pr-tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  min-width: 800px;
}

.pr-tbl th {
  background: var(--color-surface);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
}

.pr-tbl td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light);
}

.pr-tbl td i {
  margin-right: 6px;
}

.pr-level-indicator {
  display: inline-block;
}

.pr-level-arrow {
  font-size: 10px;
  color: var(--color-text-muted);
}

.pr-td-bold {
  font-weight: 600;
}

.pr-version-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  padding: 3px 8px;
  background: linear-gradient(135deg, var(--color-purple-50), var(--color-purple-100));
  color: var(--color-purple-700);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.pr-empty {
  text-align: center;
  padding: 40px;
  color: var(--color-text-muted);
}

/* 详情对话框 */
.pr-node-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.pr-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.pr-detail-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pr-detail-field label {
  font-size: 11px;
  color: var(--color-text-muted);
  font-weight: 600;
  text-transform: uppercase;
}

.pr-detail-value {
  font-size: 14px;
  color: var(--color-text);
  font-weight: 500;
}

.pr-versions-section h5 {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}

.pr-versions-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pr-version-card {
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  overflow: hidden;
}

.pr-version-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--color-surface);
}

.pr-version-time {
  font-size: 11px;
  color: var(--color-text-muted);
}

.pr-version-card-body {
  padding: 12px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 14px;
  font-size: 13px;
}

.pr-version-card-body label {
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-right: 4px;
}

.pr-versions-empty {
  padding: 20px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
}
</style>
