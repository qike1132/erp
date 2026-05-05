#!/usr/bin/env python3
"""上传 Nginx 配置到服务器（使用 Paramiko）"""
import os
import sys
from pathlib import Path

# 配置
HOST = "192.168.0.95"
USER = "administrator"
LOCAL_CONFIG = Path("d:/erp_system/config/nginx.conf")
REMOTE_TEMP = "/tmp/nginx.conf.new"
REMOTE_PATH = "/etc/nginx/nginx.conf"

def upload_with_paramiko():
    try:
        import paramiko
    except ImportError:
        print("Installing paramiko...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        import paramiko

    # 读取配置（使用 UTF-8 编码）
    config_content = LOCAL_CONFIG.read_text(encoding='utf-8', errors='ignore')
    
    # 连接服务器
    print(f"Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    # 尝试连接（可能需要密码或密钥）
    try:
        ssh.connect(HOST, username=USER, timeout=30)
    except paramiko.AuthenticationException:
        password = input(f"Enter password for {USER}@{HOST}: ")
        ssh.connect(HOST, username=USER, password=password, timeout=30)
    
    # 上传文件
    print(f"Uploading {LOCAL_CONFIG} to {REMOTE_TEMP}...")
    sftp = ssh.open_sftp()
    sftp.put(str(LOCAL_CONFIG), REMOTE_TEMP)
    sftp.close()
    
    # 执行部署命令
    commands = f"""
sudo cp {REMOTE_PATH} {REMOTE_PATH}.backup.$(date +%Y%m%d_%H%M%S) && 
sudo mv {REMOTE_TEMP} {REMOTE_PATH} && 
sudo nginx -t && 
sudo systemctl reload nginx && 
echo '=== 验证配置 ===' && 
sudo nginx -T 2>/dev/null | grep client_max_body_size | head -1
"""
    print("Executing remote commands...")
    stdin, stdout, stderr = ssh.exec_command(commands)
    
    output = stdout.read().decode()
    error = stderr.read().decode()
    
    print("\n--- OUTPUT ---")
    print(output)
    if error:
        print("--- ERROR ---")
        print(error)
    
    ssh.close()
    print("\n✅ Done!")

if __name__ == "__main__":
    if not LOCAL_CONFIG.exists():
        print(f"❌ Config not found: {LOCAL_CONFIG}")
        sys.exit(1)
    
    # 显示配置
    print("=== Current client_max_body_size ===")
    for line in LOCAL_CONFIG.read_text(encoding='utf-8', errors='ignore').splitlines():
        if "client_max_body_size" in line:
            print(line.strip())
    
    upload_with_paramiko()
