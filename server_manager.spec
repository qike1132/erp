# -*- mode: python ; coding: utf-8 -*-
"""ERP 服务器管理器 v5.33 PyInstaller 打包配置。

用法: pyinstaller server_manager.spec
产出: dist/ERP服务器管理器_v5.33.exe

说明:
  - spec 中 __file__ 不可用，项目根经 SPECPATH 解析；
  - uac_admin=True: nssm/sc 服务控制需提权，默认 asInvoker 会被静默拒绝（拒绝访问）；
  - pystray/PIL 为可选依赖: 未安装时 collect_all 降级为空，管理器自动回落普通窗口模式。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).absolute()

# 可选依赖 pystray 全量收集（hiddenimports 对其不够）；缺失时静默降级
try:
    pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
except Exception:
    pystray_datas, pystray_binaries, pystray_hiddenimports = [], [], []

datas = list(pystray_datas)
binaries = list(pystray_binaries)

hiddenimports = [
    'tkinter',
    'tkinter.scrolledtext',
    'tkinter.font',
    'pystray',
    'pystray._win32',   # Windows 平台托盘后端
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageTk',
    'psutil',           # 可选: 缺失时管理器按降级路径运行
] + list(pystray_hiddenimports)

# 排除管理器 EXE 运行期并不需要的重依赖，压缩体积
excludes = [
    'matplotlib', 'scipy', 'numpy', 'pandas', 'IPython', 'jupyter',
    'pytest', 'unittest', 'sqlalchemy', 'django', 'fastapi', 'uvicorn',
    'celery', 'redis', 'openpyxl', 'rapidfuzz', 'arrow',
]

a = Analysis(
    ['server_manager.py'],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ERP服务器管理器_v5.33',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # GUI 应用不显示控制台
    disable_windowed_traceback=False,
    uac_admin=True,       # 请求管理员权限：nssm/sc 服务控制需提权
    manifest_filename=None,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
