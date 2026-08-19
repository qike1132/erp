﻿$files = @(
  'D:\erp_system\fastapi_app\services\stock_service.py',
  'D:\erp_system\fastapi_app\services\case_service.py',
  'D:\erp_system\fastapi_app\services\staging_service.py',
  'D:\erp_system\fastapi_app\services\material_registration_service.py',
  'D:\erp_system\fastapi_app\services\daily_production_service.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\material_registration.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\case_endpoint.py',
  'D:\erp_system\fastapi_app\services\bom_service.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\stock.py',
  'D:\erp_system\fastapi_app\services\storage_service.py',
  'D:\erp_system\fastapi_app\services\report_service.py',
  'D:\erp_system\fastapi_app\services\production_summary_service.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\production_summary.py',
  'D:\erp_system\fastapi_app\services\production_plan_service.py',
  'D:\erp_system\fastapi_app\services\product_service.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\production_plan.py',
  'D:\erp_system\fastapi_app\services\fifo_allocation.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\daily_production.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\report.py',
  'D:\erp_system\fastapi_app\services\serializers\order_serializer.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\staging_stockout.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\staging_order.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\staging_stockin.py',
  'D:\erp_system\fastapi_app\services\product_search_service.py',
  'D:\erp_system\fastapi_app\services\inventory_service.py',
  'D:\erp_system\fastapi_app\services\pattern_maker_service.py',
  'D:\erp_system\fastapi_app\services\plan_utils.py',
  'D:\erp_system\fastapi_app\services\staging_utils.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\pattern_maker.py',
  'D:\erp_system\fastapi_app\api\v1\endpoints\product.py',
  'D:\erp_system\fastapi_app\services\numbering.py'
)
$results = @()
foreach ($f in $files) {
  $name = Split-Path $f -Leaf
  $content = Get-Content $f -ErrorAction SilentlyContinue
  if (-not $content) { continue }
  $lines = $content.Count
  $commentLines = ($content | Select-String -Pattern '^\s*#' -AllMatches).Count
  $docStrings = ($content | Select-String -Pattern '"""' -AllMatches).Count / 2
  $commentRatio = [math]::Round(($commentLines / $lines) * 100, 1)
  $noneCheck = ($content | Select-String -Pattern 'is None|is not None' -AllMatches).Count
  $nakedNone = ($content | Select-String -Pattern '==\s*None|!=\s*None' -AllMatches).Count
  $fstringInQuery = ($content | Select-String -Pattern '(select|insert|update|delete|where|from).*f["'']' -AllMatches).Count
  $noqaCount = ($content | Select-String -Pattern '#\s*noqa' -AllMatches).Count
  $nosecCount = ($content | Select-String -Pattern '#\s*nosec' -AllMatches).Count
  $printStmt = ($content | Select-String -Pattern '^\s*print\(' -AllMatches).Count
  $raiseCount = ($content | Select-String -Pattern '^\s*raise\s' -AllMatches).Count
  $loggerCount = ($content | Select-String -Pattern 'logger\.' -AllMatches).Count
  $results += [PSCustomObject]@{
    File = $name
    Lines = $lines
    Comments = $commentLines
    CommRatio = $commentRatio
    NoneCheck = $noneCheck
    NakedNone = $nakedNone
    FStrInSQL = $fstringInQuery
    NoQA = $noqaCount
    NoSec = $nosecCount
    Print = $printStmt
    Raise = $raiseCount
    Logger = $loggerCount
  }
}
$results | Format-Table -AutoSize