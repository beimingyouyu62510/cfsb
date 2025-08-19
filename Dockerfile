# 使用 Python 官方镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装必要的工具和依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 复制并安装本地的 mihomo deb 包
COPY backend/mihomo-linux-amd64.deb /tmp/mihomo.deb

# 安装 mihomo deb 包
RUN dpkg -i /tmp/mihomo.deb || \
    (apt-get update && apt-get install -f -y) && \
    rm /tmp/mihomo.deb

# 验证 mihomo 安装并创建软链接（如果需要）
RUN which mihomo && mihomo version || \
    (echo "Mihomo installation failed" && exit 1)

# 复制 Python 依赖文件
COPY backend/requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY backend/app.py .

# 创建必要的目录
RUN mkdir -p /app/logs

# 定义环境变量
ENV CLASH_API_SECRET="511622"
ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/bin:$PATH"

# 设置适当的权限
RUN chmod 755 /usr/bin/mihomo

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# 暴露端口（Railway 会自动设置 PORT 环境变量）
EXPOSE $PORT

# 启动服务
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
