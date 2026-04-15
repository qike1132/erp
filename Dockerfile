# 阶段1: 构建依赖
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libmariadb-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖（仅生产依赖）
COPY requirements/base.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 阶段2: 运行时镜像
FROM python:3.12-slim

WORKDIR /app

# 仅安装运行时系统依赖（无需编译工具）
RUN apt-get update && apt-get install -y \
    libmariadb3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false appuser

# 从构建阶段复制Python包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码
COPY . .

# 确保 entrypoint.sh 使用 LF 行尾并有执行权限（防止 Windows CRLF 问题）
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# 创建日志目录
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# 安全：以非root用户运行
USER appuser

# 暴露端口 (Flask:5003, FastAPI:5002)
EXPOSE 5003 5002

# 设置环境变量
ENV FLASK_APP=run.py
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# 使用 entrypoint 脚本同时启动 FastAPI 和 Flask
CMD ["/app/entrypoint.sh"]
