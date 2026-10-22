<template>
  <div
    class="ui-loading-status"
    :class="{ 'is-idle': !loading }"
    role="status"
    aria-live="polite"
    aria-atomic="true"
  >
    <template v-if="loading">
      <span class="ui-loading-status__mark" :class="`ui-loading-status__mark--${size}`" aria-hidden="true" />
      <span class="ui-loading-status__text">
        <slot>{{ label }}</slot>
      </span>
    </template>
    <template v-else-if="doneLabel">{{ doneLabel }}</template>
  </div>
</template>

<script setup lang="ts">
/**
 * 加载态播报范式（唯一入口）
 *
 * /pattern-room 审查 A11Y-13：列表与表体的「加载中…」只是普通 div，读屏器全程静默。
 * WCAG 4.1.3 要求状态消息可被播报；实现要点三条，缺一不可：
 *   1. 容器必须**常驻 DOM**（不能 v-if），首次渲染就得在无障碍树里，
 *      否则「先挂载再填字」部分读屏器不会播报；
 *   2. role="status" 即隐含 aria-live="polite"，仍显式写出，兼容旧读屏器；
 *   3. **不要**在 live region 自身上加 aria-busy —— 部分实现会因此把播报推迟到
 *      busy 变 false，等于把「加载中」这句话吞掉（最容易被顺手"优化"错的地方）。
 *
 * 空闲时用 .is-idle 视觉塌陷（仍在树内），避免占位留白。
 *
 * 注：模板首行不能放 HTML 注释 —— 那会让组件变成多根节点（fragment），
 * 导致父级传入的 class 透传失效。
 */
withDefaults(
  defineProps<{
    /** 是否处于加载中；由父级状态驱动，组件自身不持有状态 */
    loading: boolean
    /** 加载中文案（也可用默认插槽覆盖，便于带变量文案） */
    label?: string
    /** 加载结束后的播报文案。默认 undefined = 不播报，避免「完成」提示噪音 */
    doneLabel?: string
    /** 指示器尺寸 */
    size?: 'sm' | 'md'
  }>(),
  {
    label: '加载中…',
    doneLabel: undefined,
    size: 'sm',
  },
)
</script>

<style scoped>
.ui-loading-status {
  display: flex;
  /* 作为 flex 列布局的子项时不被压缩（父级常是 overflow:hidden 的滚动容器） */
  flex: none;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-secondary, #475569);
  font-size: 13px;
}

/*
 * 空闲态：留在无障碍树里但视觉塌陷（等价 sr-only）。
 * 用剪裁而非 display:none —— display:none 会把节点移出无障碍树，
 * 下一轮「加载中」就变成「新节点出现」，播报可靠性下降。
 * padding/margin/border 一并归零，防止上层传入的定位类撑出空白。
 */
.ui-loading-status.is-idle {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  border: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.ui-loading-status__mark {
  display: inline-block;
  border: 2px solid var(--color-border, #e4e7ed);
  border-top-color: var(--color-primary-500, #5b8def);
  border-radius: 50%;
  animation: ui-loading-spin 0.8s linear infinite;
}

.ui-loading-status__mark--sm {
  width: 14px;
  height: 14px;
}

.ui-loading-status__mark--md {
  width: 20px;
  height: 20px;
}

@keyframes ui-loading-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 全局 prefers-reduced-motion 已把动画压到 0.01ms，此处补一条显式停转，
   避免「转圈」变成「抖动」误导视觉用户 */
@media (prefers-reduced-motion: reduce) {
  .ui-loading-status__mark {
    animation: none;
  }
}
</style>
