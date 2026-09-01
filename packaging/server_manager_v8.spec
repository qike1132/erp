# -*- mode: python ; coding: utf-8 -*-
"""
ERP 服务器管理器 v8 GUI 打包配置（PyInstaller）

特性：
    - EXE 名称：server_manager_v8.exe（与 v6 ERP_System.exe 不同名，可并存）
    - 排除后端重依赖（fastapi/uvicorn/celery/pandas/numpy/alembic/redis-py/jose...）
      → 体积从 v6 的 200+MB 缩至 ~40-60MB
    - 包含前端 web/* 静态资源（HTML/CSS/JS）
    - hiddenimports：pywebview + server_manager_v8 子包 + psutil

使用：pyinstaller packaging/server_manager_v8.spec
"""
import os
from pathlib import Path

# 仓库根（用 PyInstaller 保证注入的 SPECPATH，兼容 `pyinstaller` 与 `python -m PyInstaller`）
# SPECPATH = <repo>/packaging，其上级目录即仓库根
ROOT = Path(SPECPATH).resolve().parent
SRV = ROOT / 'server_manager_v8'

# 资源：前端 web 目录（HTML/CSS/JS）
datas = [
    (str(SRV / 'presentation' / 'web'), str(Path('server_manager_v8') / 'presentation' / 'web')),
]

# 隐藏导入（v8 实际使用）
hiddenimports = [
    # 第三方
    'webview',
    'pythonnet',
    'clr_loader',
    # psutil 可选（缺失时 metrics 降级）
    'psutil',
    # 本包所有子包与模块（PyInstaller 自动分析有时漏）
    'server_manager_v8',
    'server_manager_v8.container',
    'server_manager_v8.domain',
    'server_manager_v8.domain.config_schema',
    'server_manager_v8.application',
    'server_manager_v8.application.auth',
    'server_manager_v8.application.usecases',
    'server_manager_v8.adapters',
    'server_manager_v8.adapters.process_win',
    'server_manager_v8.adapters.service_nssm',
    'server_manager_v8.adapters.health_http',
    'server_manager_v8.adapters.storage_json',
    'server_manager_v8.adapters.audit_jsonl',
    'server_manager_v8.adapters.metrics_psutil',
    'server_manager_v8.adapters.notify_win',
    'server_manager_v8.adapters._proc',
    'server_manager_v8.presentation',
    'server_manager_v8.presentation.bridge',
    'server_manager_v8.presentation.serializers',
    'server_manager_v8.presentation.webview_host',
    'server_manager_v8.gui_launcher',
    'server_manager_v8._guard',
]

# 完全排除后端（v8 通过 HTTP 调外部后端，不打包）
excludes = [
    # 桌面框架：v8 用 pywebview，v6 的 tkinter 不需要
    'tkinter',
    'unittest', 'pytest', 'IPython', 'jupyter', 'matplotlib', 'scipy',
    # 后端栈
    'fastapi', 'starlette', 'uvicorn', 'uvicorn.logging', 'uvicorn.loops',
    'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'starlette_csrf', 'starlette', 'slowapi', 'pydantic', 'pydantic_settings',
    'sqlalchemy', 'sqlalchemy.dialects', 'sqlalchemy.dialects.postgresql',
    'sqlalchemy.ext', 'sqlalchemy.ext.asyncio', 'alembic',
    'psycopg2', 'asyncpg', 'psycopg2_binary',
    'celery', 'celery.app', 'kombu', 'billiard', 'amqp', 'pyamqp', 'kombu.transport',
    'pandas', 'numpy', 'openpyxl', 'xlsxwriter', 'xlrd', 'xlwt',
    'cryptography', 'bcrypt', 'jwt', 'dotenv', 'python_dotenv',
    'jinja2', 'jose', 'orjson', 'arrow', 'dateutil', 'charset_normalizer',
    'pypinyin', 'rapidfuzz', 'bleach', 'httpx', 'rapidocr', 'rapidocr_pdf',
    'redis', 'fakeredis',
    # 已移除的 Flask 栈
    'flask', 'flask_sqlalchemy', 'flask_wtf', 'flask_limiter', 'flask_migrate',
    'flasgger', 'waitress', 'gunicorn', 'fuzzywuzzy',
    # 本项目后端（不让 GUI 包进去）
    'fastapi_app',
    'http.server',
    'xmlrpc', 'xmlrpc.client', 'xmlrpc.server',
    'pydoc',
]

block_cipher = None

a = Analysis(
    [str(SRV / 'gui_launcher.py')],
    pathex=[str(ROOT)],
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
    name='server_manager_v8',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 程序不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可后续添加 .ico
)
