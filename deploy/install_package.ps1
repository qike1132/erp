#Requires -Version 5.1
# ============================================================
# ERP 离线便携包 —— 安装端（在**目标机**以管理员运行）
# 用法：
#   powershell.exe -NoProfile -File install_package.ps1 `
#       -Package <加密包> -ExpectedSha256 <独立可信摘要> -ServerIP <证书主机名> ...
# 只支持全新安装；禁止覆盖、删库或跳过验收。依赖同目录 _lib.ps1。
# ============================================================
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Package,
  [Parameter(Mandatory)][ValidatePattern('\A[0-9a-fA-F]{64}\z')][string]$ExpectedSha256,
  [Parameter(Mandatory)][string]$ServerIP,
  [Parameter(Mandatory)][string]$TlsCertificate,
  [Parameter(Mandatory)][string]$TlsPrivateKey,
  [Parameter(Mandatory)][string]$TlsTrustedCa,
  [Parameter(Mandatory)][string]$OpenSsl,
  [string]$TargetDir = 'D:\erp_system',
  [string]$NginxDir = 'C:\nginx',
  [string]$RedisDir = 'C:\Redis',
  [string]$Nssm = 'C:\nssm\nssm.exe',
  [switch]$PreflightOnly,
  [switch]$Force, [switch]$Blank, [switch]$SkipVerify, [switch]$AllowDropDatabase
)
. (Join-Path $PSScriptRoot '_lib.ps1')

# ---- 本脚本私有辅助（不改 _lib.ps1）----
function Assert-ServiceRegistered([string]$Name){
  if(-not (Get-Service -Name $Name -ErrorAction SilentlyContinue)){
    Write-Fail "服务 $Name 注册失败（nssm 未生效；检查 $Nssm 与管理员权限）"
    exit 1
  }
}
function Wait-ServiceRunning([string]$Name,[int]$TimeoutSec=45){
  $deadline=(Get-Date).AddSeconds($TimeoutSec)
  while($true){
    $s=Get-Service -Name $Name -ErrorAction SilentlyContinue
    if($s -and $s.Status -eq 'Running'){ return $true }
    if((Get-Date) -ge $deadline){ return $false }
    Start-Sleep -Seconds 2
  }
}
function Start-ErpService([string]$Name){
  $s=Get-Service -Name $Name -ErrorAction SilentlyContinue
  if(-not $s){ Write-Fail "服务 $Name 不存在，无法启动"; exit 1 }
  if($s.Status -ne 'Running'){ Start-Service -Name $Name -ErrorAction SilentlyContinue }
  if(-not (Wait-ServiceRunning $Name 60)){
    $st=(Get-Service -Name $Name -ErrorAction SilentlyContinue).Status
    Write-Fail "服务 $Name 未能进入 Running（state=$st；见 logs\\$Name.log）"
    exit 1
  }
  Write-Ok "服务 $Name 运行中"
}
function New-DeployRedisConf([string]$SrcConf,[string]$DstConf,[string]$Name,[string]$RedisRoot,[string]$Password){
  # 凭据只写入安装器创建的专用 ACL 目录，不进入 NSSM 或 Redis 进程参数。
  # 并把 dir/logfile 指向部署目录（非默认 RedisDir 时避免脏数据/日志落到 C:\Redis）。
  # ⚠️ 路径一律用**正斜杠**：Redis 把反斜杠当转义符，单反斜杠的 "C:\Redis\data"
  #    会被解析成 C:Redisdata → 启动报 Can't chdir to 'C:Redisdata' → NSSM 崩溃循环置 Paused。
  $root = $RedisRoot -replace '\\','/'
  $dataDir = "$root/$Name"
  New-Item -ItemType Directory -Path (Join-Path $RedisRoot $Name) | Out-Null
  $lines=[IO.File]::ReadAllLines($SrcConf,[Text.UTF8Encoding]::new($false))
  $out = $lines | Where-Object { $_ -notmatch '^\s*requirepass(\s|$)' } | ForEach-Object {
    if($_ -match '^\s*dir\s'){ "dir `"$dataDir`"" }
    elseif($_ -match '^\s*logfile\s'){ "logfile `"$root/$Name.log`"" }
    else { $_ }
  }
  # 防回归：生成的 dir/logfile 行不得残留反斜杠（Redis 会当转义符）
  foreach($ln in $out){ if($ln -match '^\s*(dir|logfile)\s' -and $ln.Contains('\')){ Write-Fail "Redis conf 的 dir/logfile 含反斜杠（Redis 会当转义符）：$ln"; exit 1 } }
  if(-not $Password -or $Password -match '[\x00-\x1f\x7f]'){ throw 'Redis 口令不能为空或含控制字符' }
  $quoted=$Password.Replace('\','\\').Replace('"','\"')
  $out=@($out) + "requirepass `"$quoted`""
  [IO.File]::WriteAllText($DstConf, (($out -join "`r`n") + "`r`n"), [Text.UTF8Encoding]::new($false))
}
function New-BlankAdmin([string]$Py,[string]$Psql,[string]$TargetDir,[string]$WorkDir,[string]$DbUser,[string]$DbName,[string]$DbPw){
  # 空库引导：项目无内置用户种子。
  $pw = Read-DeploySecret '新 admin 口令（Argon2id 哈希后写入）'
  # 口令经环境变量进 python，绝不拼进命令行（避免进命令历史/进程列表）
  $env:ERP_ADMIN_PW = $pw
  $prevPyPath = $env:PYTHONPATH
  $env:PYTHONPATH = $TargetDir
  $hash = $null
  try {
    $hash = (& $Py -c "import os; from fastapi_app.core.security import hash_password; print(hash_password(os.environ['ERP_ADMIN_PW']))" | Out-String).Trim()
  } finally {
    Remove-Item Env:ERP_ADMIN_PW -ErrorAction SilentlyContinue
    if($prevPyPath){ $env:PYTHONPATH = $prevPyPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
  }
  if(-not $hash){ Write-Fail 'admin 口令哈希生成失败（fastapi_app.core.security 导入异常？）'; exit 1 }
  # 哈希经临时 SQL 文件喂给 psql，不进命令行；口令/哈希均不落日志
  $sqlFile = Join-Path $WorkDir ('mkadmin_' + [guid]::NewGuid().ToString('N') + '.sql')
  $sql = "INSERT INTO `"user`" (username, password, is_super, status, create_time, update_time) VALUES ('admin', '$hash', true, true, now(), now());"
  [IO.File]::WriteAllText($sqlFile, $sql, [Text.UTF8Encoding]::new($false))
  $env:PGPASSWORD = $DbPw
  try {
    & $Psql -X -w -h 127.0.0.1 -p 5432 -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -f $sqlFile
    if($LASTEXITCODE -ne 0){ Write-Fail 'admin 用户创建失败（见上方 psql 输出）'; exit 1 }
  } finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item $sqlFile -Force -ErrorAction SilentlyContinue
  }
  Write-Ok '已创建超管 admin —— 请立即登录并修改口令'
}
function Get-RedisKeyTtl([string]$RedisHost,[int]$Port,[string]$Password,[string]$Key,[int]$Db=0){
  # 只读诊断：连 Redis 依次发 AUTH/SELECT/TTL，返回键的 TTL 秒数。
  # 键不存在/连接失败/认证失败 → $null。走原始 RESP over TcpClient：口令不进命令行与进程列表，
  # 也不依赖 redis-cli.exe（并避开 PS5.1 原生 stderr 在 EA=Stop 下误抛的坑）。
  $client=$null
  try{
    $client=[Net.Sockets.TcpClient]::new()
    $client.Connect($RedisHost,$Port)
    $stream=$client.GetStream(); $stream.ReadTimeout=5000; $stream.WriteTimeout=5000
    $enc=[Text.Encoding]::UTF8
    $cmds=New-Object 'System.Collections.Generic.List[object]'
    if($Password){ $cmds.Add(@('AUTH',$Password)) }
    if($Db -gt 0){ $cmds.Add(@('SELECT',"$Db")) }
    $cmds.Add(@('TTL',$Key))
    $line=$null
    foreach($c in $cmds){
      $sb=[Text.StringBuilder]::new(); [void]$sb.Append('*').Append($c.Count).Append("`r`n")
      foreach($p in $c){ $b=$enc.GetBytes([string]$p); [void]$sb.Append('$').Append($b.Length).Append("`r`n").Append([string]$p).Append("`r`n") }
      $payload=$enc.GetBytes($sb.ToString()); $stream.Write($payload,0,$payload.Length); $stream.Flush()
      $buf=New-Object 'System.Collections.Generic.List[byte]'
      while($true){ $x=$stream.ReadByte(); if($x -lt 0){ break }; if($x -eq 13){ [void]$stream.ReadByte(); break }; [void]$buf.Add([byte]$x) }
      $line=$enc.GetString($buf.ToArray())
      if($c[0] -eq 'AUTH' -and -not $line.StartsWith('+OK')){ return $null }
    }
    if($line -match '^:?-?\d+$'){ return [int]($line -replace '^:','') }
    return $null
  } catch { return $null } finally { if($client){ $client.Close() } }
}
function Test-ArqSentinel([string]$RedisHost='127.0.0.1',[int]$Port=6380,[string]$Password='',[int]$Db=0){
  # ARQ 官方健康哨兵键判活（与 fastapi_app/core/arq_app.check_worker_health 同一契约）：
  # broker 实例上 arq:queue:health-check 的 TTL 落在 0..61 视为新鲜在线（health_check_interval=60）。
  $ttl = Get-RedisKeyTtl -RedisHost $RedisHost -Port $Port -Password $Password -Key 'arq:queue:health-check' -Db $Db
  if($null -eq $ttl){ return $false }
  return ($ttl -ge 0 -and $ttl -le 61)
}

function Assert-NewDatabase([string]$Psql,[string]$DbName,[string]$DbUser){
  $conflict=(& $Psql -X -w -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -tAc "SELECT 1 WHERE EXISTS (SELECT FROM pg_database WHERE datname='$DbName') OR EXISTS (SELECT FROM pg_roles WHERE rolname='$DbUser')" | Out-String).Trim()
  if($LASTEXITCODE -ne 0 -or $conflict){ throw '不能确认数据库及角色均不存在；拒绝更改 PostgreSQL' }
}

$work = $null
try {
  Write-Step '0 只读预检'
  Assert-FreshInstallOptions $Force $AllowDropDatabase $SkipVerify
  if(-not $PreflightOnly){ throw '便携安装尚未放行：迁移连接隔离和 Windows 恢复演练未完成；仅支持 -PreflightOnly' }
  if(-not (Test-Admin)){ throw '必须以管理员运行' }
  if(-not (Test-HostLiteral $ServerIP)){ throw "非法的 HTTPS 入口主机名：$ServerIP" }
  $hBare = $ServerIP.Trim().Trim('[',']').ToLowerInvariant()
  $is6 = Test-IsIPv6Literal $hBare
  $hUrl = if($is6){ "[$hBare]" }else{ $hBare }
  Assert-DeploymentTls $OpenSsl $TlsCertificate $TlsPrivateKey $TlsTrustedCa $hBare
  $TargetDir=Assert-LocalDeploymentPath $TargetDir
  $NginxDir=Assert-LocalDeploymentPath $NginxDir
  if($TargetDir.Contains(' ') -or $NginxDir.Contains(' ')){ throw 'nginx 模板使用未加引号的绝对路径；TargetDir 和 NginxDir 不能含空格' }
  if(-not (Test-Path -LiteralPath (Split-Path $TargetDir -Parent) -PathType Container)){ throw '目标路径的父目录不存在' }
  $RedisDir=Assert-LocalDeploymentPath $RedisDir
  $Nssm=Assert-LocalDeploymentPath $Nssm
  if(-not (Test-Path -LiteralPath $Package -PathType Leaf)){ throw '安装包不存在' }
  $Package=(Get-Item -LiteralPath $Package -Force).FullName
  $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
  $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
  $schtasks=Join-Path $env:SystemRoot 'System32\schtasks.exe'
  foreach($tool in @($tar,$curl,$schtasks)){
    if(-not (Test-Path -LiteralPath $tool -PathType Leaf)){ throw "缺少 Windows 系统工具：$tool" }
  }
  $curlVersion=& $curl -q --version
  if($LASTEXITCODE -ne 0 -or ($curlVersion -join "`n") -notmatch '\bSchannel\b'){ throw '验收需要使用 Windows 信任存储的系统 curl（Schannel）' }
  $drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($TargetDir))
  if($drive.AvailableFreeSpace -lt 8GB){ throw '目标盘可用空间不足 8GB' }
  if(Test-Path -LiteralPath $TargetDir){ throw "目标路径已存在，拒绝覆盖：$TargetDir" }
  # 停机序由 tests/test_service_order_single_source.py 锁定；新装只用其反向启动序。
  $stopOrder = @('erp-prod','erp-arq','erp-web','erp-redis','erp-redis-broker')
  $five = @($stopOrder[($stopOrder.Count-1)..0])
  foreach($svc in $five){
    if($null -ne (Get-ServiceStatus $svc)){ throw "服务已存在，拒绝替换：$svc" }
  }
  if(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -eq 'erp-watchdog' }){ throw '看门狗已存在，拒绝替换' }
  $busy=@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in 443,3000,5002,6379,6380 })
  if($busy.Count){ throw 'ERP 所需的 443/3000/5002/6379/6380 已有监听；拒绝在共用主机部署' }
  foreach($component in @((Join-Path $NginxDir 'nginx.exe'),(Join-Path $RedisDir 'redis-server.exe'),$Nssm)){
    [void](Assert-LocalDeploymentPath $component)
    if(-not (Test-Path -LiteralPath $component -PathType Leaf)){ throw "请预装可信基础组件：$component" }
  }
  $psqlGuard=Get-PgTool 'psql.exe'
  if(-not $psqlGuard){ throw '必须预装 PostgreSQL 18 和可信 psql；安装器不传递超级用户口令作为进程参数' }
  [void](Assert-LocalDeploymentPath $psqlGuard)

  Write-Step '1 验证并解包'
  $work=New-DeployStagingDirectory
  $tgz=Join-Path $work 'p.tar.gz'
  Unprotect-File -InPath $Package -OutPath $tgz -ExpectedSha256 $ExpectedSha256 -Password (Read-DeploySecret '便携包口令')
  & $tar -xzf $tgz -C $work
  if($LASTEXITCODE -ne 0){ throw 'tar 解包失败' }
  Assert-NoDeploymentLinks $work
  $roots=@(Get-ChildItem -LiteralPath $work -Directory -Force)
  if($roots.Count -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $roots[0].FullName 'manifest.txt') -PathType Leaf)){ throw '便携包缺少唯一的 manifest 根目录' }
  $pkgRoot=$roots[0]
  $appRoot=Join-Path $pkgRoot.FullName 'app'
  $envMap=Read-EnvMap (Join-Path $appRoot '.env')
  $dbPw=$envMap['DB_PASSWORD']
  if(-not $dbPw -or $dbPw -match '[\x00-\x1f\x7f]'){ throw '包内 DB_PASSWORD 为空或含控制字符' }
  $dbUser=if($envMap['DB_USER']){ $envMap['DB_USER'] }else{ 'erp_app' }
  $dbName=if($envMap['DB_NAME']){ $envMap['DB_NAME'] }else{ 'erp_system' }
  foreach($identifier in @($dbName,$dbUser)){
    if($identifier -cnotmatch '\A[a-z_][a-z0-9_]{0,62}\z'){ throw '数据库和角色必须是 PostgreSQL 小写标识符' }
  }
  foreach($p in @('app\.env','app\config\nginx-windows.conf','runtime\python313\python.exe','frontend\dist\index.html')){
    if(-not (Test-Path -LiteralPath (Join-Path $pkgRoot.FullName $p) -PathType Leaf)){ throw "便携包缺少：$p" }
  }
  if(-not $Blank){
    if(-not (Test-Path -LiteralPath (Join-Path $pkgRoot.FullName 'data\erp_system.dump') -PathType Leaf)){ throw '镜像部署缺少数据库 dump' }
    $pgrestore=Join-Path (Split-Path $psqlGuard -Parent) 'pg_restore.exe'
    [void](Assert-LocalDeploymentPath $pgrestore)
    if(-not (Test-Path -LiteralPath $pgrestore -PathType Leaf)){ throw '缺少 PostgreSQL 客户端 pg_restore' }
  }
  if(-not $envMap['REDIS_PASSWORD'] -or $envMap['REDIS_PASSWORD'] -match '[\x00-\x1f\x7f]' -or
     -not $envMap['UPLOAD_URL_SIGNING_SECRET'] -or $envMap['UPLOAD_URL_SIGNING_SECRET'] -match '[\x00-\x1f\x7f"\\$]'){
    throw '安装包缺少合规的 Redis 或上传签名凭据'
  }
  if(Test-Path -LiteralPath (Join-Path $appRoot 'config\tls')){ throw '便携包不得携带 TLS 物料' }
  $tlsDir=New-DeployPrivateDirectory (Join-Path $work 'tls')
  Copy-Item -LiteralPath $TlsCertificate -Destination (Join-Path $tlsDir 'server.crt')
  Copy-Item -LiteralPath $TlsPrivateKey -Destination (Join-Path $tlsDir 'server.key')
  Assert-DeploymentTls $OpenSsl (Join-Path $tlsDir 'server.crt') (Join-Path $tlsDir 'server.key') $TlsTrustedCa $hBare
  $nginxStaged=Join-Path $appRoot 'config\nginx-windows.conf'
  $newRoot=$TargetDir.Replace('\','/')
  [void](Update-NginxConf $nginxStaged 'D:/erp_system' $newRoot $NginxDir $hBare)
  if($PreflightOnly){
    Remove-DeployStagingDirectory $work
    $work=$null
    Write-Ok '预检通过：未连接数据库或启动部署'
    exit 0
  }
  throw '便携安装未放行；拒绝进入数据库迁移和部署'

  $PgSuperPassword = (Read-DeploySecret '目标机现有 postgres 超级用户口令')
  # ==========================================================
  Write-Step '2 建库'
  $psql=$psqlGuard
  $env:PGPASSWORD = $PgSuperPassword  # secret-scan:allow 变量引用，非字面量口令
  try {
    Assert-NewDatabase $psql $dbName $dbUser
    $esc=$dbPw.Replace("'","''")
    $sqlFile=Join-Path $work 'init-db.sql'
    $sql="SET standard_conforming_strings = on;`nCREATE ROLE `"$dbUser`" LOGIN PASSWORD '$esc';`nCREATE DATABASE `"$dbName`" WITH OWNER = `"$dbUser`" ENCODING = 'UTF8' TEMPLATE = template0;"
    [IO.File]::WriteAllText($sqlFile,$sql,[Text.UTF8Encoding]::new($false))
    try {
      & $psql -X -w -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -f $sqlFile | Out-Null
      if($LASTEXITCODE -ne 0){ throw '新建数据库或角色失败；不修改既有对象' }
    } finally { Remove-Item -LiteralPath $sqlFile -Force }
    Write-Ok "数据库 $dbName 已创建（owner=$dbUser）"
  } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }

  # ==========================================================
  Write-Step '3 部署文件'
  [void](New-DeployPrivateDirectory $TargetDir)
  $copies = @(
    @{ Src='app';           Dst=$TargetDir },
    @{ Src='runtime';       Dst=(Join-Path $TargetDir 'runtime') },
    @{ Src='frontend\dist'; Dst=(Join-Path $TargetDir 'frontend-vite\dist') }
  )
  foreach($c in $copies){
    $src = Join-Path $pkgRoot.FullName $c.Src
    robocopy $src $c.Dst /E /XJ /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if($LASTEXITCODE -ge 8){ throw "robocopy 失败 (exit=$LASTEXITCODE)：$($c.Src)" }
  }
  $targetTls=New-DeployPrivateDirectory (Join-Path $TargetDir 'config\tls')
  foreach($material in @('server.crt','server.key')){ Copy-Item -LiteralPath (Join-Path $tlsDir $material) -Destination $targetTls }
  # 包内 static 位于 data\static（spec §4）
  $staticSrc = Join-Path $pkgRoot.FullName 'data\static'
  if(Test-Path $staticSrc){
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir 'static') | Out-Null
    robocopy $staticSrc (Join-Path $TargetDir 'static') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：static"; exit 1 }
  } else { Write-Warn '包内无 data\static（跳过）' }
  foreach($d in 'logs','backups','temp'){ New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir $d) | Out-Null }
  $envPath = Join-Path $TargetDir '.env'
  if(-not (Test-Path $envPath)){ Write-Fail "部署后缺 .env（包内 app\.env 应存在）：$envPath"; exit 1 }
  Write-Ok "代码/运行时/前端/静态资源已部署到 $TargetDir"

  # ==========================================================
  Write-Step '4 .env 改写'
  Add-EnvListItemJson $envPath 'ALLOWED_HOSTS' $hUrl
  if($is6){ Add-EnvListItemJson $envPath 'ALLOWED_HOSTS' $hBare }
  Set-EnvKey $envPath 'CORS_ORIGINS' "https://$hUrl"
  Set-EnvKey $envPath 'WS_ALLOWED_ORIGINS' $hUrl
  Set-EnvKey $envPath 'DB_HOST' '127.0.0.1'
  Set-EnvKey $envPath 'DB_PORT' '5432'
  Set-EnvKey $envPath 'WEB_PORT' '3000'
  Set-EnvKey $envPath 'WEB_HEALTH_SCHEME' 'http'
  Set-EnvKey $envPath 'JWT_PRIVATE_KEY_PATH' (Join-Path $TargetDir 'config\jwt\private_v2.pem')
  Set-EnvKey $envPath 'JWT_PUBLIC_KEY_PATH'  (Join-Path $TargetDir 'config\jwt\public_v2.pem')
  # 注释 ASYNC_DATABASE_REPLICA_URL（副本未迁移，应用回退主库）
  $lines=[Collections.Generic.List[string]]([IO.File]::ReadAllLines($envPath,[Text.UTF8Encoding]::new($false)))
  for($i=0;$i -lt $lines.Count;$i++){
    if($lines[$i] -match '^\s*ASYNC_DATABASE_REPLICA_URL\s*='){ $lines[$i]='# '+$lines[$i] }
  }
  [IO.File]::WriteAllText($envPath, (($lines -join "`r`n")+"`r`n"), [Text.UTF8Encoding]::new($false))
  # 删除 DATABASE_URL / ASYNC_DATABASE_URL 整行（留空会覆盖兜底致 URL 解析失败）
  $kept=[IO.File]::ReadAllLines($envPath,[Text.UTF8Encoding]::new($false)) | Where-Object { $_ -notmatch '^\s*(ASYNC_)?DATABASE_URL\s*=' }
  [IO.File]::WriteAllText($envPath, (($kept -join "`r`n")+"`r`n"), [Text.UTF8Encoding]::new($false))
  Write-Ok '.env 已改写（ALLOWED_HOSTS/CORS/WS/JWT；副本已注释；DATABASE_URL 已删）'

  $nginxConf = Join-Path $TargetDir 'config\nginx-windows.conf'
  New-NginxTempDirs $TargetDir
  $nginxExe = Join-Path $NginxDir 'nginx.exe'

  # ==========================================================
  Write-Step '5 上传签名与 nginx 配置校验'
  $secret = (Read-EnvMap $envPath)['UPLOAD_URL_SIGNING_SECRET']  # secret-scan:allow 变量名，非字面量
  if(-not $secret){ Write-Fail '.env 缺 UPLOAD_URL_SIGNING_SECRET，无法生成 uploads-signing.conf'; exit 1 }
  # 与 config/uploads-signing.conf(.example) 逐字对齐：secret 前有一个字面空格
  [IO.File]::WriteAllText((Join-Path $TargetDir 'config\uploads-signing.conf'), "secure_link_md5 `"`$arg_st`$uri $secret`";", [Text.UTF8Encoding]::new($false))
  Write-Ok 'uploads-signing.conf 已生成'
  & $nginxExe -p $TargetDir -c $nginxConf -t
  if($LASTEXITCODE -ne 0){ throw 'nginx -t 校验失败，拒绝启动服务' }
  Write-Ok 'nginx -t 通过'

  # ==========================================================
  Write-Step '6 数据'
  $py = Join-Path $TargetDir 'runtime\python313\python.exe'
  if(-not (Test-Path $py)){ Write-Fail "包内 runtime 缺失: $py"; exit 1 }
  $alembicIni = Join-Path $TargetDir 'migrations\alembic.ini'
  Push-Location $TargetDir
  try {
    if($Blank){
      & $py -m alembic -c $alembicIni upgrade head
      if($LASTEXITCODE -ne 0){ Write-Fail 'alembic upgrade head 失败'; exit 1 }
      & $py (Join-Path $TargetDir 'scripts\init_permissions.py') --yes
      if($LASTEXITCODE -ne 0){ Write-Fail 'init_permissions 失败'; exit 1 }
      & $py (Join-Path $TargetDir 'scripts\seed_nav.py')
      if($LASTEXITCODE -ne 0){ Write-Fail 'seed_nav 失败'; exit 1 }
      New-BlankAdmin -Py $py -Psql $psql -TargetDir $TargetDir -WorkDir $work -DbUser $dbUser -DbName $dbName -DbPw $dbPw
    } else {
      $dump = Join-Path $pkgRoot.FullName 'data\erp_system.dump'
      if(-not (Test-Path $dump)){ Write-Fail "包内缺 data\erp_system.dump: $dump"; exit 1 }
      $env:PGPASSWORD = $dbPw
      try {
        # 输出落文件（不走本进程 stderr 重定向——EAP=Stop 下会终止）；非零即致命
        $rcOut = Join-Path $work 'pg_restore.out'
        $rcErr = Join-Path $work 'pg_restore.err'
        $proc = Start-Process -FilePath $pgrestore -ArgumentList @('--no-password','-h','127.0.0.1','-p','5432','-U',$dbUser,'-d',$dbName,'--no-owner','--no-privileges','-j','4',"`"$dump`"") -NoNewWindow -Wait -PassThru -RedirectStandardOutput $rcOut -RedirectStandardError $rcErr
        if($proc.ExitCode -ne 0){
          Write-Fail "pg_restore 失败（exit=$($proc.ExitCode)）：部分恢复不可用。末 20 行："
          if(Test-Path $rcErr){ Get-Content $rcErr -Tail 20 | ForEach-Object { [Console]::Error.WriteLine("    $_") } }
          exit 1
        }
        Write-Ok '数据库已从 dump 恢复'
        & $py -m alembic -c $alembicIni upgrade head   # dump 078 -> 代码 head 对齐
        if($LASTEXITCODE -ne 0){ Write-Fail 'alembic upgrade head 失败（078 -> head 对齐）'; exit 1 }
        Write-Ok '迁移已对齐到代码 head'
        # 哨兵：镜像库必须含用户（至少 admin），count<1 说明恢复不完整
        $ucRaw = (& $psql -X -w -h 127.0.0.1 -p 5432 -U $dbUser -d $dbName -tAc 'select count(*) from "user"' | Out-String).Trim()
        $uc = 0; [void][int]::TryParse($ucRaw, [ref]$uc)
        if($uc -lt 1){ Write-Fail "恢复后镜像校验失败：user 计数='$ucRaw'（应 >=1，含 admin 等）"; exit 1 }
        Write-Ok "镜像校验通过：user 行数=$uc"
      } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
  } finally { Pop-Location }

  # ==========================================================
  Write-Step '7 注册五服务'
  $uvW = (Read-EnvMap $envPath)['UVICORN_WORKERS']; if(-not $uvW){ $uvW = '4' }
  $envs=@('APP_ENV=production','FASTAPI_DEBUG=false',"PYTHONPATH=$TargetDir",'PYTHONUTF8=1','PYTHONUNBUFFERED=1',"UVICORN_WORKERS=$uvW",'WEB_PORT=3000','WEB_HEALTH_SCHEME=http')
  $logDir = Join-Path $TargetDir 'logs'
  $redisPw = (Read-EnvMap $envPath)['REDIS_PASSWORD']
  $redisExe = Join-Path $RedisDir 'redis-server.exe'
  if(-not (Test-Path $redisExe)){ throw "未找到 $redisExe" }
  $cacheTpl = Join-Path $TargetDir 'config\redis.production.conf.template'
  if(-not (Test-Path $cacheTpl)){ $cacheTpl = Join-Path $TargetDir 'config\redis.production.conf' }
  $redisState=New-DeployPrivateDirectory (Join-Path $TargetDir 'redis-state')
  $cacheConf = Join-Path $TargetDir 'config\redis.windows-service.conf'
  New-DeployRedisConf $cacheTpl $cacheConf 'erp-redis' $redisState $redisPw
  $brokerConf = Join-Path $TargetDir 'config\redis-broker.conf'
  New-DeployRedisConf $brokerConf $brokerConf 'erp-redis-broker' $redisState $redisPw

  Install-NssmService $Nssm @{Name='erp-redis';Application=$redisExe;Parameters="`"$cacheConf`"";Directory=$RedisDir;Stdout=(Join-Path $logDir 'erp-redis.log');Stderr=(Join-Path $logDir 'erp-redis.log')}
  Assert-ServiceRegistered 'erp-redis'
  Install-NssmService $Nssm @{Name='erp-redis-broker';Application=$redisExe;Parameters="`"$brokerConf`"";Directory=$RedisDir;Stdout=(Join-Path $logDir 'erp-redis-broker.log');Stderr=(Join-Path $logDir 'erp-redis-broker.log')}
  Assert-ServiceRegistered 'erp-redis-broker'
  Install-NssmService $Nssm @{Name='erp-prod';Application=$py;Parameters='-m fastapi_app.core.prod_runner --no-arq';Directory=$TargetDir;Env=$envs;DependOn='erp-redis';Stdout=(Join-Path $logDir 'erp-prod.log');Stderr=(Join-Path $logDir 'erp-prod.log')}
  Assert-ServiceRegistered 'erp-prod'
  Install-NssmService $Nssm @{Name='erp-arq';Application=$py;Parameters='-m arq fastapi_app.core.arq_app.WorkerSettings';Directory=$TargetDir;Env=$envs;DependOn='erp-redis-broker';Stdout=(Join-Path $logDir 'erp-arq.log');Stderr=(Join-Path $logDir 'erp-arq.log')}
  Assert-ServiceRegistered 'erp-arq'
  Install-NssmService $Nssm @{Name='erp-web';Application=$nginxExe;Parameters="-p `"$TargetDir`" -c `"$nginxConf`" -e `"$logDir\nginx-error.log`"";Directory=$TargetDir;Stdout=(Join-Path $logDir 'erp-web.log');Stderr=(Join-Path $logDir 'erp-web.log')}
  Assert-ServiceRegistered 'erp-web'
  Write-Ok '五个 NSSM 服务注册完成'

  # ==========================================================
  Write-Step '8 启动五服务'
  foreach($svc in $five){ Start-ErpService $svc }

  # ==========================================================
  Write-Step '9 看门狗'
  $wdCmd = Join-Path $TargetDir 'scripts\ops\watchdog_task.cmd'
  if((Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -eq 'erp-watchdog' })){ throw '看门狗已存在，拒绝替换' }
  if(Test-Path $wdCmd){
    $wd=[IO.File]::ReadAllLines($wdCmd)
    for($i=0;$i -lt $wd.Count;$i++){
      if($wd[$i] -match '^\s*set\s+"PY='){ $wd[$i]="set `"PY=$py`"" }
    }
    [IO.File]::WriteAllLines($wdCmd, $wd, [Text.ASCIIEncoding]::new())   # .cmd 保持 ASCII，勿写 BOM
    Write-Ok 'watchdog_task.cmd：PY 已指向包内 runtime'
    $action='cmd.exe /c ' + $wdCmd
    # 不传 /F；如果同名任务在预检后出现，禁止确认覆盖。
    'N' | & $schtasks /Create /TN 'erp-watchdog' /TR $action /SC MINUTE /MO 5 /RU SYSTEM /RL HIGHEST | Out-Null
    if($LASTEXITCODE -ne 0){ throw '创建看门狗任务失败；不会覆盖既有任务' }
    Write-Ok '看门狗计划任务已注册'
  } else { Write-Warn '缺 scripts\ops\watchdog_task.cmd，跳过看门狗' }

  # ==========================================================
  . {
    Write-Step '10 验收'
    Start-Sleep -Seconds 15

    # ① 后端 5002 /api/health（轮询 ~45s，仍失败即 FAIL）
    $ready=$false
    for($i=0;$i -lt 9;$i++){
      try{ $r=Invoke-WebRequest "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 10; $ready=$true; break }catch{ Start-Sleep -Seconds 5 }
    }
    if($ready){ Write-Ok "后端 /api/health -> $($r.StatusCode)" }
    else { Write-Fail '后端 /api/health 未就绪（查 logs\erp-prod.log 与 logs\prod_runner.json）'; exit 1 }

    # ② curl 连本机 nginx，仍用正式主机名做 SNI/信任链校验；不跟随跳转，不使用代理或用户配置。
    $webReady=$false
    for($i=0;$i -lt 6;$i++){
      $status=& $curl -q --noproxy '*' --connect-to "${hUrl}:443:127.0.0.1:443" --silent --max-time 10 --output NUL --write-out '%{http_code}' "https://$hUrl/api/health"
      if($LASTEXITCODE -eq 0 -and $status -eq '200'){ $webReady=$true; break }
      Start-Sleep -Seconds 5
    }
    if(-not $webReady){ throw 'HTTPS 用户入口的系统证书校验或健康探测失败（预置 Windows 受信 CA；检查 nginx 日志）' }
    Write-Ok 'HTTPS 用户入口：证书验证及 200 健康探测通过'

    # ③ prod_runner.json ready/frontend_ok（轮询 ~30s，仍失败即 FAIL）
    $pr = Join-Path $TargetDir 'logs\prod_runner.json'
    $prReady=$false
    for($i=0;$i -lt 6;$i++){
      if(Test-Path $pr){
        try{ $j=Get-Content $pr -Raw | ConvertFrom-Json; if($j.ready -and $j.frontend_ok){ $prReady=$true; break } }catch{}
      }
      Start-Sleep -Seconds 5
    }
    if($prReady){ Write-Ok 'prod_runner.json：ready=true / frontend_ok=true' }
    else { Write-Fail "prod_runner.json 未就绪（ready/frontend_ok 未同时为真）：$pr"; exit 1 }

    # ④ ARQ 哨兵键（broker :6380，见 README §4.14④）（轮询 ~30s，仍失败即 FAIL）
    $envFinal = Read-EnvMap $envPath
    $brokerDb = 0
    if("$($envFinal['REDIS_BROKER_URL'])" -match 'rediss?://[^/]*/(\d+)'){ $brokerDb=[int]$Matches[1] }
    $arqOk=$false
    for($i=0;$i -lt 6;$i++){
      if(Test-ArqSentinel -RedisHost '127.0.0.1' -Port 6380 -Password $envFinal['REDIS_PASSWORD'] -Db $brokerDb){ $arqOk=$true; break }
      Start-Sleep -Seconds 5
    }
    if($arqOk){ Write-Ok 'ARQ 哨兵键在线（arq:queue:health-check @6380）' }
    else { Write-Fail 'ARQ 哨兵键缺失（arq:queue:health-check @6380）—— erp-arq 未在线，定时备份将静默停摆'; exit 1 }

    # ⑤ 运行模式探针（存在才跑；判定非 prod 即 FAIL）
    $probe=$null
    foreach($cand in @('scripts\diag\runtime_mode_probe.py','scripts\ops\runtime_mode_probe.py')){
      $p=Join-Path $TargetDir $cand
      if(Test-Path $p){ $probe=$p; break }
    }
    if($probe){
      $pvOut=Join-Path $work 'probe.out'; $pvErr=Join-Path $work 'probe.err'
      $pp=Start-Process -FilePath $py -ArgumentList @("`"$probe`"") -NoNewWindow -Wait -PassThru -RedirectStandardOutput $pvOut -RedirectStandardError $pvErr
      if($pp.ExitCode -ne 0){ Write-Warn "运行模式探针退出码 $($pp.ExitCode)（无法判定，见 $pvErr）——跳过" }
      else{
        try{
          $pv=((Get-Content $pvOut -Raw) | ConvertFrom-Json).verdict
          if("$pv" -like 'prod*'){ Write-Ok "运行模式探针：verdict=$pv" }
          else { Write-Fail "运行模式探针判定非 prod：verdict=$pv（查 logs\prod_runner.json 与启动参数）"; exit 1 }
        } catch { Write-Warn "运行模式探针输出无法解析：$($_.Exception.Message)——跳过" }
      }
    } else { Write-Warn '未找到 scripts\diag\runtime_mode_probe.py，跳过运行模式探针' }
  }
} finally {
  Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
  if($work){ Remove-DeployStagingDirectory $work }
}
Write-Ok "安装与验收完成：https://$hUrl/；按迁移物料处置要求处理加密源包"
