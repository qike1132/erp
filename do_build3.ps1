$env:JAVA_HOME = "D:\JDK\jdk-17.0.13+11"
Set-Location "d:\erp_system\android-app"
try {
    $output = & ".\gradlew.bat" :app:assembleDebug 2>&1
    $output | Out-File "d:\erp_system\build_output.txt" -Encoding utf8
} catch {
    $_.Exception.Message | Out-File "d:\erp_system\build_error.txt" -Encoding utf8
}
