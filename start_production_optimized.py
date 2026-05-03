"""
ERP系统生产环境启动脚本 (FastAPI + Vue/Vite)

快捷方式，等价于: python start.py --prod

生产模式特点：
  - FastAPI 无 --reload（稳定运行）
  - Vue/Vite 已构建（dist 目录）

用法:
    # 启动完整系统
    python start_production_optimized.py

    # 仅启动后端
    python start_production_optimized.py --backend-only

    # 仅启动前端
    python start_production_optimized.py --frontend-only

    # 指定端口
    python start_production_optimized.py --api-port 5002 --web-port 3000
"""
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    os.environ.setdefault('FASTAPI_DEBUG', 'false')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from start import main
    # 将 --prod 插入到 sys.argv 中（如果还没有的话）
    if '--prod' not in sys.argv:
        sys.argv.insert(1, '--prod')
    main()
