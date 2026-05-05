Set-Location d:\erp_system\android-app
$env:JAVA_HOME = "D:\JDK\jdk-17.0.13+11"
$output = & ".\gradlew.bat" :app:assembleDebug 2>&1
$output | Out-File "d:\erp_system\build_output2.txt" -Encoding utf8
