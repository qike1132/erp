"""
启动服务器脚本
用于捕获并显示详细的错误信息
"""
from app import app

if __name__ == '__main__':
    try:
        print("正在启动服务器...")
        app.run(debug=True, host='0.0.0.0', port=5003)
    except Exception as e:
        print(f"启动错误: {e}")
        import traceback
        traceback.print_exc()
