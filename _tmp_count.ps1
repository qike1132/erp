Get-ChildItem 'd:\erp_system\static' -Recurse -Filter '*.js' | ForEach-Object {  = (Get-Content .FullName).Count; Write-Host (.ToString() + ' ' + .FullName) } 
