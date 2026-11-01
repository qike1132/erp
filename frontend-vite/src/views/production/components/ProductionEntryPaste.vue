<template>
  <div v-if="open" class="pr-paste-mask" data-test="qe-paste" @click.self="close">
    <div class="pr-paste-card" role="dialog" aria-label="粘贴 Excel 导入">
      <h4>粘贴 Excel 内容</h4>
      <p>
        每行一个 SKU，列顺序：<b>产品名称（或 69 码）</b> / <b>数量</b> / <b>批次号（可空）</b>，
        用制表符或逗号分隔。只接受与产品档案<b>精确匹配</b>的行，匹配不上的会逐行列出，不会替你猜。
      </p>
      <textarea
        ref="textRef"
        v-model="text"
        data-test="qe-paste-text"
        spellcheck="false"
        placeholder="白色小熊抱枕 30cm&#9;120&#9;0464628801&#10;粉色兔子玩偶 25cm&#9;80&#9;0464628801"
        @keydown.ctrl.enter.stop.prevent="doImport"
        @keydown.esc.stop.prevent="close"
      />
      <div class="pr-paste-foot">
        <span class="pr-paste-hint">Ctrl + ⏎ 导入</span>
        <button type="button" class="pr-paste-btn" @click="close">取消</button>
        <button type="button" class="pr-paste-btn pri" data-test="qe-paste-ok" :disabled="!text.trim()" @click="doImport">解析并加入</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/** ProductionEntryPaste — 粘贴 Excel 导入层（表格批量录入的提速入口） */
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  import: [text: string]
}>()

const text = ref('')
const textRef = ref<HTMLTextAreaElement>()

function close() {
  emit('update:open', false)
}
function doImport() {
  if (!text.value.trim()) return
  emit('import', text.value)
  close()
}
watch(
  () => props.open,
  (v) => {
    if (v) nextTick(() => textRef.value?.focus())
  },
)
</script>

<style scoped>
.pr-paste-mask { position: absolute; inset: 0; z-index: 30; background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(2px); display: grid; place-items: center; border-radius: 18px; }
.pr-paste-card { width: min(560px, 92%); background: #fff; border-radius: 14px; padding: 18px 20px; box-shadow: 0 20px 50px rgba(15, 23, 42, 0.3); }
.pr-paste-card h4 { margin: 0 0 6px; font-size: 16px; font-weight: 800; }
.pr-paste-card p { margin: 0 0 10px; font-size: 13px; line-height: 1.7; color: var(--color-text-muted); }
.pr-paste-card p b { color: var(--color-text-secondary); }
.pr-paste-card textarea { width: 100%; height: 128px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: 10px; font-family: 'SF Mono', Consolas, monospace; font-size: 12.5px; line-height: 1.8; resize: vertical; outline: none; color: var(--color-text-secondary); box-sizing: border-box; }
.pr-paste-card textarea:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.13); }
.pr-paste-foot { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.pr-paste-hint { margin-right: auto; font-size: 12px; color: var(--color-text-placeholder); }
.pr-paste-btn { height: 34px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--color-border); background: #fff; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; cursor: pointer; font-family: inherit; }
.pr-paste-btn.pri { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); border-color: transparent; color: #fff; }
.pr-paste-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
