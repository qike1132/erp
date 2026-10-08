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
Assert (@($arr | Where-Object { $_ -eq '10.0.0.5' }).Count -eq 1) 'ALLOWED_HOSTS 去重'
$raw = [IO.File]::ReadAllText($envf)
Assert ($raw -match '数据库口令') '中文注释行保留'
Assert ($raw[0] -ne [char]0xFEFF) '无 BOM'
Remove-Item $tmp -Recurse -Force
if($fail){ exit 1 } else { Write-Host 'ALL PASS' }
