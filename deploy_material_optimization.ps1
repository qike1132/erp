# ============================================================
# 来料页面性能优化 - 一键部署脚本
# 
# 用途：在服务器 192.168.0.95 上执行所有部署步骤
# 包含：pg_trgm 索引创建 + 后端重建重启 + 前端更新
# 
# 使用方法（在服务器上以管理员权限运行）：
#   powershell -ExecutionPolicy Bypass -File deploy_material_optimization.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = "d:\erp_system"  # 根据服务器实际路径修改

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 来料页面性能优化 - 部署脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ==================== 步骤 1：执行 pg_trgm 索引 ====================
Write-Host "[1/3] 创建 PostgreSQL pg_trgm 索引..." -ForegroundColor Yellow

$sqlFile = Join-Path $ProjectRoot "apply_material_trgm_indexes.sql"
if (-not (Test-Path $sqlFile)) {
    Write-Host "  错误：找不到 SQL 文件 $sqlFile" -ForegroundColor Red
    exit 1
}

# 查找 PostgreSQL 容器密码（从 .env 或环境变量读取）
$envFile = Join-Path $ProjectRoot ".env"
$pgPassword = $null
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw
    if ($envContent -match 'POSTGRES_PASSWORD=([^\r\n]+)') {
        $pgPassword = $matches[1].Trim()
    }
}
if (-not $pgPassword) {
    $pgPassword = Read-Host "  请输入 PostgreSQL 密码"
}

# 将 SQL 文件复制到容器并执行
Write-Host "  复制 SQL 文件到 PostgreSQL 容器..." -ForegroundColor Gray
docker cp $sqlFile erp-postgres:/tmp/apply_material_trgm_indexes.sql

Write-Host "  执行 pg_trgm 索引创建..." -ForegroundColor Gray
$result = docker exec -e PGPASSWORD="$pgPassword" erp-postgres psql -U erp -d erp_system -f /tmp/apply_material_trgm_indexes.sql 2>&1
Write-Host $result

if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] pg_trgm 索引创建成功" -ForegroundColor Green
} else {
    Write-Host "  [WARN] pg_trgm 索引创建可能部分失败，检查输出" -ForegroundColor Yellow
    Write-Host $result
}

# 清理容器内临时文件
docker exec erp-postgres rm -f /tmp/apply_material_trgm_indexes.sql

Write-Host ""

# ==================== 步骤 2：重建并重启后端 ====================
Write-Host "[2/3] 重建并重启后端服务..." -ForegroundColor Yellow

Push-Location $ProjectRoot

Write-Host "  停止 erp-app 容器..." -ForegroundColor Gray
docker compose stop app
docker compose rm -f app

Write-Host "  重新构建镜像（无缓存，确保新代码生效）..." -ForegroundColor Gray
docker compose build --no-cache app

Write-Host "  启动后端服务..." -ForegroundColor Gray
docker compose up -d app

Write-Host "  等待服务健康检查..." -ForegroundColor Gray
$maxWait = 60
$waited = 0
do {
    Start-Sleep -Seconds 3
    $waited += 3
    $health = docker inspect --format='{{.State.Health.Status}}' erp-app 2>$null
    Write-Host "    状态: $health (${waited}s)" -ForegroundColor Gray
} while ($health -ne "healthy" -and $waited -lt $maxWait)

if ($health -eq "healthy") {
    Write-Host "  [OK] 后端服务启动成功" -ForegroundColor Green
} else {
    Write-Host "  [WARN] 后端服务可能仍在启动中，请检查日志" -ForegroundColor Yellow
    Write-Host "  docker logs erp-app --tail 50" -ForegroundColor Gray
}

# 验证缓存预热日志
Write-Host "  检查缓存预热状态..." -ForegroundColor Gray
docker logs erp-app --tail 30 2>&1 | Select-String "来料模块缓存预热"

Pop-Location

Write-Host ""

# ==================== 步骤 3：重启 Nginx（更新前端） ====================
Write-Host "[3/3] 重启 Nginx 加载新前端..." -ForegroundColor Yellow

# 前端 dist 通过 volume 挂载：./frontend-vite/dist -> /app/frontend-vite/dist
# 重新加载 Nginx 使其感知文件变更
docker exec erp-nginx nginx -s reload 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] Nginx 已重新加载" -ForegroundColor Green
} else {
    Write-Host "  [WARN] Nginx reload 失败，尝试重启容器" -ForegroundColor Yellow
    docker compose restart nginx
}

Write-Host ""

# ==================== 验证 ====================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 验证部署结果" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`n容器状态:" -ForegroundColor White
docker ps --format "table {{.Names}}\t{{.Status}}" --filter name=erp-app --filter name=erp-nginx --filter name=erp-postgres

Write-Host "`npg_trgm 索引确认:" -ForegroundColor White
docker exec -e PGPASSWORD="$pgPassword" erp-postgres psql -U erp -d erp_system -c "SELECT indexname FROM pg_indexes WHERE tablename IN ('material_registration', 'purchase_order', 'material_registration_item') AND indexname LIKE '%trgm%';" 2>&1

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " 部署完成！" -ForegroundColor Green
Write-Host " 访问 http://192.168.0.95:3000/material 测试" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
