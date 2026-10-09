#Requires -Version 5.1
# ============================================================
# ERP 离线便携包 —— 安装端（在**目标机**以管理员运行）
# 用法：
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File install_package.ps1 `
#       -Package D:\erp_portable_20261008_1200.tar.gz.enc -ServerIP 192.168.1.97
#
# 分阶段装配（提权 → 解包 → 基础软件 → 建库 → 部署 → .env → 数据 → 五服务 →
# 防火墙 → 看门狗 → 验收），幂等、失败可续跑、finally 清 %TEMP% 明文与 PGPASSWORD。
# 目标机路径默认 D:\erp_system（与源机同路径）；-Force 覆盖已有部署；-Blank 走空库引导。
# 依赖同目录 _lib.ps1（dot-source）。
# ============================================================
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Package,
  [string]$TargetDir = 'D:\erp_system',
  [string]$ServerIP = '192.168.1.97',
  [string]$PgSuperPassword = '',
  [string]$NginxDir = 'C:\nginx',
  [string]$RedisDir = 'C:\Redis',
  [string]$Nssm = 'C:\nssm\nssm.exe',
  [string]$EncryptKey = '',
  [string]$AdminPassword = '',
  [switch]$Force, [switch]$Blank, [switch]$SkipVerify
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
function New-DeployRedisConf([string]$SrcConf,[string]$DstConf,[string]$Name,[string]$RedisRoot){
  # 去掉任何**生效**的 requirepass 行；口令只经 --requirepass 注入，绝不写进 .conf。
  # 并把 dir/logfile 指向部署目录（非默认 RedisDir 时避免脏数据/日志落到 C:\Redis）。
  # ⚠️ 路径一律用**正斜杠**：Redis 把反斜杠当转义符，单反斜杠的 "C:\Redis\data"
  #    会被解析成 C:Redisdata → 启动报 Can't chdir to 'C:Redisdata' → NSSM 崩溃循环置 Paused。
  $root = $RedisRoot -replace '\\','/'
  $dataDir = "$root/data"
  New-Item -ItemType Directory -Force -Path (Join-Path $RedisRoot 'data') | Out-Null
  $lines=[IO.File]::ReadAllLines($SrcConf,[Text.UTF8Encoding]::new($false))
  $out = $lines | Where-Object { $_ -notmatch '^\s*requirepass(\s|$)' } | ForEach-Object {
    if($_ -match '^\s*dir\s'){ "dir $dataDir" }
    elseif($_ -match '^\s*logfile\s'){ "logfile `"$root/$Name.log`"" }
    else { $_ }
  }
  # 防回归：生成的 dir/logfile 行不得残留反斜杠（Redis 会当转义符）
  foreach($ln in $out){ if($ln -match '^\s*(dir|logfile)\s' -and $ln.Contains('\')){ Write-Fail "Redis conf 的 dir/logfile 含反斜杠（Redis 会当转义符）：$ln"; exit 1 } }
  [IO.File]::WriteAllText($DstConf, (($out -join "`r`n") + "`r`n"), [Text.UTF8Encoding]::new($false))
}
function New-BlankAdmin([string]$Py,[string]$Psql,[string]$TargetDir,[string]$WorkDir,[string]$DbUser,[string]$DbName,[string]$DbPw,[string]$AdminPassword){
  # 空库引导：项目无内置用户种子，必须建一个超管，否则装完无法登录（README §4.10B）
  $pw = $AdminPassword
  if(-not $pw){
    $sec = Read-Host -AsSecureString '新 admin 口令（Argon2id 哈希后写入）'
    $pw = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
  }
  if(-not $pw){ Write-Fail 'admin 口令为空，无法建用户'; exit 1 }
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
    & $Psql -h localhost -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -f $sqlFile
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

$work = Join-Path $env:TEMP ("erp_pkg_" + [guid]::NewGuid().ToString('N'))
try {
  # ==========================================================
  Write-Step '0 提权 + 参数'
  if(-not (Test-Admin)){ Write-Fail '必须以管理员运行'; exit 1 }
  if(-not (Test-HostLiteral $ServerIP)){ Write-Fail "非法 ServerIP（需 IPv4 / IPv6 / 域名）: $ServerIP"; exit 1 }
  if(-not (Test-Path -LiteralPath $Package)){ Write-Fail "找不到安装包: $Package"; exit 1 }
  if(-not (Get-Command tar.exe -ErrorAction SilentlyContinue)){ Write-Fail '未找到 tar.exe（需 Win10 1809+）'; exit 1 }
  $drive=([IO.Path]::GetPathRoot($TargetDir)).TrimEnd('\',':')
  $free=(Get-PSDrive -Name $drive).Free
  if($free -lt 8GB){ Write-Fail "目标盘可用空间不足 8GB（实 $([math]::Round($free/1GB,1))GB）"; exit 1 }
  # 命令行明文口令会进 PowerShell 历史与进程列表——与构建端同一告警
  $cliSecrets=@(); if($EncryptKey){ $cliSecrets+='-EncryptKey' }; if($PgSuperPassword){ $cliSecrets+='-PgSuperPassword' }; if($AdminPassword){ $cliSecrets+='-AdminPassword' }
  if($cliSecrets.Count -gt 0){ Write-Warn (($cliSecrets -join '/') + ' 会进入 PowerShell 历史与进程列表；建议省略改用交互式隐藏输入') }
  if(-not $EncryptKey){ $sec=Read-Host -AsSecureString '便携包口令'; $EncryptKey=[Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }

  # ==========================================================
  Write-Step '1 解密解包'
  # 包完整性：随包带的 .sha256 侧车先比对（spec §6.2）；缺失仅告警不硬失败
  $shaSide = "$Package.sha256"
  if(Test-Path -LiteralPath $shaSide){
    $want=([IO.File]::ReadAllText($shaSide)).Trim().ToLower()
    $got=(Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLower()
    if(-not $want -or $want -ne $got){
      Write-Fail "包 sha256 校验失败（期望 '$want'，实算 '$got'）——包损坏或被篡改"; exit 1
    }
    Write-Ok '包 sha256 校验通过'
  } else {
    Write-Warn "未找到 $shaSide，跳过包完整性校验（建议随包携带 .sha256）"
  }
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  $tgz = Join-Path $work 'p.tar.gz'
  try {
    Unprotect-File -InPath $Package -OutPath $tgz -Password $EncryptKey
  } catch [System.Security.Cryptography.CryptographicException] {
    Write-Fail '口令错误或包损坏（解密失败）'; exit 1
  }
  & tar.exe -xzf $tgz -C $work
  if($LASTEXITCODE -ne 0){ throw 'tar 解包失败' }
  $pkgRoot = (Get-ChildItem $work -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'manifest.txt') } | Select-Object -First 1)
  if(-not $pkgRoot){ throw '包内未找到 manifest.txt（口令错误或包损坏）' }
  $binDir = Join-Path $pkgRoot.FullName 'binaries'
  Write-Ok "解包到 $($pkgRoot.FullName)"

  # postgres 超级用户口令：优先命令行，其次包内 settings\.env 的 PG_SUPER_PASSWORD，最后交互式隐藏输入
  if(-not $PgSuperPassword){
    $pgEnv = Read-EnvMap (Join-Path $pkgRoot.FullName 'settings\.env')
    if($pgEnv['PG_SUPER_PASSWORD']){ $PgSuperPassword=$pgEnv['PG_SUPER_PASSWORD']; Write-Ok '已从包内 settings\.env 取用 PG_SUPER_PASSWORD' }
    else { $sec=Read-Host -AsSecureString 'postgres 超级用户口令'; $PgSuperPassword=[Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }
  }
  if(-not $PgSuperPassword){ Write-Fail 'postgres 超级用户口令为空（-PgSuperPassword / 包内 PG_SUPER_PASSWORD / 交互式输入）'; exit 1 }

  # ---- 覆盖守卫：无 -Force 时拒绝 ----
  # 诚实边界：基础软件步骤是幂等「已装跳过」；若本步之后中途失败，可能已装过 PostgreSQL/Redis/nginx…
  # 故只承诺「不覆盖既有库/服务」，不声称「未改动任何现场」。
  $five = @('erp-redis','erp-redis-broker','erp-prod','erp-arq','erp-web')
  $existingSvc = @($five | Where-Object { Get-Service -Name $_ -ErrorAction SilentlyContinue })
  $targetExists = Test-Path -LiteralPath $TargetDir

  # 库存在性预检：仅在能定位 psql 时做（无 psql 则跳过，留待第 3 步判定）
  $dbNameGuard = 'erp_system'
  $pgEnvMap = Read-EnvMap (Join-Path $pkgRoot.FullName 'settings\.env')
  if($pgEnvMap['DB_NAME']){ $dbNameGuard = $pgEnvMap['DB_NAME'] }
  $dbExistsGuard = $false
  $psqlGuard = Get-PgTool 'psql.exe'
  if($psqlGuard){
    try{
      $env:PGPASSWORD = $PgSuperPassword
      $q = (& $psqlGuard -h localhost -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbNameGuard'" | Out-String).Trim()
      if($q -eq '1'){ $dbExistsGuard = $true }
    } catch { } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
  } else {
    Write-Warn '未定位到 psql，跳过建库前「库已存在」预检（第 3 步仍会判定）'
  }

  $conflicts=@()
  if($targetExists){ $conflicts += $TargetDir }
  if($existingSvc.Count -gt 0){ $conflicts += ($existingSvc -join ',') }
  if($dbExistsGuard){ $conflicts += "库 $dbNameGuard" }
  if(-not $Force -and $conflicts.Count -gt 0){
    Write-Fail ("已存在: " + ($conflicts -join '; ') + "；覆盖请加 -Force（不会覆盖既有库/服务；基础软件可能已先装）")
    exit 1
  }
  if($Force -and $conflicts.Count -gt 0){
    Write-Warn ("-Force：将覆盖 " + ($conflicts -join '; '))
  }

  # ==========================================================
  Write-Step '2 装基础软件（已装跳过）'
  function Find-Bin([string]$Pattern){
    @(Get-ChildItem -Path $binDir -Filter $Pattern -File -ErrorAction SilentlyContinue) | Sort-Object Name | Select-Object -First 1
  }

  # VC++ 运行库（1638=已装更高版本；3010=需重启，均判成功）
  $vc = Find-Bin 'vc_redist*'
  if($vc){
    $vcExe = $vc
    if($vc.Extension -ieq '.zip'){
      $vcDir = Join-Path $work 'vc'; Expand-Archive -LiteralPath $vc.FullName -DestinationPath $vcDir -Force
      $vcExe = @(Get-ChildItem $vcDir -Recurse -Filter 'vc_redist*.exe' -File | Select-Object -First 1)[0]
    }
    if($vcExe){
      $p=Start-Process -FilePath $vcExe.FullName -ArgumentList '/install','/quiet','/norestart' -Wait -PassThru
      if($p.ExitCode -in 0,1638,3010){ Write-Ok "VC++ 运行库就绪 (exit=$($p.ExitCode))" }
      else { Write-Warn "VC++ 运行库安装返回 $($p.ExitCode)（可继续）" }
    }
  } else { Write-Warn 'deploy\binaries 无 vc_redist（若已装可忽略）' }

  # PostgreSQL 18（检测 postgresql* 服务或 psql 是否存在，缺才静默装）
  $pgSvc = @(Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue)
  $pgInstalled = ($pgSvc.Count -gt 0) -or [bool](Get-PgTool 'psql.exe')
  if($pgInstalled){
    Write-Ok 'PostgreSQL 已安装（跳过）'
  } else {
    $pgInst = Find-Bin 'pg*'
    if(-not $pgInst){ Write-Fail '未找到 PostgreSQL 安装器（deploy\binaries\pg18*）。官方：https://www.enterprisedb.com/downloads/postgres-postgresql-downloads'; exit 1 }
    $p=Start-Process -FilePath $pgInst.FullName -ArgumentList '--mode','unattended','--superpassword',$PgSuperPassword,'--serverport','5432' -Wait -PassThru
    if($p.ExitCode -ne 0){ Write-Fail "PostgreSQL 静默安装失败 exit=$($p.ExitCode)"; exit 1 }
    foreach($s in @(Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue)){ if($s.Status -ne 'Running'){ Start-Service $s -ErrorAction SilentlyContinue } }
    Start-Sleep -Seconds 3
    Write-Ok 'PostgreSQL 18 已静默安装'
  }

  # Redis（tporadowski 发行版，解压到 RedisDir）
  if(Test-Path (Join-Path $RedisDir 'redis-server.exe')){
    Write-Ok 'Redis 已就位（跳过）'
  } else {
    $rz = Find-Bin 'Redis-x64-*'
    if(-not $rz){ Write-Fail '未找到 Redis 包（deploy\binaries\Redis-x64-5.0.14.1*）。官方：https://github.com/tporadowski/redis/releases'; exit 1 }
    New-Item -ItemType Directory -Force -Path $RedisDir | Out-Null
    Expand-Archive -LiteralPath $rz.FullName -DestinationPath $RedisDir -Force
    if(-not (Test-Path (Join-Path $RedisDir 'redis-server.exe'))){ Write-Fail 'Redis 解压后未见 redis-server.exe'; exit 1 }
    Write-Ok "Redis 解压到 $RedisDir"
  }

  # nginx（zip 内常含一层 nginx-<ver>\ 目录）
  if(Test-Path (Join-Path $NginxDir 'nginx.exe')){
    Write-Ok 'nginx 已就位（跳过）'
  } else {
    $ng = Find-Bin 'nginx*.zip'
    if(-not $ng){ Write-Fail '未找到 nginx 压缩包（deploy\binaries\nginx*zip）。官方：https://nginx.org/en/download.html'; exit 1 }
    $ngTmp = Join-Path $work 'nginx'; Expand-Archive -LiteralPath $ng.FullName -DestinationPath $ngTmp -Force
    $inner = @(Get-ChildItem $ngTmp -Directory)
    $src = if($inner.Count -gt 0){ $inner[0].FullName } else { $ngTmp }
    New-Item -ItemType Directory -Force -Path $NginxDir | Out-Null
    robocopy $src $NginxDir /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if(-not (Test-Path (Join-Path $NginxDir 'nginx.exe'))){ Write-Fail 'nginx 解压后未见 nginx.exe'; exit 1 }
    Write-Ok "nginx 解压到 $NginxDir"
  }

  # NSSM（zip 内含 win64\ 与 win32\，取 win64）
  if(Test-Path $Nssm){
    Write-Ok 'nssm 已就位（跳过）'
  } else {
    $nz = Find-Bin 'nssm*.zip'
    if(-not $nz){ Write-Fail '未找到 nssm 包（deploy\binaries\nssm*zip）。官方：https://nssm.cc/download'; exit 1 }
    $nzTmp = Join-Path $work 'nssm'; Expand-Archive -LiteralPath $nz.FullName -DestinationPath $nzTmp -Force
    $nx = @(Get-ChildItem $nzTmp -Recurse -Filter 'nssm.exe' -File | Sort-Object FullName -Descending | Select-Object -First 1)
    if($nx.Count -eq 0){ Write-Fail 'nssm 包内未见 nssm.exe'; exit 1 }
    New-Item -ItemType Directory -Force -Path (Split-Path $Nssm -Parent) | Out-Null
    Copy-Item $nx[0].FullName $Nssm -Force
    Write-Ok "nssm 就位：$Nssm"
  }

  # Node（仅前端开发需要；生产只需 dist，缺则 WARN）
  $nodeOk = [bool](Get-Command node.exe -ErrorAction SilentlyContinue) -or (Test-Path (Join-Path ${env:ProgramFiles} 'nodejs\node.exe'))
  if($nodeOk){
    Write-Ok 'Node 已安装（跳过）'
  } else {
    $msi = Find-Bin 'node*.msi'
    if($msi){
      $p=Start-Process msiexec.exe -ArgumentList '/i',"`"$($msi.FullName)`"",'/qn','/norestart' -Wait -PassThru
      if($p.ExitCode -in 0,1638,3010){ Write-Ok "Node 安装完成 (exit=$($p.ExitCode))" } else { Write-Warn "Node 安装返回 $($p.ExitCode)" }
    } else { Write-Warn '未找到 Node msi（deploy\binaries\node*.msi）—— 目标机不做前端开发可忽略' }
  }

  # ==========================================================
  Write-Step '3 建库'
  $psql = Get-PgTool 'psql.exe'; if(-not $psql){ Write-Fail '未找到 psql（PostgreSQL 是否安装成功？）'; exit 1 }
  $envMap = Read-EnvMap (Join-Path $pkgRoot.FullName 'settings\.env')
  $dbPw = $envMap['DB_PASSWORD']; if(-not $dbPw){ Write-Fail '包内 .env 缺 DB_PASSWORD'; exit 1 }
  $dbUser = if($envMap['DB_USER']) { $envMap['DB_USER'] } else { 'erp_app' }
  $dbName = if($envMap['DB_NAME']) { $envMap['DB_NAME'] } else { 'erp_system' }
  $env:PGPASSWORD = $PgSuperPassword
  try {
    $esc = $dbPw.Replace("'","''")
    $roleExists = (& $psql -h localhost -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$dbUser'" | Out-String).Trim()
    if($roleExists -ne '1'){
      & $psql -h localhost -U postgres -d postgres -c "CREATE ROLE $dbUser LOGIN PASSWORD '$esc'" | Out-Null
      if($LASTEXITCODE -ne 0){ Write-Fail 'CREATE ROLE 失败'; exit 1 }
      Write-Ok "角色 $dbUser 已创建"
    } else {
      & $psql -h localhost -U postgres -d postgres -c "ALTER ROLE $dbUser LOGIN PASSWORD '$esc'" | Out-Null
      Write-Ok "角色 $dbUser 已存在，口令已同步"
    }
    $dbExists = (& $psql -h localhost -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbName'" | Out-String).Trim()
    if($dbExists -ne '1'){
      & $psql -h localhost -U postgres -d postgres -c "CREATE DATABASE $dbName WITH OWNER = $dbUser ENCODING = 'UTF8' TEMPLATE = template0" | Out-Null
      if($LASTEXITCODE -ne 0){ Write-Fail 'CREATE DATABASE 失败'; exit 1 }
      Write-Ok "数据库 $dbName 已创建（owner=$dbUser）"
    } elseif($Force){
      Write-Warn "库 $dbName 已存在，-Force：重建"
      & $psql -h localhost -U postgres -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$dbName' AND pid<>pg_backend_pid()" | Out-Null
      & $psql -h localhost -U postgres -d postgres -c "DROP DATABASE $dbName" | Out-Null
      if($LASTEXITCODE -ne 0){ Write-Fail 'DROP DATABASE 失败'; exit 1 }
      & $psql -h localhost -U postgres -d postgres -c "CREATE DATABASE $dbName WITH OWNER = $dbUser ENCODING = 'UTF8' TEMPLATE = template0" | Out-Null
      if($LASTEXITCODE -ne 0){ Write-Fail 'CREATE DATABASE（重建）失败'; exit 1 }
      Write-Ok "数据库 $dbName 已重建"
    } else {
      Write-Fail "$dbName 已存在；覆盖请加 -Force（不会覆盖既有库/服务）"; exit 1
    }
  } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }

  # ==========================================================
  Write-Step '4 部署文件'
  if(Test-Path -LiteralPath $TargetDir){
    # 覆盖前：停并移除旧的五服务
    foreach($n in $five){
      $s=Get-Service -Name $n -ErrorAction SilentlyContinue
      if($s -and $s.Status -ne 'Stopped'){ & $Nssm stop $n | Out-Null }
    }
    foreach($n in $five){
      if(Get-Service -Name $n -ErrorAction SilentlyContinue){ & $Nssm remove $n confirm | Out-Null }
    }
    Write-Ok '旧服务已停止并移除（-Force 覆盖）'
  }
  $copies = @(
    @{ Src='app';           Dst=$TargetDir },
    @{ Src='runtime';       Dst=(Join-Path $TargetDir 'runtime') },
    @{ Src='frontend\dist'; Dst=(Join-Path $TargetDir 'frontend-vite\dist') }
  )
  foreach($c in $copies){
    $src = Join-Path $pkgRoot.FullName $c.Src
    if(-not (Test-Path $src)){ Write-Fail "包内缺少 $($c.Src)"; exit 1 }
    New-Item -ItemType Directory -Force -Path $c.Dst | Out-Null
    robocopy $src $c.Dst /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：$($c.Src)"; exit 1 }
  }
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
  Write-Step '5 .env 改写'
  # 主机字面量：IPv6 需两种写法（TrustedHost 取带方括号、WS 的 urlparse 取裸形式）；域名/IPv4 一种即可
  $hBare = $ServerIP.Trim().Trim('[',']')
  $is6   = Test-IsIPv6Literal $ServerIP
  $hUrl  = if($is6){ "[$hBare]" } else { $hBare }
  Add-EnvListItemJson  $envPath 'ALLOWED_HOSTS' $hUrl
  if($is6){ Add-EnvListItemJson $envPath 'ALLOWED_HOSTS' $hBare }
  # CORS_ORIGINS 同时给 https（公网/TLS）与 http（内网私网）；生产过滤器会自行剔除公网 http 源
  Add-EnvListItemComma $envPath 'CORS_ORIGINS' "https://${hUrl}:3000"
  Add-EnvListItemComma $envPath 'CORS_ORIGINS' "http://${hUrl}:3000"
  # WS_ALLOWED_ORIGINS 是 host:port（不带 scheme）；IPv6 两种写法都加
  Add-EnvListItemComma $envPath 'WS_ALLOWED_ORIGINS' "${hUrl}:3000"
  if($is6){ Add-EnvListItemComma $envPath 'WS_ALLOWED_ORIGINS' "${hBare}:3000" }
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

  # nginx conf：根路径改写 + 注释 443 块 + mime.types 路径，然后建 temp 目录并 nginx -t
  $nginxConf = Join-Path $TargetDir 'config\nginx-windows.conf'
  $newRoot = ($TargetDir -replace '\\','/')
  $cnt = Update-NginxConf -ConfPath $nginxConf -OldRoot 'D:/erp_system' -NewRoot $newRoot -NginxDir $NginxDir
  Write-Ok "nginx conf 已改写（替换计数=$cnt，443 块已注释，3000 块由 443 派生为 HTTP 入口）"
  New-NginxTempDirs $TargetDir
  $nginxExe = Join-Path $NginxDir 'nginx.exe'
  if(Test-Path $nginxExe){
    & $nginxExe -p $TargetDir -c $nginxConf -t   # 输出走 stderr 直显；勿重定向（EAP=Stop 下会终止）
    if($LASTEXITCODE -ne 0){ Write-Fail 'nginx -t 校验失败（检查 config\nginx-windows.conf）'; exit 1 }
    Write-Ok 'nginx -t 通过'
  } else { Write-Warn "未找到 $nginxExe，跳过 nginx -t" }

  # ==========================================================
  Write-Step '6 uploads-signing.conf'
  $secret = (Read-EnvMap $envPath)['UPLOAD_URL_SIGNING_SECRET']
  if(-not $secret){ Write-Fail '.env 缺 UPLOAD_URL_SIGNING_SECRET，无法生成 uploads-signing.conf'; exit 1 }
  # 与 config/uploads-signing.conf(.example) 逐字对齐：secret 前有一个字面空格
  [IO.File]::WriteAllText((Join-Path $TargetDir 'config\uploads-signing.conf'), "secure_link_md5 `"`$arg_st`$uri $secret`";", [Text.UTF8Encoding]::new($false))
  Write-Ok 'uploads-signing.conf 已生成'

  # ==========================================================
  Write-Step '7 数据'
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
      New-BlankAdmin -Py $py -Psql $psql -TargetDir $TargetDir -WorkDir $work -DbUser $dbUser -DbName $dbName -DbPw $dbPw -AdminPassword $AdminPassword
    } else {
      $dump = Join-Path $pkgRoot.FullName 'data\erp_system.dump'
      if(-not (Test-Path $dump)){ Write-Fail "包内缺 data\erp_system.dump: $dump"; exit 1 }
      $pgrestore = Get-PgTool 'pg_restore.exe'
      if(-not $pgrestore){ Write-Fail '未找到 pg_restore.exe（PostgreSQL 客户端工具是否安装成功？）'; exit 1 }
      $env:PGPASSWORD = $dbPw
      try {
        # 输出落文件（不走本进程 stderr 重定向——EAP=Stop 下会终止）；非零即致命
        $rcOut = Join-Path $work 'pg_restore.out'
        $rcErr = Join-Path $work 'pg_restore.err'
        $proc = Start-Process -FilePath $pgrestore -ArgumentList @('-h','localhost','-U',$dbUser,'-d',$dbName,'--no-owner','--no-privileges','-j','4',"`"$dump`"") -NoNewWindow -Wait -PassThru -RedirectStandardOutput $rcOut -RedirectStandardError $rcErr
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
        $ucRaw = (& $psql -h localhost -U $dbUser -d $dbName -tAc 'select count(*) from "user"' | Out-String).Trim()
        $uc = 0; [void][int]::TryParse($ucRaw, [ref]$uc)
        if($uc -lt 1){ Write-Fail "恢复后镜像校验失败：user 计数='$ucRaw'（应 >=1，含 admin 等）"; exit 1 }
        Write-Ok "镜像校验通过：user 行数=$uc"
      } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
  } finally { Pop-Location }

  # ==========================================================
  Write-Step '8 注册五服务'
  $uvW = (Read-EnvMap $envPath)['UVICORN_WORKERS']; if(-not $uvW){ $uvW = '4' }
  $envs=@('APP_ENV=production','FASTAPI_DEBUG=false',"PYTHONPATH=$TargetDir",'PYTHONUTF8=1','PYTHONUNBUFFERED=1',"UVICORN_WORKERS=$uvW")
  $logDir = Join-Path $TargetDir 'logs'
  $redisPw = (Read-EnvMap $envPath)['REDIS_PASSWORD']
  if(-not $redisPw){ Write-Warn '.env 无 REDIS_PASSWORD —— Redis 将无认证启动（生产不建议）' }
  $redisExe = Join-Path $RedisDir 'redis-server.exe'
  if(-not (Test-Path $redisExe)){ Write-Fail "未找到 $redisExe（基础软件步骤失败？）"; exit 1 }

  # --- redis conf 落位：去 requirepass，口令经 --requirepass 注入 ---
  $cacheTpl = Join-Path $TargetDir 'config\redis.production.conf.template'
  if(-not (Test-Path $cacheTpl)){ $cacheTpl = Join-Path $TargetDir 'config\redis.production.conf' }
  if(-not (Test-Path $cacheTpl)){ Write-Fail '缺 config\redis.production.conf(.template)，无法生成缓存实例 conf'; exit 1 }
  $cacheConf = Join-Path $RedisDir 'redis.windows-service.conf'
  New-DeployRedisConf $cacheTpl $cacheConf 'erp-redis' $RedisDir
  $brokerConf = Join-Path $TargetDir 'config\redis-broker.conf'
  if(-not (Test-Path $brokerConf)){ Write-Fail "缺 $brokerConf"; exit 1 }
  New-DeployRedisConf $brokerConf $brokerConf 'erp-redis-broker' $RedisDir
  # 口令加引号：不带引号时含空格/特殊字符的口令会被 NSSM 拆成多个参数，
  # requirepass 只吃到第一段，实际口令与应用侧 .env 不一致（连不上）。
  $authArg = if($redisPw){ ('--requirepass "{0}"' -f ($redisPw -replace '"','\"')) } else { '' }

  # 先装 Redis（erp-prod/arq 依赖其存在——SCM 拒绝依赖不存在的服务）
  Install-NssmService $Nssm @{Name='erp-redis';Application=$redisExe;Parameters=("$cacheConf $authArg").Trim();Directory=$RedisDir;Stdout=(Join-Path $logDir 'erp-redis.log');Stderr=(Join-Path $logDir 'erp-redis.log')}
  Assert-ServiceRegistered 'erp-redis'
  Install-NssmService $Nssm @{Name='erp-redis-broker';Application=$redisExe;Parameters=("$brokerConf $authArg").Trim();Directory=$RedisDir;Stdout=(Join-Path $logDir 'erp-redis-broker.log');Stderr=(Join-Path $logDir 'erp-redis-broker.log')}
  Assert-ServiceRegistered 'erp-redis-broker'

  Install-NssmService $Nssm @{Name='erp-prod';Application=$py;Parameters='-m fastapi_app.core.prod_runner --no-arq';Directory=$TargetDir;Env=$envs;DependOn='erp-redis';Stdout=(Join-Path $logDir 'erp-prod.log');Stderr=(Join-Path $logDir 'erp-prod.log')}
  Assert-ServiceRegistered 'erp-prod'
  Install-NssmService $Nssm @{Name='erp-arq';Application=$py;Parameters='-m arq fastapi_app.core.arq_app.WorkerSettings';Directory=$TargetDir;Env=$envs;DependOn='erp-redis-broker';Stdout=(Join-Path $logDir 'erp-arq.log');Stderr=(Join-Path $logDir 'erp-arq.log')}
  Assert-ServiceRegistered 'erp-arq'
  Install-NssmService $Nssm @{Name='erp-web';Application=$nginxExe;Parameters="-p $TargetDir -c $nginxConf -e $logDir\nginx-error.log";Directory=$TargetDir;Stdout=(Join-Path $logDir 'erp-web.log');Stderr=(Join-Path $logDir 'erp-web.log')}
  Assert-ServiceRegistered 'erp-web'
  Write-Ok '五个 NSSM 服务注册完成'

  # ==========================================================
  Write-Step '9 防火墙 + 启停'
  if(-not (Get-NetFirewallRule -DisplayName 'erp-web-3000' -ErrorAction SilentlyContinue)){
    New-NetFirewallRule -DisplayName 'erp-web-3000' -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow | Out-Null
    Write-Ok '已放行入站 TCP 3000'
  } else { Write-Ok '防火墙规则 erp-web-3000 已存在（跳过）' }
  foreach($svc in 'erp-redis','erp-redis-broker','erp-prod','erp-arq','erp-web'){ Start-ErpService $svc }

  # ==========================================================
  Write-Step '10 看门狗'
  $wdCmd = Join-Path $TargetDir 'scripts\ops\watchdog_task.cmd'
  if(Test-Path $wdCmd){
    $wd=[IO.File]::ReadAllLines($wdCmd)
    for($i=0;$i -lt $wd.Count;$i++){
      if($wd[$i] -match '^\s*set\s+"PY='){ $wd[$i]="set `"PY=$py`"" }
    }
    [IO.File]::WriteAllLines($wdCmd, $wd, [Text.ASCIIEncoding]::new())   # .cmd 保持 ASCII，勿写 BOM
    Write-Ok 'watchdog_task.cmd：PY 已指向包内 runtime'
    $wdInstaller = Join-Path $TargetDir 'scripts\ops\install_watchdog_task.ps1'
    if(Test-Path $wdInstaller){
      & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wdInstaller
      if($LASTEXITCODE -ne 0){ Write-Warn "看门狗计划任务注册返回 $LASTEXITCODE（可稍后手工注册）" } else { Write-Ok '看门狗计划任务已注册' }
    } else { Write-Warn '缺 install_watchdog_task.ps1，跳过计划任务注册' }
  } else { Write-Warn '缺 scripts\ops\watchdog_task.cmd，跳过看门狗' }

  # ==========================================================
  if(-not $SkipVerify){
    Write-Step '11 验收'
    Start-Sleep -Seconds 15

    # ① 后端 5002 /api/health（轮询 ~45s，仍失败即 FAIL）
    $ready=$false
    for($i=0;$i -lt 9;$i++){
      try{ $r=Invoke-WebRequest "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 10; $ready=$true; break }catch{ Start-Sleep -Seconds 5 }
    }
    if($ready){ Write-Ok "后端 /api/health -> $($r.StatusCode)" }
    else { Write-Fail '后端 /api/health 未就绪（查 logs\erp-prod.log 与 logs\prod_runner.json）'; exit 1 }

    # ② 用户入口 3000/api/health（轮询 ~30s，仍失败即 FAIL——半可用不许报成功）
    $webReady=$false
    for($i=0;$i -lt 6;$i++){
      try{ $r2=Invoke-WebRequest "http://127.0.0.1:3000/api/health" -UseBasicParsing -TimeoutSec 10; $webReady=$true; break }catch{ Start-Sleep -Seconds 5 }
    }
    if($webReady){ Write-Ok "用户入口 :3000 -> $($r2.StatusCode)" }
    else { Write-Fail '用户入口 http://127.0.0.1:3000/api/health 未就绪（查 logs\erp-web.log 与 config\nginx-windows.conf）'; exit 1 }

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
  Write-Ok "完成：内网 http://${hUrl}:3000 ；若前置 TLS（自签/域名）则用 https://${hUrl}:3000  （请立即删除源包并确认 %TEMP% 已清）"
} finally {
  if(Test-Path $work){ Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
  Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
