#Requires -Version 5.1
# 构建端：把本机（生产，只读）ERP 整套打成口令加密的离线便携包。
# 用法：powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\build_package.ps1 [-DryRun]
# 只读承诺：仅 pg_dump 快照 + 读文件；不停/启服务、不 npm、只写 OutDir。
# -DryRun：做完整编排自检（预检/排除/pg_dump/manifest），但容忍 deploy\binaries 缺失、
#          跳过 runtime 依赖安装与导入自检、跳过 tar+加密。真实构建须全跑（缺件/自检失败即 FAIL）。
# -EncryptKey：会进入 PowerShell 历史与进程列表；生产建议省略该参数、改用交互式隐藏输入。
[CmdletBinding()]
param(
  [string]$ProjectDir = 'D:\erp_system',
  [string]$PyDir = '',
  [string]$OutDir = 'D:\erp_portable',
  [string]$ServerIP = '192.168.1.97',
  [string]$EncryptKey = '',
  [switch]$SkipZip, [switch]$DryRun, [switch]$WithNodeModules
)
. (Join-Path $PSScriptRoot '_lib.ps1')
Write-Step "ERP 便携包构建"
if($DryRun){ Write-Warn '-DryRun：跳过 runtime 依赖安装/导入自检/打包加密，仅验证编排、排除与 dump' }
if(-not (Test-SafeOutDir $OutDir $ProjectDir)){ Write-Fail "危险 OutDir: $OutDir"; exit 1 }

# 预检
$need = @{
  '.env' = (Join-Path $ProjectDir '.env')
  'jwt私钥' = (Join-Path $ProjectDir 'config\jwt\private_v2.pem')
  '上传签名' = (Join-Path $ProjectDir 'config\uploads-signing.conf')
  '前端dist' = (Join-Path $ProjectDir 'frontend-vite\dist\index.html')
}
$miss = Test-Prereqs $need; if($miss){ Write-Fail ("缺少: " + ($miss -join ', ')); exit 1 }
$pgDump = Get-PgTool 'pg_dump.exe'; if(-not $pgDump){ Write-Fail '未找到 pg_dump（PG_TOOLS_BIN/PATH/约定目录，含18）'; exit 1 }
# dump 的 alembic_version 用 psql 读取（源机 .env 不保证有 DATABASE_URL，不能靠它连库）
$psql = Get-PgTool 'psql.exe'; if(-not $psql){ Write-Fail '未找到 psql（PG_TOOLS_BIN/PATH/约定目录，含18）'; exit 1 }
$binNeed = @{ 'PG安装器'='pg18*'; 'Redis'='Redis-x64-5.0.14.1*'; 'nginx'='nginx*zip'; 'nssm'='nssm*zip'; 'node'='node*.msi'; 'vcredist'='vc_redist*zip*' }
$binDir = Join-Path $PSScriptRoot 'binaries'
$binMiss=@(); foreach($k in $binNeed.Keys){ if(-not (Get-ChildItem $binDir -Filter $binNeed[$k] -ErrorAction SilentlyContinue)){ $binMiss+=$k } }
if($binMiss){
  if($DryRun){ Write-Warn ("deploy\binaries\ 缺: " + ($binMiss -join ', ') + "（-DryRun 容忍；真实构建此处 FAIL）") }
  else { Write-Fail ("deploy\binaries\ 缺: " + ($binMiss -join ', ') + " —— 见 deploy\README.md 下载清单"); exit 1 }
}
if(-not $PyDir){ foreach($c in @("$env:LOCALAPPDATA\Programs\Python\Python313","C:\Python313")){ if(Test-Path (Join-Path $c 'python.exe')){ $PyDir=$c; break } } }
if(-not $PyDir -or -not (Test-Path (Join-Path $PyDir 'python.exe'))){ Write-Fail '未找到系统 Python 3.13（-PyDir）'; exit 1 }

# git 清洁（不打包未提交改动）
Push-Location $ProjectDir
$dirty = (git status --porcelain); $head = (git rev-parse HEAD)
Pop-Location
if($dirty){ Write-Fail "工作区不干净，拒绝打包（先提交/清理）"; exit 1 }

# 组装
if(Test-Path $OutDir){ Remove-Item $OutDir -Recurse -Force }
foreach($s in 'app','runtime','settings','deploy','data','binaries','frontend'){ New-Item -ItemType Directory -Force -Path (Join-Path $OutDir $s) | Out-Null }

Write-Step '1/6 拷代码'
$xd = @((Join-Path $ProjectDir '.git'),(Join-Path $ProjectDir '.venv'),(Join-Path $ProjectDir 'logs'),
        (Join-Path $ProjectDir 'temp'),(Join-Path $ProjectDir 'backups'),(Join-Path $ProjectDir 'dist'),
        (Join-Path $ProjectDir '_ops'),(Join-Path $ProjectDir 'config\pgbouncer'))
# /XD 除构建垃圾外，须排除 AGENTS.md §7 的全部 AI 工具痕迹目录（15+），避免打进包
$aiTrail = @('.agent','.claude','.cursor','.graphflow','.graphflow-cache','graphflow-out','.trae','.qoder','.workbuddy','.reasonix','.superpowers','.codebuddy','.freebuff','.lean-ctx','.resultverify','.codeartsdoer','.zcode')
robocopy $ProjectDir (Join-Path $OutDir 'app') /E /XD @('node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache') $aiTrail @xd /XF @('*.pyc','*.pyo','*.log','*.tmp','*.pid','dsh-web-dump-config.txt','nul') /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if($WithNodeModules){ robocopy (Join-Path $ProjectDir 'frontend-vite\node_modules') (Join-Path $OutDir 'app\frontend-vite\node_modules') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null }

Write-Step '2/6 拷 runtime'
robocopy $PyDir (Join-Path $OutDir 'runtime\python313') /E /XD '__pycache__' /XF @('*.pyc','*.pyo') /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if($DryRun){
  Write-Warn 'DryRun：跳过 runtime 依赖安装（pip install base/dev/test/ocr）与导入自检'
} else {
  & (Join-Path $OutDir 'runtime\python313\python.exe') -m pip install -q -r (Join-Path $ProjectDir 'requirements\base.txt') -r (Join-Path $ProjectDir 'requirements\dev.txt') -r (Join-Path $ProjectDir 'requirements\test.txt') -r (Join-Path $ProjectDir 'requirements\ocr.txt')
  if($LASTEXITCODE -ne 0){ Write-Fail "runtime 依赖安装失败 exit=$LASTEXITCODE"; exit 1 }
  $smoke = & (Join-Path $OutDir 'runtime\python313\python.exe') -c "import fastapi,uvicorn,sqlalchemy,asyncpg,pytest,ruff;print('imports-ok')" 2>&1
  if($smoke -notmatch 'imports-ok'){ Write-Fail "runtime 自检失败: $smoke"; exit 1 }
}

Write-Step '3/6 拷前端 dist'
robocopy (Join-Path $ProjectDir 'frontend-vite\dist') (Join-Path $OutDir 'frontend\dist') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null

Write-Step '4/6 拷 settings + static + dump'
Copy-Item (Join-Path $ProjectDir '.env') (Join-Path $OutDir 'settings\.env') -Force
foreach($f in 'nginx-windows.conf','redis-broker.conf','security-headers.conf','log_policy.json','nssm-services.json'){ Copy-Item (Join-Path $ProjectDir "config\$f") (Join-Path $OutDir "settings\$f") -Force }
robocopy (Join-Path $ProjectDir 'config\jwt') (Join-Path $OutDir 'settings\jwt') /E /NFL /NDL /NJH /NJS /NP | Out-Null
Copy-Item (Join-Path $ProjectDir 'config\uploads-signing.conf') (Join-Path $OutDir 'settings\uploads-signing.conf') -Force
robocopy (Join-Path $ProjectDir 'static') (Join-Path $OutDir 'data\static') /E /NFL /NDL /NJH /NJS /NP | Out-Null
if(Test-Path $binDir){ foreach($f in (Get-ChildItem $binDir -File)){ Copy-Item $f.FullName (Join-Path $OutDir 'binaries') -Force } }
# install_package.ps1 由 Task 4 产出；此处缺失非致命（Task 4 后重建包即含）
$instSrc = Join-Path $PSScriptRoot 'install_package.ps1'
if(Test-Path $instSrc){ Copy-Item $instSrc (Join-Path $OutDir 'deploy\install_package.ps1') -Force }
else { Write-Warn 'install_package.ps1 尚未创建（Task 4），本次包内暂缺' }
$env:PGPASSWORD = (Read-EnvMap (Join-Path $ProjectDir '.env'))['DB_PASSWORD']
if(-not $env:PGPASSWORD){ Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue; Write-Fail '源机 .env 缺 DB_PASSWORD，无法 dump'; exit 1 }
& $pgDump -h localhost -p 5432 -U erp_app -d erp_system -Fc -f (Join-Path $OutDir 'data\erp_system.dump')
$dumpRc = $LASTEXITCODE
if($dumpRc -ne 0){ Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue; Write-Fail "pg_dump 失败 exit=$dumpRc"; exit 1 }
$dumpVer = "$(& $psql -h localhost -p 5432 -U erp_app -d erp_system -tAc 'select version_num from alembic_version')".Trim()
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
$dumpFile = Get-Item (Join-Path $OutDir 'data\erp_system.dump') -ErrorAction SilentlyContinue
if(-not $dumpFile -or $dumpFile.Length -le 0){ Write-Fail 'dump 文件缺失或为空'; exit 1 }
if(-not $dumpVer){ Write-Fail '未能从 dump 读取 alembic_version（psql 查询为空）'; exit 1 }

Write-Step '5/6 manifest + 打包'
$stamp=Get-Date -Format 'yyyyMMdd_HHmm'
$sb=@"
ERP Portable Package
built_at   : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
git_head   : $head
python     : $PyDir
dump_alembic_version : $dumpVer
target_ip  : $ServerIP
"@
[IO.File]::WriteAllText((Join-Path $OutDir 'manifest.txt'),$sb,[Text.UTF8Encoding]::new($false))

if(-not $SkipZip -and -not $DryRun){
  Write-Step '6/6 加密 + sha256'
  if($EncryptKey){ Write-Warn '-EncryptKey 会进入 PowerShell 历史与进程列表；建议省略改用交互式隐藏输入' }
  $tgz = Join-Path ([IO.Path]::GetDirectoryName($OutDir)) "erp_portable_$stamp.tar.gz"
  Push-Location (Split-Path $OutDir -Parent)
  & tar.exe -czf $tgz (Split-Path $OutDir -Leaf); $rc=$LASTEXITCODE; Pop-Location
  if($rc -ne 0){ Write-Fail "tar 失败 exit=$rc"; exit 1 }
  if(-not $EncryptKey){ $sec=Read-Host -AsSecureString '设置便携包加密口令'; $EncryptKey=[Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }
  $enc = "$tgz.enc"; Protect-File -InPath $tgz -OutPath $enc -Password $EncryptKey; Remove-Item $tgz -Force
  ([IO.File]::ReadAllBytes($enc) | ForEach-Object { $_.ToString('x2') }) -join '' | Set-Content "$enc.sha256"
  Write-Ok "产出 $enc"
}
Write-Ok 'BUILD COMPLETE'
