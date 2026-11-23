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

function Assert-PackageHash([IO.Stream]$InputStream,[string]$Expected){
  if($Expected -cnotmatch '\A[0-9a-fA-F]{64}\z'){ throw '必须提供独立可信渠道取得的 64 位 SHA-256 十六进制值' }
  $hash = [Security.Cryptography.SHA256]::Create()
  try { $actual = [BitConverter]::ToString($hash.ComputeHash($InputStream)).Replace('-','') }
  finally { $hash.Dispose() }
  if($actual -ine $Expected){ throw '安装包 SHA-256 与独立信任值不一致，拒绝解密' }
  $InputStream.Position = 0
}

function Assert-FreshInstallOptions([bool]$Force,[bool]$AllowDropDatabase,[bool]$SkipVerify){
  if($Force -or $AllowDropDatabase -or $SkipVerify){
    throw '便携包仅支持全新安装；已禁用 Force、AllowDropDatabase 和 SkipVerify'
  }
}

function Read-DeploySecret([string]$Prompt){
  $secret=Read-Host -AsSecureString $Prompt
  $bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
  try {
    if(-not $secret.Length){ throw '口令不能为空' }
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secret.Dispose()
  }
}

function Assert-LocalDeploymentPath([string]$Path){
  if($Path -notmatch '\A[A-Za-z]:[\\/][A-Za-z0-9_. \\/-]+\z' -or $Path -match '[. ](?:[\\/]|\z)' -or $Path -match '[\\/]{2}' -or
     $Path -match '(?i)[\\/](?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|[\\/]|\z)'){
    throw "路径必须是规范的本地绝对路径（不支持链接、盘根、点段和特殊字符）：$Path"
  }
  $full=[IO.Path]::GetFullPath($Path).TrimEnd('\','/')
  $drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))
  if($drive.DriveType -ne 'Fixed' -or $drive.DriveFormat -ne 'NTFS'){ throw "路径必须位于本机固定 NTFS 磁盘：$Path" }
  for($part=$full; $part; $part=Split-Path $part -Parent){
    try { $item=Get-Item -LiteralPath $part -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] { continue }
    if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){ throw "拒绝重解析点路径：$part" }
  }
  $full
}

function New-DeployPrivateDirectory([string]$Path){
  $full=Assert-LocalDeploymentPath $Path
  if(Test-Path -LiteralPath $full){ throw "拒绝使用已有目录：$full" }
  if(-not (Test-Path -LiteralPath (Split-Path $full -Parent) -PathType Container)){ throw "父目录不存在：$full" }
  $owner=[Security.Principal.WindowsIdentity]::GetCurrent().User
  $acl=[Security.AccessControl.DirectorySecurity]::new()
  $acl.SetAccessRuleProtection($true,$false)
  foreach($sid in @($owner,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))){
    $rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
  }
  # Win32 CreateDirectory 在目录已存在（包括竞态）时失败，绝不接管旧目录。
  if(-not ('ErpDeployDirectory' -as [type])){
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ErpDeployDirectory {
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes {
        public int Length;
        public IntPtr SecurityDescriptor;
        public int InheritHandle;
    }
    [DllImport("kernel32.dll", EntryPoint="CreateDirectoryW", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateDirectory(string path, ref SecurityAttributes attrs);
    public static void Create(string path, byte[] descriptor) {
        var handle = GCHandle.Alloc(descriptor, GCHandleType.Pinned);
        try {
            var attrs = new SecurityAttributes {
                Length = Marshal.SizeOf(typeof(SecurityAttributes)),
                SecurityDescriptor = handle.AddrOfPinnedObject(),
                InheritHandle = 0
            };
            if (!CreateDirectory(path, ref attrs))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        } finally { handle.Free(); }
    }
}
'@
  }
  [ErpDeployDirectory]::Create($full,$acl.GetSecurityDescriptorBinaryForm())
  $applied=Get-Acl -LiteralPath $full
  $allowed=@($owner.Value,'S-1-5-18','S-1-5-32-544') | Select-Object -Unique
  $rules=@($applied.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
  $expectedInheritance=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
  $unexpected=@($rules | Where-Object {
    $_.IsInherited -or $_.AccessControlType -ne 'Allow' -or $_.IdentityReference.Value -notin $allowed -or
    $_.FileSystemRights -ne 'FullControl' -or $_.InheritanceFlags -ne $expectedInheritance -or $_.PropagationFlags -ne 'None'
  })
  if(-not $applied.AreAccessRulesProtected -or $unexpected.Count -or $rules.Count -ne @($allowed).Count){
    throw "暂存目录 ACL 验证失败；未写入明文：$full"
  }
  $full
}

function New-DeployStagingDirectory {
  $parent=[Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)
  New-DeployPrivateDirectory (Join-Path $parent ('erp-stage-' + [guid]::NewGuid().ToString('N')))
}

function Assert-NoDeploymentLinks([string]$Path){
  $pending=[Collections.Generic.Stack[string]]::new()
  $pending.Push($Path)
  while($pending.Count){
    $item=Get-Item -LiteralPath $pending.Pop() -Force
    if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){ throw "发现不允许的重解析点：$($item.FullName)" }
    if($item.PSIsContainer){ foreach($child in Get-ChildItem -LiteralPath $item.FullName -Force){ $pending.Push($child.FullName) } }
  }
}

function Remove-DeployStagingDirectory([string]$Path){
  $parent=[Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)
  $full=Assert-LocalDeploymentPath $Path
  if((Split-Path $full -Parent) -ine $parent -or (Split-Path $full -Leaf) -cnotmatch '\Aerp-stage-[0-9a-f]{32}\z'){
    throw "拒绝清理非本次专用暂存路径：$full"
  }
  try {
    Assert-NoDeploymentLinks $full
    Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
  } catch { throw "明文暂存未能清理；请隔离并人工检查：$full（$($_.Exception.Message)）" }
}

function Unprotect-File([string]$InPath,[string]$OutPath,[string]$Password,[string]$ExpectedSha256){
  # 持有不允许共享写/删除的句柄；校验与解密使用同一流，防止校验后换包。
  $in=[IO.File]::Open($InPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  try{
    Assert-PackageHash $in $ExpectedSha256
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

function Assert-DeploymentTls([string]$OpenSsl,[string]$Certificate,[string]$PrivateKey,[string]$TrustedCa,[string]$ServerName){
  foreach($p in @($OpenSsl,$Certificate,$PrivateKey,$TrustedCa)){
    [void](Assert-LocalDeploymentPath $p)
    if(-not (Test-Path -LiteralPath $p -PathType Leaf)){ throw '缺少 OpenSSL、目标机证书、密钥或独立受信 CA 文件' }
  }
  if($Certificate -eq $TrustedCa){ throw '受信 CA 必须由独立可信渠道提供，不能直接使用服务端证书链文件' }
  $caPem=[IO.File]::ReadAllText($TrustedCa)
  if($caPem -cnotmatch '\A\s*-----BEGIN CERTIFICATE-----\s+([A-Za-z0-9+/=\r\n]+)-----END CERTIFICATE-----\s*\z'){
    throw '受信 CA 文件必须只含一张 PEM 根证书'
  }
  $ca=[Security.Cryptography.X509Certificates.X509Certificate2]::new([Convert]::FromBase64String($Matches[1]))
  try {
    if(-not (Test-Path -LiteralPath "Cert:\LocalMachine\Root\$($ca.Thumbprint)")){ throw '独立 CA 尚未预置为 Windows 本机受信根' }
  } finally { $ca.Dispose() }
  $version=& $OpenSsl version
  if($LASTEXITCODE -ne 0 -or "$version" -notmatch '^OpenSSL 3\.'){ throw 'TLS 预检需要目标机预装可信 OpenSSL 3' }
  $isIp=[uri]::CheckHostName($ServerName) -in 'IPv4','IPv6'
  $verifyName = if($isIp){ '-verify_ip' } else { '-verify_hostname' }
  $sanType = if($isIp){ 'IP Address:' } else { 'DNS:' }
  $sans=& $OpenSsl x509 -in $Certificate -noout -ext subjectAltName
  if($LASTEXITCODE -ne 0 -or ($sans -join "`n") -cnotmatch $sanType){ throw 'TLS 叶证书必须包含适用于目标主机的 SAN' }
  & $OpenSsl verify -x509_strict -purpose sslserver -no-CAfile -no-CApath -no-CAstore -trusted $TrustedCa -untrusted $Certificate $verifyName $ServerName $Certificate | Out-Null
  if($LASTEXITCODE -ne 0){ throw 'TLS 证书链、有效期、用途或入口主机名校验失败' }
  $leafPub=& $OpenSsl x509 -in $Certificate -pubkey -noout
  if($LASTEXITCODE -ne 0){ throw '无法读取 TLS 证书公钥' }
  $keyPub=& $OpenSsl pkey -in $PrivateKey -passin 'pass:' -pubout
  if($LASTEXITCODE -ne 0 -or -not $keyPub -or (($leafPub -join "`n") -cne ($keyPub -join "`n"))){ throw 'TLS 私钥不可读、加密或与证书不匹配' }
}

function Update-NginxConf([string]$ConfPath,[string]$OldRoot,[string]$NewRoot,[string]$NginxDir,[string]$ServerName){
  if(-not (Test-HostLiteral $ServerName)){ throw '无效的 HTTPS 入口主机名' }
  $h=$ServerName.Trim().Trim('[',']').ToLowerInvariant()
  $urlHost=if(Test-IsIPv6Literal $h){ "[$h]" }else{ $h }
  $body=[IO.File]::ReadAllText($ConfPath,[Text.UTF8Encoding]::new($false))
  # 仅支持已知模板；不将 443 的 location 复制到明文端口。
  $redirect='(?m)^([ \t]*return 301 https://)[^\s;/]+(\$request_uri;\r?)$'
  $hostCheck='(?m)^([ \t]*if \(\$host != ")[^"\r\n]+("\) \{\r?)$'
  if(([regex]::Matches($body,$redirect)).Count -ne 1 -or ([regex]::Matches($body,$hostCheck)).Count -ne 1 -or
     $body -notmatch '(?m)^\s*listen 443 ssl default_server;' -or $body -notmatch '(?m)^\s*listen 3000 default_server;' -or
     $body -notmatch '(?m)^\s*ssl_certificate\s+[^;]+/config/tls/server\.crt;' -or $body -notmatch '(?m)^\s*ssl_certificate_key\s+[^;]+/config/tls/server\.key;'){
    throw 'nginx 模板必须保留 443 TLS 与 3000 固定主机跳转'
  }
  $body=[regex]::Replace($body,$redirect, { param($m) $m.Groups[1].Value + $urlHost + $m.Groups[2].Value })
  $body=[regex]::Replace($body,$hostCheck, { param($m) $m.Groups[1].Value + $urlHost + $m.Groups[2].Value })
  # 将 3000 探针也限制到本机；prod_runner/watchdog 仍可在环回探测。
  $probe='(?m)^(\s*location = /nginx-health \{\r?\n)([ \t]*)access_log off;'
  if(([regex]::Matches($body,$probe)).Count -ne 1){ throw 'nginx 模板缺少唯一的 /nginx-health 探针' }
  # return 与 if 同属 rewrite 阶段；仅用 allow/deny 会被既有 return 200 提前绕过。
  $body=[regex]::Replace($body,$probe, { param($m) $m.Groups[1].Value + $m.Groups[2].Value + 'if ($remote_addr !~ "^(127\.0\.0\.1|::1)$") { return 403; }' + "`n" + $m.Groups[2].Value + 'access_log off;' })
  $count=([regex]::Matches($body,[regex]::Escape($OldRoot))).Count
  $body=$body.Replace($OldRoot,$NewRoot).Replace('C:/nginx/conf/mime.types',($NginxDir -replace '\\','/') + '/conf/mime.types')
  [IO.File]::WriteAllText($ConfPath,$body,[Text.UTF8Encoding]::new($false))
  return $count
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
  if($null -ne (Get-ServiceStatus $name)){ throw "服务 $name 已存在，拒绝替换" }
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
  if($h -match '^[0-9.]+$'){
    return ($h -match '\A(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}\z' -and [uri]::CheckHostName($h) -eq 'IPv4')
  }
  if($h.Contains(':') -or $h.Contains('[') -or $h.Contains(']')){
    return ((($h -match '\A[0-9a-fA-F:.]+\z') -or ($h -match '\A\[[0-9a-fA-F:.]+\]\z')) -and (Test-IsIPv6Literal $h))
  }
  if($h.Length -gt 253){ return $false }
  foreach($label in $h.Split('.')){
    if($label -notmatch '\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\z'){ return $false }
  }
  return ([uri]::CheckHostName($h) -eq 'Dns')
}

function Test-IsIPv6Literal([string]$HostValue){
  # 裸或带方括号的 IPv6 → $true（用于决定是否补带方括号形式）。
  if(-not $HostValue){ return $false }
  $h = $HostValue.Trim().Trim('[',']')
  return ($h -match '\A[0-9A-Fa-f:.]+\z' -and [uri]::CheckHostName($h) -eq 'IPv6')
}
