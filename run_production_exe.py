"""
ERP系统生产环境启动脚本（用于打包为EXE）
使用 Waitress 作为生产级 WSGI 服务器
"""
import os
import sys
from pathlib import Path

# 获取可执行文件所在目录（支持打包后运行）
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

# 添加项目路径到 sys.path
sys.path.insert(0, str(BASE_DIR))

# 设置环境变量
os.environ['FLASK_ENV'] = 'production'
os.environ['PYTHONOPTIMIZE'] = '1'

print("=" * 60)
print("ERP 系统 - 生产环境启动")
print("=" * 60)

try:
    from app import create_app
    
    # 创建应用
    app = create_app('default')
    
    # 生产环境配置
    app.config['DEBUG'] = False
    app.config['TESTING'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = False
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600  # 1小时缓存
    
    print(f"[OK] Flask 应用初始化完成")
    print(f"[INFO] 工作目录: {BASE_DIR}")
    print(f"[INFO] 数据库: {app.config.get('SQLALCHEMY_DATABASE_URI', '未配置')}")
    print(f"[INFO] 密钥状态: {'已设置' if app.secret_key else '未设置'}")
    
    # 导入 Waitress
    try:
        from waitress import serve
        print("[OK] Waitress WSGI 服务器已加载")
    except ImportError:
        print("[ERROR] Waitress 未安装，请运行: pip install waitress")
        input("按回车键退出...")
        sys.exit(1)
    
    print("=" * 60)
    print("服务器即将启动")
    print("访问地址: http://127.0.0.1:5003")
    print("访问地址: http://0.0.0.0:5003")
    print("按 Ctrl+C 停止服务器")
    print("=" * 60)
    
    # 启动 Waitress 服务器
    serve(
        app,
        host='0.0.0.0',
        port=5003,
        threads=8,
        connection_limit=100,
        channel_timeout=120,
        send_bytes=1024 * 1024,  # 1MB
        ident='ERP-System',
        url_prefix='',
        backlog=128,
        recv_bytes=8192,
        inbuf_overflow=524288,  # 512KB
        outbuf_overflow=1048576  # 1MB
    )
    
except KeyboardInterrupt:
    print("\n[INFO] 服务器已停止")
except Exception as e:
    print(f"\n[ERROR] 启动失败: {str(e)}")
    import traceback
    traceback.print_exc()
    input("\n按回车键退出...")
    sys.exit(1)
