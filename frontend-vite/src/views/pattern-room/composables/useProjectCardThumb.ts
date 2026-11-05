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
 *
 * ⚠️ 复位条件必须是「渲染用的 src 真的变了」，不能是「proj 对象被替换了」：
 * 签名 URL 的 st 按小时对齐（services/signed_urls.py），同一小时内重新签发的 URL
 * 逐字节相同。此时 <img> 的 src 未变，浏览器不会再派发 load，一旦误复位
 * thumbLoaded，.is-loaded 被摘掉、模糊占位图重新显形且永远不会淡出——表现为
 * 「点完成 / 列表静默刷新后图片变模糊」（2026-11-05 线上问题）。
 * 因此 watch 源直接取模板里那个 src 表达式，而不是 [url, thumbUrl] 数组字面量
 * （数组字面量每次求值都是新引用，hasChanged 恒为 true，等于「任何刷新都复位」）。
 */
import { ref, toValue, watch, type MaybeRefOrGetter } from 'vue'

interface ThumbSource {
  product_image_url?: string | null
  product_image_thumbnail_url?: string | null
}

/** 模板 <img> 实际使用的地址：缩略图优先，历史数据无缩略图时回退原图。 */
function resolveThumbSrc(p: ThumbSource): string {
  return p.product_image_thumbnail_url || p.product_image_url || ''
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
    () => resolveThumbSrc(toValue(proj)),
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
