﻿﻿$files = @(
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
  $broadExcept = ($content | Select-String -Pattern 'except\s+Exception\s*:|except\s*:' -AllMatches).Count
  $todo = ($content | Select-String -Pattern '#\s*TODO|#\s*FIXME|#\s*XXX' -AllMatches).Count
  $textCall = ($content | Select-String -Pattern 'text\(' -AllMatches).Count
  $sessionClose = ($content | Select-String -Pattern 'session\.close' -AllMatches).Count
  $asyncDef = ($content | Select-String -Pattern '^\s*async\s+def\s' -AllMatches).Count
  $syncDef = ($content | Select-String -Pattern '^\s*def\s' -AllMatches).Count
  $anyType = ($content | Select-String -Pattern ':\s*Any\b|->\s*Any\b|List\[Any\]|Dict\[.*Any' -AllMatches).Count
  $fstringSql = ($content | Select-String -Pattern 'execute\(.*f["'']' -AllMatches).Count
  $results += [PSCustomObject]@{
    File = $name
    BroadExcept = $broadExcept
    TODO = $todo
    Text = $textCall
    SessClose = $sessionClose
    AsyncDef = $asyncDef
    SyncDef = $syncDef
    AnyType = $anyType
    FStrSQL = $fstringSql
  }
}
$results | Format-Table -AutoSize