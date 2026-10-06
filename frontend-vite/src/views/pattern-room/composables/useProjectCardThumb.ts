/**
 * 打样项目卡片缩略图状态机（ProjectCardItem 专用）
 *
 * 抽出原因：卡片接近巨型组件门禁上限（400 行），把「骨架屏 → 模糊图 → 清晰图 →
 * 回退原图 → 占位」的状态与错误回退链路独立出来，模板只消费状态。
 *
 * URL 失效重载：SWR 静默刷新 / 缓存恢复会整体替换 proj 对象，签名 URL 随之更新
 * （旧链接可能已过期 410 而加载失败）。URL 变化时必须复位加载/失败状态，否则
 * imgFailed 置真后卡片会永久卡在 T 恤占位——占位分支下 <img> 已不在 DOM，
 * 新 URL 根本没机会加载。
 */
import { ref, toValue, watch, type MaybeRefOrGetter } from 'vue'

interface ThumbSource {
  product_image_url?: string | null
  product_image_thumbnail_url?: string | null
}

export function useProjectCardThumb(proj: MaybeRefOrGetter<ThumbSource>) {
  /** 缩略图加载完成（骨架屏/模糊底图据此淡出） */
  const thumbLoaded = ref(false)
  /** 清晰缩略图元素引用（URL 变化时需清掉 DOM 上残留的回退标记） */
  const thumbImg = ref<HTMLImageElement | null>(null)
  /**
   * 最终加载失败标记。历史数据存在 storage_key 指向的文件已丢失的情况
   * （URL 仍非空但服务端 404），缩略图与原图均失败后置真，切换到 T 恤占位分支，
   * 否则骨架屏动画会永久闪烁（thumbLoaded 恒为 false）。
   */
  const imgFailed = ref(false)

  watch(
    () => {
      const p = toValue(proj)
      return [p.product_image_url, p.product_image_thumbnail_url] as const
    },
    () => {
      imgFailed.value = false
      thumbLoaded.value = false
      // 复用的 <img> 元素上残留的 data-fallback 标记会让新缩略图失败时跳过原图回退
      if (thumbImg.value) delete thumbImg.value.dataset.fallback
    },
  )

  /**
   * 缩略图加载失败时回退到原图。
   * - 历史数据（缩略图未生成）会出现 404，需要回退
   * - 设置 data-fallback 标记位防止反复重试
   * - 原图也失败（文件已丢失）时置 imgFailed，切换到占位分支停止骨架屏
   */
  function onThumbError(e: Event) {
    const img = e.target as HTMLImageElement
    const url = toValue(proj).product_image_url
    if (img.dataset.fallback || !url) {
      imgFailed.value = true
      return
    }
    img.dataset.fallback = '1'
    img.src = url
  }

  /** 模糊占位图加载失败：仅隐藏自身，不影响清晰图的加载与回退链路 */
  function onBlurError(e: Event) {
    ;(e.target as HTMLImageElement).style.display = 'none'
  }

  return { thumbLoaded, thumbImg, imgFailed, onThumbError, onBlurError }
}
