# -*- mode: python ; coding: utf-8 -*-
"""
ERP 服务器管理器 PyInstaller 打包配置文件
使用方法: pyinstaller server_manager.spec
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# 获取项目根目录（spec 文件中 __file__ 不可用，使用 SPECPATH）
project_root = Path(SPECPATH).absolute()

# 强制收集 pystray 及其子模块（hiddenimports 对 pystray 不够）
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')

# 收集数据文件 — 管理器 EXE 仅需运行时资源，不含 ERP 应用代码
datas = pystray_datas

# 如果有 .env 文件，也包含进去
# if (project_root / '.env').exists():
#     datas.append((str(project_root / '.env'), '.'))

# 收集隐藏导入 — 仅包含管理器实际运行所需的模块
hiddenimports = [
    # GUI
    'tkinter',

    # 系统托盘
    'pystray',
    'pystray._win32',     # Windows 平台托盘后端
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageTk',        # 窗口图标
] + pystray_hiddenimports

# 排除不必要的模块
excludes = [
    'matplotlib',
    'scipy',
    'numpy',
    'IPython',
    'jupyter',
    'pytest',
    'unittest',
    'pandas',
    'sqlalchemy',
    'django',
    'fastapi',
    'uvicorn',
    'celery',
    'redis',
    'openpyxl',
    'rapidfuzz',
    'arrow',
]

block_cipher = None

a = Analysis(
    ['server_manager.py'],
    pathex=[str(project_root)],
    binaries=pystray_binaries,
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
    name='ERP服务器管理器_v4.1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 应用不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加 .ico 文件路径
)
