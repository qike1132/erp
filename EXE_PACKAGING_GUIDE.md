# ERP 系统打包为 EXE 可执行文件指南

## 概述

本指南说明如何将 ERP 系统 Python 应用打包为独立的 Windows `.exe` 可执行文件，使其无需安装 Python 环境即可运行。

---

## 目录

1. [打包前准备](#打包前准备)
2. [快速打包](#快速打包)
3. [手动打包步骤](#手动打包步骤)
4. [常见问题及解决方案](#常见问题及解决方案)
5. [部署到目标机器](#部署到目标机器)
6. [高级配置](#高级配置)

---

## 打包前准备

### 1. 环境要求

- **操作系统**: Windows 10/11 (64位)
- **Python**: 3.8 或更高版本
- **虚拟环境** (推荐): 使用虚拟环境打包可减少文件大小

### 2. 安装依赖

确保所有项目依赖已安装：

```bash
# 激活虚拟环境（如果有）
.\venv\Scripts\activate

# 安装项目依赖
pip install -r requirements.txt

# 安装 PyInstaller
pip install pyinstaller
```

### 3. 检查项目结构

确保以下文件存在：
- `run_production_exe.py` - 生产环境启动脚本
- `erp_system.spec` - PyInstaller 配置文件
- `build_exe.bat` - 自动化打包脚本

---

## 快速打包

### 方法一：使用自动化脚本（推荐）

双击运行 `build_exe.bat`，脚本会自动完成以下步骤：

1. 检查 Python 环境
2. 安装 PyInstaller（如未安装）
3. 清理旧的打包文件
4. 执行打包
5. 测试运行（可选）

### 方法二：使用命令行

在项目根目录打开命令行，执行：

```bash
# 激活虚拟环境
.\venv\Scripts\activate

# 清理旧文件
rmdir /s /q build dist

# 执行打包
pyinstaller --clean erp_system.spec
```

打包完成后，可执行文件位于 `dist\ERP_System.exe`

---

## 手动打包步骤

### 步骤 1: 测试生产环境脚本

在打包前，先测试生产环境脚本是否正常运行：

```bash
python run_production_exe.py
```

访问 http://127.0.0.1:5003 验证功能正常。

### 步骤 2: 创建或修改 .spec 文件

`erp_system.spec` 文件已预置，关键配置说明：

```python
# 入口文件
['run_production_exe.py']

# 数据文件（模板、静态文件等）
datas = [
    ('templates', 'templates'),
    ('static', 'static'),
]

# 隐藏导入（PyInstaller 无法自动检测的模块）
hiddenimports = [
    'flask',
    'flask_sqlalchemy',
    'waitress',
    # ... 更多模块
]

# 排除不必要的模块（减小体积）
excludes = [
    'tkinter',
    'matplotlib',
    # ... 更多模块
]
```

### 步骤 3: 执行打包

```bash
pyinstaller --clean erp_system.spec
```

参数说明：
- `--clean`: 清理临时文件
- `--onefile` (可选): 打包为单个文件（不推荐，启动慢）
- `--windowed` (可选): 无控制台窗口（不推荐，看不到日志）

### 步骤 4: 测试可执行文件

```bash
cd dist
ERP_System.exe
```

验证：
1. 服务器正常启动
2. 可以访问 Web 界面
3. 数据库连接正常
4. 所有功能正常

---

## 常见问题及解决方案

### 问题 1: ModuleNotFoundError

**错误信息**: `ModuleNotFoundError: No module named 'xxx'`

**原因**: PyInstaller 未检测到某些依赖

**解决方案**: 在 `erp_system.spec` 的 `hiddenimports` 中添加缺失的模块：

```python
hiddenimports = [
    # ... 其他模块
    '缺失的模块名',
]
```

### 问题 2: 模板或静态文件找不到

**错误信息**: `TemplateNotFound` 或 404 静态文件

**原因**: 数据文件未正确打包

**解决方案**: 确保 `datas` 配置正确：

```python
datas = [
    (str(project_root / 'templates'), 'templates'),
    (str(project_root / 'static'), 'static'),
]
```

### 问题 3: 数据库连接失败

**错误信息**: 数据库连接错误

**原因**: 
- .env 文件未打包
- 数据库路径问题

**解决方案**:
1. 将 `.env` 文件复制到 `dist` 目录
2. 或修改配置使用相对路径
3. 确保目标机器有数据库（MySQL 或 SQLite）

### 问题 4: EXE 文件体积过大

**现状**: 打包后的文件可能有 50-200MB

**优化方案**:
1. 在虚拟环境中打包（只包含必要依赖）
2. 在 `excludes` 中排除不需要的模块
3. 使用 UPX 压缩（已在 spec 中启用）
4. 考虑使用 `--onedir` 模式而非 `--onefile`

### 问题 5: 杀毒软件误报

**现象**: 杀毒软件将 EXE 识别为病毒

**原因**: PyInstaller 打包的程序常被误报

**解决方案**:
1. 将 EXE 添加到杀毒软件白名单
2. 代码签名（需要证书）
3. 向杀毒软件厂商提交误报

### 问题 6: 启动很慢（onefile 模式）

**原因**: onefile 模式需要解压到临时目录

**解决方案**: 使用 onedir 模式（默认），启动更快

### 问题 7: 中文乱码

**原因**: 控制台编码问题

**解决方案**: 在启动脚本中设置编码：

```python
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

---

## 部署到目标机器

### 1. 准备部署包

将以下内容打包：
- 整个 `dist` 文件夹
- `.env` 配置文件（如需要）
- `README_DEPLOY.txt` 部署说明

### 2. 目标机器要求

- Windows 10/11 (64位)
- 无需安装 Python
- 如使用 MySQL，需要安装 MySQL 服务
- 如使用 SQLite，无需额外配置

### 3. 部署步骤

1. 将 `dist` 文件夹复制到目标机器
2. 配置 `.env` 文件（如需要）
3. 双击运行 `ERP_System.exe`
4. 访问 http://127.0.0.1:5003

### 4. 配置为 Windows 服务（可选）

使用 NSSM (Non-Sucking Service Manager) 将程序注册为 Windows 服务：

```batch
# 下载 NSSM: https://nssm.cc/download
nssm install ERP-System "C:\path\to\ERP_System.exe"
nssm start ERP-System
```

---

## 高级配置

### 1. 添加程序图标

准备一个 `.ico` 格式的图标文件，修改 `erp_system.spec`：

```python
exe = EXE(
    # ... 其他配置
    icon='path/to/icon.ico',
)
```

### 2. 修改应用名称

在 `erp_system.spec` 中修改：

```python
exe = EXE(
    # ...
    name='MyERP_System',  # 修改这里
)
```

### 3. 版本信息

创建 `version_info.txt` 文件添加版本信息：

```
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    # ... 更多配置
  ),
  # ...
)
```

在 spec 文件中引用：

```python
exe = EXE(
    # ...
    version='version_info.txt',
)
```

### 4. 单文件模式（不推荐）

如需单文件，修改 spec 文件：

```python
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
    onefile=True,  # 添加这行
)
```

**注意**: 单文件模式启动较慢，不推荐生产使用。

---

## 文件清单

### 打包相关文件

| 文件 | 说明 |
|------|------|
| `run_production_exe.py` | 生产环境启动脚本 |
| `erp_system.spec` | PyInstaller 配置文件 |
| `build_exe.bat` | 自动化打包脚本 |
| `EXE_PACKAGING_GUIDE.md` | 本文档 |

### 打包输出

| 目录/文件 | 说明 |
|-----------|------|
| `build/` | 临时构建文件（可删除） |
| `dist/ERP_System.exe` | 主可执行文件 |
| `dist/_internal/` | 依赖库和资源文件（onedir 模式） |

---

## 技术支持

如遇到问题，请检查：

1. Python 版本是否兼容
2. 所有依赖是否安装
3. 是否在虚拟环境中打包
4. 查看 PyInstaller 文档: https://pyinstaller.org/

---

## 附录：快速命令参考

```bash
# 安装 PyInstaller
pip install pyinstaller

# 使用 spec 文件打包
pyinstaller --clean erp_system.spec

# 清理构建文件
rmdir /s /q build dist

# 测试可执行文件
cd dist
ERP_System.exe
```
