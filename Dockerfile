FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/
COPY config/ ./config/

# 创建必要的目录
RUN mkdir -p /app/logs /app/cursor

# 运行应用
CMD ["python", "-m", "src.main"]