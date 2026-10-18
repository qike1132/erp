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
$arr = @($m['ALLOWED_HOSTS'] | ConvertFrom-Json | ForEach-Object { $_ })
Assert (@($arr | Where-Object { $_ -eq '10.0.0.5' }).Count -eq 1 -and @($arr | Where-Object { $_ -eq 'localhost' }).Count -eq 1) 'ALLOWED_HOSTS 去重且保留原值'
$raw = [IO.File]::ReadAllText($envf)
Assert ($raw -match '数据库口令') '中文注释行保留'
Assert ($raw[0] -ne [char]0xFEFF) '无 BOM'

# 单元素也必须产出 JSON 数组（否则目标机 pydantic 按 list 解析裸串会 SettingsError）
$envf2 = Join-Path $tmp 'e2.env'
[IO.File]::WriteAllText($envf2, "ALLOWED_HOSTS=`r`n", [Text.UTF8Encoding]::new($false))
Add-EnvListItemJson -Path $envf2 -Key 'ALLOWED_HOSTS' -Item '10.1.1.1'
$rawA = [IO.File]::ReadAllText($envf2)
$mA = Read-EnvMap $envf2
$arrA = @($mA['ALLOWED_HOSTS'] | ConvertFrom-Json | ForEach-Object { $_ })
Assert ($rawA -match 'ALLOWED_HOSTS=\[') '空表追加1项后写出以 [ 开头（数组）'
Assert ($arrA.Count -eq 1 -and ($arrA[0] -is [string]) -and $arrA[0] -eq '10.1.1.1') '空表追加1项解析为长度1的扁平数组'
Add-EnvListItemJson -Path $envf2 -Key 'ALLOWED_HOSTS' -Item '10.1.1.1'   # 二次应去重
Add-EnvListItemJson -Path $envf2 -Key 'ALLOWED_HOSTS' -Item '10.2.2.2'   # 追加第 2 项
$rawB = [IO.File]::ReadAllText($envf2)
$mB = Read-EnvMap $envf2
$arrB = @($mB['ALLOWED_HOSTS'] | ConvertFrom-Json | ForEach-Object { $_ })
Assert ($rawB -match 'ALLOWED_HOSTS=\[') '追加第2项后仍写出数组'
Assert ($arrB.Count -eq 2 -and @($arrB | Where-Object { $_ -eq '10.1.1.1' }).Count -eq 1) '追加第2项后长度2且不重复'
# Add-EnvListItemComma 去重 + 追加
$envf3 = Join-Path $tmp 'e3.env'
[IO.File]::WriteAllText($envf3, "CORS_ORIGINS=`r`n", [Text.UTF8Encoding]::new($false))
Add-EnvListItemComma -Path $envf3 -Key 'CORS_ORIGINS' -Item 'http://a'
Add-EnvListItemComma -Path $envf3 -Key 'CORS_ORIGINS' -Item 'http://a'   # 二次应去重
$mC = Read-EnvMap $envf3
Assert ((@($mC['CORS_ORIGINS'].Split(',')).Count -eq 1) -and $mC['CORS_ORIGINS'] -eq 'http://a') '逗号列表二次去重，仅一项'
Add-EnvListItemComma -Path $envf3 -Key 'CORS_ORIGINS' -Item 'http://b'   # 追加新项
$mC2 = Read-EnvMap $envf3
Assert ($mC2['CORS_ORIGINS'] -eq 'http://a,http://b') '逗号列表追加新项'

# nginx 改写：D:/erp_system 全替换；443 块被注释；3000 块由 443 块派生为 HTTP 入口
$nf = Join-Path $tmp 'n.conf'; Copy-Item (Join-Path $PSScriptRoot 'fixtures\nginx-sample.conf') $nf
$cnt = Update-NginxConf -ConfPath $nf -OldRoot 'D:/erp_system' -NewRoot 'E:/erp' -NginxDir 'C:\nginx'
$body=[IO.File]::ReadAllText($nf)
Assert ($cnt -ge 2) "nginx 替换计数>=2 (实=$cnt)"
Assert ($body -notmatch 'D:/erp_system') '旧根全清'
Assert ($body -match '#\s*server\s*\{[\s\S]*?listen 443 ssl[\s\S]*?\n\s*#?\s*\}') '443 块已注释'
Assert ($body -match 'listen 3000 default_server') 'HTTP 块保留'
Assert ($body -match '3000 HTTP 入口（安装端由 443 块派生）') '3000 块被替换为派生块'
Assert ($body -match 'access_log logs/nginx-access\.log main;') '派生块日志改回明文名'
Assert ($body -match 'location /api/') '派生块继承 443 块的 location'

# ConvertTo-NginxHttpEntry 纯函数：端口/ssl_/日志 三类改写
$derived = @(ConvertTo-NginxHttpEntry @(
  '        listen 443 ssl default_server;',
  '        listen [::]:443 ssl default_server;',
  '        ssl_certificate     k.crt;',
  '        ssl_certificate_key k.key;',
  '        ssl_protocols       TLSv1.2 TLSv1.3;',
  '        root frontend-vite/dist;',
  '        access_log logs/nginx-access-ssl.log main;',
  '        error_log logs/nginx-error-ssl.log warn;',
  '        location /api/ { proxy_pass http://backend; }'
))
Assert (@($derived | Where-Object { $_ -match 'listen 3000 default_server;' }).Count -eq 1) '派生：IPv4 端口改 3000'
Assert (@($derived | Where-Object { $_ -match 'listen \[::\]:3000 default_server;' }).Count -eq 1) '派生：IPv6 端口改 3000'
Assert (@($derived | Where-Object { $_ -match 'ssl_' }).Count -eq 0) '派生：无任何 ssl_ 指令'
Assert (@($derived | Where-Object { $_ -match 'access_log logs/nginx-access\.log main;' }).Count -eq 1) '派生：access_log 去 -ssl'
Assert (@($derived | Where-Object { $_ -match 'error_log logs/nginx-error\.log warn;' }).Count -eq 1) '派生：error_log 去 -ssl'
Assert (@($derived | Where-Object { $_ -match 'root frontend-vite/dist;' }).Count -eq 1) '派生：非 ssl 行原样保留'
Assert (@($derived | Where-Object { $_ -match 'location /api/' }).Count -eq 1) '派生：location 原样保留'

# Install-NssmService 可选键（DependOn/Env）容错：StrictMode 下缺席不抛、不产对应行
$specMin = @{ Name='erp-web'; Application='C:\x\python.exe'; Parameters='-m x'; Directory='C:\d'; Stdout='C:\o.log'; Stderr='C:\e.log' }
$argsMin = @(Get-NssmArgs $specMin)
$flatMin = (@($argsMin | ForEach-Object { $_ -join ' ' }) -join "`n")
Assert ($argsMin.Count -ge 1) 'Get-NssmArgs 缺可选键不抛且产出参数行'
Assert ($flatMin -notmatch 'DependOnService' -and $flatMin -notmatch 'AppEnvironmentExtra') '缺可选键时不产 DependOnService/AppEnvironmentExtra'
$specFull = $specMin.Clone(); $specFull['DependOn']='erp-redis'; $specFull['Env']=@('A=1','B=2')
$argsFull = @(Get-NssmArgs $specFull)
$flatFull = (@($argsFull | ForEach-Object { $_ -join ' ' }) -join "`n")
Assert ($flatFull -match 'DependOnService') '有 DependOn 时产 DependOnService'
Assert ($flatFull -match 'AppEnvironmentExtra') '有 Env 时产 AppEnvironmentExtra'

# Test-SafeOutDir 危险路径守卫（表驱动；保护源树不被 OutDir 覆盖）
$sdCases = @(
  @{ Out='D:\';             Proj='D:\erp_system'; Want=$false; Name='拒绝盘根' }
  @{ Out='D:\erp_system';   Proj='D:\erp_system'; Want=$false; Name='拒绝等于库目录' }
  @{ Out='D:\';             Proj='D:\erp_system'; Want=$false; Name='拒绝库目录的祖辈' }
  @{ Out='D:\erp_system\pkg'; Proj='D:\erp_system'; Want=$false; Name='拒绝库目录的子孙' }
  @{ Out='D:\erp_portable'; Proj='D:\erp_system'; Want=$true;  Name='接受独立目录' }
)
foreach($c in $sdCases){
  Assert (([bool](Test-SafeOutDir $c.Out $c.Proj)) -eq $c.Want) ("Test-SafeOutDir " + $c.Name + " ($($c.Out))")
}

# 主机字面量判定（IPv4/IPv6/域名），供安装端 .env 改写用
$hostCases = @(
  @{ H='192.168.1.97'; Want=$true;  Is6=$false; Name='IPv4' }
  @{ H='240e:3b1:d052:1130:b156:742e:8e8a:fd37'; Want=$true; Is6=$true; Name='裸 IPv6' }
  @{ H='[240e:3b1:d052:1130:b156:742e:8e8a:fd37]'; Want=$true; Is6=$true; Name='带方括号 IPv6' }
  @{ H='erp.example.com'; Want=$true; Is6=$false; Name='域名' }
  @{ H=''; Want=$false; Is6=$false; Name='空' }
  @{ H='a,b'; Want=$false; Is6=$false; Name='逗号串非法' }
  @{ H='has space'; Want=$false; Is6=$false; Name='含空白非法' }
  @{ H='a:b'; Want=$false; Is6=$false; Name='单冒号非 IPv6' }
  @{ H='::1'; Want=$true; Is6=$true; Name='简写 IPv6' }
)
foreach($c in $hostCases){
  Assert (([bool](Test-HostLiteral $c.H)) -eq $c.Want) ("Test-HostLiteral " + $c.Name + " ($($c.H))")
  Assert (([bool](Test-IsIPv6Literal $c.H)) -eq $c.Is6) ("Test-IsIPv6Literal " + $c.Name)
}

# Paused/PausePending 需要先 continue 才能 stop；其它状态不应触发
$pauseCases = @(
  @{ S='Paused'; Want=$true }
  @{ S='PausePending'; Want=$true }
  @{ S='Running'; Want=$false }
  @{ S='Stopped'; Want=$false }
  @{ S='StartPending'; Want=$false }
)
foreach($c in $pauseCases){
  Assert (([bool](Test-ServiceStatusNeedsContinue $c.S)) -eq $c.Want) ("Test-ServiceStatusNeedsContinue " + $c.S)
}

# 任何 *Pending 都不接受控制码
$pendingCases = @(
  @{ S='StartPending'; Want=$true }
  @{ S='StopPending'; Want=$true }
  @{ S='PausePending'; Want=$true }
  @{ S='ContinuePending'; Want=$true }
  @{ S='Paused'; Want=$false }
  @{ S='Running'; Want=$false }
  @{ S='Stopped'; Want=$false }
)
foreach($c in $pendingCases){
  Assert (([bool](Test-ServiceStatusPending $c.S)) -eq $c.Want) ("Test-ServiceStatusPending " + $c.S)
}

# Redis 口令脱敏（安全相关，防止错误信息/截图泄露 --requirepass）
$maskCases = @(
  @{ A=@('set','erp-redis','AppParameters','--requirepass "p w"'); Name='双引号含空格' }
  @{ A=@('set','erp-redis','AppParameters','--requirepass ''p w'''); Name='单引号含空格' }
  @{ A=@('set','erp-redis','AppParameters','--requirepass "p w\"'); Name='末尾转义引号（无闭合）' }
  @{ A=@('set','erp-redis','AppParameters','--requirepass "p\"q w"'); Name='转义引号后仍含空格' }
  @{ A=@('set','erp-redis','AppParameters','--requirepass secret123'); Name='无引号' }
)
foreach($c in $maskCases){
  $m = ConvertTo-MaskedNssmArgs $c.A
  Assert ($m -match '--requirepass \*\*\*') ("脱敏保留标记 " + $c.Name)
  Assert ($m -notmatch 'secret123') ("脱敏不含明文 " + $c.Name)
  Assert ($m -notmatch '\bp w') ("脱敏不含含空格口令片段 " + $c.Name)
}
$noPw = ConvertTo-MaskedNssmArgs @('set','erp-web','AppParameters','-m x')
Assert ($noPw -notmatch '\*\*\*') '非口令参数不被改写'

# Invoke-Nssm 失败时必须把动作/退出码写进异常 Data（Stop-NssmService 靠它区分可降级失败）
$fakeNssm = Join-Path $tmp 'nssm-fail.cmd'
[IO.File]::WriteAllText($fakeNssm, "@exit /b 3`r`n", [Text.ASCIIEncoding]::new())
try {
  Invoke-Nssm $fakeNssm @('stop','erp-x') 'stop'
  Assert $false 'Invoke-Nssm 应对非零退出码抛异常'
} catch {
  Assert ($_.Exception.Data['nssmAction'] -eq 'stop') '异常 Data 携带 nssmAction'
  Assert ([int]$_.Exception.Data['nssmExitCode'] -eq 3) '异常 Data 携带退出码'
}

# Stop-NssmService 行为：已停止直接成功；Pending → Stopped 需等待后成功
function New-FakeService([string]$Status){
  $o=New-Object psobject
  $o | Add-Member NoteProperty Status $Status
  $o | Add-Member ScriptMethod Dispose {}
  $o
}
$script:svcQueue=[Collections.Queue]::new()
function global:Get-Service {
  [CmdletBinding()] param([string]$Name)
  if($script:svcQueue.Count -gt 0){ New-FakeService ([string]$script:svcQueue.Dequeue()) }
  else { New-FakeService 'Running' }
}
$script:svcQueue.Enqueue('Stopped')
Assert ((Stop-NssmService 'x' 'erp-test') -eq $true) 'Stop-NssmService：已停止直接成功'
$script:svcQueue.Clear(); $script:svcQueue.Enqueue('StartPending'); $script:svcQueue.Enqueue('Stopped')
Assert ((Stop-NssmService 'x' 'erp-test') -eq $true) 'Stop-NssmService：等待 Pending 落定后成功'

# 服务不存在（ObjectNotFound）→ 视为已停止；查询故障不得被当成不存在
function global:Get-Service {
  [CmdletBinding()] param([string]$Name)
  $er=[System.Management.Automation.ErrorRecord]::new([System.Exception]::new('missing'),'x','ObjectNotFound',$null)
  throw $er
}
Assert ($null -eq (Get-ServiceStatus 'missing')) 'Get-ServiceStatus：ObjectNotFound → $null'
Remove-Item function:Get-Service -ErrorAction SilentlyContinue

Remove-Item $tmp -Recurse -Force
if($fail){ exit 1 } else { Write-Host 'ALL PASS' }
