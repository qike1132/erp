$env:JAVA_HOME = "D:\JDK\jdk-17.0.13+11"
Set-Location "d:\erp_system\android-app"
$proc = Start-Process -FilePath ".\gradlew.bat" -ArgumentList ":app:assembleDebug" -NoNewWindow -Wait -PassThru -RedirectStandardOutput "d:\erp_system\stdout.txt" -RedirectStandardError "d:\erp_system\stderr.txt"
"Exit code: $($proc.ExitCode)" | Out-File "d:\erp_system\exit_code.txt"
