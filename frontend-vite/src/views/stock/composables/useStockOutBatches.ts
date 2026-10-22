/**
 * StockOutTab 的成品批次列表与批次级闸门（2026-10-19 OCR-R5 从 StockOutTab.vue 外移）。
 *
 * 外移动机：主文件已贴 400 行门禁上限（399/400），批次逻辑（列表拉取/三态哨兵/
 * 失败保留/批次闸门）自成一块，整体搬迁为主文件腾出修改余量。行为与外移前逐分支等价，
 * 除修复：
 *  1) OCR-R5 M:155 批次失败保留按产品域约束——切产品后拉取失败不再保留上一 SKU 的列表；
 *  2) OCR-R5 L:229 批次闸门入参改判别联合——删除 `missingHint ?? '请清除批次后重试'` 死代码；
 *  3) OCR-R6 M1 页面级回落加产品域守卫——列表不属于当前产品时不得拿来做批次校验。
 *
 * 导出面（OCR-R6 L4）：仅 `useStockOutBatches` 公开；三态哨兵函数与判别联合类型
 * 均为模块内部实现细节，无外部消费者，不导出。
 */
import { ref } from 'vue'
import type { Ref } from 'vue'
import { finishedStockApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { BatchAvailable, StagedStockout } from '@/types'

/** 三态哨兵结果：null=被在途请求顶掉（丢弃过期响应）；'failed'=请求失败；数组=成功（含空列表） */
type BatchFetchResult = BatchAvailable[] | null | 'failed'

/** 按产品拉批次；seq 由调用方持有（页面级/编辑级各自独立的序号池，2026-10-19 OCR-2 L3） */
async function fetchBatchesForProduct(
  productId: string | number,
  seq: { v: number },
): Promise<BatchFetchResult> {
  const my = ++seq.v
  try {
    const res = await finishedStockApi.batches(Number(productId))
    return my !== seq.v ? null : (res.data ?? [])
  } catch {
    return my !== seq.v ? null : 'failed'
  }
}

/** 批次闸门公共入参。OCR-R11 L-h：无 customer 字段——批次可用性按 (product, batch)
 *  聚合（M-D 口径），闸门不读客户作用域，保留「死但必填」字段只会误导调用方。 */
interface BatchGateBase {
  productId: string
  batchNo: string
  quantity: number
  /** 编辑路径排除被编辑项自身（已计入 staged，不排除会把可用量算小） */
  excludeId?: number
}

/** 编辑路径入参：batches 为权威拉取结果——数组=权威列表（找不到=批次已不存在，拦截并提示）；
 *  null=数据不可得（放行后端兜底）。missingHint 必填：编辑弹窗无批次控件，提示语与
 *  新增路径不同（OCR-R5 L:229 判别联合，删除死代码 fallback）。 */
interface BatchGateAuthoritative extends BatchGateBase {
  batches: BatchAvailable[] | null
  missingHint: string
}

/** 直调/测试面入参（R22-L4 口径）：R21-M3 起生产调用点（addStaged/saveEditStaged）
 *  均显式传 batches，本形态只剩直调与测试使用；不传 batches 时回落页面级列表（纵深防御）。 */
interface BatchGatePageLevel extends BatchGateBase {
  batches?: undefined
}

/** 批次闸门入参（判别联合）：编辑路径必须「权威结果 + 缺失提示」成对出现 */
type BatchGateInput = BatchGateAuthoritative | BatchGatePageLevel

export function useStockOutBatches(
  staged: Ref<StagedStockout[]>,
  form: { productId: string; batchNo: string },
) {
  const batchOptions = ref<BatchAvailable[]>([])
  /** 页面级/编辑级各自独立的序号池：编辑保存的批次请求不顶掉页面级在途请求（OCR-2 L3） */
  const pageBatchSeq = { v: 0 }
  const editBatchSeq = { v: 0 }
  /** 当前 batchOptions 所属产品（OCR-R5 M:155）：失败保留只在「请求产品==列表产品」时生效 */
  let loadedBatchProductId: string | null = null

  /** 清空页面级批次下拉时同步推进序号，让在途请求失效（否则迟到响应把旧产品批次写回，OCR-3 Low）。
   *  batchNo 一并内置重置（OCR-R7 残余 Low）：「列表为空 ⇒ batchNo 也为空」是
   *  checkBatchAvailability 页面级分支依赖的不变式——由本函数统一保证，而非依赖
   *  每个调用方记得随后补 form.batchNo = ''（漏一处就重新引入过期批次提交隐患）。 */
  function clearPageBatches() {
    pageBatchSeq.v++
    batchOptions.value = []
    loadedBatchProductId = null
    form.batchNo = ''
  }

  async function fetchBatchOptions() {
    if (!form.productId) {
      clearPageBatches()
      return
    }
    // 快照本次请求的产品号并全程使用（R7-L3）：await 后 form.productId 可能已变，
    // 归属判断/赋值若重读 form 会把「列表所属产品」记错——「列表非空 ⇒ 标记=列表
    // 所属产品」的不变式不得依赖「productId 变更必伴随新的 fetchBatchOptions」这一调用约定。
    const requestedProductId = form.productId
    const batches = await fetchBatchesForProduct(requestedProductId, pageBatchSeq)
    if (batches === null) return // 已有更新的请求在途，丢弃过期响应
    if (batches === 'failed') {
      if (loadedBatchProductId === requestedProductId) {
        // 瞬时失败 ≠ 权威空列表（OCR-4 M2）：清掉会连带清已选批次并隐藏下拉，
        // 用户以「不指定批次」盲提交——同产品时保留旧值。
        // 注意：此分支要求标记非 null——「空列表成功」不记标记（见下），列表为空时
        // 走下面的失败清理分支，不会谎称「已保留」（R7-L7）。
        showToast('批次列表拉取失败，已保留上次结果；若刚入库请稍后刷新', 'warning')
        return
      }
      // OCR-R5 M:155：切产品后拉取失败——此时 batchOptions 装的是上一 SKU 的列表，
      // 用户会选到错产品的批次，add 路径闸门还用错产品的数量校验通过，直到后端
      // 提交才被拒（「部分出货成功」）。失败也不保留：清空（batchNo 由内置重置）。
      clearPageBatches()
      showToast('批次列表拉取失败，请稍后重试', 'warning')
      return
    }
    batchOptions.value = batches
    // 权威空列表不记产品标记（R7-L7）：「列表为空 ⇒ 标记必为 null」是守卫与失败
    // 保留分支共同依赖的不变式。若把空列表也记为当前产品，随后同产品重拉失败会
    // 弹「已保留上次结果」——但下拉本就是空的，什么都没保留。
    loadedBatchProductId = batches.length > 0 ? requestedProductId : null
    // 当前选中批次若不在新列表里则清空，避免提交一个不存在/不属于该产品的批次（仅成功响应才清）
    if (form.batchNo && !batchOptions.value.some((b) => b.batch_no === form.batchNo)) {
      form.batchNo = ''
    }
  }

  /** 编辑路径的批次拉取（独立序号池，OCR-2 L3）：主文件不再持有 editBatchSeq。
   *  OCR-R10 L-d：'failed' 与 null 在编辑路径语义相同（放行后端兜底），在这里收敛，
   *  私有三态哨兵不再泄漏进公共签名——调用方无须（也不会忘了）做归一化，
   *  否则 'failed' 字符串会跳过闸门的 undefined/null 守卫后在 .find 炸掉。 */
  async function fetchEditBatches(productId: string | number): Promise<BatchAvailable[] | null> {
    const res = await fetchBatchesForProduct(productId, editBatchSeq)
    return res === 'failed' ? null : res
  }

  /** 批次可用量校验：「已暂存同批次量 + 本次数量」≤ 批次可用（excludeId 排除被编辑项）。
   *  聚合按 (product, batch) 全局累计（OCR-R10 M-D）：后端 get_batch_available 不接收
   *  customer——批次可用是与客户无关的事实，批量提交逐行 flush 时后端同样按
   *  (product, batch) 拒超额行。若按同客户过滤，客户A/客户B 各自暂存同批次都能过闸，
   *  合计超可用直到提交才被后端拒（正是闸门要防的「部分出货成功」）。 */
  function checkBatchQty(batch: BatchAvailable, opts: BatchGateBase): boolean {
    const stagedSameBatch = staged.value
      .filter((s) => s.product_id === opts.productId
        && (s.batch_no || '') === opts.batchNo && s.id !== opts.excludeId)
      .reduce((sum, s) => sum + (s.quantity || 0), 0)
    if (stagedSameBatch + opts.quantity > batch.available_quantity) {
      showToast(`批次「${opts.batchNo}」可用不足！可用: ${batch.available_quantity}，已暂存: ${stagedSameBatch}`, 'error')
      return false
    }
    return true
  }

  /** R34-#12（2026-10-20）：两 gate 分支共用的「查找 → 缺失回调 → 数量校验」形状——
   *  `list.find(batch_no)` 与 checkBatchQty 只此一处，缺失语义（放行/拦截与提示
   *  文案）由 onMissing 回调各自保留：权威分支 missingHint、页面级「空列表 ⇒ 放行」。 */
  const gateAgainstList = (
    list: BatchAvailable[],
    opts: BatchGateBase,
    onMissing: () => boolean,
  ): boolean => {
    const batch = list.find((b) => b.batch_no === opts.batchNo)
    if (!batch) return onMissing()
    return checkBatchQty(batch, opts)
  }

  /** 批次级闸门：「已暂存同批次量 + 本次数量」≤ 批次可用（否则提交被后端拒=「部分出货成功」） */
  function checkBatchAvailability(opts: BatchGateInput): boolean {
    if (!opts.batchNo) return true
    if (opts.batches === undefined) {
      // 直调/测试面 + 纵深防御（R22-L4）：R21-M3 起生产调用点（addStaged/
      // saveEditStaged）均显式传 batches，本分支服务直调与测试。列表只有确实
      // 属于 opts.productId 时才是权威依据（OCR-R6 M1）：切产品后新列表尚未返回，
      // 列表装的是上一 SKU 的批次，拿来校验=用别的产品做 allow/deny（与编辑路径
      // OCR-3 M2 禁止的降级同罪）。
      if (batchOptions.value.length > 0 && loadedBatchProductId !== opts.productId) {
        showToast('批次列表尚未加载完成，请稍后再添加', 'warning')
        return false
      }
      // 放行严格限定「列表为空」（R22-L4）：空=未加载（正常 UI 下拉仅在列表非空时
      // 渲染、清列表路径都同步清 batchNo），保持旧语义放行后端兜底；域匹配的非空
      // 列表仍缺该批次=批次已删除——放行与权威分支「已不存在 → 拦截」口径不一致，
      // 拦截并对齐提示口径（hint 同 addStaged 调用处「请清除批次后重试」）。
      return gateAgainstList(batchOptions.value, opts, () => {
        if (batchOptions.value.length === 0) return true // 页面级列表未加载：放行，后端兜底
        showToast(`批次「${opts.batchNo}」已不存在（入库记录可能已删除），请清除批次后重试`, 'warning')
        return false
      })
    }
    // 编辑路径。显式 null=数据不可得：放行后端兜底（OCR-3 M2）。不得降级页面级列表——
    // 那装的是 form.productId 的批次，拿来校验 item.product_id 等于用别的产品做 allow/deny。
    if (opts.batches === null) return true
    // 权威列表找不到=批次已不存在（如入库被删）：拦截（OCR-2 M2）。
    // missingHint 由判别联合保证必填（编辑弹窗无批次控件，提示删除重加，OCR-3 Low）。
    return gateAgainstList(opts.batches, opts, () => {
      showToast(`批次「${opts.batchNo}」已不存在（入库记录可能已删除），${opts.missingHint}`, 'warning')
      return false
    })
  }

  return {
    batchOptions,
    fetchBatchOptions,
    clearPageBatches,
    fetchEditBatches,
    checkBatchAvailability,
  }
}