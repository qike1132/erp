$env:JAVA_HOME = "D:\JDK\jdk-17.0.13+11"
Set-Location "d:\erp_system\android-app"
$output = & ".\gradlew.bat" clean :app:assembleDebug 2>&1
$output | Out-File "d:\erp_system\build_result.txt" -Encoding utf8
