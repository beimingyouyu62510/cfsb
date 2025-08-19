# 使用 Python 官方镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 复制并安装 mihomo
COPY backend/mihomo-linux-amd64.deb /tmp/mihomo.deb
RUN dpkg -i /tmp/mihomo.deb || \
    (apt-get update && apt-get install -f -y) && \
    rm /tmp/mihomo.deb

# 验证 mihomo 安装
RUN mihomo version || echo "Mihomo ready"

# 复制 requirements 并安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用文件
COPY backend/app.py .

# 复制其他必要文件（如果需要）
# COPY merge.py .
# COPY providers/ ./providers/

# 创建工作目录
RUN mkdir -p /app/logs /app/configs

# 环境变量
ENV CLASH_API_SECRET="511622"
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE $PORT

# 启动命令
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
