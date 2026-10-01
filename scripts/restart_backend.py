import os
import socket
import subprocess
import sys
import time

# 注意：此脚本为快速重启工具，生产建议改用 server_manager「生产托管」注册的
# erp-prod / erp-arq Windows 服务（开机自启 + 崩溃自愈）。

def kill_port_process(port):
    """找到占用指定端口的进程并杀掉"""
    try:
        # 使用 netstat 和 taskkill
        netstat_cmd = ['netstat', '-ano']
        result = subprocess.run(netstat_cmd, capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                print(f"发现进程占用端口 {port}, PID: {pid}")
                subprocess.run(['taskkill', '/F', '/T', '/PID', pid], check=True)  # /T: 连同子进程树（worker/supervisor），避免残留进程继续占用端口
                print(f"已终止 PID {pid}")
                time.sleep(2)
                return True
    except Exception as e:
        print(f"终止进程时出错: {e}")
    return False

def is_port_free(port):
    """检查端口是否空闲"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result != 0
    except Exception:
        return True

if __name__ == "__main__":
    PORT = 5002
    print(f"=== 正在重启后端服务 (端口 {PORT}) ===\n")

    # 1. 杀掉旧进程
    print("步骤 1: 尝试终止占用端口的进程...")
    kill_port_process(PORT)

    # 2. 等待端口释放
    print("\n步骤 2: 等待端口释放...")
    for i in range(5):
        if is_port_free(PORT):
            print(f"端口 {PORT} 现在空闲了！")
            break
        print(f"等待端口释放... ({i+1}/5)")
        time.sleep(1)

    # 3. 启动新后端（多 worker 生产配置）
    print("\n步骤 3: 启动后端服务...")
    try:
        # 使用 uvicorn 多 worker 直接启动
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        workers = os.getenv("UVICORN_WORKERS", "4")
        print(f"执行: python -m uvicorn fastapi_app.main:app --workers {workers}")
        subprocess.run([
            sys.executable, "-m", "uvicorn", "fastapi_app.main:app",
            # P0-6(c)：仅绑回环，与 prod_runner.py 的生产拓扑一致
            # （同机 nginx 反代，绑 0.0.0.0 会被局域网绕过网关直连）。
            "--host", "127.0.0.1", "--port", str(PORT),
            "--workers", workers, "--http", "httptools",
            "--no-access-log", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1",
        ])
    except KeyboardInterrupt:
        print("\n\n后端已停止。")
