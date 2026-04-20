#!/usr/bin/env bash
# ============================================================
# SOP v9.0 阶段5: 环境初始化与增强备份 (Bash)
# 用途: FIX阶段启动前的环境校验、双备份、校验和生成
# 调用: bash phase5-init-backup.sh [--health-url url] [--language python] [--grace-period 3]
# 输出: stdout JSON 结果
# ============================================================
set -euo pipefail

# 解析参数
HEALTH_URL=""
LANGUAGE="python"
GRACE_PERIOD=3

while [[ $# -gt 0 ]]; do
    case "$1" in
        --health-url) HEALTH_URL="$2"; shift 2 ;;
        --language) LANGUAGE="$2"; shift 2 ;;
        --grace-period) GRACE_PERIOD="$2"; shift 2 ;;
        *) echo "[WARN] 未知参数: $1" >&2; shift ;;
    esac
done

# 钳位 GracePeriod
GRACE_PERIOD=$(echo "$GRACE_PERIOD" | awk '{v=$1; if(v<1) v=1; if(v>60) v=60; print v}')

# 参数消毒
if [[ "$HEALTH_URL" == *".."* ]]; then
    echo "[ERROR] [PATH_TRAVERSAL_BLOCKED] HealthUrl 包含路径穿越" >&2; exit 1
fi

# 5.2 Bash 环境校验
if [ -z "$BASH_VERSION" ]; then
    echo "[ERROR] [FATAL] 需要 Bash 环境" >&2; exit 1
fi

# 5.3 权限检测
if [ "$(id -u)" -eq 0 ]; then
    PRIVILEGE_MODE="full"
else
    PRIVILEGE_MODE="limited"
fi

# 5.4 初始化临时目录
rm -rf .tmp 2>/dev/null || true
mkdir -p .tmp/code_backup .tmp/config_backup .tmp/logs .tmp/test_results

# 5.5 磁盘空间智能预估（需要3倍源码空间）
SOURCE_SIZE=$(find . -type f \
    -not -path "./.tmp/*" \
    -not -path "./node_modules/*" \
    -not -path "./__pycache__/*" \
    -exec stat -f%z {} + 2>/dev/null | awk '{s+=$1} END {print s+0}')
if [ "$SOURCE_SIZE" -eq 0 ]; then SOURCE_SIZE=524288000; fi
ESTIMATED_NEED=$((SOURCE_SIZE * 3))
FREE_SPACE=$(df -P . | awk 'NR==2 {print $4 * 1024}')
if [ "$FREE_SPACE" -lt "$ESTIMATED_NEED" ]; then
    echo "[ERROR] [FATAL] 磁盘空间不足 (需要: $((ESTIMATED_NEED/1048576))MB, 可用: $((FREE_SPACE/1048576))MB)" >&2; exit 1
fi

# 5.6 依赖服务健康检查
HEALTH_STATUS="SKIPPED"
if [ -n "$HEALTH_URL" ]; then
    if curl -s --max-time 5 "$HEALTH_URL" | grep -q '"status".*:.*200\|"status".*:.*"ok"'; then
        HEALTH_STATUS="OK"
        echo "[DEP_OK] 服务可达"
    else
        HEALTH_STATUS="DOWN"
        echo "[DEP_DOWN] 服务不可达" >&2
    fi
fi

# 5.7 双备份创建
BACKUP_METHOD="git_stash"
if git rev-parse --git-dir &>/dev/null 2>&1; then
    git stash push -m "FIX前自动备份" 2>/dev/null || true
else
    BACKUP_METHOD="file_copy"
    rsync -a --exclude='.tmp' --exclude='node_modules' --exclude='__pycache__' --exclude='.git' \
        ./ .tmp/code_backup/primary/ 2>/dev/null || true
    rsync -a --exclude='.tmp' --exclude='node_modules' --exclude='__pycache__' \
        ./ .archive/pre-fix-backup/secondary/ 2>/dev/null || true
fi

# 5.8 生成 SHA256 校验文件
CHECKSUM_COUNT=0
if [ -d ".tmp/code_backup/primary" ]; then
    CHECKSUM_COUNT=$(find .tmp/code_backup/primary -type f 2>/dev/null | wc -l | tr -d ' ')
    find .tmp/code_backup/primary -type f 2>/dev/null | while read -r file; do
        hash=$(sha256sum "$file" 2>/dev/null | awk '{print $1}')
        relpath="${file#.tmp/code_backup/primary/}"
        echo "\"$relpath\": \"$hash\""
    done | paste -sd, | sed 's/^/{/;s/$/}/' > .tmp/code_backup/checksums.json 2>/dev/null || true
fi

# 5.9 配置脱敏备份 + 依赖快照
find . -type f \( -name "*.json" -o -name "*.config" -o -name "*.env" -o -name "*.ini" \) \
    -not -path "./.tmp/*" -not -path "./node_modules/*" 2>/dev/null | while read -r file; do
    sed -E \
        -e 's/((?i)password|passwd|pwd)\s*[=:]\s*["'"'"']?\w[^"'"'"',\s}]*/\1=***/g' \
        -e 's/"((?i)password|secret|key|token|api_key|auth_token)"\s*:\s*"[^"]*"/"\1":"***"/g' \
        "$file" > ".tmp/config_backup/$(basename "$file")" 2>/dev/null || true
done
pip freeze > .tmp/deps_before.txt 2>/dev/null || true

# 5.10 生成基线 JSON
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DISK_FREE_MB=$((FREE_SPACE / 1048576))
cat > .tmp/baseline.json << BASELINE_EOF
{
    "sop_version": "9.0",
    "phase": "FIX_START",
    "privilege_mode": "$PRIVILEGE_MODE",
    "disk_free_mb": $DISK_FREE_MB,
    "backup_primary": ".tmp/code_backup/primary",
    "backup_secondary": ".archive/pre-fix-backup/secondary",
    "checksum_count": $CHECKSUM_COUNT,
    "backup_method": "$BACKUP_METHOD",
    "health_status": "$HEALTH_STATUS",
    "exec_timestamp": "$TIMESTAMP"
}
BASELINE_EOF

# 输出结构化结果
cat << RESULT_EOF
{
    "status": "COMPLETED",
    "phase": 5,
    "privilege_mode": "$PRIVILEGE_MODE",
    "disk_free_mb": $DISK_FREE_MB,
    "backup_method": "$BACKUP_METHOD",
    "health_status": "$HEALTH_STATUS",
    "checksum_count": $CHECKSUM_COUNT,
    "baseline_file": ".tmp/baseline.json"
}
RESULT_EOF
