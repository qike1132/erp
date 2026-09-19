# -*- mode: python ; coding: utf-8 -*-
"""
⚠️ 已废弃（2026-09-17 标注）：本 spec 指向的历史 EXE 打包链路（run.py 入口）
已不再是生产部署方式——生产由 NSSM 托管 `python -m fastapi_app.core.prod_runner`。
datas/hiddenimports 引用已过期，请勿再用于构建；保留仅供历史参考。
GUI 打包请用 server_manager.spec（v5.40）。

ERP 系统 PyInstaller 打包配置文件（FastAPI 版）
使用方法: pyinstaller erp_system.spec
"""

import os
from pathlib import Path

# 获取项目根目录
project_root = Path(__file__).parent.absolute()

# 收集数据文件
datas = [
    # 模板文件
    (str(project_root / 'templates'), 'templates'),
    # 静态文件
    (str(project_root / 'static'), 'static'),
    # 日志配置
    (str(project_root / 'fastapi_app' / 'log_config.json'), 'fastapi_app'),
]

# 如果有 .env 文件，也包含进去
if (project_root / '.env').exists():
    datas.append((str(project_root / '.env'), '.'))

# 收集隐藏导入（FastAPI 栈）
hiddenimports = [
    # FastAPI 核心
    'fastapi',
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'starlette',
    'starlette.responses',
    'starlette.routing',
    'starlette.middleware',
    'starlette_csrf',

    # 数据库
    'psycopg2',
    'asyncpg',
    'cryptography',
    'sqlalchemy',
    'sqlalchemy.dialects.postgresql',
    'sqlalchemy.ext.asyncio',
    'alembic',

    # 数据验证
    'pydantic',
    'pydantic_settings',

    # 安全
    'jwt',
    'bcrypt',

    # 序列化
    'orjson',

    # 限流
    'slowapi',

    # 模板
    'jinja2',

    # Excel 处理
    'pandas',
    'openpyxl',
    'xlsxwriter',

    # 异步任务
    'celery',
    'celery.app',

    # 其他依赖
    'dotenv',
    'redis',
    'arrow',
    'dateutil',
    'charset_normalizer',
    'pypinyin',
    'rapidfuzz',
    'bleach',
    'httpx',

    # OCR
    'rapidocr',
    'rapidocr_pdf',

    # FastAPI 应用模块
    'fastapi_app',
    'fastapi_app.main',
    'fastapi_app.core',
    'fastapi_app.core.config',
    'fastapi_app.core.database',
    'fastapi_app.core.deps',
    'fastapi_app.core.security',
    'fastapi_app.core.templates',
    'fastapi_app.core.nav_context',
    'fastapi_app.core.celery_app',
    'fastapi_app.shared_models',
    'fastapi_app.api',
    'fastapi_app.api.v1',
    'fastapi_app.api.v1.router',
]

# 排除不必要的模块
excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'IPython',
    'jupyter',
    'pytest',
    'unittest',
    'http.server',
    # 已移除的 Flask 栈
    'flask',
    'flask_sqlalchemy',
    'flask_wtf',
    'flask_limiter',
    'flask_migrate',
    'flasgger',
    'waitress',
    'gunicorn',
    'fuzzywuzzy',
    'jose',
]

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ERP_System',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加 .ico 文件路径
)
