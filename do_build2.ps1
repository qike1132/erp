$env:JAVA_HOME = "D:\JDK\jdk-17.0.13+11"
Set-Location "d:\erp_system\android-app"
Remove-Item -Path "d:\erp_system\build_log.txt" -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c gradlew.bat :app:assembleDebug 2>&1" -NoNewWindow -Wait -PassThru -WorkingDirectory "d:\erp_system\android-app" -RedirectStandardOutput "d:\erp_system\build_stdout.txt" -RedirectStandardError "d:\erp_system\build_stderr.txt"
"Exit: $($proc.ExitCode)" | Out-File "d:\erp_system\build_exit.txt"
