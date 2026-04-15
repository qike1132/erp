# 依赖优化快速使用指南

**版本**: v1.0.0  
**日期**: 2026-04-10

---

## 📋 目录

1. [文件说明](#1-文件说明)
2. [快速开始](#2-快速开始)
3. [常用命令](#3-常用命令)
4. [验证步骤](#4-验证步骤)

---

## 1. 文件说明

| 文件 | 用途 | 环境 |
|------|------|------|
| `requirements.txt` | 当前依赖（备份状态） | - |
| `requirements.optimized.txt` | 优化后的生产依赖 | ✅ 生产环境 |
| `requirements-dev.txt` | 开发依赖 | ✅ 开发环境 |
| `scripts/analyze_dependencies.py` | 依赖分析脚本 | 🔧 工具 |
| `docs/upgrade/UNUSED_DEPENDENCY_OPTIMIZATION.md` | 完整优化方案 | 📚 文档 |

---

## 2. 快速开始

### 2.1 生产环境部署

```bash
# 1. 备份当前依赖
cp requirements.txt requirements.backup.txt

# 2. 使用优化后的依赖
cp requirements.optimized.txt requirements.txt

# 3. 安装生产依赖
pip install -r requirements.txt
```

### 2.2 开发环境设置

```bash
# 1. 安装生产依赖
pip install -r requirements.txt

# 2. 安装开发依赖
pip install -r requirements-dev.txt
```

### 2.3 依赖分析

```bash
# 运行依赖分析脚本
python scripts/analyze_dependencies.py
```

---

## 3. 常用命令

### 3.1 安装相关

```bash
# 仅安装生产依赖
pip install -r requirements.txt

# 安装开发依赖
pip install -r requirements-dev.txt

# 同时安装生产和开发依赖
pip install -r requirements.txt -r requirements-dev.txt

# 导出当前环境依赖
pip freeze > requirements.current.txt
```

### 3.2 验证相关

```bash
# 检查依赖冲突
pip check

# 查看已安装的包
pip list

# 查看依赖树（需要pipdeptree）
pip install pipdeptree
pipdeptree

# 安全审计（需要pip-audit）
pip install pip-audit
pip-audit
```

### 3.3 测试相关

```bash
# 运行所有测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=app --cov-report=html

# 运行特定测试文件
pytest tests/test_new_libraries.py -v
```

---

## 4. 验证步骤

### 4.1 安装前验证

```bash
# 1. 备份当前环境
pip freeze > requirements.backup.txt

# 2. 运行完整测试
pytest

# 3. 检查系统启动
python run.py
# 访问 http://127.0.0.1:5003 验证系统正常
```

### 4.2 安装后验证

```bash
# 1. 使用优化后的依赖
cp requirements.optimized.txt requirements.txt

# 2. 重新安装依赖
pip install -r requirements.txt

# 3. 运行完整测试
pytest

# 4. 检查系统启动
python run.py

# 5. 验证核心功能
# - 登录功能
# - 产品列表
# - 订单创建
# - 报表导出
```

### 4.3 性能验证

```bash
# 1. 测量启动时间
python -c "
import time
start = time.time()
from app import create_app
app = create_app()
end = time.time()
print(f'启动时间: {end - start:.2f}秒')
"

# 2. 检查内存占用
# Windows: 任务管理器查看Python进程
# Linux: ps aux | grep python
```

---

## 5. 回滚步骤

### 5.1 快速回滚

```bash
# 1. 恢复备份的依赖
cp requirements.backup.txt requirements.txt

# 2. 重新安装
pip install -r requirements.txt

# 3. 重启服务
python run.py
```

### 5.2 Git回滚

```bash
# 如果有Git备份
git checkout <commit-hash> -- requirements.txt
pip install -r requirements.txt
```

---

## 6. 注意事项

### 6.1 生产环境注意事项

- ✅ 使用 `requirements.optimized.txt`
- ❌ 不要安装 `requirements-dev.txt`
- ✅ 先在测试环境验证
- ✅ 保留备份文件

### 6.2 开发环境注意事项

- ✅ 同时安装生产和开发依赖
- ✅ 使用开发工具（black、pylint等）
- ✅ 定期运行依赖分析

### 6.3 可选依赖使用

```bash
# 如果需要PDF功能
pip install PyPDF2==3.0.1

# 如果需要HTTP请求功能
pip install requests>=2.31.0

# 更新到requirements.optimized.txt（取消注释）
```

---

## 7. 预期效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 依赖数量 | 52 | 33 |
| 安装时间 | ~120秒 | ~70秒 |
| 启动时间 | ~3.2秒 | ~2.7秒 |
| 内存占用 | ~120MB | ~105MB |

---

**文档状态**: 就绪  
**最后更新**: 2026-04-10
