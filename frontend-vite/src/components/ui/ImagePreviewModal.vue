<template>
  <!--
    产品图片「原图」预览（共享组件，2026-10-17 从 views/pattern-room/components/ 抽到 ui/，
    供 pattern-room 与 finished-stock 复用）。基于共享 UiDialog 复用 Esc 关闭 /
    焦点陷阱 / 滚动锁。行为：Esc 关闭、✕ 关闭；点遮罩空白不关闭（UiDialog
    closeOnOverlayClick 默认 false，即全站约定 2026-10-14）。
    对外契约：image prop + update:image 事件；image↔open 的适配只在本组件内部完成。
    传**原图** URL（相对路径，本组件内部走 resolveStaticUrl）。
  -->
  <UiDialog
    :open="!!image"
    max-width-class="max-w-[800px]"
    overlay-z-class="z-[var(--z-page-modal)]"
    content-z-class="z-[var(--z-page-modal)] pim-card"
    :body-padded="false"
    @update:open="onOpenChange"
  >
    <template #title>
      <span class="pim-title">产品图片</span>
    </template>
    <div class="pim-body">
      <img v-if="image" :src="resolveStaticUrl(image)" class="pim-img-view" alt="产品图片" />
    </div>
  </UiDialog>
</template>

<script setup lang="ts">
import { resolveStaticUrl } from '@/api/request'
import UiDialog from './UiDialog.vue'

defineProps<{ image: string | null }>()
const emit = defineEmits<{ 'update:image': [v: string | null] }>()

/** UiDialog 的 open = 「image 非空」；关闭（Esc / ✕ / 取消）时把 image 置空，维持对外契约 */
function onOpenChange(open: boolean) {
  if (!open) emit('update:image', null)
}
</script>

<style>
/* pim- 前缀：内容经 DialogPortal 渲染到 body，需全局样式（非 scoped）。
   仅保留迁移后仍生效的视觉声明；遮罩 50% 黑、焦点陷阱、滚动锁由 UiDialog 提供。 */
.pim-card {
  /* UiDialog 默认 rounded-2xl(16px)；此处维持迁移前的 18px 圆角 */
  border-radius: 18px !important;
}
.pim-title { font-size: 14px; font-weight: 700; color: var(--color-text); }
.pim-body {
  display: flex; align-items: center; justify-content: center;
  min-height: 50vh; padding: 20px; background: var(--color-surface);
  border-radius: 12px;
}
.pim-img-view {
  max-width: 100%; max-height: 80vh; object-fit: contain;
  border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}
</style>
