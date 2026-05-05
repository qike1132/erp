# ERP Nginx 配置部署脚本
param(
    [string]$ServerIP = "192.168.0.95",
    [string]$SshUser = "administrator",
    [string]$NginxConf = "d:\erp_system\config\nginx.conf"
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "ERP Nginx 配置部署脚本" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 检查配置文件存在
if (-not (Test-Path $NginxConf)) {
    Write-Error "配置文件不存在: $NginxConf"
    exit 1
}

# 显示配置中的关键设置
Write-Host "`n[1/4] 检查配置文件..." -ForegroundColor Yellow
$bodySizeLine = Select-String -Path $NginxConf -Pattern "client_max_body_size"
if ($bodySizeLine) {
    Write-Host "✅ 找到上传限制配置: $($bodySizeLine.Line.Trim())" -ForegroundColor Green
} else {
    Write-Warning "⚠️ 未找到 client_max_body_size 配置"
}

# 生成 SCP/SSH 命令
$remotePath = "/etc/nginx/nginx.conf"
$backupPath = "/etc/nginx/nginx.conf.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "`n[2/4] 部署命令（在 PowerShell 中执行）：" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray

Write-Host "# 方式 A：使用 scp 上传配置文件" -ForegroundColor Cyan
Write-Host "scp '$NginxConf' ${SshUser}@${ServerIP}:/tmp/nginx.conf.new" -ForegroundColor White

Write-Host "`n# 方式 B：SSH 到服务器执行部署" -ForegroundColor Cyan
$commands = @"
# 备份原配置
sudo cp $remotePath $backupPath

# 移动新配置
sudo mv /tmp/nginx.conf.new $remotePath

# 测试配置语法
echo "=== 测试 Nginx 配置 ==="
sudo nginx -t

# 如果测试通过，重载 Nginx
if [ `$? -eq 0 ]; then
    echo "=== 重载 Nginx ==="
    sudo systemctl reload nginx
    echo "✅ Nginx 重载成功"
else
    echo "❌ 配置测试失败，恢复原配置"
    sudo cp $backupPath $remotePath
fi

# 验证配置生效
echo "=== 验证配置 ==="
sudo nginx -T 2>/dev/null | grep client_max_body_size | head -1
"@
Write-Host $commands -ForegroundColor White

Write-Host "----------------------------------------" -ForegroundColor Gray

# 一键部署选项
Write-Host "`n[3/4] 一键部署命令（合并执行）：" -ForegroundColor Yellow
$oneLine = "scp '$NginxConf' ${SshUser}@${ServerIP}:/tmp/nginx.conf.new && ssh ${SshUser}@${ServerIP} 'sudo cp $remotePath $backupPath && sudo mv /tmp/nginx.conf.new $remotePath && sudo nginx -t && sudo systemctl reload nginx'"
Write-Host $oneLine -ForegroundColor Green

Write-Host "`n[5/5] 本地测试（Windows 环境）：" -ForegroundColor Yellow
Write-Host "nginx -t -c $NginxConf" -ForegroundColor White

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "部署完成！" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
