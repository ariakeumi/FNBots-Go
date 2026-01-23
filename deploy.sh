#!/bin/bash

# FN Message Bot 部署脚本

set -e  # 遇到错误时退出

echo "FN Message Bot 部署脚本"
echo "========================"

# 检查是否安装了 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: 未找到 Docker，请先安装 Docker"
    exit 1
fi

# 检查是否安装了 Docker Compose
if ! docker compose version &> /dev/null; then
    echo "错误: 未找到 Docker Compose，请确保安装了 Docker Compose V2"
    exit 1
fi

# 检查 docker-compose.yml 文件是否存在
if [ ! -f "docker-compose.yml" ]; then
    echo "错误: 未找到 docker-compose.yml 文件"
    exit 1
fi

# 检查 docker-compose.yml 文件中的配置
if grep -q "your_actual_webhook_key_here\|your_webhook_key" docker-compose.yml; then
    echo "错误: 请先编辑 docker-compose.yml 文件，配置你的企业微信机器人 Webhook 地址"
    echo "请将 docker-compose.yml 文件中的 WECHAT_WEBHOOK_URL 替换为实际值"
    exit 1
fi

echo "开始部署 FN Message Bot..."

# 构建最新的镜像
echo "构建最新镜像..."
docker compose build

# 拉取可能的外部依赖
echo "拉取最新依赖..."
docker compose pull

# 启动服务
echo "启动服务..."
docker compose up -d

# 显示服务状态
echo "服务状态:"
docker compose ps

# 显示最近的日志
echo ""
echo "最近的日志:"
docker compose logs --tail=20

echo ""
echo "部署完成！"
echo "服务正在后台运行。"
echo ""
echo "常用命令："
echo "  查看实时日志: docker compose logs -f"
echo "  停止服务: docker compose down"
echo "  重启服务: docker compose restart"
echo "  查看服务状态: docker compose ps"