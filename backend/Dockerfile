# 使用 Python 官方镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制 Clash 核心可执行文件
# 请确保你的 Clash 核心文件名为 clash-linux-amd64
# 你需要将这个文件手动上传到你的仓库中
COPY clash-linux-amd64 .

# 赋予可执行权限
RUN chmod +x ./clash-linux-amd64

# 复制 Python 依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .

# 定义环境变量（可选）
ENV CLASH_API_SECRET="511622"

# 启动服务
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
