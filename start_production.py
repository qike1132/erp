"""
生产环境启动脚本（Windows）
使用Waitress生产服务器
"""
import os
import sys

# 设置UTF-8编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 使用新架构
os.environ['USE_NEW_ARCH'] = 'true'

from waitress import serve
from app import app

print("=" * 60)
print("生产环境启动 - Waitress服务器")
print("=" * 60)
print(f"数据库: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
print(f"密钥状态: {'已设置' if app.secret_key else '未设置'}")
print("=" * 60)
print("访问地址:")
print("  本地: http://127.0.0.1:5003")
print("  局域网: http://192.168.0.95:5003")
print("=" * 60)
print("配置信息:")
print("  线程数: 8")
print("  端口: 5003")
print("  模式: 生产环境")
print("=" * 60)
print("按 Ctrl+C 停止服务")
print("=" * 60)

# 启动Waitress服务器
serve(
    app,
    host='0.0.0.0',
    port=5003,
    threads=8,  # 8个工作线程（性能提升）
    channel_timeout=30,  # 请求超时30秒
    expose_tracebacks=False  # 不暴露错误详情（安全）
)
