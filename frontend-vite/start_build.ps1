$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'npx.cmd'
$psi.Arguments = 'vite build'
$psi.WorkingDirectory = 'd:\erp_system\frontend-vite'
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host ('Started PID: ' + $proc.Id)