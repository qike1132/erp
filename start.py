"""
ERP 系统统一启动脚本 (FastAPI)

用法:
    python start.py --dev              # 开发模式（FastAPI reload + 提示启动 Vue dev server）
    python start.py --prod             # 生产模式（FastAPI + 静态文件）
    python start.py --backend-only     # 仅启动后端
    python start.py --frontend-only    # 仅启动前端（需要先 npm install && npm run dev）
    python start.py --api-port 5002 --web-port 3000

说明:
    本模块替代旧的 run.py / start_production_optimized.py，
    提供统一的命令行入口，消除 Flask 遗留代码。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend-vite"


def parse_args():
    parser = argparse.ArgumentParser(description="ERP 系统启动脚本")
    parser.add_argument(
        "--dev", action="store_true",
        help="开发模式：FastAPI 开启 reload，Vue 开启 HMR"
    )
    parser.add_argument(
        "--prod", action="store_true",
        help="生产模式：FastAPI 无 reload"
    )
    parser.add_argument(
        "--backend-only", action="store_true",
        help="仅启动后端 API 服务"
    )
    parser.add_argument(
        "--frontend-only", action="store_true",
        help="仅启动前端开发服务器"
    )
    parser.add_argument("--api-port", type=int, default=5002, help="API 服务端口（默认 5002）")
    parser.add_argument("--web-port", type=int, default=3000, help="前端开发端口（默认 3000）")
    return parser.parse_args()


def start_backend(args: argparse.Namespace):
    """启动 FastAPI 后端"""
    os.environ.setdefault("FASTAPI_DEBUG", "true" if args.dev else "false")
    os.environ.setdefault("APP_ENV", "development" if args.dev else "production")

    sys.path.insert(0, str(PROJECT_ROOT))

    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    reload_flag = args.dev

    print(f"[ERP] FastAPI 启动: http://{host}:{args.api_port}")
    print(f"[ERP] API 文档: http://{host}:{args.api_port}/api/docs")
    print(f"[ERP] 模式: {'开发 (reload)' if reload_flag else '生产'}")

    uvicorn.run(
        "fastapi_app.main:app",
        host=host,
        port=args.api_port,
        reload=reload_flag,
        log_level="info" if not reload_flag else "debug",
    )


def start_frontend(args: argparse.Namespace):
    """启动 Vue 前端开发服务器"""
    if not FRONTEND_DIR.is_dir():
        print(f"[ERP] 错误：前端目录不存在 {FRONTEND_DIR}")
        sys.exit(1)

    print(f"[ERP] Vue 开发服务器启动: http://localhost:{args.web_port}")

    subprocess.run(
        ["npm", "run", "dev", "--", "--port", str(args.web_port)],
        cwd=str(FRONTEND_DIR),
        check=False,
    )


def main():
    args = parse_args()

    # 默认行为：如果没有明确参数且未指定 --prod，按开发模式启动
    if not any([args.backend_only, args.frontend_only, args.prod]):
        args.dev = True

    if args.frontend_only:
        start_frontend(args)
    elif args.backend_only:
        start_backend(args)
    else:
        # 完整启动：后端为主，提示前端路径
        print(f"[ERP] 前端开发服务器请手动启动:")
        print(f"      cd {FRONTEND_DIR}")
        print(f"      npm run dev")
        print()
        start_backend(args)


if __name__ == "__main__":
    main()
