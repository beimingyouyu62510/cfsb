# 使用 Python 官方镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 下载 Clash 核心
# 你需要找到最新的版本号和下载链接
# 示例链接可能不是最新的，请自行替换
# https://github.com/MetaCubeX/mihomo/releases/download/v1.18.2/mihomo-linux-amd64-v1.18.2.gz
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gzip && \
    curl -L "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.2/mihomo-linux-amd64-v1.18.2.gz" -o mihomo.gz && \
    gzip -d mihomo.gz && \
    mv mihomo-linux-amd64-v1.18.2 mihomo && \
    chmod +x mihomo && \
    rm -rf /var/lib/apt/lists/*

# 复制 Python 依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .

# 定义环境变量（可选）
ENV CLASH_API_SECRET="your-api-secret"

# 启动服务
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
