# ==================== Stage 1: 前端构建 ====================
FROM node:22-alpine AS frontend-build

WORKDIR /build
COPY frontend-vite/package.json frontend-vite/package-lock.json* ./
RUN npm ci --frozen-lockfile

COPY frontend-vite/ ./
RUN npm run build

# ==================== Stage 2: Python依赖安装 ====================
FROM python:3.12-slim AS python-deps

WORKDIR /deps
COPY requirements/base.txt requirements/base.txt
COPY requirements/ requirements/

RUN pip install --no-cache-dir --prefix=/install -r requirements/base.txt

# ==================== Stage 3: 运行时镜像 ====================
FROM python:3.12-slim AS runtime

LABEL maintainer="ERP System"
LABEL org.opencontainers.image.source="https://github.com/binfa/erp_system"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    PORT=5002

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

COPY --from=python-deps /install /usr/local

WORKDIR /app

COPY fastapi_app/ fastapi_app/
COPY utils/ utils/
COPY migrations/ migrations/
COPY config/ config/
COPY scripts/ scripts/

COPY --from=frontend-build /build/dist /app/frontend-vite/dist

RUN mkdir -p /app/static/uploads /app/logs && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 5002

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5002/api/health')" || exit 1

# Worker 数量通过环境变量 UVICORN_WORKERS 动态配置，默认 4
# 使用 sh -c 以支持 shell 参数展开 ${VAR:-default}
CMD ["sh", "-c", "uvicorn fastapi_app.main:app --host 0.0.0.0 --port 5002 --workers ${UVICORN_WORKERS:-4} --loop uvloop --http httptools --no-access-log"]
