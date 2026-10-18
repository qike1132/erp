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
      $k=$Matches[1]
      $v=$Matches[2].Trim()
      # 剥掉「值后跟空白+#」的行内注释。只在不带引号的值上做：
      # 带引号的值按整串保留（口令里含 # 合法）。
      if($v -notmatch '^["'']'){
        $hashIdx=$v.IndexOf(' #')
        if($hashIdx -ge 0){ $v=$v.Substring(0,$hashIdx).Trim() }
        elseif($v -eq '#'){ $v='' }
        elseif($v.StartsWith('#')){ $v='' }
      }
      if($v.Length -ge 2 -and (($v[0] -eq '"' -and $v[-1] -eq '"') -or ($v[0] -eq "'" -and $v[-1] -eq "'"))){ $v=$v.Substring(1,$v.Length-2) }
      $map[$k]=$v
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
  if($m.ContainsKey($Key) -and $m[$Key].Trim()){ try{ $cur=@($m[$Key] | ConvertFrom-Json | ForEach-Object { $_ }) }catch{ $cur=@() } }
  if($cur -notcontains $Item){ $cur+=$Item }
  Set-EnvKey $Path $Key (ConvertTo-Json -InputObject @($cur) -Compress)
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
  $rng=_NewRng; $rng.GetBytes($salt); $rng.GetBytes($iv)
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

function Test-SafeOutDir([string]$OutDir,[string]$ProjectDir){
  $o=[IO.Path]::GetFullPath($OutDir).TrimEnd('\','/'); $p=[IO.Path]::GetFullPath($ProjectDir).TrimEnd('\','/')
  $r=[IO.Path]::GetPathRoot($o).TrimEnd('\','/')
  -not ($o -eq '' -or $o -eq $r -or $o -eq $p -or $p.StartsWith($o + '\',[StringComparison]::OrdinalIgnoreCase) -or $o.StartsWith($p + '\',[StringComparison]::OrdinalIgnoreCase))
}

function Get-PgTool([string]$ExeName){
  if($env:PG_TOOLS_BIN){ $c=Join-Path $env:PG_TOOLS_BIN $ExeName; if(Test-Path $c){ return $c } }
  $cmd=Get-Command $ExeName -ErrorAction SilentlyContinue; if($cmd){ return $cmd.Source }
  $dirs=@('C:\Program Files\PostgreSQL\18\bin','C:\Program Files\PostgreSQL\17\bin',
          'C:\Program Files\PostgreSQL\16\bin','D:\PostgreSQL\bin','C:\PostgreSQL\bin')
  foreach($d in $dirs){ $c=Join-Path $d $ExeName; if(Test-Path $c){ return $c } }
  $null
}

function Get-NginxServerBlockExtent([Collections.Generic.List[string]]$Lines,[int]$ListenIdx){
  # 由 'listen ...' 行定位其所属 server 块的 [起始行, 结束行]（含配对花括号）。纯函数，供单测。
  $s=$ListenIdx; while($s -ge 0 -and $Lines[$s] -notmatch 'server\s*\{'){ $s-- }
  if($s -lt 0){ return ,@(-1,-1) }
  $d=0; $e=$s
  for($j=$s;$j -lt $Lines.Count;$j++){
    $d += ([regex]::Matches($Lines[$j],'\{')).Count - ([regex]::Matches($Lines[$j],'\}')).Count
    if($d -le 0 -and $j -gt $s){ $e=$j; break }
  }
  ,@($s,$e)
}

function ConvertTo-NginxHttpEntry([string[]]$BlockLines){
  # 由 443 server 块派生 3000 HTTP 入口块：端口改 3000、去掉 ssl_* 指令、日志改回明文名。
  # 部署包不带证书（443 块在安装端会被注释），故不另抄一份 3000 块——改 443 块后本块自动跟随。
  $out=[Collections.Generic.List[string]]::new()
  foreach($l in $BlockLines){
    if($l -match '^\s*listen\s+\[::\]:443\s+ssl'){ $out.Add(($l -replace '\[::\]:443\s+ssl','[::]:3000')); continue }
    if($l -match '^\s*listen\s+443\s+ssl'){ $out.Add(($l -replace 'listen\s+443\s+ssl','listen 3000')); continue }
    if($l -match '^\s*ssl_(certificate_key|certificate|protocols|session_cache|session_timeout)\b'){ continue }
    if($l -match 'nginx-access-ssl\.log'){ $out.Add(($l -replace 'nginx-access-ssl\.log','nginx-access.log')); continue }
    if($l -match 'nginx-error-ssl\.log'){ $out.Add(($l -replace 'nginx-error-ssl\.log','nginx-error.log')); continue }
    $out.Add($l)
  }
  ,$out
}

function Update-NginxConf([string]$ConfPath,[string]$OldRoot,[string]$NewRoot,[string]$NginxDir){
  $lines=[Collections.Generic.List[string]]([IO.File]::ReadAllLines($ConfPath,[Text.UTF8Encoding]::new($false)))
  $cnt=0
  for($i=0;$i -lt $lines.Count;$i++){
    if($lines[$i] -like "*$OldRoot*"){ $lines[$i]=$lines[$i].Replace($OldRoot,$NewRoot); $cnt++ }
    if($NginxDir -and $lines[$i] -match 'mime\.types'){ $lines[$i]=[regex]::Replace($lines[$i],'C:/nginx',($NginxDir -replace '\\','/')) }
  }

  # 部署包不带证书，故安装端对 443 块：①由它派生 3000 HTTP 入口块 ②整块注释掉。
  # 顺序：先派生（用未注释内容）→ 注释 443（不改行数）→ 替换 3000 块。
  $idx443=-1; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match 'listen\s+443\s+ssl'){ $idx443=$i; break } }
  if($idx443 -ge 0){
    $b443=Get-NginxServerBlockExtent $lines $idx443
    if($b443[0] -ge 0){
      $httpBlock=ConvertTo-NginxHttpEntry @($lines[$b443[0]..$b443[1]])

      # 3000 块：整块替换为派生块；连同其上方紧邻注释一起替换，避免留下「301 跳转」这类过期说明
      $idx3000=-1; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match 'listen\s+3000\s'){ $idx3000=$i; break } }
      if($idx3000 -ge 0){
        $b3000=Get-NginxServerBlockExtent $lines $idx3000
        if($b3000[0] -ge 0){
          $c=$b3000[0]; while($c-1 -ge 0 -and $lines[$c-1] -match '^\s*#'){ $c-- }
          $indent=[regex]::Match($lines[$b3000[0]],'^\s*').Value
          $new=[Collections.Generic.List[string]]::new()
          $new.Add("$indent# ==================== 3000 HTTP 入口（安装端由 443 块派生） ====================")
          $new.Add("$indent# 部署包不带证书：安装端注释 443 块，并由 443 块派生本块作 HTTP 入口")
          $new.Add("$indent# （端口改 3000、去掉 ssl_* 指令）。改 443 块后本块自动跟随。")
          foreach($l in $httpBlock){ $new.Add($l) }
          $lines.RemoveRange($c, $b3000[1]-$c+1)
          $lines.InsertRange($c, $new)
        }
      }

      # 注释 443 块：3000 块在其后，替换不改 443 行号（注释本身也不改行数）
      for($k=$b443[0];$k -le $b443[1];$k++){ if($lines[$k] -notmatch '^\s*#'){ $lines[$k]='#'+$lines[$k] } }
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

function Get-NssmArgs([hashtable]$Spec){
  # 纯函数：组装 nssm 'set' 参数行（每行 string[]），供 Install-NssmService 调用，也可单测。
  # 可选键 DependOn/Env 缺席时静默跳过——必须先 ContainsKey，否则 Set-StrictMode -Latest 会抛 PropertyNotFoundStrict。
  $name=$Spec.Name
  $list=New-Object 'System.Collections.Generic.List[object]'
  $list.Add(@('set',$name,'AppParameters',$Spec.Parameters))
  $list.Add(@('set',$name,'AppDirectory',$Spec.Directory))
  $list.Add(@('set',$name,'AppStdout',$Spec.Stdout))
  $list.Add(@('set',$name,'AppStderr',$Spec.Stderr))
  $list.Add(@('set',$name,'AppRotateFiles','1'))
  $list.Add(@('set',$name,'AppRotateBytes','10485760'))
  $list.Add(@('set',$name,'AppExit','Default','Restart'))
  $list.Add(@('set',$name,'AppRestartDelay','5000'))
  $list.Add(@('set',$name,'Start','SERVICE_AUTO_START'))
  $list.Add(@('set',$name,'AppNoConsole','1'))
  if($Spec.ContainsKey('DependOn') -and $Spec.DependOn){ $list.Add(@('set',$name,'DependOnService',$Spec.DependOn)) }
  if($Spec.ContainsKey('Env') -and $Spec.Env){ $list.Add(@(@('set',$name,'AppEnvironmentExtra')) + @($Spec.Env)) }
  $list
}

function ConvertTo-MaskedNssmArgs([string[]]$ArgList){
  # 纯函数：错误信息/日志里不得回显 --requirepass 明文。
  # 同时覆盖带引号（含空格、转义引号）与不带引号两种形式。
  # 注意参数不能叫 $Args：那是 PowerShell 自动变量，取到的会是空数组。
  ($ArgList -join ' ') -replace '(--requirepass\s+)("(?:\\.|[^"\\])*"?|''[^'']*''?|\S+)', '$1***'
}

function Invoke-Nssm([string]$Nssm,[string[]]$NssmArgs,[string]$Action){
  # 2026-10-17 审计 P2-80：此前所有 nssm 调用都 | Out-Null 且不看退出码，
  # 安装/配置失败会被静默吞掉。
  & $Nssm @NssmArgs | Out-Null
  if($LASTEXITCODE -ne 0){
    # 2026-10-18 OCR 评审：错误信息不得回显 --requirepass <明文>（会进日志/截图）
    $shown = ConvertTo-MaskedNssmArgs $NssmArgs
    $ex = [System.Exception]::new("nssm $Action 失败（exit=$LASTEXITCODE）：$shown")
    $ex.Data['nssmAction'] = $Action
    $ex.Data['nssmExitCode'] = $LASTEXITCODE
    throw $ex
  }
}

function Test-ServiceStatusNeedsContinue([string]$Status){
  # Paused / PausePending 都不接受 STOP 控制码（NSSM 崩溃循环限流会进这两个状态）
  return ($Status -like 'Pause*')
}

function Test-ServiceStatusPending([string]$Status){
  # Start/Stop/Pause/ContinuePending 期间 SCM 一律拒绝控制码（1061）
  return ($Status -like '*Pending')
}

function Get-ServiceStatus([string]$Name){
  # 返回状态字符串；服务未注册返回 $null（查询故障照抛，不能与「不存在」混同）
  try { $svc=Get-Service -Name $Name -ErrorAction Stop }
  catch {
    if($_.CategoryInfo.Category -eq 'ObjectNotFound'){ return $null }
    throw
  }
  $st=$svc.Status.ToString(); $svc.Dispose(); return $st
}

function Stop-NssmService([string]$Nssm,[string]$Name,[int]$PendingTimeoutSec=15){
  # 重装前的有序停机：erp-prod/arq 依赖 erp-redis，依赖方还在跑时 stop erp-redis
  # 会被 SCM 以 1051 拒绝 → 后续 remove/install 只能跳过，旧配置（含旧 --requirepass）
  # 继续生效。调用方必须先按逆依赖序停掉依赖方，再停被依赖者。
  $status = Get-ServiceStatus $Name
  if($null -eq $status -or $status -eq 'Stopped'){ return $true }

  # 1) 任何 *Pending 状态都不接受控制码：先等它落定（有独立短超时）
  $deadline=(Get-Date).AddSeconds($PendingTimeoutSec)
  while((Test-ServiceStatusPending $status) -and (Get-Date) -lt $deadline){
    Start-Sleep -Milliseconds 300
    $status = Get-ServiceStatus $Name
    if($null -eq $status -or $status -eq 'Stopped'){ return $true }
  }
  if(Test-ServiceStatusPending $status){
    # 状态一直落不下来：此时发 stop 必被 1061 拒绝，明确返回失败而不是白等 45s
    return $false
  }

  # 2) Paused/PausePending：continue 后再等离开 Pause*/Pending；continue 本身也可能
  #    因 Pending 被拒，故最多重试 3 次。
  $attempts=0
  while((Test-ServiceStatusNeedsContinue $status) -and $attempts -lt 3){
    try { Invoke-Nssm $Nssm @('continue',$Name) 'continue' }
    catch { Write-Warning "$($_.Exception.Message)（Paused 服务恢复失败，继续等待）" }
    $attempts++
    $resumeDeadline=(Get-Date).AddSeconds(5)
    while((Get-Date) -lt $resumeDeadline){
      Start-Sleep -Milliseconds 300
      $status = Get-ServiceStatus $Name
      if($null -eq $status -or $status -eq 'Stopped'){ return $true }
      if(-not (Test-ServiceStatusPending $status) -and -not (Test-ServiceStatusNeedsContinue $status)){ break }
    }
  }
  if($status -eq 'Stopped'){ return $true }

  # 3) 状态已落定（或已尽力恢复）：发 stop 并等 STOPPED
  try { Invoke-Nssm $Nssm @('stop',$Name) 'stop' }
  catch {
    if($_.Exception.Data['nssmAction'] -ne 'stop'){ throw }
    Write-Warning "$($_.Exception.Message)（继续等待 STOPPED 终态）"
  }
  $stopDeadline=(Get-Date).AddSeconds(45)
  while((Get-Date) -lt $stopDeadline){
    Start-Sleep -Milliseconds 500
    $status = Get-ServiceStatus $Name
    if($null -eq $status -or $status -eq 'Stopped'){ return $true }
  }
  return $false
}

function Install-NssmService([string]$Nssm,[hashtable]$Spec){
  $name=$Spec.Name
  $cur=Get-Service -Name $name -ErrorAction SilentlyContinue
  if($cur){
    # 已 STOPPED 时不调用 stop（nssm 会返回非零，属良性）。
    # 2026-10-18 OCR 评审：非零在 STOP_PENDING/依赖占用时也常见（1051：被运行中的
    # 依赖方占着，re-install 的正序停机就会撞上），按 WARNING 处理，
    # 由下面的「等 STOPPED」循环做权威判定。
    if($cur.Status -ne 'Stopped'){
      try { Invoke-Nssm $Nssm @('stop',$name) 'stop' }
      catch {
        # 只降级「stop 命令本身返回非零」：nssm 不存在/无法启动是硬失败，
        # 继续往下走只会在 remove/install 处报更离谱的错。判定走异常数据而不是文案。
        if($_.Exception.Data['nssmAction'] -ne 'stop'){ throw }
        Write-Warning "$($_.Exception.Message)（继续等待 STOPPED 终态）"
      }
    }
    # 停后必须等 STOPPED，不能立即 remove（旧实现会与正在停止的服务竞争）
    $svc=$null
    $deadline=(Get-Date).AddSeconds(30)
    do {
      Start-Sleep -Milliseconds 500
      if($svc){ $svc.Dispose() }
      $svc=Get-Service -Name $name -ErrorAction SilentlyContinue
    } while($svc -and $svc.Status -ne 'Stopped' -and (Get-Date) -lt $deadline)
    if($svc -and $svc.Status -ne 'Stopped'){
      # 2026-10-18 OCR 复评：1051 是被依赖方占用，重装前不可能停成；此时应跳过
      # remove/install（保留现有服务），而不是抛异常中止整个安装。
      $stillBlocked = $false
      if($svc.Status -ne 'Stopped'){ $stillBlocked = $true }
      if($svc){ $svc.Dispose() }
      if($cur){ $cur.Dispose() }
      if($stillBlocked){
        Write-Warning "服务 $name 未能停止（可能被运行中的依赖方占用，错误 1051）；跳过本次重装，保留现有服务定义"
        # 返回 false 让调用方计入「未按本次配置重装」，避免安装流程报全绿
        return $false
      }
      throw "服务 $name 未能停止"
    }
    # 2026-10-18 OCR 评审：ServiceController 句柄未释放时 remove 只会标记删除，
    # 随后的 install 会报 ERROR_SERVICE_MARKED_FOR_DELETE (1072)。
    if($svc){ $svc.Dispose() }
    if($cur){ $cur.Dispose() }
    Invoke-Nssm $Nssm @('remove',$name,'confirm') 'remove'
    $rmDeadline=(Get-Date).AddSeconds(30)
    do {
      Start-Sleep -Milliseconds 300
      if($svc){ $svc.Dispose(); $svc=$null }
      $poll=Get-Service -Name $name -ErrorAction SilentlyContinue
      $gone= -not $poll
      if($poll){ $poll.Dispose() }
    } while(-not $gone -and (Get-Date) -lt $rmDeadline)
    if(-not $gone){ throw "服务 $name 删除未完成（可能仍标记为删除中）" }
  }
  Invoke-Nssm $Nssm @('install',$name,$Spec.Application) 'install'
  foreach($a in (Get-NssmArgs $Spec)){ Invoke-Nssm $Nssm $a 'set' }
  return $true
}

function Test-Prereqs([hashtable]$Wanted){
  $missing=@()
  foreach($k in $Wanted.Keys){ if(-not (Test-Path $Wanted[$k])){ $missing += $k } }
  $missing
}

function Test-HostLiteral([string]$HostValue){
  # 判定是否是可作为 Host 的合法字面量：IPv4 / IPv6（裸或带方括号）/ 域名。空、含空白或非法字符 → $false。
  if(-not $HostValue){ return $false }
  $h = $HostValue.Trim()
  if($h -match '^\d{1,3}(\.\d{1,3}){3}$'){ return $true }               # IPv4
  if($h -match '^\[[0-9A-Fa-f:.]+\]$'){ return $true }                  # [IPv6]
  # 裸 IPv6 至少两个冒号（最短 :: 也含两个）；单个冒号的全十六进制串（如 a:b）不是 IPv6
  if($h.Contains(':') -and $h -match '^[0-9A-Fa-f:]+$' -and $h.Split(':').Count -ge 3){ return $true }
  if($h -match '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$'){ return $true } # 域名
  return $false
}

function Test-IsIPv6Literal([string]$HostValue){
  # 裸或带方括号的 IPv6 → $true（用于决定是否补带方括号形式）。
  if(-not $HostValue){ return $false }
  $h = $HostValue.Trim().Trim('[',']')
  return ($h.Contains(':') -and ($h -match '^[0-9A-Fa-f:]+$') -and ($h.Split(':').Count -ge 3))
}
