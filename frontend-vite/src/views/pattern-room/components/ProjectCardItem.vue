<template>
  <div
    :class="['cgl-project-card', { active: selected, 'is-completed': proj.status === 'completed' }]"
    role="button"
    tabindex="0"
  >
    <div class="cgl-card-left">
      <div
        v-if="proj.product_image_url && !imgFailed"
        class="cgl-card-thumb"
        :class="{ 'is-loaded': thumbLoaded }"
        role="button"
        title="点击查看大图"
        @click.stop="emit('preview', proj.product_image_url!)"
      >
        <!-- 骨架屏：图片加载完成前显示微光动画占位 -->
        <div class="cgl-thumb-skeleton" aria-hidden="true" />
        <!-- 模糊占位图（32px，blur-up）：滚动即见，清晰图加载后淡出 -->
        <img
          v-if="proj.product_image_blur_url"
          :src="proj.product_image_blur_url"
          class="cgl-thumb-blur"
          alt=""
          aria-hidden="true"
          decoding="async"
          fetchpriority="low"
          @error="onBlurError"
        />
        <!-- 清晰缩略图：加载完成后淡入 -->
        <img
          ref="thumbImg"
          :src="proj.product_image_thumbnail_url || proj.product_image_url"
          class="cgl-thumb-img"
          alt=""
          width="300"
          height="240"
          loading="lazy"
          decoding="async"
          fetchpriority="low"
          @error="onThumbError($event)"
          @load="thumbLoaded = true"
        />
        <span v-if="proj.status === 'completed'" class="cgl-card-status-badge">
          <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 已完成
        </span>
      </div>
      <div v-else class="cgl-card-thumb cgl-card-thumb-placeholder">
        <FontAwesomeIcon icon="shirt" aria-hidden="true" />
        <span v-if="proj.status === 'completed'" class="cgl-card-status-badge">
          <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 已完成
        </span>
      </div>
    </div>
    <div class="cgl-card-right">
      <div class="cgl-card-info">
        <div class="cgl-card-name">{{ proj.product_name }}</div>
        <div class="cgl-card-meta">
          <span class="cgl-card-meta-label">版师：</span>
          <span class="cgl-card-meta-value">{{ makerName || '-' }}</span>
        </div>
        <div class="cgl-card-meta">
          <span class="cgl-card-meta-label">编号：</span>
          <span class="cgl-card-meta-value">{{ displayNumber }}</span>
        </div>
        <div class="cgl-card-time">时间：{{ formatTime(proj.updated_at) }}</div>
      </div>
      <div v-if="canManage" class="cgl-card-actions">
        <button
          type="button"
          class="cgl-card-action cgl-card-action--edit"
          title="编辑该打样项目"
          @click.stop="emit('edit', proj.id)"
        >
          <FontAwesomeIcon icon="pen" aria-hidden="true" /> 编辑
        </button>
        <button
          v-if="proj.status === 'in_progress'"
          type="button"
          class="cgl-card-action cgl-card-action--done"
          title="标记为已完成"
          @click.stop="emit('complete', proj.id)"
        >
          <FontAwesomeIcon icon="check" aria-hidden="true" /> 完成
        </button>
        <button
          v-if="proj.status === 'in_progress'"
          type="button"
          class="cgl-card-action cgl-card-action--cancel"
          title="取消该打样项目"
          @click.stop="emit('cancel', proj.id)"
        >
          <FontAwesomeIcon icon="xmark" aria-hidden="true" /> 取消
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ProjectCardItem — 打样项目卡片（虚拟列表行）
 * 模板与样式自 CustomerGroupList.vue 原样搬移。
 * 注意：卡片根元素的 click / keyup.enter（选中项目）由父组件通过
 * attrs 透传绑定（保持原 VirtualList 插槽内联写法），本组件不再重复绑定。
 */
import type { ProjectSummary } from '@/api/patternRoom'
import { useProjectCardThumb } from '../composables/useProjectCardThumb'

const props = defineProps<{
  /** 项目摘要数据 */
  proj: ProjectSummary
  /** 是否为当前选中项目（原 selectedProjectId === proj.id） */
  selected: boolean
  /** 版师姓名（原 selectedGroup?.pattern_maker_name） */
  makerName: string | undefined
  /** 展示编号（原 projectDisplayNumbers.get(proj.id)） */
  displayNumber: string | undefined
  /** 是否可管理（显示操作按钮） */
  canManage: boolean
}>()

const emit = defineEmits<{
  /** 点击缩略图查看大图 */
  preview: [url: string]
  /** 编辑项目 */
  edit: [id: number]
  /** 标记项目完成 */
  complete: [id: number]
  /** 取消项目 */
  cancel: [id: number]
}>()

// 缩略图加载状态与错误回退链路（骨架屏→模糊图→清晰图→回退原图→占位），
// 见 composables/useProjectCardThumb.ts
const { thumbLoaded, thumbImg, imgFailed, onThumbError, onBlurError } = useProjectCardThumb(
  () => props.proj,
)

/** 时间格式化缓存（同一 ISO 字符串多次渲染复用结果） */
const _timeFormatCache = new Map<string, string>()
function formatTime(iso: string): string {
  if (!iso) return ''
  const cached = _timeFormatCache.get(iso)
  if (cached) return cached
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  const result = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (_timeFormatCache.size > 500) _timeFormatCache.clear()
  _timeFormatCache.set(iso, result)
  return result
}

</script>

<style scoped>
/* 项目卡片（固定高度，配合虚拟滚动）
   高度消费父级 :style 注入的 --pr-card-h（CustomerProjectArea 的 DEFAULT_CARD_H 唯一字面量），本组件不硬编码 */
.cgl-project-card {
  display: flex;
  gap: 10px;
  width: 100%;
  height: var(--pr-card-h);
  margin-bottom: 10px;
  padding: 8px;
  box-sizing: border-box;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}

.cgl-project-card:hover {
  border-color: #ff9f4340;
  background: #ff9f4308;
}

.cgl-project-card.active {
  border-color: #ff9f43;
  background: #ff9f4310;
}

.cgl-card-left {
  /* flex-basis 必须为 0：auto 会让基准尺寸取自图片固有宽度，导致各卡缩略图宽度不一，
     并挤压右侧文字列使按钮换行。0 则各卡等分剩余空间，宽度一致。 */
  flex: 1 1 0;
  min-width: 0;
}

.cgl-card-thumb {
  position: relative;
  /* 宽度弹性铺满左侧区域（高度固定 240，不改变卡片高度）；右侧文字列固定宽度故不再有空白 */
  width: 100%;
  height: 240px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--color-surface, #f3f4f6);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* 缩略图描边：必须画在图片上层。图片 object-fit:cover 会铺满整格，
   容器自身的 inset box-shadow 会被图片整个盖住而不可见。 */
.cgl-card-thumb::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 5;
  border-radius: 8px;
  box-shadow: inset 0 0 0 1px var(--color-border, #e4e7ed);
  pointer-events: none;
}

/* 骨架屏：微光扫过动画，清晰图加载完成后淡出 */
.cgl-thumb-skeleton {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: linear-gradient(100deg, #f1f5f9 40%, #e2e8f0 50%, #f1f5f9 60%);
  background-size: 200% 100%;
  animation: cgl-shimmer 1.4s linear infinite;
  opacity: 1;
  transition: opacity 0.3s ease;
}

.cgl-card-thumb.is-loaded .cgl-thumb-skeleton {
  opacity: 0;
}

@keyframes cgl-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}

/* 模糊占位图（blur-up）：铺满 + CSS 模糊放大，清晰图加载后淡出 */
.cgl-thumb-blur {
  position: absolute;
  inset: 0;
  z-index: 2;
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: blur(10px);
  transform: scale(1.15);
  opacity: 1;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.cgl-card-thumb.is-loaded .cgl-thumb-blur {
  opacity: 0;
}

/* 清晰缩略图：默认透明，加载完成后淡入（避免占位闪烁）
   使用 cover 铺满整格（与下方模糊底图同款取景，清晰图淡入时无取景跳变）。 */
.cgl-thumb-img {
  position: relative;
  z-index: 3;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.cgl-card-thumb.is-loaded .cgl-thumb-img {
  opacity: 1;
}

/* 仅作用于占位图的 T 恤图标（直接子元素），避免污染已完成角标内的对勾图标 */
.cgl-card-thumb-placeholder > svg {
  font-size: 48px;
  color: var(--color-text-secondary);
  opacity: 0.5;
}

/* 已完成角标（叠加在缩略图右上角） */
.cgl-card-status-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 4;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(22, 163, 74, 0.92);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.6;
  pointer-events: none;
}

/* 已完成卡片：绿色边框 */
.cgl-project-card.is-completed {
  border-color: #22c55e40;
}
.cgl-project-card.is-completed.active {
  border-color: #16a34a;
}

.cgl-card-right {
  /* 固定为内容所需宽度（按钮行实测约 205px），不再 flex:1 撑满 → 消除右侧空白 */
  flex: 0 1 220px;
  min-width: 0;
}

.cgl-card-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 名称：卡片视觉锚点，放大加粗，扫读时最先被眼睛抓住 */
.cgl-card-name {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cgl-card-meta {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 13px;
  line-height: 1.5;
}

.cgl-card-meta-label {
  flex-shrink: 0;
  color: var(--color-text-secondary);
}

.cgl-card-meta-value {
  min-width: 0;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 时间：最弱层级，仅作参考 */
.cgl-card-time {
  font-size: 12px;
  color: var(--color-text-muted, #64748b);
}

/* 卡片操作按钮（编辑 / 完成） */
.cgl-card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.cgl-card-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  color: var(--color-text-primary);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.cgl-card-action:hover {
  border-color: #ff9f43;
  color: #ff9f43;
  background: #ff9f4308;
}

.cgl-card-action--done:hover {
  border-color: #16a34a;
  color: #16a34a;
  background: #16a34a0a;
}

.cgl-card-action--cancel:hover {
  border-color: #ef4444;
  color: #ef4444;
  background: #ef44440a;
}
</style>
