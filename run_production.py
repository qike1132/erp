"""
ERP系统生产启动脚本
使用 waitress 作为 WSGI 服务器
"""
import os

print("=" * 50)
print("ERP系统启动中... (生产模式)")
print("=" * 50)

from app import app, db

if __name__ == '__main__':
    print(f"数据库: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    print(f"密钥状态: {'已设置' if app.secret_key else '未设置'}")
    print("=" * 50)
    print("访问地址: http://127.0.0.1:5003")
    print("访问地址: http://192.168.0.95:5003")
    print("=" * 50)

    from waitress import serve
    serve(app, host='0.0.0.0', port=5003, threads=4)
