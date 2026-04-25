foreach ( in Get-ChildItem " d:\erp_system\static\ -Recurse -Filter \*.js\) { = (Get-Content .FullName).Count; Write-Host " \ }
