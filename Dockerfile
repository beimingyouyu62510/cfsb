# 使用 Python 官方镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装必要的工具
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gzip && \
    rm -rf /var/lib/apt/lists/*

# 下载 Mihomo 内核
RUN curl -L "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.2/mihomo-linux-amd64-v1.18.2.gz" -o mihomo.gz && \
    gzip -d mihomo.gz && \
    mv mihomo-linux-amd64-v1.18.2 mihomo && \
    chmod +x mihomo

# 复制 Python 依赖文件
COPY backend/requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY backend/app.py .

# 定义环境变量（可选）
ENV CLASH_API_SECRET="511622"

# 启动服务
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
