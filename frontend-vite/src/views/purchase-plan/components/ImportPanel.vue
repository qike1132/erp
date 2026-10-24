<template>
  <div>
    <div
      class="csd-upload-area"
      :class="{ 'csd-upload-hover': dragOver }"
      @click="fileInp?.click()"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="onDrop"
    >
      <div class="csd-upload-label">
        <FontAwesomeIcon icon="file-excel" aria-hidden="true" />
        <span v-if="file" class="csd-file-selected"><FontAwesomeIcon icon="check-circle" aria-hidden="true" />{{ file.name }}</span>
        <span v-else>拖拽文件到此处或点击选择 · 仅支持 .xlsx</span>
      </div>
      <div class="csd-upload-buttons">
        <button class="csd-inline-btn" aria-label="模板" @click.stop="dlTpl">模板</button>
        <button class="csd-inline-btn csd-inline-btn-primary" :disabled="!file || uploading" aria-label="导入" @click.stop="doUpload">
          <FontAwesomeIcon v-if="!uploading" icon="upload" aria-hidden="true" />
          <FontAwesomeIcon v-else icon="spinner" spin /> 导入
        </button>
        <button v-if="file" class="csd-inline-btn csd-inline-btn-danger" aria-label="删除" @click.stop="clearFile">
          <FontAwesomeIcon icon="trash" aria-hidden="true" />
        </button>
      </div>
      <input ref="fileInp" type="file" accept=".xlsx" hidden aria-label="上传文件" @change="onFile" />
    </div>
    <div v-if="upMsg" class="csd-upload-message" :class="{ 'csd-upload-success': upOk, 'csd-upload-error': !upOk }">
      <FontAwesomeIcon :icon="upOk ? 'check-circle' : 'exclamation-circle'" aria-hidden="true" />
      {{ upMsg }}
    </div>

    <!-- 导入结果：成功/失败条数与归属月份（不自动消失，便于查看与导出） -->
    <div v-if="outcome" class="csd-result">
      <div class="csd-result-stats">
        <span class="csd-stat">共 {{ outcome.totalRows }} 行</span>
        <span class="csd-stat csd-stat-ok">成功 {{ outcome.successCount }} 条</span>
        <span v-if="outcome.failCount" class="csd-stat csd-stat-bad">失败 {{ outcome.failCount }} 条</span>
        <span class="csd-stat">计划单 {{ outcome.planCount }} 个</span>
        <span v-if="outcome.month" class="csd-stat">数据月份 {{ outcome.month }}</span>
      </div>
    </div>

    <!-- 失败明细：可查看 + 可导出 CSV -->
    <div v-if="allErrors.length" class="csd-errors">
      <div class="csd-errors-head">
        <span class="csd-errors-title">
          <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />
          失败明细（{{ allErrors.length }} 条）
        </span>
        <button class="csd-inline-btn" aria-label="导出错误清单" @click.stop="downloadErrors">
          <FontAwesomeIcon icon="download" aria-hidden="true" /> 导出错误清单
        </button>
      </div>
      <div class="csd-errors-body">
        <div v-for="(e, i) in shownErrors" :key="i" class="csd-error-row">
          <span class="csd-error-seq">{{ e.seq || '—' }}</span>
          <span class="csd-error-msg">{{ e.message }}</span>
        </div>
        <div v-if="allErrors.length > shownErrors.length" class="csd-error-more">
          仅显示前 {{ shownErrors.length }} 条，完整清单请导出查看
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 出货计划「批量导入」面板（从 CreateShipmentPlanDialog.vue 抽出，模板与上传逻辑原样搬移）
import { computed, ref, watch } from 'vue'
import { planApi, type StagingErrorItem } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { downloadCsv, buildCsvRow } from '@/utils/csv'

const props = defineProps<{ open: boolean }>()

const emit = defineEmits<{
  /** 导入完成（含部分失败）。参数为数据所属月份 YYYY-MM，供列表跳转 */
  imported: [month?: string]
}>()

// 批量导入相关
const file = ref<File | null>(null)
const fileInp = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const uploading = ref(false)
const upMsg = ref('')
const upOk = ref(true)
let _ut: ReturnType<typeof setTimeout> | null = null

// 导入结果：总行数、成功/失败条数、生成计划单数、数据月份
const outcome = ref<{ totalRows: number; successCount: number; failCount: number; planCount: number; month: string } | null>(null)
// 解析阶段失败（未进入暂存区，仅有原始文案）
const parseErrors = ref<string[]>([])
// 校验阶段失败（暂存区明细，含行序号与原始字段）
const checkErrors = ref<StagingErrorItem[]>([])

// 两类失败合并展示：解析失败在前（已含「第N行」），校验失败在后
const allErrors = computed<StagingErrorItem[]>(() => [
  ...parseErrors.value.map((message) => ({ seq: 0, customer_name: '', product_name: '', barcode: '', quantity: 0, plan_date: '', message })),
  ...checkErrors.value,
])
// 明细列表最多渲染 50 条，避免大文件导入时 DOM 过载；完整清单走 CSV 导出
const shownErrors = computed(() => allErrors.value.slice(0, 50))

// 批量导入功能
function onDrop(ev: DragEvent) { dragOver.value = false; const fs = ev.dataTransfer?.files; if (fs?.length && fs[0]) vfile(fs[0]) }
function onFile(ev: Event) { const t2 = ev.target as HTMLInputElement; if (t2.files?.length && t2.files[0]) vfile(t2.files[0]); t2.value = '' }
// 后端仅接受 .xlsx（openpyxl 读取，.xls/.csv 会被 400 拒绝），此处保持一致避免误导
function vfile(f: File) { clearUpMsg(); const ext = '.' + (f.name.split('.').pop()?.toLowerCase() ?? ''); if (ext !== '.xlsx') { showUpMsg('仅支持 .xlsx 格式文件', false); return; } if (f.size > 10 * 1024 * 1024) { showUpMsg('文件超过 10MB', false); return; } if (f.size === 0) { showUpMsg('文件为空', false); return; } file.value = f }
function clearFile() { file.value = null; clearUpMsg() }
function showUpMsg(msg: string, ok: boolean) { upMsg.value = msg; upOk.value = ok; if (_ut) clearTimeout(_ut); _ut = setTimeout(() => upMsg.value = '', 5000) }
function clearUpMsg() { upMsg.value = ''; if (_ut) clearTimeout(_ut) }
async function dlTpl() { try { await planApi.downloadTemplate() } catch { showToast('下载失败', 'error') } }

/** 清空暂存区：失败不影响主流程，避免残留数据混入下次导入 */
async function safeClearStaging() {
  try {
    await planApi.stagingClear()
  } catch {
    // 暂存区清理失败不阻塞结果反馈，下次导入会按 batch_id 精确隔离
  }
}

/**
 * 批量导入。
 *
 * 后端为「暂存 → 校验 → 确认」三段式：upload 仅解析落暂存区，
 * 必须再经 staging/validate + staging/confirm 才会写入正式计划表。
 * 此前只调用了 upload，数据停留在暂存区，故列表始终查不到。
 */
async function doUpload() {
  const f = file.value
  if (!f) return
  uploading.value = true
  clearUpMsg()
  outcome.value = null
  parseErrors.value = []
  checkErrors.value = []
  try {
    // 0) 先清空暂存区：后端 validate 按用户维度全量校验（不区分批次），
    //    残留的上次导入数据会混入本次错误清单，造成难以理解的报错
    await safeClearStaging()

    const fd = new FormData()
    fd.append('file', f)

    // 1) 解析 Excel 并写入暂存区（此时尚未进入正式计划表）
    const up = await planApi.upload(fd)
    parseErrors.value = up?.errors ?? []
    if (!up?.total) {
      await safeClearStaging()
      showUpMsg(parseErrors.value[0] ?? '未能从文件中解析到数据行，请按模板填写后重试', false)
      return
    }

    // 2) 校验客户/产品是否存在、是否还有订单余量（订单已发完/不存在则不可添加）
    const val = await planApi.stagingValidate()
    checkErrors.value = val?.errors ?? []
    const failCount = parseErrors.value.length + (val?.error_count ?? checkErrors.value.length)

    // 3) 全部未通过：不写正式表，保留失败明细供查看与导出
    if (!val?.valid_count) {
      await safeClearStaging()
      showUpMsg(`导入失败：共 ${up.total + parseErrors.value.length} 行全部未通过校验，请查看下方失败明细`, false)
      return
    }

    // 4) 确认写入正式表（带 batch_id，仅确认本次批次，避免与暂存区历史残留混淆）
    const cf = await planApi.stagingConfirm({ batch_id: up.batch_id })
    outcome.value = {
      // 总行数含解析失败行（未进暂存区），保证「成功 + 失败」可与总数对账
      totalRows: up.total + parseErrors.value.length,
      successCount: cf?.created_count ?? val.valid_count,
      failCount,
      planCount: cf?.created_plans?.length ?? 0,
      month: up.detected_month ?? '',
    }
    clearFile()
    // 回传数据月份，列表据此跳月后再刷新，否则新数据可能因月度筛选不可见
    if (up.detected_month) {
      emit('imported', up.detected_month)
    } else {
      emit('imported')
    }
    showUpMsg(
      failCount
        ? `导入完成：成功 ${outcome.value.successCount} 条，失败 ${failCount} 条（明细见下方）`
        : `导入成功，共 ${outcome.value.successCount} 条`,
      true,
    )
  } catch (e: unknown) {
    await safeClearStaging()
    showUpMsg(getErrorMessage(e, '导入失败'), false)
  } finally {
    uploading.value = false
  }
}

/** 导出失败明细为 CSV，便于离线修正后重新导入 */
function downloadErrors() {
  const list = allErrors.value
  if (!list.length) return
  const rows = [buildCsvRow(['序号', '客户名称', '产品名称', '69码', '数量', '计划日期', '失败原因'])]
  for (const e of list) {
    rows.push(buildCsvRow([e.seq || '', e.customer_name, e.product_name, e.barcode, e.quantity || '', e.plan_date, e.message]))
  }
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}`
  downloadCsv(rows, `出货计划导入失败清单_${stamp}.csv`)
  showToast('错误清单已导出', 'success')
}

// 对话框打开时重置全部状态（含上一轮的导入结果与失败明细）
watch(() => props.open, (val) => {
  if (!val) return
  clearFile()
  outcome.value = null
  parseErrors.value = []
  checkErrors.value = []
})
</script>

<style scoped src="./ImportPanel.css"></style>
