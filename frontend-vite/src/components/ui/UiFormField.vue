<template>
  <div class="ui-form-field">
    <label v-if="label" class="ui-form-field__label" :for="controlId">
      {{ label }}
      <span v-if="required" class="ui-form-field__required" aria-hidden="true">*</span>
    </label>

    <slot v-bind="fieldProps" />

    <p v-if="hint" :id="hintId" class="ui-form-field__hint">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="ui-form-field__error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'

/**
 * 表单字段标签范式（唯一入口）
 *
 * /pattern-room 审查 A11Y-04/05/18：全模块 6 个可见 <label> 无一绑定 for，
 * 读屏器只能退化成读 placeholder。本组件存在的意义是让「可见标签 + 程序化关联」
 * 只从一条路径产出，避免各页面手写 id 拼装。
 * 用法见 docs/designs/2026-10-22-a11y-shared-patterns-design.md。
 *
 * 注 1：模板首行不能放 HTML 注释 —— 会变成多根节点，父级 class 透传失效。
 * 注 2：useId() 的唯一性范围是**单个 Vue app**。本仓只挂载一个 #app，故够用；
 *       若将来同页并存多个 app（微前端/嵌入式组件），需各自设置
 *       app.config.idPrefix，否则 id 会重复、label 关联会串台。
 */

/** 透传给控件（input / textarea / UiSelect …）的属性集合 */
export interface UiFormFieldControlProps {
  id: string
  required?: true
  'aria-required'?: 'true'
  'aria-invalid'?: 'true'
  'aria-describedby'?: string
}

const props = withDefaults(
  defineProps<{
    /** 可见标签文案。省略则不渲染 <label>（如纯视觉占位场景，需自行给控件 aria-label） */
    label?: string
    /** 辅助说明，渲染在控件下方并计入 aria-describedby */
    hint?: string
    /** 校验错误，渲染在控件下方、role="alert"，并置 aria-invalid */
    error?: string
    /** 必填：渲染 * 与 required / aria-required */
    required?: boolean
    /** 指定控件 id。省略时用 useId() 生成，同页多字段不会冲突 */
    id?: string
  }>(),
  {
    label: undefined,
    hint: undefined,
    error: undefined,
    required: false,
    id: undefined,
  },
)

defineSlots<{
  default: (props: UiFormFieldControlProps) => unknown
}>()

/**
 * Vue 3.5 的 useId()：同一组件实例稳定、跨实例唯一，
 * 避免手写 `id="product-name"` 在弹窗叠加/列表复用时撞车。
 */
const uid = useId()
const controlId = computed(() => props.id ?? `field-${uid}`)
const hintId = computed(() => `${controlId.value}-hint`)
const errorId = computed(() => `${controlId.value}-error`)

/**
 * 说明文本按 hint → error 顺序拼接。
 * 空字符串视为「未提供」：调用方常传 `error || ''`，不能让它产出 "xxx-error"
 * 这种指向不存在节点的 id（读屏器会念出空描述）。
 */
const describedBy = computed(() => {
  const ids: string[] = []
  if (props.hint) ids.push(hintId.value)
  if (props.error) ids.push(errorId.value)
  return ids.length > 0 ? ids.join(' ') : undefined
})

const fieldProps = computed<UiFormFieldControlProps>(() => ({
  id: controlId.value,
  // 原生 required 负责浏览器校验，aria-required 负责读屏播报；
  // 两者都只在必填时出现，非必填保持缺省（而非 false），语义更干净。
  required: props.required ? true : undefined,
  'aria-required': props.required ? 'true' : undefined,
  'aria-invalid': props.error ? 'true' : undefined,
  'aria-describedby': describedBy.value,
}))
</script>

<style scoped>
.ui-form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ui-form-field__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary, #1a1a2e);
}

.ui-form-field__required {
  color: var(--color-danger-500, #ef4444);
}

.ui-form-field__hint {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--color-text-muted, #64748b);
}

/* 错误文案用 danger-700 而非 danger-500：#ea5455 对白底仅 3.56:1，
   11px 小字需 4.5:1（WCAG 1.4.3）；danger-700 #b33335 实测 6.1:1 */
.ui-form-field__error {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  font-weight: 500;
  color: var(--color-danger-700, #b33335);
}
</style>
