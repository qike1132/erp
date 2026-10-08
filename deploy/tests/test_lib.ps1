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

# nginx 改写：2 处 D:/erp_system 全替换；443 server 块被注释；HTTP server 块保留
$nf = Join-Path $tmp 'n.conf'; Copy-Item (Join-Path $PSScriptRoot 'fixtures\nginx-sample.conf') $nf
$cnt = Update-NginxConf -ConfPath $nf -OldRoot 'D:/erp_system' -NewRoot 'E:/erp' -NginxDir 'C:\nginx'
$body=[IO.File]::ReadAllText($nf)
Assert ($cnt -ge 2) "nginx 替换计数>=2 (实=$cnt)"
Assert ($body -notmatch 'D:/erp_system') '旧根全清'
Assert ($body -match '#\s*server\s*\{[\s\S]*?listen 443 ssl[\s\S]*?\n\s*#?\s*\}') '443 块已注释'
Assert ($body -match 'listen 3000 default_server') 'HTTP 块保留'

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
  @{ Out='D:\erp_portable'; Proj='D:\erp_system'; Want=$true;  Name='接受独立目录' }
)
foreach($c in $sdCases){
  Assert (([bool](Test-SafeOutDir $c.Out $c.Proj)) -eq $c.Want) ("Test-SafeOutDir " + $c.Name + " ($($c.Out))")
}

Remove-Item $tmp -Recurse -Force
if($fail){ exit 1 } else { Write-Host 'ALL PASS' }
