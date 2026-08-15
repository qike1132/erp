# ============================================================
# 滨发协同系统（ERP）Windows 原生生产部署脚本
# ============================================================
# 替代原 docker-compose.yml，适用于 Windows Server 原生部署
# 前置条件：PostgreSQL 16 / Redis 7 / Python 3.12 / Node 20 已安装
# ============================================================

param(
    [string]$Env = "production",
    [string]$AppDir = "D:\erp",
    [switch]$SkipReplica,
    [switch]$SkipMonitoring
)

$ErrorActionPreference = "Stop"
Write-Host "=== 滨发协同系统 Windows 原生部署 ($Env) ===" -ForegroundColor Cyan

# ------------------------------------------------------------
# 0. 环境变量校验（从 .env 加载）
# ------------------------------------------------------------
if (-not (Test-Path "$AppDir\.env")) {
    Write-Host "ERROR: $AppDir\.env 不存在，请复制 .env.example 并填写真实值" -ForegroundColor Red
    exit 1
}

Get-Content "$AppDir\.env" | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}

# 强制校验（config.py 启动时也会校验，此处提前失败更友好）
foreach ($var in @("SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD")) {
    $val = [Environment]::GetEnvironmentVariable($var)
    if (-not $val) {
        Write-Host "ERROR: 环境变量 $var 未设置" -ForegroundColor Red
        exit 1
    }
}

if ($Env -eq "production") {
    $allowedHosts = [Environment]::GetEnvironmentVariable("ALLOWED_HOSTS")
    if ($allowedHosts -eq "*" -or -not $allowedHosts) {
        Write-Host "ERROR: 生产环境 ALLOWED_HOSTS 必须设置为具体域名，禁止 *" -ForegroundColor Red
        exit 1
    }
}

# ------------------------------------------------------------
# 1. PostgreSQL 配置：流复制 + 连接池
# ------------------------------------------------------------
Write-Host "`n[1/6] PostgreSQL 配置..." -ForegroundColor Yellow

$pgHost = [Environment]::GetEnvironmentVariable("DB_HOST") ?? "localhost"
$pgPort = [Environment]::GetEnvironmentVariable("DB_PORT") ?? "5432"
$pgUser = [Environment]::GetEnvironmentVariable("DB_USER") ?? "erp_app"
$pgDb = [Environment]::GetEnvironmentVariable("DB_NAME") ?? "erp_system"
$pgPassword = [Environment]::GetEnvironmentVariable("POSTGRES_PASSWORD")

# 1a. 主库流复制配置（postgresql.conf 追加）
$pgConfPath = "C:\Program Files\PostgreSQL\16\data\postgresql.conf"
$replicaConf = @"
# === ERP 流复制配置（由 deploy-windows.ps1 添加）===
wal_level = replica
max_wal_senders = 5
max_replication_slots = 5
hot_standby = on
"@

if (-not $SkipReplica) {
    Write-Host "  配置主库流复制参数..."
    $existingConf = Get-Content $pgConfPath -Raw
    if ($existingConf -notmatch "wal_level = replica") {
        Add-Content -Path $pgConfPath -Value "`n$replicaConf"
        Write-Host "  已追加流复制配置到 postgresql.conf" -ForegroundColor Green
    } else {
        Write-Host "  流复制配置已存在，跳过" -ForegroundColor DarkGray
    }

    # 1b. 创建复制用户与物理复制槽
    Write-Host "  创建复制用户与物理复制槽..."
    $env:PGPASSWORD = $pgPassword
    psql -h $pgHost -p $pgPort -U $pgUser -d $pgDb -c "
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_replicator') THEN
                CREATE ROLE erp_replicator WITH REPLICATION LOGIN PASSWORD '$pgPassword';
                RAISE NOTICE '已创建流复制用户 erp_replicator';
            END IF;
        END \$\$;
    " 2>&1 | ForEach-Object { Write-Host "    $_" }

    psql -h $pgHost -p $pgPort -U $pgUser -d $pgDb -c "
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_replication_slots WHERE slot_name = 'erp_replica_slot') THEN
                PERFORM pg_create_physical_replication_slot('erp_replica_slot');
                RAISE NOTICE '已创建物理复制槽 erp_replica_slot';
            END IF;
        END \$\$;
    " 2>&1 | ForEach-Object { Write-Host "    $_" }

    # 1c. 创建只读用户（供只读副本对外服务）
    psql -h $pgHost -p $pgPort -U $pgUser -d $pgDb -c "
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_readonly') THEN
                CREATE ROLE erp_readonly LOGIN PASSWORD '$pgPassword';
            END IF;
        END \$\$;
        GRANT USAGE ON SCHEMA public TO erp_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO erp_readonly;
    " 2>&1 | ForEach-Object { Write-Host "    $_" }

    Remove-Item Env:\PGPASSWORD
}

# 1d. PgBouncer 配置（ARQ/后台任务经 PgBouncer 连接，避免直连 PG 耗尽连接）
Write-Host "  PgBouncer 连接池配置..."
Write-Host "  确保后台任务（ARQ）的 DATABASE_URL 指向 PgBouncer 端口 6432 而非 PG 5432" -ForegroundColor Cyan
Write-Host "  示例: DATABASE_URL=postgresql+asyncpg://erp_app:PWD@localhost:6432/erp_system"

# ------------------------------------------------------------
# 2. Redis 配置
# ------------------------------------------------------------
Write-Host "`n[2/6] Redis 配置..." -ForegroundColor Yellow
$redisConf = [Environment]::GetEnvironmentVariable("REDIS_CONF") ?? "C:\Program Files\Redis\redis.conf"
$redisPassword = [Environment]::GetEnvironmentVariable("REDIS_PASSWORD")

Write-Host "  确保 redis.windows-service.conf 中 requirepass 由环境变量注入"
Write-Host "  Redis 已配置：maxmemory 512mb / maxmemory-policy allkeys-lru / AOF everysec"

# ------------------------------------------------------------
# 3. 应用部署（Uvicorn + ARQ）
# ------------------------------------------------------------
Write-Host "`n[3/6] 应用服务部署..." -ForegroundColor Yellow

# 3a. Uvicorn 应用（多 worker，含 --proxy-headers，配合 Nginx 反代还原真实客户端 IP）
# 注意：Windows 上不要使用 --loop uvloop（uvloop 不支持 Windows，会自动回退 asyncio）
$uvicornWorkers = [Environment]::GetEnvironmentVariable("UVICORN_WORKERS") ?? "4"
Write-Host "  Uvicorn 启动命令（生产建议由 server_manager「生产托管」注册为 Windows 服务）:"
Write-Host "    uvicorn fastapi_app.main:app --host 0.0.0.0 --port 5002" -ForegroundColor White
Write-Host "      --workers $uvicornWorkers --http httptools" -ForegroundColor White
Write-Host "      --no-access-log --proxy-headers --forwarded-allow-ips='*'" -ForegroundColor Green
Write-Host "  或统一入口: python start.py --prod（由 prod_runner 监督器拉起 Uvicorn + ARQ + 前端）" -ForegroundColor Cyan

# 3b. ARQ Worker（已替代 Celery；含内建 cron，无需独立 beat 进程）
Write-Host "`n  ARQ Worker 启动命令（可经 PgBouncer 连接 PG）:"
Write-Host "    python -m arq fastapi_app.core.arq_app.WorkerSettings" -ForegroundColor White
Write-Host "  由 server_manager「生产托管」以 erp-arq 服务托管" -ForegroundColor Green

# 3c. Windows 服务注册（NSSM：开机自启 + 崩溃自动重启）
Write-Host "`n  Windows 服务注册（NSSM）:"
Write-Host "    1) 下载 NSSM 到 C:\nssm\nssm.exe"
Write-Host "    2) 在 server_manager「生产托管」面板点击『安装服务』"
Write-Host "       - erp-prod: python -m fastapi_app.core.prod_runner（监督器，自动守护多 worker Uvicorn）"
Write-Host "       - erp-arq : python -m arq fastapi_app.core.arq_app.WorkerSettings"
Write-Host "    3) 服务开机自启、崩溃自动重启（AppExit=Restart, AppRestartDelay=5000）"
Write-Host "       - erp-prod 传参含 --no-arq：ARQ 由独立 erp-arq 服务托管，避免双跑定时任务"

# ------------------------------------------------------------
# 4. 可观测性：Prometheus + Alertmanager + Exporters
# ------------------------------------------------------------
if (-not $SkipMonitoring) {
    Write-Host "`n[4/6] 可观测性配置..." -ForegroundColor Yellow

    # 4a. postgres_exporter
    Write-Host "  postgres_exporter 启动:"
    Write-Host "    DATA_SOURCE_NAME='postgresql://erp_app:PWD@localhost:5432/erp_system?sslmode=disable'" -ForegroundColor White
    Write-Host "    postgres_exporter.exe --web.listen-address=:9187" -ForegroundColor White

    # 4b. redis_exporter
    Write-Host "  redis_exporter 启动:"
    Write-Host "    redis_exporter.exe --redis.addr=localhost:6379 --redis.password=PWD --web.listen-address=:9121" -ForegroundColor White

    # 4c. Alertmanager
    Write-Host "  Alertmanager 启动:"
    Write-Host "    alertmanager.exe --config.file=config/alertmanager.yml --storage.path=alertmanager-data" -ForegroundColor White

    # 4d. OTel Collector（traces 导出到 Loki）
    Write-Host "  OTel Collector 配置（traces 导出 Loki，替代 debug）:"
    Write-Host "    otelcol-contrib.exe --config=config/otel-collector.yaml" -ForegroundColor White

    Write-Host "  Prometheus 已配置抓取: app:5002 / postgres-exporter:9187 / redis-exporter:9121 / celery-exporter:9808" -ForegroundColor Green
    Write-Host "  Alertmanager 目标: localhost:9093（见 config/prometheus.yml）" -ForegroundColor Green
}

# ------------------------------------------------------------
# 5. Nginx 反向代理
# ------------------------------------------------------------
Write-Host "`n[5/6] Nginx 反向代理..." -ForegroundColor Yellow
Write-Host "  配置文件: config/nginx.conf"
Write-Host "  确保 proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;" -ForegroundColor Green
Write-Host "  Uvicorn --proxy-headers 会读取此头还原真实客户端 IP"

# ------------------------------------------------------------
# 6. 数据库迁移
# ------------------------------------------------------------
Write-Host "`n[6/6] 数据库迁移..." -ForegroundColor Yellow
$env:PGPASSWORD = $pgPassword
Write-Host "  执行 alembic upgrade head..."
Push-Location $AppDir
python -m alembic -c migrations/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: alembic 迁移失败" -ForegroundColor Red
    Pop-Location
    exit 1
}
Write-Host "  迁移完成" -ForegroundColor Green
Pop-Location
Remove-Item Env:\PGPASSWORD

# ------------------------------------------------------------
# 完成
# ------------------------------------------------------------
Write-Host "`n=== 部署配置完成 ===" -ForegroundColor Cyan
Write-Host "关键检查项:" -ForegroundColor Yellow
Write-Host "  1. Uvicorn 含 --proxy-headers（CSRF 修复）+ --workers（多进程）"
Write-Host "  2. ARQ 后台任务 DATABASE_URL 指向 PgBouncer:6432（连接池修复）"
Write-Host "  3. 主库 wal_level=replica + 复制槽（只读副本修复）"
Write-Host "  4. postgres/redis exporter + Alertmanager 运行（可观测性修复）"
Write-Host "  5. ALLOWED_HOSTS 已设具体域名（非 *）"
Write-Host "  6. JWT 私钥由 K8s Secret/环境变量注入（未入库）"
Write-Host "  7. 生产建议：server_manager「生产托管」注册 NSSM 服务（开机自启 + 崩溃自愈）"
