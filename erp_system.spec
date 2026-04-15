# -*- mode: python ; coding: utf-8 -*-
"""
ERP 系统 PyInstaller 打包配置文件
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
    # 配置文件（如果有）
]

# 如果有 .env 文件，也包含进去
if (project_root / '.env').exists():
    datas.append((str(project_root / '.env'), '.'))

# 收集隐藏导入
hiddenimports = [
    # Flask 相关
    'flask',
    'flask_sqlalchemy',
    'flask_wtf',
    'flask_limiter',
    'flask_migrate',
    'flasgger',
    
    # 数据库
    'pymysql',
    'cryptography',
    
    # Excel 处理
    'pandas',
    'openpyxl',
    'xlsxwriter',
    'xlrd',
    
    # WSGI 服务器
    'waitress',
    
    # 其他依赖
    'dotenv',
    'redis',
    'arrow',
    'dateutil',
    'chardet',
    'pypinyin',
    'fuzzywuzzy',
    'rapidfuzz',
    'bleach',
    
    # 应用模块
    'app',
    'app.models',
    'app.routes',
    'app.utils',
    
    # SQLAlchemy 驱动
    'sqlalchemy.dialects.mysql',
    'sqlalchemy.dialects.sqlite',
]

# 排除不必要的模块
excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'numpy',
    'IPython',
    'jupyter',
    'pytest',
    'unittest',
    'email',
    'http.server',
]

block_cipher = None

a = Analysis(
    ['run_production_exe.py'],
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
