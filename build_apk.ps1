$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
Set-Location "D:\erp_system\android-app"
& .\gradlew.bat assembleDebug 2>&1 | Out-File -FilePath "D:\erp_system\build_output.txt" -Encoding utf8
