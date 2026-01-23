FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 设置PYTHONPATH以包含app目录
ENV PYTHONPATH=/app

# 设置工作目录
WORKDIR /app

# 安装必要的系统工具（如果可用）
# 包含ps、top、free等命令
# 包含pstree、killall等命令
# 包含netstat、ifconfig等命令
# 包含ip、ss等命令
RUN set -ex && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        systemd \
        sudo \
        procps \
        coreutils \
        psmisc \
        net-tools \
        iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    || true

# 配置sudo权限（允许应用用户运行journalctl，如果存在）
RUN echo 'ALL ALL=(ALL) NOPASSWD: /usr/bin/journalctl' >> /etc/sudoers 2>/dev/null || echo "sudoers配置可能需要额外处理"

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/

# 复制健康检查脚本（已在复制时设置执行权限）
COPY --chmod=755 healthcheck.sh /app/healthcheck.sh

# 创建数据目录
RUN mkdir -p /app/logs /tmp/cursor



# 容器入口点
ENTRYPOINT ["python", "-u", "src/main.py"]

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD /app/healthcheck.sh