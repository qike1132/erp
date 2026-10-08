#Requires -Version 5.1
<#
  Task6 · 构建端本机端到端 dry-run 自检
  ------------------------------------------------------------------
  在【隔离的干净源码树】上跑 deploy\build_package.ps1 -DryRun，核验产物要点。
  全通过 → 打印 "E2E DRYRUN PASS" 并 exit 0；任一断言失败 → exit 1。

  为什么隔离：build_package.ps1 拒绝在「工作区不干净」时打包（这是它的正确设计，
  防止把未提交代码打进包），而生产主机常有并发会话的未提交改动（本仓尤甚）。
  若直接对 D:\erp_system 跑，会因与构建无关的改动误报失败。故本脚本先把 HEAD
  克隆到临时目录（克隆的 .git 是【目录】，能被 robocopy /XD 正常排除；若用
  git worktree，.git 是文件、/XD 排除不掉会漏进 app\ ），补上被 .gitignore 的
  必需前置，再对副本构建。

  只读承诺：不写 D:\erp_system、不停/启任何服务、不跑 npm；仅 pg_dump 快照生产库（只读）。
  所有写入都在 $env:TEMP 下的临时目录，finally 里清理（成功或失败都清）。
  注意：每次运行都会读【生产 .env】（拷进隔离树）并对其 DB_PASSWORD 指向的库跑一次真实
        (只读) 的 pg_dump（localhost:5432/erp_system）——即每调用一次就真连生产库一次。

  用法：powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\e2e_dryrun.ps1
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$here        = $PSScriptRoot                         # ...\deploy\tests
$deployDir   = Split-Path $here -Parent              # ...\deploy
$RepoDir     = Split-Path $deployDir -Parent         # 仓库根
$buildScript = Join-Path $deployDir 'build_package.ps1'
# 目录名带 $PID 后缀：同机两次并发跑本脚本时互不踩（固定名会互相清理对方的工作目录）。
$OutDir      = Join-Path $env:TEMP ('erp_pkg_dry_' + $PID)    # 必须在仓库之外（否则 Test-SafeOutDir 拒）
$WorkDir     = Join-Path $env:TEMP ('erp_e2e_src_' + $PID)    # 隔离源码树
$logOut      = Join-Path $env:TEMP ('erp_e2e_build_' + $PID + '.log')
$psExe       = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$fail = 0
function Assert([bool]$Cond,[string]$Msg){
  if($Cond){ Write-Host "  [PASS] $Msg" -ForegroundColor Green }
  else     { Write-Host "  [FAIL] $Msg" -ForegroundColor Red; $script:fail++ }
}
function Section([string]$m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }

# ---- 前置：脚本与仓库根可识别 ----
Assert (Test-Path $buildScript) ("构建脚本存在：" + $buildScript)
Assert (Test-Path (Join-Path $RepoDir '.git')) ("仓库根可识别：" + $RepoDir)
if($fail -gt 0){ Write-Host "`n前置不满足，终止。" -ForegroundColor Red; exit 1 }

$buildRc  = -999
$buildOut = ''
try {
  Section '1/7 清空临时目录'
  foreach($x in @($OutDir,$WorkDir,$logOut)){ if(Test-Path $x){ Remove-Item $x -Recurse -Force } }

  Section '2/7 隔离源码树（git clone HEAD → 干净副本）'
  & git clone --quiet $RepoDir $WorkDir
  Assert ($LASTEXITCODE -eq 0) 'git clone 成功'
  $headSha = (& git -C $WorkDir rev-parse HEAD).Trim()
  Write-Host "        HEAD = $headSha"
  $st = (& git -C $WorkDir status --porcelain | Out-String).Trim()
  Assert ($st -eq '') '隔离树 git 状态干净'

  Section '3/7 补入被 .gitignore 的前置 + 实体化忽略工件（供排除项断言）'
  $fileCopies = @(
    '.env',
    'config\uploads-signing.conf',
    'config\jwt\private_v2.pem',
    'config\jwt\public_v2.pem'
  )
  foreach($rel in $fileCopies){
    $src = Join-Path $RepoDir $rel
    Assert (Test-Path $src) ("源存在：" + $rel)
    if(Test-Path $src){ Copy-Item $src (Join-Path $WorkDir $rel) -Force }
  }
  $distS = Join-Path $RepoDir 'frontend-vite\dist'
  $distT = Join-Path $WorkDir 'frontend-vite\dist'
  Assert (Test-Path $distS) '源存在：frontend-vite\dist'
  if(Test-Path $distS){
    if(Test-Path $distT){ Remove-Item $distT -Recurse -Force }
    Copy-Item $distS $distT -Recurse -Force
  }
  Assert (Test-Path (Join-Path $distT 'index.html')) '前端 dist\index.html 到位'

  # 关键：下列路径全被 .gitignore，纯净克隆里【本就不存在】。若不在此把它们实体化，
  # 那么第 6/7 段「app\ 下不存在它」的断言在【build_package.ps1 删掉对应 /XD 或 /XF
  # 排除项后仍会通过】（恒真）——尤其 _ops\credentials 泄入包这种安全属性就守不住。
  # 实体化后，排除断言才真正检验构建脚本的排除规则。
  $dummyArtifacts = @(
    '_ops\credentials\dummy.txt',
    '.venv\dummy.txt',
    'node_modules\dummy.txt',
    '.cursor\dummy.txt',
    '.codeartsdoer\dummy.txt',
    '.mimosa\dummy.txt',
    'pytest-of-Administrator\dummy.txt',
    '.zcodeignore'
  )
  foreach($rel in $dummyArtifacts){
    $p   = Join-Path $WorkDir $rel
    $dir = Split-Path $p -Parent
    if(-not (Test-Path $dir)){ New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Set-Content -LiteralPath $p -Value 'e2e dummy ignored artifact' -Encoding ASCII -Force
    Assert (Test-Path $p) ("已实体化忽略工件：" + $rel)
  }

  $st2 = (& git -C $WorkDir status --porcelain | Out-String).Trim()
  Assert ($st2 -eq '') '补入前置与忽略工件后隔离树仍干净（均为 ignored）'

  Section '4/7 跑构建（build_package.ps1 -DryRun，独立进程）'
  # 用 cmd 做整行重定向：避开 PS5.1 把原生 stderr 当错误记录、在 EA=Stop 下误抛的坑
  $cmdline = '"{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -DryRun -ProjectDir "{2}" -OutDir "{3}" > "{4}" 2>&1' `
             -f $psExe, $buildScript, $WorkDir, $OutDir, $logOut
  & cmd.exe /c $cmdline
  $buildRc = $LASTEXITCODE
  $buildOut = [string](Get-Content $logOut -Raw -ErrorAction SilentlyContinue)
  Assert ($buildRc -eq 0) ("build_package.ps1 -DryRun 退出码 0（实=$buildRc）")
  Assert ($buildOut -match '\[OK\] BUILD COMPLETE') '构建输出含 [OK] BUILD COMPLETE'

  Section '5/7 核验 manifest 与 dump'
  $man = Join-Path $OutDir 'manifest.txt'
  Assert (Test-Path $man) 'manifest.txt 存在'
  $ver = ''
  if(Test-Path $man){
    foreach($ln in [IO.File]::ReadAllLines($man,[Text.UTF8Encoding]::new($false))){
      if($ln -match '^\s*dump_alembic_version\s*:\s*(\S.*?)\s*$'){ $ver = $Matches[1]; break }
    }
  }
  Assert ($ver -ne '') ("manifest 的 dump_alembic_version 非空（=$ver）")

  $dump = Join-Path $OutDir 'data\erp_system.dump'
  Assert (Test-Path $dump) 'data\erp_system.dump 存在'
  $dumpLen = 0
  if(Test-Path $dump){ $dumpLen = (Get-Item $dump).Length }
  Assert ($dumpLen -gt 0) ("dump 长度 > 0（=$dumpLen 字节）")

  Section '6/7 核验排除项（AI 痕迹 / 运行期数据不进包）'
  $mustAbsent = @(
    'app\_ops','app\config\pgbouncer','app\node_modules','app\.git',
    'app\.venv','app\.codeartsdoer','app\.cursor','app\.zcodeignore',
    'app\.mimosa','app\pytest-of-Administrator','app\static'
  )
  foreach($rel in $mustAbsent){ Assert (-not (Test-Path (Join-Path $OutDir $rel))) ("不存在：" + $rel) }

  Section '7/7 核验 runtime 可用'
  $py = Join-Path $OutDir 'runtime\python313\python.exe'
  Assert (Test-Path $py) 'runtime\python313\python.exe 存在'
  if(Test-Path $py){
    $v = (& $py '-c' 'import sys;print(sys.version)' 2>&1 | Out-String).Trim()
    Assert ($v -match '^3\.13\b') ("runtime python 版本为 3.13（=$v）")
  }
}
finally {
  Section '清理临时目录'
  foreach($x in @($OutDir,$WorkDir)){ if(Test-Path $x){ Remove-Item $x -Recurse -Force -ErrorAction SilentlyContinue } }
  if(Test-Path $logOut){ Remove-Item $logOut -Force -ErrorAction SilentlyContinue }
}

if($fail -eq 0){ Write-Host "`nE2E DRYRUN PASS" -ForegroundColor Green; exit 0 }
Write-Host "`nE2E DRYRUN FAIL（$fail 项）" -ForegroundColor Red
exit 1
