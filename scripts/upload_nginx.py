#!/usr/bin/env python3
"""上传 Nginx 配置到服务器（使用 Paramiko）"""
import sys
from pathlib import Path

# 配置
HOST = "192.168.0.95"
USER = "administrator"
LOCAL_CONFIG = Path("d:/erp_system/config/nginx.conf")
REMOTE_TEMP = "/tmp/nginx.conf.new"  # noqa: S108 远程服务器临时路径
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
    LOCAL_CONFIG.read_text(encoding='utf-8', errors='ignore')

    # 连接服务器
    print(f"Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 内网可信主机

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
    _stdin, stdout, stderr = ssh.exec_command(commands)

    output = stdout.read().decode()
    error = stderr.read().decode()

    print("\n--- OUTPUT ---")
    print(output)
    if error:
        print("--- ERROR ---")
        print(error)

    ssh.close()
    print("\n✅ Done!")

def deprecated_guard_engaged(argv: list[str]) -> bool:
    """L-3（2026-10-25 上线前审计）弃用守卫：未显式 ``--accept-deprecated`` 时返回 True。

    本脚本面向**远端 Linux** nginx（systemctl/nginx -t），上传的是本仓死配置
    config/nginx.conf（其 root /app 在 Windows 永不生效）；本机生产生效配置是
    config/nginx-windows.conf（erp-web 服务直读，无需上传）。历史遗留工具，
    勿在当前拓扑误用——确需远端部署时显式传 --accept-deprecated。
    """
    if "--accept-deprecated" not in argv:
        print("Deprecated: remote-Linux nginx uploader for the dead config/nginx.conf.")
        print("Live config on this host = config/nginx-windows.conf (erp-web).")
        print("Pass --accept-deprecated to override.")
        return True
    return False


if __name__ == "__main__":
    if deprecated_guard_engaged(sys.argv[1:]):
        sys.exit(1)

    if not LOCAL_CONFIG.exists():
        print(f"❌ Config not found: {LOCAL_CONFIG}")
        sys.exit(1)

    # 显示配置
    print("=== Current client_max_body_size ===")
    for line in LOCAL_CONFIG.read_text(encoding='utf-8', errors='ignore').splitlines():
        if "client_max_body_size" in line:
            print(line.strip())

    upload_with_paramiko()
