<template>
  <div v-if="restoreResult" class="bk-section">
    <div class="bk-section-label">恢复结果</div>
    <div class="bk-result-card" :class="restoreResult.errors?.length || restoreResult.warnings?.length || restoreResult.results?.warnings?.length ? 'bk-result-partial' : 'bk-result-success'">
      <div class="bk-result-header">
        <FontAwesomeIcon :icon="restoreResult.errors?.length ? 'exclamation-circle' : 'check-circle'" />
        {{ restoreResult.errors?.length ? '恢复完成（部分异常）' : '恢复成功' }}
      </div>
      <div class="bk-result-stats">
        <span v-if="restoreResult.format === 'zip' || restoreResult.database || restoreResult.results?.database">ZIP 完整备份恢复 <template v-if="restoreResult.total_inserted">（{{ restoreResult.total_inserted }} 条记录）</template></span>
        <span v-else>共恢复 <b>{{ restoreResult.total_inserted }}</b> 条记录</span>
        <span v-if="(restoreResult.database || restoreResult.results?.database)?.status" class="bk-result-db-status">数据库: {{ (restoreResult.database || restoreResult.results?.database)?.status }}</span>
        <span v-if="restoreResult.results?.filestore?.restored" class="bk-result-fs-status">附件: {{ restoreResult.results?.filestore?.restored }} 个</span>
        <span v-if="restoreResult.results?.config?.restored?.length" class="bk-result-cfg-status">配置: {{ restoreResult.results?.config?.restored?.length }} 个文件</span>
      </div>
      <div v-if="(restoreResult.database || restoreResult.results?.database)?.errors" class="bk-result-errors" style="color: var(--color-danger-500);">
        <div v-for="e in normalizeErrors((restoreResult.database || restoreResult.results?.database)?.errors)" :key="e" class="bk-result-err-item">{{ e }}</div>
      </div>
      <div v-if="(restoreResult.database || restoreResult.results?.database)?.error" class="bk-result-errors">
        <div class="bk-result-err-item">{{ (restoreResult.database || restoreResult.results?.database)?.error }}</div>
      </div>
      <div v-if="restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup" class="bk-pre-restore-info">
        <FontAwesomeIcon icon="shield-alt" /> 安全备份: {{ (restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup)?.success ? '已创建' : '创建失败' }}
        <span v-if="(restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup)?.filename">({{ (restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup)?.filename }})</span>
      </div>
      <div v-if="restoreResult.rollback || restoreResult.results?.rollback" class="bk-result-errors">
        <div class="bk-result-err-item" :style="{ color: (restoreResult.rollback || restoreResult.results?.rollback)?.success ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
          <FontAwesomeIcon :icon="(restoreResult.rollback || restoreResult.results?.rollback)?.success ? 'check-circle' : 'times-circle'" />
          回滚{{ (restoreResult.rollback || restoreResult.results?.rollback)?.success ? '成功' : '失败' }}
          <span v-if="(restoreResult.rollback || restoreResult.results?.rollback)?.error">: {{ (restoreResult.rollback || restoreResult.results?.rollback)?.error }}</span>
        </div>
      </div>
      <div v-if="(restoreResult.warnings || restoreResult.results?.warnings)?.length" class="bk-result-errors" style="color: var(--color-warning-500);">
        <div v-for="w in (restoreResult.warnings || restoreResult.results?.warnings)" :key="w" class="bk-result-err-item">{{ w }}</div>
      </div>
      <div v-if="restoreResult.errors?.length" class="bk-result-errors">
        <div v-for="e in restoreResult.errors" :key="e" class="bk-result-err-item">{{ e }}</div>
      </div>
    </div>
    <!-- 验证报告 -->
    <div v-if="restoreResult.results?.verification || restoreResult.verification" class="bk-verify-card">
      <div class="bk-verify-title">
        <FontAwesomeIcon icon="shield-alt" :class="(restoreResult.results?.verification || restoreResult.verification)?.overall_pass ? '' : 'bk-verify-fail'" />
        数据完整性验证
      </div>
      <div class="bk-verify-summary">
        <span :class="(restoreResult.results?.verification || restoreResult.verification)?.l1_row_count?.mismatch?.length ? 'bk-verify-warn' : 'bk-verify-ok'">
          L1 行数比对: {{ (restoreResult.results?.verification || restoreResult.verification)?.l1_row_count?.summary || '未执行' }}
        </span>
        <span :class="(restoreResult.results?.verification || restoreResult.verification)?.l2_fingerprint?.tables_checked ? 'bk-verify-ok' : ''">
          L2 指纹校验: {{ (restoreResult.results?.verification || restoreResult.verification)?.l2_fingerprint?.tables_checked || 0 }} 表已检查
        </span>
        <span>
          L3 抽样验证: {{ (restoreResult.results?.verification || restoreResult.verification)?.l3_sampling?.tables_checked || 0 }} 表已抽样
        </span>
      </div>
      <!-- L1 mismatch details -->
      <div v-if="(restoreResult.results?.verification || restoreResult.verification)?.l1_row_count?.mismatch?.length" class="bk-verify-mismatches">
        <div v-for="m in (restoreResult.results?.verification || restoreResult.verification)?.l1_row_count?.mismatch" :key="m.table" class="bk-verify-mismatch-item">
          <b>{{ m.table }}</b>: 期望 {{ m.expected }} 行，实际 {{ m.actual }} 行
        </div>
      </div>
      <!-- L2 fingerprint details -->
      <div v-if="(restoreResult.results?.verification || restoreResult.verification)?.l2_fingerprint?.results?.length" class="bk-verify-fp-list">
        <div v-for="fp in (restoreResult.results?.verification || restoreResult.verification)?.l2_fingerprint?.results" :key="fp.table" class="bk-verify-fp-item">
          <span :class="fp.match === true ? 'bk-verify-ok' : fp.match === false ? 'bk-verify-fail' : ''">
            <FontAwesomeIcon :icon="fp.match === true ? 'fas fa-check' : fp.match === false ? 'times' : 'minus'" />
            {{ fp.table }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { RestoreResult } from '@/components/backup/RestoreProgressBar.vue'

defineProps<{
  restoreResult: RestoreResult | null
}>()

function normalizeErrors(errors: string[] | string | undefined): string[] {
  if (Array.isArray(errors)) return errors
  if (errors === undefined || errors === null) return []
  return [errors]
}
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }

.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.bk-result-card {
  padding: 16px;
  border-radius: var(--radius-sm);
  border: 1px solid;
}

.bk-result-success {
  background: linear-gradient(135deg, var(--color-success-50), var(--color-surface));
  border-color: var(--color-success-200);
}

.bk-result-partial {
  background: linear-gradient(135deg, var(--color-warning-50), var(--color-surface));
  border-color: var(--color-warning-200);
}

.bk-result-header {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.bk-result-success .bk-result-header i { color: var(--color-success-500); }
.bk-result-partial .bk-result-header i { color: var(--color-warning-500); }

.bk-result-stats {
  font-size: 13px;
  color: var(--color-text-secondary);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.bk-result-db-status,
.bk-result-fs-status,
.bk-result-cfg-status {
  font-size: 12px;
  color: var(--color-success-600);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.bk-result-errors {
  margin-top: 10px;
  max-height: 120px;
  overflow-y: auto;
}

.bk-result-err-item {
  font-size: 12px;
  color: var(--color-danger-600);
  padding: 4px 0;
  border-top: 1px solid var(--color-danger-100);
}

.bk-pre-restore-info {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-info-600);
  display: flex;
  align-items: center;
  gap: 4px;
}

.bk-pre-restore-info i { color: var(--color-info-500); }

.bk-verify-card {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-neutral-50);
  border-radius: 10px;
  border: 1px solid var(--color-border-light);
}

.bk-verify-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-neutral-700);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.bk-verify-fail { color: var(--color-danger-500); }

.bk-verify-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--color-neutral-600);
}

.bk-verify-ok { color: var(--color-success-600); }
.bk-verify-warn { color: var(--color-warning-600); }

.bk-verify-mismatches {
  margin-top: 6px;
  padding: 6px 8px;
  background: var(--color-warning-50);
  border-radius: 6px;
  font-size: 12px;
}

.bk-verify-mismatch-item {
  color: var(--color-warning-700);
  padding: 2px 0;
}

.bk-verify-fp-list {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.bk-verify-fp-item {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--color-neutral-100);
}
</style>