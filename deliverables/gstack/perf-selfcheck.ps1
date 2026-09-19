#Requires -Version 5.1
<#
.SYNOPSIS
    ERP 生产栈模式自检（严格只读，不修改任何服务状态）

.DESCRIPTION
    回答一个核心问题："我现在访问的到底是不是生产栈？"
    并给出关键健康信号，逐项判定 PASS / FAIL / WARN。

    累计型指标（强制重启次数 / [emerg] / 静态 404）采用【增量基线棘轮】：
    这些指标读的是全量历史日志，重启服务不会让它们归零，直接判 >0 会永久
    FAIL 并掩盖真实变化。脚本把它们记入 .perf-selfcheck-baseline.json，只对
    「自基线起的新增」报警；在无新增（或日志轮转导致回落）时才重设基线，
    因此不会洗白新增。

    配套报告：deliverables/gstack/perf-debugmode-vs-production-2026-09-17.md  §5.1

.PARAMETER WebPort
    前端端口，默认 3000

.PARAMETER ApiPort
    后端端口，默认 5002

.PARAMETER OutFile
    结果落盘路径。默认在脚本同目录生成 perf-selfcheck-<时间戳>.log

.PARAMETER UpdateBaseline
    强制把当前累计值重设为基线（即使存在新增）。一般不需要 —— 脚本在无新增时
    会自动重设基线。仅在「已确认新增项已被人工处置、需要归零」时使用。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\perf-selfcheck.ps1

.NOTES
    只读脚本：不 Kill 进程、不启动/停止服务、不写任何配置。
#>
[CmdletBinding()]
param(
    [int]    $WebPort = 3000,
    [int]    $ApiPort = 5002,
    [string] $OutFile = "",
    [switch] $UpdateBaseline = $false
)

$ErrorActionPreference = 'Continue'

# ---------- 输出编码（中文 Windows 控制台防乱码） ----------
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---------- 结果收集 ----------
$script:Results = New-Object System.Collections.ArrayList
$script:Lines   = New-Object System.Collections.ArrayList

function Write-Line {
    param([string]$Text = "")
    [void]$script:Lines.Add($Text)
    Write-Output $Text
}

function Add-Check {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('PASS', 'FAIL', 'WARN', 'INFO')][string]$Status,
        [string]$Detail = "",
        [string]$Expect = ""
    )
    [void]$script:Results.Add([pscustomobject]@{
            Item   = $Name
            Status = $Status
            Detail = $Detail
            Expect = $Expect
        })
    $icon = switch ($Status) {
        'PASS' { '[ OK ]' }
        'FAIL' { '[FAIL]' }
        'WARN' { '[WARN]' }
        default { '[INFO]' }
    }
    Write-Line ("{0} {1}" -f $icon, $Name)
    if ($Detail) { Write-Line ("        实测: {0}" -f $Detail) }
    if ($Expect -and $Status -ne 'PASS') { Write-Line ("        期望: {0}" -f $Expect) }
}

# ---------- HTTP 原始请求（关闭自动解压，才能看到 Content-Encoding） ----------
function Invoke-RawHttp {
    param(
        [string]$Url,
        [string]$AcceptEncoding = 'gzip, deflate, br',
        [int]   $TimeoutMs = 5000
    )
    $resp = $null
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method = 'GET'
        $req.Timeout = $TimeoutMs
        $req.ReadWriteTimeout = $TimeoutMs
        $req.AutomaticDecompression = [System.Net.DecompressionMethods]::None
        $req.Headers['Accept-Encoding'] = $AcceptEncoding
        $req.UserAgent = 'erp-selfcheck/1.0'
        $resp = $req.GetResponse()
        $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $body = $sr.ReadToEnd()
        $sr.Close()
        $hdr = @{}
        foreach ($k in $resp.Headers.AllKeys) { $hdr[$k] = $resp.Headers[$k] }
        return [pscustomobject]@{
            Status  = [int]$resp.StatusCode
            Headers = $hdr
            Body    = $body
            Error   = $null
        }
    }
    catch {
        return [pscustomobject]@{
            Status = 0; Headers = @{}; Body = ''
            Error  = $_.Exception.Message
        }
    }
    finally {
        if ($resp) { try { $resp.Close() } catch { } }
    }
}

function Get-ListenerPid {
    param([int]$Port)
    $c = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
         Where-Object { $_.LocalAddress -eq '0.0.0.0' -or $_.LocalAddress -eq '127.0.0.1' } |
         Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return $null
}

function Get-ProcName {
    # 注意：参数名不能用 $Pid —— 那是 PowerShell 自动变量（当前进程 ID），会静默失效
    param([int]$ProcId)
    if (-not $ProcId) { return '(none)' }
    $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if ($p) { return $p.ProcessName }
    return "(pid $ProcId 已退出)"
}

# =====================================================================
Write-Line ""
Write-Line "=================================================================="
Write-Line "  ERP 生产栈模式自检   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Line "  前端 :$WebPort   后端 :$ApiPort    (只读，不改动任何服务)"
Write-Line "=================================================================="
Write-Line ""

# ---------- 1. 端口归属 ----------
Write-Line "--- [1] 端口归属 -------------------------------------------------"
$webPid = Get-ListenerPid -Port $WebPort
$apiPid = Get-ListenerPid -Port $ApiPort
$webName = Get-ProcName -ProcId $webPid
$apiName = Get-ProcName -ProcId $apiPid

Add-Check -Name "前端 :$WebPort 监听者" `
    -Status $(if ($webPid) { 'INFO' } else { 'FAIL' }) `
    -Detail $(if ($webPid) { "PID $webPid / $webName" } else { "无监听" }) `
    -Expect "PID 应为 nginx（生产）"

Add-Check -Name "后端 :$ApiPort 监听者" `
    -Status $(if ($apiPid) { 'INFO' } else { 'FAIL' }) `
    -Detail $(if ($apiPid) { "PID $apiPid / $apiName" } else { "无监听" }) `
    -Expect "PID 应为 python（uvicorn）"

# ---------- 2. 前端是 dev 还是 dist ----------
Write-Line ""
Write-Line "--- [2] 前端运行模式 ---------------------------------------------"
$idx = Invoke-RawHttp -Url "http://127.0.0.1:$WebPort/"
$isDev = $false
if ($idx.Status -eq 200) {
    $isDev = $idx.Body -match '@vite/client'
    Add-Check -Name "前端产物模式（@vite/client 注入）" `
        -Status $(if ($isDev) { 'FAIL' } else { 'PASS' }) `
        -Detail $(if ($isDev) { '检测到 @vite/client  -> Vite DEV SERVER' } else { '未注入 HMR 客户端 -> 预构建产物' }) `
        -Expect "0（生产应为 dist 静态产物，无 HMR）"

    $srcHit = $idx.Body -match '/src/main\.ts'
    Add-Check -Name "前端是否直出源码（/src/main.ts）" `
        -Status $(if ($srcHit) { 'FAIL' } else { 'PASS' }) `
        -Detail $(if ($srcHit) { 'HTML 引用 /src/main.ts -> 源码直服，dev 独有' } else { '未引用源码入口' }) `
        -Expect "生产应引用 /assets/index-*.js"

    $svr = ''
    if ($idx.Headers.ContainsKey('Server')) { $svr = $idx.Headers['Server'] }
    Add-Check -Name ":$WebPort 的 Server 响应头" `
        -Status $(if ($svr -match 'nginx') { 'PASS' } else { 'FAIL' }) `
        -Detail $(if ($svr) { $svr } else { '(无 Server 头)' }) `
        -Expect "nginx"

    $cc = ''
    if ($idx.Headers.ContainsKey('Cache-Control')) { $cc = $idx.Headers['Cache-Control'] }
    Add-Check -Name "index.html 缓存策略" `
        -Status $(if ($cc -match 'no-cache|no-store|must-revalidate') { 'PASS' } else { 'WARN' }) `
        -Detail $(if ($cc) { $cc } else { '(无 Cache-Control)' }) `
        -Expect "no-cache / no-store / must-revalidate（HTML 必须不缓存，否则 hash 撕裂）"
}
else {
    Add-Check -Name "前端 :$WebPort 可达性" -Status 'FAIL' `
        -Detail "HTTP $($idx.Status) $($idx.Error)" -Expect "200"
}

# ---------- 3. nginx 进程 ----------
Write-Line ""
Write-Line "--- [3] Nginx 与 Windows 服务 -------------------------------------"
$ngx = @(Get-Process nginx -ErrorAction SilentlyContinue)
Add-Check -Name "nginx 进程数" `
    -Status $(if ($ngx.Count -ge 1) { 'PASS' } else { 'FAIL' }) `
    -Detail "$($ngx.Count) 个" `
    -Expect ">=1（0 即表示前端托管层根本没跑，所有 nginx 配置都是废纸）"

foreach ($svc in @('erp-prod', 'erp-arq', 'erp-redis', 'erp-redis-broker')) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if (-not $s) {
        Add-Check -Name "NSSM 服务 $svc" -Status 'WARN' -Detail '未注册' -Expect 'Running'
    }
    else {
        Add-Check -Name "NSSM 服务 $svc" `
            -Status $(if ($s.Status -eq 'Running') { 'PASS' } else { 'WARN' }) `
            -Detail $s.Status.ToString() -Expect 'Running'
    }
}

# ---------- 4. 压缩 ----------
Write-Line ""
Write-Line "--- [4] 传输压缩（gzip / br） -------------------------------------"
# 注意：GZipMiddleware 默认 minimum_size=1000，小于 1KB 的响应按设计就不压缩，
# 所以必须挑一个"大响应"端点才测得准 —— 故优先 /metrics（实测 ~18KB）。
$apiOk = $false
foreach ($ep in @('/metrics', '/api/health', '/docs')) {
    $r = Invoke-RawHttp -Url "http://127.0.0.1:${ApiPort}${ep}"
    if ($r.Status -ne 200) { continue }
    $raw = $r.Body.Length
    if ($raw -lt 1000) {
        Write-Line ("        跳过 $ep（响应仅 $raw 字节 < gzip minimum_size 1000，恒不压缩，测不出问题）")
        continue
    }
    $apiOk = $true
    $enc = ''
    if ($r.Headers.ContainsKey('Content-Encoding')) { $enc = $r.Headers['Content-Encoding'] }
    # 本地估算 gzip 后体积，量化浪费比例
    $gz = 0
    try {
        $ms = New-Object System.IO.MemoryStream
        $gzs = New-Object System.IO.Compression.GzipStream($ms, [System.IO.Compression.CompressionMode]::Compress, $true)
        $buf = [System.Text.Encoding]::UTF8.GetBytes($r.Body)
        $gzs.Write($buf, 0, $buf.Length); $gzs.Close()
        $gz = $ms.Length
    }
    catch { }
    $waste = ''
    if ($gz -gt 0 -and $raw -gt 0) {
        $waste = ("，gzip 后约 {0} 字节 → 当前多传 {1:P1}" -f $gz, (1 - $gz / $raw))
    }
    Add-Check -Name "API 响应压缩  $ep" `
        -Status $(if ($enc) { 'PASS' } else { 'FAIL' }) `
        -Detail $(if ($enc) { "Content-Encoding: $enc" } else { "无 Content-Encoding，明文 $raw 字节$waste" }) `
        -Expect "gzip / br"
    break
}
if (-not $apiOk) {
    Add-Check -Name "API 响应压缩" -Status 'WARN' `
        -Detail "后端 :$ApiPort 未找到 >=1KB 的可探测端点（可手动试 /metrics）" -Expect "gzip / br"
}

# 静态资源压缩（从 index.html 里抓真实 asset 名）
$assetPath = ''
if ($idx.Status -eq 200 -and $idx.Body -match '(/assets/[A-Za-z0-9_\-\.]+\.js)') {
    $assetPath = $Matches[1]
}
if ($assetPath) {
    $r = Invoke-RawHttp -Url "http://127.0.0.1:${WebPort}${assetPath}"
    $enc = ''
    if ($r.Headers.ContainsKey('Content-Encoding')) { $enc = $r.Headers['Content-Encoding'] }
    $ct = ''
    if ($r.Headers.ContainsKey('Content-Type')) { $ct = $r.Headers['Content-Type'] }
    Add-Check -Name "静态资源压缩  $assetPath" `
        -Status $(if ($enc) { 'PASS' } else { 'FAIL' }) `
        -Detail $(if ($enc) { "Content-Encoding: $enc" } else { "无压缩；Content-Type=$ct，响应 $($r.Body.Length) 字节" }) `
        -Expect "gzip / br"
    if ($r.Status -eq 200 -and $ct -match 'text/html') {
        Add-Check -Name "静态资源是否被 SPA 回退吞掉" -Status 'FAIL' `
            -Detail "$assetPath 返回了 text/html 而非 application/javascript" `
            -Expect "application/javascript（回退成 HTML 说明该资源 404 了）"
    }
    $acc = ''
    if ($r.Headers.ContainsKey('Cache-Control')) { $acc = $r.Headers['Cache-Control'] }
    Add-Check -Name "静态资源长缓存" `
        -Status $(if ($acc -match 'immutable|max-age=3|max-age=6|max-age=\d{6,}') { 'PASS' } else { 'WARN' }) `
        -Detail $(if ($acc) { $acc } else { '(无 Cache-Control)' }) `
        -Expect "public, max-age=31536000, immutable"
}

# ---------- 5. 端口保留区间（10013 排查） ----------
Write-Line ""
Write-Line "--- [5] Windows 保留端口区间（bind 10013 排查） -------------------"
$excluded = & netsh int ipv4 show excludedportrange protocol=tcp 2>$null
$hitEx = @()
if ($excluded) {
    foreach ($line in $excluded) {
        if ($line -match '^\s*(\d+)\s*[-–]\s*(\d+)\s*$') {
            $lo = [int]$Matches[1]; $hi = [int]$Matches[2]
            if ($WebPort -ge $lo -and $WebPort -le $hi) { $hitEx += "${lo}-${hi}" }
        }
        elseif ($line -match '^\s*(\d+)\s*$') {
            if ([int]$Matches[1] -eq $WebPort) { $hitEx += $Matches[1] }
        }
    }
    Add-Check -Name ":$WebPort 是否落在保留区间" `
        -Status $(if ($hitEx.Count -eq 0) { 'PASS' } else { 'FAIL' }) `
        -Detail $(if ($hitEx.Count -eq 0) { '未被排除，端口可正常绑定' } else { "命中排除区间: $($hitEx -join ', ')" }) `
        -Expect "不落排除区间；若命中需换端口或重启 winnat"
    Write-Line ("        全部排除段: " + (($excluded | Where-Object { $_ -match '\d' } | Select-Object -Skip 2) -join ' | '))
}
else {
    Add-Check -Name ":$WebPort 是否落在保留区间" -Status 'WARN' `
        -Detail 'netsh 未返回数据（权限不足或被拦截），未能闭环' -Expect '需在有权限会话补跑'
}

# ---------- 6. 日志信号 ----------
Write-Line ""
Write-Line "--- [6] 日志信号 ---------------------------------------------------"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root 'logs'))) { $root = (Get-Location).Path }
$logDir = Join-Path $root 'logs'

# ---------- 增量基线棘轮 ----------
# 累计型指标读的是全量历史日志，重启不会归零，直接判 >0 会永久 FAIL。
# 这里只对「自基线起的新增」报警；无新增/日志轮转回落时才重设基线（不洗白新增）。
$baselinePath = Join-Path $PSScriptRoot '.perf-selfcheck-baseline.json'
$script:Baseline = $null
if (Test-Path $baselinePath) {
    try { $script:Baseline = Get-Content $baselinePath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { $script:Baseline = $null }
}
$script:NewBaseline = [ordered]@{ ts = (Get-Date -Format 'o') }
function Get-Delta {
    param([string]$Key, [int]$Current)
    $base = $null
    if ($null -ne $script:Baseline -and ($script:Baseline.PSObject.Properties.Name -contains $Key)) {
        $base = [int]$script:Baseline.$Key
    }
    $d = if ($null -eq $base) { 0 } else { $Current - $base }
    $rebase = ($null -eq $base) -or ($UpdateBaseline.IsPresent) -or ($d -le 0)
    $script:NewBaseline[$Key] = $(if ($rebase) { $Current } else { $base })
    return $d
}

$prodLog = Join-Path $logDir 'erp-prod.log'
if (Test-Path $prodLog) {
    $n = (Select-String -Path $prodLog -Pattern '健康检查持续失败' -SimpleMatch -ErrorAction SilentlyContinue | Measure-Object).Count
    $dn = Get-Delta -Key 'restart_count' -Current $n
    Add-Check -Name "后端强制重启次数（自基线起新增）" `
        -Status $(if ($dn -le 0) { 'PASS' } else { 'FAIL' }) `
        -Detail "累计 $n 次，自基线起新增 $dn 次" -Expect "新增 0（>0 即新出现重启风暴）"
}
else {
    Add-Check -Name "后端强制重启次数" -Status 'INFO' -Detail "未找到 $prodLog"
}

$ngxErr = Join-Path $logDir 'nginx-error.log'
if (Test-Path $ngxErr) {
    $e = (Select-String -Path $ngxErr -Pattern '\[emerg\]' -ErrorAction SilentlyContinue | Measure-Object).Count
    $b = (Select-String -Path $ngxErr -Pattern 'bind\(\).*failed' -ErrorAction SilentlyContinue | Measure-Object).Count
    $de = Get-Delta -Key 'emerg_count' -Current $e
    Add-Check -Name "nginx-error.log 致命错误 [emerg]（自基线起新增）" `
        -Status $(if ($de -le 0) { 'PASS' } else { 'FAIL' }) `
        -Detail "累计 $e 条（其中 bind 失败 $b 条），自基线起新增 $de 条" -Expect "新增 0"
    if ($e -gt 0) {
        Write-Line "        最近一条："
        Select-String -Path $ngxErr -Pattern '\[emerg\]' -ErrorAction SilentlyContinue |
            Select-Object -Last 1 | ForEach-Object { Write-Line ("        " + $_.Line.Trim()) }
        Write-Line "        ⚠ 该错误曾无人读取（Popen 丢弃 handle + stderr=DEVNULL）。"
        Write-Line "          D4 已修：_FrontendNginx._spawn 保存句柄并把 stdout 落 logs/nginx-spawn.out.log；"
        Write-Line "          且 _ensure_started 失败时会 dump 该文件尾部（_dump_error_log_tail）。"
    }
    $f404 = (Select-String -Path $ngxErr -Pattern 'CreateFile.*failed' -ErrorAction SilentlyContinue | Measure-Object).Count
    $d404 = Get-Delta -Key 'static_404' -Current $f404
    Add-Check -Name "静态资源 404（自基线起新增）" `
        -Status $(if ($d404 -le 0) { 'PASS' } else { 'WARN' }) `
        -Detail "累计 $f404 条，自基线起新增 $d404 条" -Expect "新增 0（增长即旧 HTML + 新 assets）"
}
else {
    Add-Check -Name "nginx-error.log" -Status 'INFO' -Detail "未找到 $ngxErr"
}

# ---- 心跳：prod_runner.json 新鲜度 + frontend_ok（D1/D3 落地后才有的字段） ----
$statusFile = Join-Path $logDir 'prod_runner.json'
if (Test-Path $statusFile) {
    $age = (New-TimeSpan -Start (Get-Item $statusFile).LastWriteTime -End (Get-Date)).TotalSeconds
    $sj = $null
    try { $sj = Get-Content $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    $hasField = ($null -ne $sj) -and ($sj.PSObject.Properties.Name -contains 'frontend_ok')
    $fok = if ($hasField) { [bool]$sj.frontend_ok } else { $false }
    $detail = ('心跳龄 {0:N0}s；frontend_ok={1}' -f $age, $fok)
    if (-not $hasField) {
        Add-Check -Name "prod_runner 心跳（状态文件 + frontend_ok）" -Status 'WARN' `
            -Detail "$detail（缺 frontend_ok → 跑的还是旧代码，D1/D3 未生效）" `
            -Expect "心跳龄 <30s 且含 frontend_ok"
    }
    elseif ($age -gt 30) {
        Add-Check -Name "prod_runner 心跳（状态文件 + frontend_ok）" -Status 'FAIL' `
            -Detail "$detail（守护循环可能已停）" -Expect "心跳龄 <30s"
    }
    elseif (-not $fok) {
        Add-Check -Name "prod_runner 心跳（状态文件 + frontend_ok）" -Status 'FAIL' `
            -Detail "$detail（前端托管不健康）" -Expect "frontend_ok=True"
    }
    else {
        Add-Check -Name "prod_runner 心跳（状态文件 + frontend_ok）" -Status 'PASS' `
            -Detail $detail -Expect "心跳龄 <30s 且 frontend_ok=True"
    }
}
else {
    Add-Check -Name "prod_runner 心跳" -Status 'INFO' -Detail "未找到 $statusFile"
}

# ---- 落盘新基线（棘轮） ----
try {
    ($script:NewBaseline | ConvertTo-Json -Depth 4) | Set-Content -Path $baselinePath -Encoding UTF8
}
catch { Write-Line "  [WARN] 基线写入失败: $($_.Exception.Message)" }

$today = Get-Date -Format 'yyyyMMdd'
$smLog = Join-Path $logDir "server_manager_$today.log"
if (Test-Path $smLog) {
    $r = (Select-String -Path $smLog -Pattern 'Reloading' -ErrorAction SilentlyContinue | Measure-Object).Count
    Add-Check -Name "今日 --reload 触发次数" `
        -Status $(if ($r -eq 0) { 'PASS' } else { 'WARN' }) `
        -Detail "$r 次" -Expect "0（生产不应有 reload）"
}

# =====================================================================
Write-Line ""
Write-Line "=================================================================="
$nf = @($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$nw = @($script:Results | Where-Object { $_.Status -eq 'WARN' }).Count

Write-Line "  汇总: FAIL $nf 项 / WARN $nw 项"
Write-Line "  （累计型指标按『自基线起新增』判定；基线: $baselinePath）"
Write-Line ""

# 综合判定
if ($isDev) {
    Write-Line "  >>> 判定：当前跑的是 【开发栈】<<<"
    Write-Line "      :$WebPort 是 Vite dev server，nginx 未托管前端。"
    Write-Line "      你在此状态下测得的任何'生产性能'都不是生产性能。"
    Write-Line "      修复：停掉占用 :$WebPort 的 $webName(PID $webPid)，再 nssm start erp-prod"
}
elseif ($ngx.Count -ge 1) {
    Write-Line "  >>> 判定：当前跑的是 【生产栈】<<<"
    Write-Line "      nginx 已托管前端，产物为 dist。可在此基础上做 A/B 基线。"
}
else {
    Write-Line "  >>> 判定：【混合/降级态】<<<"
    Write-Line "      前端非 dev，但 nginx 进程为 0 —— 多半是 vite preview 降级托管。"
    Write-Line "      见 _FrontendNginx：检测不到 nginx.exe 时静默降级为 vite preview，不写状态、不报警。"
}
Write-Line ""
if ($nf -eq 0 -and $nw -eq 0) {
    Write-Line "  结论: 全部通过"
}
else {
    Write-Line "  优先修这几项（按严重度）："
    $script:Results | Where-Object { $_.Status -eq 'FAIL' } | ForEach-Object {
        Write-Line ("    - " + $_.Item + "   [" + $_.Detail + "]")
    }
}
Write-Line "=================================================================="
Write-Line ""

# ---------- 落盘 ----------
if (-not $OutFile) {
    $OutFile = Join-Path $PSScriptRoot ("perf-selfcheck-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
try {
    $script:Lines | Set-Content -Path $OutFile -Encoding UTF8
    Write-Output "结果已写入: $OutFile"
}
catch {
    Write-Output "落盘失败: $($_.Exception.Message)"
}

Write-Output ""
Write-Output "提示：先跑一次存档作为【优化前基线】，修完再跑一次对比。"
