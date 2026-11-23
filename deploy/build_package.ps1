#Requires -Version 5.1
# 构建端：把本机（生产，只读）ERP 整套打成口令加密的离线便携包。
# 用法：powershell.exe -NoProfile -File deploy\build_package.ps1 [-DryRun]
# 源应用和数据库只读；受限 ACL 暂存，发布目录只保留加密包和摘要。
# -DryRun 只做前置检查，不组装、不查询数据库、不写文件。
[CmdletBinding()]
param(
  [string]$ProjectDir = 'D:\erp_system',
  [string]$PyDir = '',
  [string]$OutDir = 'D:\erp_portable',
  [string]$ServerIP = '192.168.1.97',
  [switch]$SkipZip, [switch]$DryRun, [switch]$WithNodeModules
)
. (Join-Path $PSScriptRoot '_lib.ps1')
Write-Step "ERP 便携包构建"
if($SkipZip){ throw '已禁用 SkipZip，不允许导出未加密便携包' }
$ProjectDir=Assert-LocalDeploymentPath $ProjectDir
$publishDir=Assert-LocalDeploymentPath $OutDir
if(-not (Test-SafeOutDir $publishDir $ProjectDir) -or -not (Test-Path -LiteralPath $publishDir -PathType Container)){
  throw '发布目录必须已存在且独立于源项目；脚本不会覆盖或删除目录'
}
if($DryRun){ Write-Warn '-DryRun 只做前置检查，不连库、不写文件' }

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
if(-not $PyDir){ foreach($c in @("$env:LOCALAPPDATA\Programs\Python\Python313","C:\Python313")){ if(Test-Path (Join-Path $c 'python.exe')){ $PyDir=$c; break } } }
if(-not $PyDir -or -not (Test-Path (Join-Path $PyDir 'python.exe'))){ Write-Fail '未找到系统 Python 3.13（-PyDir）'; exit 1 }

# git 闸门（2026-10-17 审计 P2-5）：发布包只能来自 **main 的干净提交**。
#   ① git 命令失败必须 fail-closed —— 原实现把 `git status` 的输出直接当判据：命令失败
#      （index.lock / 非仓库 / safe.directory 拒绝）时输出为空 → 放行，且下方 manifest 的
#      git_head 会是空串（= 无法证明打的是哪个提交）；
#   ② 必须校验分支 —— NSSM 的 AppDirectory 就是本仓库工作区，从特性分支打包等于把该分支
#      当发布版本（2026-10-14 已有 75 分钟实害事故）；
#   ③ `-DryRun` 无发布产物，因此分支不符只警告；仍拒绝读取失败或有改动的工作区。
Push-Location $ProjectDir
$branch = (git rev-parse --abbrev-ref HEAD 2>$null); $rcBranch = $LASTEXITCODE
$dirty  = (git status --porcelain 2>$null);          $rcDirty  = $LASTEXITCODE
$head   = (git rev-parse HEAD 2>$null);              $rcHead   = $LASTEXITCODE
Pop-Location
# Git 读取失败不是分支不符，任何模式都不得放行。
if($rcHead -ne 0){
  Write-Fail ("git rev-parse HEAD 失败（退出码 " + $rcHead + "）—— 无法证明打包的是哪个提交，拒绝打包")
  exit 1
}
if($rcDirty -ne 0){
  Write-Fail ("git status 失败（退出码 " + $rcDirty + "）—— 读不出工作区状态，拒绝打包")
  exit 1
}
if($rcBranch -ne 0 -or -not $branch){ Write-Fail 'git 无法确定打包分支，拒绝打包'; exit 1 }
if(-not $head -or $head.Trim().Length -lt 7){ Write-Fail '读不到 HEAD 提交，拒绝打包'; exit 1 }
if($dirty){ Write-Fail '工作区不干净，拒绝打包（先提交/清理）'; exit 1 }
if($branch.Trim() -ne 'main'){
  if($DryRun){ Write-Warn ("DryRun：当前分支 '" + $branch.Trim() + "' 不是 main（真实构建此处 FAIL）") }
  else { Write-Fail ("当前分支 '" + $branch.Trim() + "' 不是 main —— 发布包只能来自 main"); exit 1 }
}

if($DryRun){ Write-Ok 'DRY RUN PRECHECK COMPLETE'; exit 0 }
if(-not (Test-Admin)){ throw '生成含敏感数据的便携包必须以管理员运行' }
$tar=Join-Path $env:SystemRoot 'System32\tar.exe'
if(-not (Test-Path -LiteralPath $tar -PathType Leaf)){ throw '缺少 Windows 系统 tar' }
$EncryptKey=Read-DeploySecret '设置便携包加密口令'
$stage=$null
try {
$stage=New-DeployStagingDirectory
$OutDir=Join-Path $stage 'payload'
foreach($s in 'app','runtime','data','frontend'){ New-Item -ItemType Directory -Force -Path (Join-Path $OutDir $s) | Out-Null }

Write-Step '1/6 拷代码'
$xd = @((Join-Path $ProjectDir '.git'),(Join-Path $ProjectDir '.venv'),(Join-Path $ProjectDir 'logs'),
        (Join-Path $ProjectDir 'temp'),(Join-Path $ProjectDir 'backups'),(Join-Path $ProjectDir 'dist'),
        (Join-Path $ProjectDir 'build'),(Join-Path $ProjectDir 'evidence'),
        (Join-Path $ProjectDir '_ops'),(Join-Path $ProjectDir 'config\pgbouncer'),(Join-Path $ProjectDir 'config\tls'),
        (Join-Path $ProjectDir 'deploy'),
        (Join-Path $ProjectDir 'static'))
# /XD 除构建垃圾外，须排除 AGENTS.md §7 的全部 AI 工具痕迹目录（15+），避免打进包
$aiTrail = @('.agent','.claude','.cursor','.graphflow','.graphflow-cache','graphflow-out','.trae','.qoder','.workbuddy','.workbuddy-ai','.reasonix','.superpowers','.codebuddy','.freebuff','.lean-ctx','.resultverify','.codeartsdoer','.zcode','.agent-teams','.mimosa')
robocopy $ProjectDir (Join-Path $OutDir 'app') /E /XJ /XD @('node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','pytest-of-Administrator') $aiTrail @xd /XF @('*.pyc','*.pyo','*.log','*.tmp','*.pid','dsh-web-dump-config.txt','nul','.zcodeignore') /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：拷 app 代码"; exit 1 }
if($WithNodeModules){ robocopy (Join-Path $ProjectDir 'frontend-vite\node_modules') (Join-Path $OutDir 'app\frontend-vite\node_modules') /E /XJ /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
  if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：拷 node_modules"; exit 1 } }

Write-Step '2/6 拷 runtime'
robocopy $PyDir (Join-Path $OutDir 'runtime\python313') /E /XJ /XD '__pycache__' /XF @('*.pyc','*.pyo') /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：拷 runtime"; exit 1 }
# --require-hashes：锁内每个包都带 sha256，安装时强制校验。
& (Join-Path $OutDir 'runtime\python313\python.exe') -m pip install -q --no-cache-dir --require-hashes -r (Join-Path $ProjectDir 'requirements\base.lock') -r (Join-Path $ProjectDir 'requirements\dev.lock') -r (Join-Path $ProjectDir 'requirements\test.lock') -r (Join-Path $ProjectDir 'requirements\ocr.lock')
if($LASTEXITCODE -ne 0){ throw "runtime 依赖安装失败 exit=$LASTEXITCODE" }
$smoke = & (Join-Path $OutDir 'runtime\python313\python.exe') -c "import fastapi,uvicorn,sqlalchemy,asyncpg,pytest,ruff;print('imports-ok')" 2>&1
if($LASTEXITCODE -ne 0 -or $smoke -notmatch 'imports-ok'){ throw "runtime 自检失败: $smoke" }

Write-Step '3/6 拷前端 dist'
robocopy (Join-Path $ProjectDir 'frontend-vite\dist') (Join-Path $OutDir 'frontend\dist') /E /XJ /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：拷 frontend\dist"; exit 1 }

Write-Step '4/6 拷静态文件并导出数据库'
# 仅保留运行所需的应用配置副本，不将源机 postgres 超管口令带入迁移包。
$packedEnv=Join-Path $OutDir 'app\.env'
$deployLines=[IO.File]::ReadAllLines($packedEnv,[Text.UTF8Encoding]::new($false)) | Where-Object { $_ -notmatch '^\s*(?:export\s+)?PG_SUPER_PASSWORD\s*=' }
_Save-Env $packedEnv $deployLines
robocopy (Join-Path $ProjectDir 'static') (Join-Path $OutDir 'data\static') /E /XJ /NFL /NDL /NJH /NJS /NP | Out-Null
if($LASTEXITCODE -ge 8){ Write-Fail "robocopy 失败 (exit=$LASTEXITCODE)：拷 static"; exit 1 }
$env:PGPASSWORD = (Read-EnvMap (Join-Path $ProjectDir '.env'))['DB_PASSWORD']
if(-not $env:PGPASSWORD){ Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue; Write-Fail '源机 .env 缺 DB_PASSWORD，无法 dump'; exit 1 }
& $pgDump -w -h 127.0.0.1 -p 5432 -U erp_app -d erp_system -Fc -f (Join-Path $OutDir 'data\erp_system.dump')
$dumpRc = $LASTEXITCODE
if($dumpRc -ne 0){ Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue; Write-Fail "pg_dump 失败 exit=$dumpRc"; exit 1 }
$dumpVer = (& $psql -X -w -h 127.0.0.1 -p 5432 -U erp_app -d erp_system -v ON_ERROR_STOP=1 -tAc 'select version_num from alembic_version' | Out-String).Trim()
$versionRc=$LASTEXITCODE
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
$dumpFile = Get-Item (Join-Path $OutDir 'data\erp_system.dump') -ErrorAction SilentlyContinue
if(-not $dumpFile -or $dumpFile.Length -le 0){ Write-Fail 'dump 文件缺失或为空'; exit 1 }
if($versionRc -ne 0 -or -not $dumpVer){ throw '未能读取源数据库的 alembic_version' }

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

Write-Step '6/6 加密 + sha256'
Assert-NoDeploymentLinks $OutDir
$tgz=Join-Path $stage 'payload.tar.gz'
& $tar -czf $tgz -C $stage 'payload'
if($LASTEXITCODE -ne 0){ throw "tar 失败 exit=$LASTEXITCODE" }
$name="erp_portable_${stamp}_$([guid]::NewGuid().ToString('N')).tar.gz.enc"
$enc=Join-Path $stage $name
Protect-File -InPath $tgz -OutPath $enc -Password $EncryptKey
$hash=(Get-FileHash -LiteralPath $enc -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$enc.sha256", $hash, [Text.UTF8Encoding]::new($false))
$published=Join-Path (Assert-LocalDeploymentPath $publishDir) $name
[IO.File]::Copy($enc,$published,$false)
[IO.File]::Copy("$enc.sha256","$published.sha256",$false)
} finally {
  Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
  if($stage){ Remove-DeployStagingDirectory $stage }
}
Write-Ok "已生成 $published；通过独立可信渠道向安装人交付以下 SHA-256：$hash"
Write-Ok 'BUILD COMPLETE'
