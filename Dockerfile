# ==========================================
# 滨发协同系统 - Dockerfile 多阶段构建
# 版本: v1.0
# 目标镜像大小: ≤350MB
# ==========================================

# ------------------------------------------
# Stage 1: 前端构建 (Node.js)
# ------------------------------------------
FROM node:18-alpine AS frontend-builder

WORKDIR /app/frontend

# 复制依赖文件
COPY frontend/package*.json ./
RUN npm ci --only=production

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# ------------------------------------------
# Stage 2: Python 依赖安装
# ------------------------------------------
FROM python:3.11-slim AS python-builder

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements/ ./requirements/
RUN pip install --no-cache-dir --user -r requirements/base.txt

# ------------------------------------------
# Stage 3: 生产镜像
# ------------------------------------------
FROM python:3.11-slim AS production

# 安全：创建非 root 用户
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制 Python 依赖
COPY --from=python-builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# 复制应用代码
COPY fastapi_app/ ./fastapi_app/
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY utils/ ./utils/
COPY run.py ./

# 从前端构建阶段复制构建产物
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 设置权限
RUN chown -R appuser:appgroup /app
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5002/api/health')" || exit 1

# 暴露端口
EXPOSE 5002 5003

# 启动命令
CMD ["python", "run.py"]
