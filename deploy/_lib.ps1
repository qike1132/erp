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
