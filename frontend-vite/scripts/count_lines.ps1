$files = $args
foreach ($f in $files) {
  $c = (Get-Content $f).Count
  Write-Output ($f + ' : ' + $c + ' lines')
}