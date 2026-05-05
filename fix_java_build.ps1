$java_home = "C:\Users\Administrator\AppData\Local\Android\Sdk\jbr"
# Set machine-level environment variable
[System.Environment]::SetEnvironmentVariable("JAVA_HOME", $java_home, "Machine")
Write-Host "JAVA_HOME set to: $java_home"

# Verify
$verify = [System.Environment]::GetEnvironmentVariable("JAVA_HOME", "Machine")
Write-Host "Verified JAVA_HOME: $verify"

# Now run gradle
Set-Location "D:\erp_system\android-app"
$env:JAVA_HOME = $java_home
$env:PATH = "$java_home\bin;$env:PATH"

Write-Host "Stopping gradle daemon..."
& .\gradlew.bat --stop 2>&1 | Out-Null

Write-Host "Building APK..."
$output = & .\gradlew.bat clean assembleDebug --stacktrace 2>&1
$exitCode = $LASTEXITCODE

Write-Host "Build finished with exit code: $exitCode"
Write-Host "Output lines: $($output.Count)"

# Save to file
$output | Out-File -FilePath "D:\erp_system\build_output.txt" -Encoding utf8

# Check APK
$apkPath = "D:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
if (Test-Path $apkPath) {
    $size = (Get-Item $apkPath).Length / 1MB
    Write-Host "APK created: $apkPath ($size MB)"
} else {
    Write-Host "APK NOT FOUND"
}
