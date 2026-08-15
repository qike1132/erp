"""
ERP系统生产环境启动脚本 (FastAPI) — 兼容快捷方式

快捷方式，等价于: python start.py --prod

生产模式特点：
  - FastAPI 无 --reload（稳定运行）
  - Vue/Vite 已构建（dist 目录）

用法:
    python start_production_optimized.py                  # 生产模式启动
    python start_production_optimized.py --backend-only   # 仅后端
    python start.py --help                                # 查看所有选项

注意：此文件为历史兼容快捷方式，请直接使用 python start.py --prod
"""
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    os.environ.setdefault('FASTAPI_DEBUG', 'false')
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    # 清理并重建参数：替换为 --prod，保留额外参数
    extra_args = [a for a in sys.argv[1:] if a not in ('--prod',)]
    sys.argv = [sys.argv[0], '--prod'] + extra_args

    from start import main
    main()
