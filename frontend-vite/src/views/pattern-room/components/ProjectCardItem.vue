<template>
  <!--
    卡片语义重构（审查 A11Y-01/02/03）：
    原来根节点是 role="button" + tabindex="0"，内部又塞了「查看大图」和「编辑/完成/取消」
    四个按钮。ARIA 规定 role="button" 的子代全部 presentational —— 读屏器会把内部按钮
    压平，三个操作对读屏器用户等于不存在（axe: nested-interactive）。
    现在改为三个平级可聚焦元素：看图按钮、选中按钮（伪元素拉伸铺满卡片）、操作按钮。
  -->
  <div :class="['cgl-project-card', { active: selected, 'is-completed': proj.status === 'completed' }]">
    <div class="cgl-card-left">
      <!-- 看图：真实 button，Tab 可达，Enter/Space 均可激活（原 div role=button 无 tabindex，键盘够不到） -->
      <button
        v-if="proj.product_image_url && !imgFailed"
        type="button"
        class="cgl-card-thumb"
        :class="{ 'is-loaded': thumbLoaded }"
        :aria-label="`查看「${proj.product_name}」产品图片大图`"
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
      </button>
      <div v-else class="cgl-card-thumb cgl-card-thumb-placeholder">
        <FontAwesomeIcon icon="shirt" aria-hidden="true" />
        <span v-if="proj.status === 'completed'" class="cgl-card-status-badge">
          <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 已完成
        </span>
      </div>
    </div>
    <div class="cgl-card-right">
      <div class="cgl-card-info">
        <!--
          选中：真按钮，用 aria-current 表达「当前项」（原来只有 CSS 类 active）。
          ::after 绝对定位铺满整张卡片，保留「点卡片任意空白处即选中」的手感；
          看图按钮与操作按钮已抬高 z-index，点击仍落到各自元素上。
        -->
        <button
          type="button"
          class="cgl-card-select"
          :aria-current="selected ? 'true' : undefined"
          @click="emit('select', proj.id)"
        >
          {{ proj.product_name }}<span class="sr-only">，查看项目详情</span>
        </button>
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
 *
 * 交互契约（2026-10-22 无障碍重构，审查 A11Y-01/02/03）：
 * 卡片不再是 role="button" 的整体热区 —— 那样会把内部按钮压平（nested-interactive）。
 * 现在有三个平级可聚焦元素：缩略图按钮（看大图）、名称按钮（选中，伪元素拉伸铺满卡片）、
 * 操作按钮（编辑/完成/取消）。选中不再由父级 attrs 透传 @click / @keyup.enter 驱动，
 * 改为本组件 emit('select', id)。
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
  /** 选中该项目（原由父级透传 @click / @keyup.enter，现收敛为本组件内的真按钮） */
  select: [id: number]
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

<style scoped src="./ProjectCardItem.css"></style>
