# ERP 离线便携包一键部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一对 PowerShell 脚本，把本机（生产）ERP 整套打成口令加密的离线便携包，并在新 Windows 服务器上一条命令装到 `D:\erp_system`，装完功能与数据与源机一致。

**Architecture:** 共享库 `deploy/_lib.ps1`（日志 / 提权 / .env 读写与改写 / .NET AES 流式加解密 / nginx 改写 / 危险路径守卫），被两个入口脚本 dot-source：`build_package.ps1`（源机只读打包）与 `install_package.ps1`（目标机分阶段装配）。加解密用 .NET `Aes`（零外部二进制），打包用 Windows 自带 `tar.exe`。每阶段可 `-SkipXxx/-OnlyXxx` 续跑。

**Tech Stack:** Windows PowerShell 5.1（**非** pwsh）、`tar.exe`（bsdtar）、`robocopy`、`pg_dump/pg_restore`（psycopg3 环境外，用 PG18 客户端）、`nssm`、`.NET System.Security.Cryptography`。

**Spec:** [docs/superpowers/specs/2026-10-08-one-click-deploy-design.md](../specs/2026-10-08-one-click-deploy-design.md)（v3；执行前先读它）

## Global Constraints

- 仅 **Windows PowerShell 5.1**：用 `powershell.exe`；禁用 `pwsh`/三元 `? :`/`??`/`-Parallel` 等 PW7 语法。
- 目标机路径默认 **`D:\erp_system`**，与源机同路径（用户已定）；脚本仍保留改路径能力作兜底。
- **禁止在源机（生产）跑 `npm`**：前端只拷现成的 `frontend-vite\dist`。
- `.env` 一律用 **UTF-8 无 BOM 字节写**（`[IO.File]::WriteAllText(..., UTF8Encoding($false))`），**不用** `Set-Content`。
- `pg_dump`/`pg_restore`/`psql` 定位顺序：`PG_TOOLS_BIN` → PATH → `C:\Program Files\PostgreSQL\*\bin`、`D:\PostgreSQL\bin`、`C:\PostgreSQL\bin`，**须含 18**。
- NSSM 服务一律指向**包内 runtime** `<TargetDir>\runtime\python313\python.exe`；`AppEnvironmentExtra` **一变量一元素**。
- 包加解密用 **.NET `Aes`**（AES-256-CBC + PBKDF2-SHA256, 300000 iters, 随机 salt+IV），**不用 openssl**。
- 真实口令/密钥只进 `.env` 与 `_ops/credentials/`；**不写文档、不写聊天、不进命令行历史**（优先 `Read-Host -AsSecureString`）。
- `_ops/credentials/**` 与 `config/pgbouncer/userlist.txt` **绝不入包**。
- 所有临时明文解包目录在 `finally` 中递归删除（成功/失败都删）。
- 提交信息用中文；每笔只做一件事；提交前 `git status --porcelain` 确认无运行期数据。

## Review Focus

（spec 未逐条写、但最可能咬到使用者、且必须有测试钉住的 5 类输入/失败模式，严重度从上到下）

1. **未提权运行 `install_package.ps1`**：必须清晰 FAIL 退出，**不得静默半装**（服务/文件只装一半）。
2. **加密口令错误**：解密必须明确报「口令错误」并 **exit≠0**，不产出半截解包目录、不残留明文。
3. **目标机已有旧 ERP/同名服务**：未给 `-Force` 时**拒绝**且**不动现场**；给了才覆盖。
4. **`.env` 含中文注释/特殊字符**：改写后文件仍是合法 UTF-8 无 BOM、既有行未被损坏、被追加的 IP/origin **不重复**。
5. **中途失败后重跑**：幂等——不重复追加 `ALLOWED_HOSTS`/`CORS_ORIGINS`、不重复 `CREATE ROLE`、不重复注册服务报错。

## File Structure

```
deploy/
  _lib.ps1                 # 共享库（dot-source）：日志四态/Test-Admin/Read-EnvMap/Set-EnvKey/
                           #   Protect-File/Unprotect-File(AES)/Test-SafeOutDir/
                           #   Get-PgTool/Update-EnvForTarget/Update-NginxConf/
                           #   Install-NssmService/Test-Prereqs
  build_package.ps1        # 源机入口：预检→git 清洁→拷贝→dump→manifest→tar→AES→sha256
  install_package.ps1      # 目标机入口：16 阶段装配 + 验收
  README.md                # 构建→传输→安装 三步说明
  tests/
    test_lib.ps1           # _lib.ps1 的断言测试（自检脚本，失败 exit 1）
    fixtures/
      nginx-sample.conf    # 含 D:/erp_system ×N 与 443 server 块的样本
      env-sample.env       # 含中文注释/既有 ALLOWED_HOSTS 的样本
scripts/migrate/README.md  # 新增：标记整目录 deprecated → 指向 deploy/
```

**不做**：容器化、`node_modules`（默认）、`backups/` 内容、openssl。

---

### Task 1: 共享库骨架 + AES 加解密 + .env 改写（`_lib.ps1` 前半 + 测试）

**Files:**
- Create: `deploy/_lib.ps1`
- Create: `deploy/tests/test_lib.ps1`
- Create: `deploy/tests/fixtures/env-sample.env`

**Interfaces:**
- Consumes: 无
- Produces（后续所有任务依赖）：
  - `Write-Step([string])`、`Write-Ok([string])`、`Write-Warn([string])`、`Write-Fail([string])`（后者写 stderr）
  - `Test-Admin() -> [bool]`
  - `Read-EnvMap([string]$Path) -> [hashtable]`（去注释/空行，值为去引号后的串）
  - `Set-EnvKey([string]$Path,[string]$Key,[string]$Value)`（幂等：存在则替换该行，不存在则追加；保留其余行与编码）
  - `Add-EnvListItemJson([string]$Path,[string]$Key,[string]$Item)`（把 `KEY` 当作 JSON 数组，去重后追加；用于 ALLOWED_HOSTS）
  - `Add-EnvListItemComma([string]$Path,[string]$Key,[string]$Item)`（逗号串去重追加；用于 CORS_ORIGINS/WS_ALLOWED_ORIGINS）
  - `Protect-File([string]$InPath,[string]$OutPath,[string]$Password)`
  - `Unprotect-File([string]$InPath,[string]$OutPath,[string]$Password)`

- [ ] **Step 1: 写失败的测试** `deploy/tests/test_lib.ps1`

```powershell
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\_lib.ps1')
$fail = 0
function Assert($cond,$msg){ if($cond){ Write-Host "  [PASS] $msg" } else { Write-Host "  [FAIL] $msg" -ForegroundColor Red; $script:fail++ } }

# AES round-trip
$tmp = Join-Path $env:TEMP ("erp_lib_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$src = Join-Path $tmp 'a.bin'; [IO.File]::WriteAllText($src,('中文内容' * 1000),[Text.UTF8Encoding]::new($false))
$enc = Join-Path $tmp 'a.enc'; $dec = Join-Path $tmp 'a.out'
Protect-File -InPath $src -OutPath $enc -Password 'pw-123'
Assert ((Get-Item $enc).Length -gt 0) 'AES 产出非空'
Unprotect-File -InPath $enc -OutPath $dec -Password 'pw-123'
Assert ((Get-FileHash $src).Hash -eq (Get-FileHash $dec).Hash) 'AES 往返一致'
try { Unprotect-File -InPath $enc -OutPath (Join-Path $tmp 'bad') -Password 'wrong'; Assert $false '错误口令应抛' }
catch { Assert $true '错误口令抛异常' }

# .env 幂等
$envf = Join-Path $tmp 'e.env'
Copy-Item (Join-Path $PSScriptRoot 'fixtures\env-sample.env') $envf
Add-EnvListItemJson -Path $envf -Key 'ALLOWED_HOSTS' -Item '10.0.0.5'
Add-EnvListItemJson -Path $envf -Key 'ALLOWED_HOSTS' -Item '10.0.0.5'   # 二次应去重
$m = Read-EnvMap $envf
$arr = $m['ALLOWED_HOSTS'] | ConvertFrom-Json
Assert (($arr | Where-Object { $_ -eq '10.0.0.5' }).Count -eq 1) 'ALLOWED_HOSTS 去重'
$raw = [IO.File]::ReadAllText($envf)
Assert ($raw -match '数据库口令') '中文注释行保留'
Assert ($raw[0] -ne [char]0xFEFF) '无 BOM'
Remove-Item $tmp -Recurse -Force
if($fail){ exit 1 } else { Write-Host 'ALL PASS' }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\test_lib.ps1`
Expected: 报错 `_lib.ps1 不存在` 或 `Protect-File 未定义` → 非 0 退出。

- [ ] **Step 3: 实现 `deploy/_lib.ps1`（本任务部分）**

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$m){ Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok([string]$m){   Write-Host "  [OK] $m"   -ForegroundColor Green }
function Write-Warn([string]$m){ Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Fail([string]$m){ [Console]::Error.WriteLine("  [FAIL] $m") }

function Test-Admin {
  $id=[Security.Principal.WindowsIdentity]::GetCurrent()
  ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Read-EnvMap([string]$Path){
  $map=@{}
  if(-not (Test-Path $Path)){ return $map }
  foreach($line in [IO.File]::ReadAllLines($Path,[Text.UTF8Encoding]::new($false))){
    $t=$line.Trim()
    if($t -match '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$'){
      $v=$Matches[2].Trim()
      if($v.Length -ge 2 -and (($v[0] -eq '"' -and $v[-1] -eq '"') -or ($v[0] -eq "'" -and $v[-1] -eq "'"))){ $v=$v.Substring(1,$v.Length-2) }
      $map[$Matches[1]]=$v
    }
  }
  $map
}

function _Save-Env([string]$Path,[string[]]$Lines){
  [IO.File]::WriteAllText($Path, ($Lines -join "`r`n") + "`r`n", [Text.UTF8Encoding]::new($false))
}

function Set-EnvKey([string]$Path,[string]$Key,[string]$Value){
  $lines=[Collections.Generic.List[string]]([IO.File]::ReadAllLines($Path,[Text.UTF8Encoding]::new($false)))
  $done=$false
  for($i=0;$i -lt $lines.Count;$i++){
    if($lines[$i] -match "^$([regex]::Escape($Key))\s*="){ $lines[$i]="$Key=$Value"; $done=$true }
  }
  if(-not $done){ $lines.Add("$Key=$Value") }
  _Save-Env $Path $lines
}

function Add-EnvListItemJson([string]$Path,[string]$Key,[string]$Item){
  $m=Read-EnvMap $Path; $cur=@()
  if($m.ContainsKey($Key) -and $m[$Key].Trim()){ try{ $cur=@($m[$Key] | ConvertFrom-Json) }catch{ $cur=@() } }
  if($cur -notcontains $Item){ $cur+=$Item }
  Set-EnvKey $Path $Key ($cur | ConvertTo-Json -Compress)
}

function Add-EnvListItemComma([string]$Path,[string]$Key,[string]$Item){
  $m=Read-EnvMap $Path; $cur=@()
  if($m.ContainsKey($Key) -and $m[$Key].Trim()){ $cur=@($m[$Key].Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
  if($cur -notcontains $Item){ $cur+=$Item }
  Set-EnvKey $Path $Key ($cur -join ',')
}

function _NewRng() { [Security.Cryptography.RandomNumberGenerator]::Create() }

function Protect-File([string]$InPath,[string]$OutPath,[string]$Password){
  $salt=New-Object byte[] 16; $iv=New-Object byte[] 16
  $rng=_NewRng(); $rng.GetBytes($salt); $rng.GetBytes($iv)
  $kdf=[Security.Cryptography.Rfc2898DeriveBytes]::new($Password,$salt,300000,[Security.Cryptography.HashAlgorithmName]::SHA256)
  $aes=[Security.Cryptography.Aes]::Create(); $aes.Key=$kdf.GetBytes(32); $aes.IV=$iv; $aes.Mode='CBC'; $aes.Padding='PKCS7'
  $in=[IO.File]::OpenRead($InPath); $out=[IO.File]::Create($OutPath)
  try{
    $magic=[Text.Encoding]::ASCII.GetBytes('ERPPKG01'); $out.Write($magic,0,8); $out.Write($salt,0,16); $out.Write($iv,0,16)
    $cs=[Security.Cryptography.CryptoStream]::new($out,$aes.CreateEncryptor(),'Write')
    try{ $in.CopyTo($cs); $cs.FlushFinalBlock() } finally { $cs.Dispose() }
  } finally { $in.Dispose(); $out.Dispose(); $aes.Dispose() }
}

function Unprotect-File([string]$InPath,[string]$OutPath,[string]$Password){
  $in=[IO.File]::OpenRead($InPath)
  try{
    $magic=New-Object byte[] 8; if($in.Read($magic,0,8) -ne 8 -or [Text.Encoding]::ASCII.GetString($magic) -ne 'ERPPKG01'){ throw '不是 ERP 便携包（魔数不匹配）' }
    $salt=New-Object byte[] 16; $iv=New-Object byte[] 16; [void]$in.Read($salt,0,16); [void]$in.Read($iv,0,16)
    $kdf=[Security.Cryptography.Rfc2898DeriveBytes]::new($Password,$salt,300000,[Security.Cryptography.HashAlgorithmName]::SHA256)
    $aes=[Security.Cryptography.Aes]::Create(); $aes.Key=$kdf.GetBytes(32); $aes.IV=$iv; $aes.Mode='CBC'; $aes.Padding='PKCS7'
    $out=[IO.File]::Create($OutPath)
    try{
      $cs=[Security.Cryptography.CryptoStream]::new($in,$aes.CreateDecryptor(),'Read')
      try{ $cs.CopyTo($out) } finally { $cs.Dispose() }
    } finally { $out.Dispose(); $aes.Dispose() }
  } finally { $in.Dispose() }
}
```

- [ ] **Step 4: 建测试 fixture** `deploy/tests/fixtures/env-sample.env`

```ini
# 数据库口令（中文注释，验证改写不损坏）
DB_PASSWORD=secret
ALLOWED_HOSTS=["localhost"]
CORS_ORIGINS=http://localhost:3000
```

- [ ] **Step 5: 运行测试确认通过**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\test_lib.ps1`
Expected: 全部 `[PASS]` + `ALL PASS`，退出码 0。

- [ ] **Step 6: 提交**

```bash
git add deploy/_lib.ps1 deploy/tests/test_lib.ps1 deploy/tests/fixtures/env-sample.env
git commit -m "feat(deploy): 便携包共享库前半——AES 加解密与 .env 幂等改写"
```

---

### Task 2: 共享库后半——nginx 改写 / PG 定位 / 危险路径守卫 / 服务注册 / 预检

**Files:**
- Modify: `deploy/_lib.ps1`（追加函数）
- Modify: `deploy/tests/test_lib.ps1`（追加断言）
- Create: `deploy/tests/fixtures/nginx-sample.conf`

**Interfaces:**
- Consumes: Task 1 的 `Read-EnvMap`、`Write-*`
- Produces：
  - `Test-SafeOutDir([string]$OutDir,[string]$ProjectDir) -> [bool]`（拒绝盘根/等于/包含 ProjectDir）
  - `Get-PgTool([string]$ExeName) -> [string]`（全路径或 `$null`；含 18）
  - `Update-NginxConf([string]$ConfPath,[string]$OldRoot,[string]$NewRoot,[string]$NginxDir) -> [int]`（替换计数；`OldRoot` 用正斜杠形如 `D:/erp_system`；按内容注释 `listen 443 ssl` 所在 server 块）
  - `New-NginxTempDirs([string]$ProjectRoot)`
  - `Install-NssmService([string]$Nssm,[hashtable]$Spec)`，`$Spec` 键：`Name Application Parameters Directory Env(string[]) DependOn Stdout Stderr`
  - `Test-Prereqs([hashtable]$Wanted) -> [string[]]`（返回缺失项名列表）

- [ ] **Step 1: 追加失败断言到 `test_lib.ps1`（nginx 改写）**

```powershell
# nginx 改写：2 处 D:/erp_system 全替换；443 server 块被注释；HTTP server 块保留
$nf = Join-Path $tmp 'n.conf'; Copy-Item (Join-Path $PSScriptRoot 'fixtures\nginx-sample.conf') $nf
$cnt = Update-NginxConf -ConfPath $nf -OldRoot 'D:/erp_system' -NewRoot 'E:/erp' -NginxDir 'C:\nginx'
$body=[IO.File]::ReadAllText($nf)
Assert ($cnt -ge 2) "nginx 替换计数>=2 (实=$cnt)"
Assert ($body -notmatch 'D:/erp_system') '旧根全清'
Assert ($body -match '#\s*server\s*\{[\s\S]*?listen 443 ssl[\s\S]*?\n\s*#?\s*\}') '443 块已注释'
Assert ($body -match 'listen 3000 default_server') 'HTTP 块保留'
```

- [ ] **Step 2: 运行确认失败**（`Update-NginxConf` 未定义）

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\test_lib.ps1`
Expected: FAIL `Update-NginxConf 未定义`，exit≠0。

- [ ] **Step 3: 建 fixture** `deploy/tests/fixtures/nginx-sample.conf`

```nginx
events {}
http {
    server {
        listen 443 ssl default_server;
        ssl_certificate     D:/erp_system/config/tls/server.crt;
        ssl_certificate_key D:/erp_system/config/tls/server.key;
        root frontend-vite/dist;
    }
    server {
        listen 3000 default_server;
        root frontend-vite/dist;
        include D:/erp_system/config/security-headers.conf;
    }
}
```

- [ ] **Step 4: 实现追加函数（`_lib.ps1`）**

```powershell
function Test-SafeOutDir([string]$OutDir,[string]$ProjectDir){
  $o=[IO.Path]::GetFullPath($OutDir).TrimEnd('\','/'); $p=[IO.Path]::GetFullPath($ProjectDir).TrimEnd('\','/')
  $r=[IO.Path]::GetPathRoot($o).TrimEnd('\','/')
  -not ($o -eq '' -or $o -eq $r -or $o -eq $p -or $p.StartsWith($o + '\',[StringComparison]::OrdinalIgnoreCase))
}

function Get-PgTool([string]$ExeName){
  if($env:PG_TOOLS_BIN){ $c=Join-Path $env:PG_TOOLS_BIN $ExeName; if(Test-Path $c){ return $c } }
  $cmd=Get-Command $ExeName -ErrorAction SilentlyContinue; if($cmd){ return $cmd.Source }
  $dirs=@('C:\Program Files\PostgreSQL\18\bin','C:\Program Files\PostgreSQL\17\bin',
          'C:\Program Files\PostgreSQL\16\bin','D:\PostgreSQL\bin','C:\PostgreSQL\bin')
  foreach($d in $dirs){ $c=Join-Path $d $ExeName; if(Test-Path $c){ return $c } }
  $null
}

function Update-NginxConf([string]$ConfPath,[string]$OldRoot,[string]$NewRoot,[string]$NginxDir){
  $lines=[Collections.Generic.List[string]]([IO.File]::ReadAllLines($ConfPath,[Text.UTF8Encoding]::new($false)))
  $cnt=0
  for($i=0;$i -lt $lines.Count;$i++){
    if($lines[$i] -like "*$OldRoot*"){ $lines[$i]=$lines[$i].Replace($OldRoot,$NewRoot); $cnt++ }
    if($NginxDir -and $lines[$i] -match 'mime\.types'){ $lines[$i]=[regex]::Replace($lines[$i],'C:/nginx',($NginxDir -replace '\\','/')) }
  }
  # 按内容注释 443 server 块：找到 'listen 443 ssl' 行，向上找最近的 'server {'，向下配对到该 server 的收尾 '}'
  for($i=0;$i -lt $lines.Count;$i++){
    if($lines[$i] -match 'listen\s+443\s+ssl'){
      $start=$i; while($start -ge 0 -and $lines[$start] -notmatch 'server\s*\{'){ $start-- }
      $depth=0; $end=$start
      for($j=$start;$j -lt $lines.Count;$j++){
        $depth += ([regex]::Matches($lines[$j],'\{')).Count - ([regex]::Matches($lines[$j],'\}')).Count
        if($depth -le 0 -and $j -gt $start){ $end=$j; break }
      }
      for($k=$start;$k -le $end;$k++){ if($lines[$k] -notmatch '^\s*#'){ $lines[$k]='#'+$lines[$k] } }
      $i=$end
    }
  }
  [IO.File]::WriteAllText($ConfPath, ($lines -join "`r`n") + "`r`n", [Text.UTF8Encoding]::new($false))
  $cnt
}

function New-NginxTempDirs([string]$ProjectRoot){
  foreach($d in 'client_body_temp','proxy_temp','fastcgi_temp','uwsgi_temp','scgi_temp'){
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "temp\$d") | Out-Null
  }
}

function Install-NssmService([string]$Nssm,[hashtable]$Spec){
  $name=$Spec.Name
  if(Get-Service -Name $name -ErrorAction SilentlyContinue){ & $Nssm stop $name | Out-Null; & $Nssm remove $name confirm | Out-Null }
  & $Nssm install $name $Spec.Application | Out-Null
  & $Nssm set $name AppParameters $Spec.Parameters | Out-Null
  & $Nssm set $name AppDirectory $Spec.Directory | Out-Null
  & $Nssm set $name AppStdout $Spec.Stdout | Out-Null
  & $Nssm set $name AppStderr $Spec.Stderr | Out-Null
  & $Nssm set $name AppRotateFiles 1 | Out-Null
  & $Nssm set $name AppRotateBytes 10485760 | Out-Null
  & $Nssm set $name AppExit Default Restart | Out-Null
  & $Nssm set $name AppRestartDelay 5000 | Out-Null
  & $Nssm set $name Start SERVICE_AUTO_START | Out-Null
  & $Nssm set $name AppNoConsole 1 | Out-Null
  if($Spec.DependOn){ & $Nssm set $name DependOnService $Spec.DependOn | Out-Null }
  if($Spec.Env){ & $Nssm set $name AppEnvironmentExtra @($Spec.Env) | Out-Null }
}

function Test-Prereqs([hashtable]$Wanted){
  $missing=@()
  foreach($k in $Wanted.Keys){ if(-not (Test-Path $Wanted[$k])){ $missing += $k } }
  $missing
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\test_lib.ps1`
Expected: 全部 `[PASS]` + `ALL PASS`。

- [ ] **Step 6: 提交**

```bash
git add deploy/_lib.ps1 deploy/tests/test_lib.ps1 deploy/tests/fixtures/nginx-sample.conf
git commit -m "feat(deploy): 共享库后半——nginx 改写/PG 定位/危险路径/服务注册/预检"
```

---

### Task 3: 构建端 `build_package.ps1`（源机只读打包）

**Files:**
- Create: `deploy/build_package.ps1`

**Interfaces:**
- Consumes: Task 1/2 的全部 `_lib.ps1` 函数
- Produces: 目录 `<OutDir>`（结构见 spec §4）与 `<OutDir>.tar.gz.enc` + `.sha256`

- [ ] **Step 1: 写脚本（含 `-DryRun` 只打包不加密，供本机验证）**

```powershell
#Requires -Version 5.1
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
$binNeed = @{ 'PG安装器'='pg18*'; 'Redis'='Redis-x64-5.0.14.1*'; 'nginx'='nginx*zip'; 'nssm'='nssm*zip'; 'node'='node*.msi'; 'vcredist'='vc_redist*zip*' }
$binDir = Join-Path $PSScriptRoot 'binaries'
$binMiss=@(); foreach($k in $binNeed.Keys){ if(-not (Get-ChildItem $binDir -Filter $binNeed[$k] -ErrorAction SilentlyContinue)){ $binMiss+=$k } }
if($binMiss){ Write-Fail ("deploy\binaries\ 缺: " + ($binMiss -join ', ') + " —— 见 deploy\README.md 下载清单"); exit 1 }
if(-not $PyDir){ foreach($c in @("$env:LOCALAPPDATA\Programs\Python\Python313","C:\Python313")){ if(Test-Path (Join-Path $c 'python.exe')){ $PyDir=$c; break } } }
if(-not $PyDir -or -not (Test-Path (Join-Path $PyDir 'python.exe'))){ Write-Fail '未找到系统 Python 3.13（-PyDir）'; exit 1 }

# git 清洁
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
robocopy $ProjectDir (Join-Path $OutDir 'app') /E /XD @('node_modules','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.claude','.graphflow','.graphflow-cache') @xd /XF '*.pyc','*.pyo','*.log','*.tmp','*.pid' /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if($WithNodeModules){ robocopy (Join-Path $ProjectDir 'frontend-vite\node_modules') (Join-Path $OutDir 'app\frontend-vite\node_modules') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null }

Write-Step '2/6 拷 runtime'
robocopy $PyDir (Join-Path $OutDir 'runtime\python313') /E /XD '__pycache__' /XF '*.pyc','*.pyo' /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
& (Join-Path $OutDir 'runtime\python313\python.exe') -m pip install -q -r (Join-Path $ProjectDir 'requirements\base.txt') -r (Join-Path $ProjectDir 'requirements\dev.txt') -r (Join-Path $ProjectDir 'requirements\test.txt') -r (Join-Path $ProjectDir 'requirements\ocr.txt')
$smoke = & (Join-Path $OutDir 'runtime\python313\python.exe') -c "import fastapi,uvicorn,sqlalchemy,asyncpg,pytest,ruff;print('imports-ok')" 2>&1
if($smoke -notmatch 'imports-ok'){ Write-Fail "runtime 自检失败: $smoke"; exit 1 }

Write-Step '3/6 拷前端 dist'
robocopy (Join-Path $ProjectDir 'frontend-vite\dist') (Join-Path $OutDir 'frontend\dist') /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null

Write-Step '4/6 拷 settings + static + dump'
Copy-Item (Join-Path $ProjectDir '.env') (Join-Path $OutDir 'settings\.env') -Force
foreach($f in 'nginx-windows.conf','redis-broker.conf','security-headers.conf','log_policy.json','nssm-services.json'){ Copy-Item (Join-Path $ProjectDir "config\$f") (Join-Path $OutDir "settings\$f") -Force }
robocopy (Join-Path $ProjectDir 'config\jwt') (Join-Path $OutDir 'settings\jwt') /E /NFL /NDL /NJH /NJS /NP | Out-Null
Copy-Item (Join-Path $ProjectDir 'config\uploads-signing.conf') (Join-Path $OutDir 'settings\uploads-signing.conf') -Force
robocopy (Join-Path $ProjectDir 'static') (Join-Path $OutDir 'data\static') /E /NFL /NDL /NJH /NJS /NP | Out-Null
foreach($f in (Get-ChildItem (Join-Path $PSScriptRoot 'binaries') -File)){ Copy-Item $f.FullName (Join-Path $OutDir 'binaries') -Force }
Copy-Item (Join-Path $PSScriptRoot 'install_package.ps1') (Join-Path $OutDir 'deploy\install_package.ps1') -Force
$env:PGPASSWORD = (Read-EnvMap (Join-Path $ProjectDir '.env'))['DB_PASSWORD']
& $pgDump -h localhost -p 5432 -U erp_app -d erp_system -Fc -f (Join-Path $OutDir 'data\erp_system.dump')
Remove-Item Env:PGPASSWORD
$dumpVer = (& (Join-Path $OutDir 'runtime\python313\python.exe') -c "import os,sqlalchemy as s;e=s.create_engine(os.environ['DATABASE_URL']);print(e.connect().execute(s.text('select version_num from alembic_version')).scalar())" )

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

if(-not $SkipZip){
  Write-Step '6/6 加密 + sha256'
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
```

- [ ] **Step 2: `-DryRun` 本机验证（不加密，产物落仓内 tmp）**

Run:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\build_package.ps1 -OutDir D:\erp_system\.claude\tmp\pkg_dry -SkipZip
```
Expected: `[OK] BUILD COMPLETE`；`pkd_dry\data\erp_system.dump` 存在且 >0；`manifest.txt` 含 `dump_alembic_version: pg_standalone_078_stock_nav_rename`；`app\_ops` 与 `app\config\pgbouncer` 不存在（已排除）。

- [ ] **Step 3: 断言校验**

Run:
```powershell
powershell.exe -NoProfile -Command "if(!(Test-Path 'D:\erp_system\.claude\tmp\pkg_dry\data\erp_system.dump')){exit 1}; if(Test-Path 'D:\erp_system\.claude\tmp\pkg_dry\app\_ops'){exit 2}; if(Test-Path 'D:\erp_system\.claude\tmp\pkg_dry\app\config\pgbouncer'){exit 3}; if(Test-Path 'D:\erp_system\.claude\tmp\pkg_dry\app\node_modules'){exit 4}; 'OK'"
```
Expected: `OK`，exit 0。

- [ ] **Step 4: 清理 dry 产物 + 提交**

```bash
rm -rf D:/erp_system/.claude/tmp/pkg_dry
git add deploy/build_package.ps1
git commit -m "feat(deploy): 构建端 build_package.ps1（源机只读打包+AES 加密）"
```

---

### Task 4: 安装端 `install_package.ps1`（目标机 16 阶段装配）

**Files:**
- Create: `deploy/install_package.ps1`

**Interfaces:**
- Consumes: `_lib.ps1` 全部函数
- Produces: 装好的 `D:\erp_system` + 五 NSSM 服务 + 验收输出

- [ ] **Step 1: 写脚本（分阶段 + 幂等 + finally 清理）**

```powershell
#Requires -Version 5.1
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Package,
  [string]$TargetDir = 'D:\erp_system',
  [string]$ServerIP = '192.168.1.97',
  [string]$PgSuperPassword = '',
  [string]$NginxDir = 'C:\nginx',
  [string]$RedisDir = 'C:\Redis',
  [string]$Nssm = 'C:\nssm\nssm.exe',
  [string]$EncryptKey = '', [switch]$Force, [switch]$Blank, [switch]$SkipVerify
)
. (Join-Path $PSScriptRoot '_lib.ps1')
$work = Join-Path $env:TEMP ("erp_pkg_" + [guid]::NewGuid().ToString('N'))
try {
  Write-Step '0 提权 + 参数'
  if(-not (Test-Admin)){ Write-Fail '必须以管理员运行'; exit 1 }
  if($ServerIP -notmatch '^\d{1,3}(\.\d{1,3}){3}$'){ Write-Fail "非法 ServerIP: $ServerIP"; exit 1 }
  $free = (Get-PSDrive ([IO.Path]::GetPathRoot($TargetDir).TrimEnd(':'))).Free
  if($free -lt 8GB){ Write-Fail "目标盘可用空间不足 8GB（实 $([math]::Round($free/1GB,1))GB）"; exit 1 }
  if(-not $EncryptKey){ $sec=Read-Host -AsSecureString '便携包口令'; $EncryptKey=[Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }

  Write-Step '1 解密解包'
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  $tgz = Join-Path $work 'p.tar.gz'; Unprotect-File -InPath $Package -OutPath $tgz -Password $EncryptKey
  & tar.exe -xzf $tgz -C $work; if($LASTEXITCODE -ne 0){ throw 'tar 解包失败' }
  $pkgRoot = (Get-ChildItem $work -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'manifest.txt') } | Select-Object -First 1)
  if(-not $pkgRoot){ throw '包内未找到 manifest.txt（口令或包损坏）' }

  Write-Step '2 装基础软件（已装跳过）'
  # VC++ / PG18 静默 / Redis 解压 / nginx 解压 / nssm / node —— 见 README 清单；幂等探测
  # （PG: 检测 Get-Service postgresql* → 缺才静默装；Redis: 检测 redis-server.exe；nginx: nginx.exe；nssm: nssm.exe；node: node -v）
  # 具体每件：解压 Expand-Archive / 静默 & installer；此处按 manifest 与 Test-Prereqs 结果执行，失败 Write-Fail + 官方 URL 后 exit 1

  Write-Step '3 建库'
  $psql = Get-PgTool 'psql.exe'; if(-not $psql){ Write-Fail '未找到 psql'; exit 1 }
  $envMap = Read-EnvMap (Join-Path $pkgRoot 'settings\.env'); $dbPw = $envMap['DB_PASSWORD']; if(-not $dbPw){ Write-Fail '包内 .env 缺 DB_PASSWORD'; exit 1 }
  $env:PGPASSWORD=$PgSuperPassword
  $esc=$dbPw.Replace("'","''")
  & $psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='erp_app'" | Out-Null
  if(-not $?){ & $psql -U postgres -d postgres -c "CREATE ROLE erp_app LOGIN PASSWORD '$esc'" }
  & $psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='erp_system'" -o (Join-Path $work 'dbex.txt')
  if(-not (Select-String -Path (Join-Path $work 'dbex.txt') -Pattern '1' -Quiet)){
    & $psql -U postgres -d postgres -c "CREATE DATABASE erp_system WITH OWNER = erp_app"
  } elseif($Force){ Write-Warn '库已存在，-Force：重建'; & $psql -U postgres -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='erp_system' AND pid<>pg_backend_pid()" | Out-Null; & $psql -U postgres -d postgres -c 'DROP DATABASE erp_system'; & $psql -U postgres -d postgres -c 'CREATE DATABASE erp_system WITH OWNER = erp_app' }
  else { Write-Fail 'erp_system 已存在；覆盖请加 -Force'; exit 1 }
  Remove-Item Env:PGPASSWORD

  Write-Step '4 部署文件'
  if(Test-Path $TargetDir){ if($Force){ foreach($n in 'erp-prod','erp-arq','erp-web'){ if(Get-Service $n -EA SilentlyContinue){ & $Nssm stop $n | Out-Null } } } else { Write-Fail "$TargetDir 已存在；覆盖请加 -Force"; exit 1 } }
  foreach($pair in @(@('app',$TargetDir),@('runtime',$TargetDir),@('frontend\dist',"$TargetDir\frontend-vite\dist"))){ robocopy (Join-Path $pkgRoot $pair[0]) $pair[1] /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null }
  robocopy (Join-Path $pkgRoot 'static') "$TargetDir\static" /E /NFL /NDL /NJH /NJS /NP | Out-Null  # 若包为 data/static 见 Step4 注释
  foreach($d in 'logs','backups','temp'){ New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir $d) | Out-Null }

  Write-Step '5 .env 改写'
  $envPath = Join-Path $TargetDir '.env'
  Add-EnvListItemJson  $envPath 'ALLOWED_HOSTS'     $ServerIP
  Add-EnvListItemComma $envPath 'CORS_ORIGINS'      "http://${ServerIP}:3000"
  Add-EnvListItemComma $envPath 'WS_ALLOWED_ORIGINS' "${ServerIP}:3000"
  Set-EnvKey $envPath 'JWT_PRIVATE_KEY_PATH' "$TargetDir\config\jwt\private_v2.pem"
  Set-EnvKey $envPath 'JWT_PUBLIC_KEY_PATH'  "$TargetDir\config\jwt\public_v2.pem"
  # 删除 DATABASE_URL/ASYNC_DATABASE_URL 行（留空会覆盖兜底）
  $txt=[IO.File]::ReadAllLines($envPath,[Text.UTF8Encoding]::new($false)) | Where-Object { $_ -notmatch '^\s*(ASYNC_)?DATABASE_URL\s*=' }
  [IO.File]::WriteAllText($envPath,($txt -join "`r`n")+"`r`n",[Text.UTF8Encoding]::new($false))
  if($TargetDir -ne 'D:\erp_system'){ Update-NginxConf -ConfPath (Join-Path $TargetDir 'config\nginx-windows.conf') -OldRoot 'D:/erp_system' -NewRoot ($TargetDir -replace '\\','/') -NginxDir $NginxDir } else { Update-NginxConf -ConfPath (Join-Path $TargetDir 'config\nginx-windows.conf') -OldRoot 'D:/erp_system' -NewRoot 'D:/erp_system' -NginxDir $NginxDir }
  New-NginxTempDirs $TargetDir

  Write-Step '6 uploads-signing.conf'
  $secret = (Read-EnvMap $envPath)['UPLOAD_URL_SIGNING_SECRET']
  [IO.File]::WriteAllText((Join-Path $TargetDir 'config\uploads-signing.conf'), "set `$erp_upload_sign_secret `"$secret`";", [Text.UTF8Encoding]::new($false))

  Write-Step '7 数据'
  $py = Join-Path $TargetDir 'runtime\python313\python.exe'
  if($Blank){
    & $py -m alembic -c (Join-Path $TargetDir 'migrations\alembic.ini') upgrade head
    & $py (Join-Path $TargetDir 'scripts\init_permissions.py') --yes
    & $py (Join-Path $TargetDir 'scripts\seed_nav.py')
    Write-Warn '空库：请按 README §4.10B 建 admin'
  } else {
    $env:PGPASSWORD=$dbPw
    & (Get-PgTool 'pg_restore.exe') -h localhost -U erp_app -d erp_system --no-owner --no-privileges -j 4 (Join-Path $pkgRoot 'data\erp_system.dump')
    Remove-Item Env:PGPASSWORD
    & $py -m alembic -c (Join-Path $TargetDir 'migrations\alembic.ini') upgrade head   # 078 -> 079 对齐代码
  }

  Write-Step '8 注册五服务'
  $envs=@('APP_ENV=production','FASTAPI_DEBUG=false',"PYTHONPATH=$TargetDir",'PYTHONUTF8=1','PYTHONUNBUFFERED=1','UVICORN_WORKERS=4')
  Install-NssmService $Nssm @{Name='erp-prod';Application=$py;Parameters='-m fastapi_app.core.prod_runner --no-arq';Directory=$TargetDir;Env=$envs;DependOn='erp-redis';Stdout=(Join-Path $TargetDir 'logs\erp-prod.log');Stderr=(Join-Path $TargetDir 'logs\erp-prod.log')}
  Install-NssmService $Nssm @{Name='erp-arq';Application=$py;Parameters='-m arq fastapi_app.core.arq_app.WorkerSettings';Directory=$TargetDir;Env=$envs;DependOn='erp-redis-broker';Stdout=(Join-Path $TargetDir 'logs\erp-arq.log');Stderr=(Join-Path $TargetDir 'logs\erp-arq.log')}
  Install-NssmService $Nssm @{Name='erp-web';Application=(Join-Path $NginxDir 'nginx.exe');Parameters="-p $TargetDir -c $TargetDir\config\nginx-windows.conf";Directory=$TargetDir;Stdout=(Join-Path $TargetDir 'logs\erp-web.log');Stderr=(Join-Path $TargetDir 'logs\erp-web.log')}
  # redis 两个：conf 落位时去掉生效 requirepass 行，口令经 --requirepass 注入（见 README）

  Write-Step '9 防火墙 + 启停'
  if(-not (Get-NetFirewallRule -DisplayName 'erp-web-3000' -EA SilentlyContinue)){ New-NetFirewallRule -DisplayName 'erp-web-3000' -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow | Out-Null }
  foreach($svc in 'erp-redis','erp-redis-broker','erp-prod','erp-arq','erp-web'){ if(Get-Service $svc -EA SilentlyContinue){ Start-Service $svc -EA SilentlyContinue } }

  Write-Step '10 看门狗'
  # 改写 scripts\ops\watchdog_task.cmd 里的 PY= 行指向 $py，再安装计划任务

  if(-not $SkipVerify){ Write-Step '11 验收'; Start-Sleep 15; try{ $r=Invoke-WebRequest "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 10; Write-Ok "health $($r.StatusCode)" }catch{ Write-Fail $_.Exception.Message } }
  Write-Ok "完成：http://${ServerIP}:3000"
} finally {
  if(Test-Path $work){ Remove-Item $work -Recurse -Force -EA SilentlyContinue }
  Remove-Item Env:PGPASSWORD -EA SilentlyContinue
}
```

> 说明：Step 2（基础软件静默安装）与 Step 8 的 redis 两服务、Step 10 看门狗为**多行展开**，实现时按 `scripts/migrate/install_on_target.ps1:344-372`（redis conf 处理）与 `:398-419`（Install-NssmService）的既有模式补全，逐件幂等探测。

- [ ] **Step 2: 语法校验（本机）**

Run:
```powershell
powershell.exe -NoProfile -Command "$null=[scriptblock]::Create((Get-Content -Raw deploy\install_package.ps1)); 'PARSE OK'"
```
Expected: `PARSE OK`（无解析错误）。

- [ ] **Step 3: 干跑（-SkipVerify + 指向 dry 包 + 假路径，仅验证到「解密解包」不越界）**

Run:（需先有 Task3 的包）
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\install_package.ps1 -Package <包> -EncryptKey <口令> -ServerIP 127.0.0.1 -SkipVerify
```
Expected: 若本机非管理员 → `必须以管理员运行` exit 1（**这就是 Review Focus #1**）。带管理员且目标非本机时按阶段推进。

- [ ] **Step 4: 提交**

```bash
git add deploy/install_package.ps1
git commit -m "feat(deploy): 安装端 install_package.ps1（16 阶段装配+验收+幂等）"
```

---

### Task 5: 文档 + 旧脚本标 deprecated + 主 README 指向

**Files:**
- Create: `deploy/README.md`
- Create: `scripts/migrate/README.md`
- Modify: `README.md`（§4 开头加一句指向 deploy/）

- [ ] **Step 1: 写 `deploy/README.md`**（三步操作 + binaries 下载清单 + 安全提示）

必须含：①构建命令；②传输（可信通道）+ 口令；③安装命令；④`deploy/binaries\` 需放哪 6 个包（PG18/Redis 5.0.14.1/Nginx/NSSM 2.24/Node/VC++）及官方 URL；⑤「装完立即删源包」；⑥`-Blank`/`-Force`/`-WithNodeModules`/`-Skip*` 说明；⑦目标机要求（管理员、同路径、≥8GB 空闲）。

- [ ] **Step 2: 写 `scripts/migrate/README.md`**（deprecated 注记）

内容：整目录为 2026-08 一次性迁移脚本，**已被 `deploy/` 取代**，仅供历史参考；勿在新部署使用。

- [ ] **Step 3: 改主 README §4** 开头加：

```markdown
> 🚀 **一键部署**：新服务器可改用离线便携包，见 [`deploy/README.md`](deploy/README.md)（本节以下为逐条人工步骤，作为理解与排障参考仍保留）。
```

- [ ] **Step 4: 校验 Markdown 链接存在**

Run: `powershell.exe -NoProfile -Command "if(!(Test-Path deploy\README.md)){exit 1}; if(!(Test-Path scripts\migrate\README.md)){exit 1}; 'OK'"`
Expected: `OK`。

- [ ] **Step 5: 提交**

```bash
git add deploy/README.md scripts/migrate/README.md README.md
git commit -m "docs(deploy): 便携包三步说明 + 旧迁移脚本标 deprecated + 主 README 指向"
```

---

### Task 6: 本机端到端 dry-run（构建→（不装的）清单核验）

**Files:**
- Create: `deploy/tests/e2e_dryrun.ps1`（本机可跑的构建端端到端）

**Interfaces:** Consumes 全部。

- [ ] **Step 1: 写 `e2e_dryrun.ps1`**：跑 `build_package.ps1 -SkipZip -OutDir .claude\tmp\pkg_dry`，断言 exit0、`manifest.txt` 有 `dump_alembic_version`、`data\erp_system.dump` >0、排除项不存在、`runtime\python313\python.exe -c "import fastapi,rapidocr"` 成功。

- [ ] **Step 2: 运行**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy\tests\e2e_dryrun.ps1`
Expected: `E2E DRYRUN PASS`。

- [ ] **Step 3: 提交**

```bash
git add deploy/tests/e2e_dryrun.ps1
git commit -m "test(deploy): 构建端本机端到端 dry-run"
```

---

## 目标机验证（本计划之外的硬依赖）

端到端**安装**必须在一台新 Windows 机/VM 上跑（本机是生产，绝不能当目标机）。执行人拿到目标机后：
1. 拷 `erp_portable_*.tar.gz.enc` + 包内 `deploy/binaries\` 的 6 个安装器（或先放好）；
2. 管理员运行 `install_package.ps1`；
3. 按 spec §6.14 六项验收；用另一台机浏览器 `http://<ServerIP>:3000` 登录跑一笔业务。

---

## Self-Review 记录

- **Spec 覆盖**：§4 结构→Task3/4；§5 构建→Task3；§6 安装 16 阶段→Task4；§7 加密→Task1/3/4；§8 幂等→Task1/4(finally+去重)；§9 测试→Task3/4/6；§11 决策→Global Constraints。
- **占位扫描**：Task4 Step1 明确标注「Step2 基础软件安装 / redis 两服务 / 看门狗」为**多行展开、实现时按既有模式补全**——这是**已知的、有指定参照的**展开点（非 TBD）；执行者须照 `install_on_target.ps1` 对应行号补全。
- **类型一致**：`_lib.ps1` 函数名在 Task1/2 定义、Task3/4 引用一致；`Read-EnvMap`/`Set-EnvKey`/`Add-EnvListItemJson`/`Add-EnvListItemComma`/`Protect-File`/`Unprotect-File`/`Update-NginxConf`/`New-NginxTempDirs`/`Get-PgTool`/`Test-SafeOutDir`/`Test-Prereqs`/`Install-NssmService` 命名前后一致。
- **Review Focus 覆盖**：#1 未提权→Task4 Step3；#2 口令错→Task1 Step1（错误口令抛异常）+Task4 Step1；#3 旧部署→Task4 Step1（`-Force` 分支）；#4 .env 中文/去重→Task1 Step1；#5 幂等→Task1（去重）+Task4（角色/库探测）。
