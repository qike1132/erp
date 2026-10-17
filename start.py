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
        help="生产模式：由 prod_runner 监督器统一拉起多 worker Uvicorn / ARQ / 前端"
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
    parser.add_argument(
        "--workers", type=int, default=0,
        help="生产模式 worker 数（默认取 UVICORN_WORKERS 或 min(4, CPU)）"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="生产模式环境自检（不拉起进程）"
    )
    return parser.parse_args()


def start_backend(args: argparse.Namespace):
    """启动 FastAPI 后端"""
    os.environ.setdefault("FASTAPI_DEBUG", "true" if args.dev else "false")
    os.environ.setdefault("APP_ENV", "development" if args.dev else "production")

    sys.path.insert(0, str(PROJECT_ROOT))

    import uvicorn

    # 默认仅回环（本机 nginx 反代）；确需局域网直连时显式设 API_HOST=0.0.0.0
    host = os.getenv("API_HOST", "127.0.0.1")
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


def start_production(args: argparse.Namespace):
    """生产模式：由 prod_runner 监督器统一拉起多 worker Uvicorn / ARQ / 前端。

    prod_runner 支持 --check 环境自检；worker 数通过 UVICORN_WORKERS 透传给子进程
    （database.py 会按该值分摊数据库连接池）。
    """
    os.environ.setdefault("FASTAPI_DEBUG", "false")
    os.environ.setdefault("APP_ENV", "production")
    if args.workers > 0:
        os.environ["UVICORN_WORKERS"] = str(args.workers)

    sys.path.insert(0, str(PROJECT_ROOT))

    # 2026-10-17 审计 AUD-28：生产启动前过 git 分支闸门（非 main 拒绝）
    from server_manager.git_guard import check_production_branch

    ok, guard_msg = check_production_branch(PROJECT_ROOT)
    if not ok:
        print(f'[ERROR] {guard_msg}')
        raise SystemExit(1)
    if guard_msg.startswith('警告') or '覆盖' in guard_msg:
        print(f'[WARN] {guard_msg}')

    from fastapi_app.core import prod_runner

    runner_args = ["--check"] if args.check else []
    raise SystemExit(prod_runner.main(runner_args))


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
    elif args.prod:
        start_production(args)
    else:
        # 完整启动：后端为主，提示前端路径
        print("[ERP] 前端开发服务器请手动启动:")
        print(f"      cd {FRONTEND_DIR}")
        print("      npm run dev")
        print()
        start_backend(args)


if __name__ == "__main__":
    main()
