#!/bin/bash

# Docker 镜像发布脚本

set -e  # 遇到错误时退出

echo "FN Message Bot Docker 镜像发布脚本"
echo "=================================="

# 检查是否安装了 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: 未找到 Docker，请先安装 Docker"
    exit 1
fi

# 检查是否提供了镜像名称参数
if [ $# -eq 0 ]; then
    echo "用法: $0 <docker-image-name> [tag]"
    echo "示例: $0 sunanang/fn-message-bots"
    echo "      $0 your-username/fn-message-bots"
    echo "      $0 your-username/fn-message-bots latest"
    exit 1
fi

IMAGE_NAME=$1
TAG=${2:-"latest"}

echo "镜像名称: $IMAGE_NAME:$TAG"

# 构建镜像
echo "正在构建镜像 $IMAGE_NAME:$TAG ..."
docker build -t $IMAGE_NAME:$TAG .

# 推送镜像
echo "正在推送镜像 $IMAGE_NAME:$TAG ..."
docker push $IMAGE_NAME:$TAG

echo ""
echo "镜像发布完成！"
echo ""
echo "你可以通过以下命令使用镜像："
echo "  docker run -d --network=host \\"
echo "    -v /var/log/journal:/var/log/journal:ro \\"
echo "    -v /run/log/journal:/run/log/journal:ro \\"
echo "    -v /var/log/syslog:/var/log/syslog:ro \\"
echo "    -v ./data/logs:/app/logs:rw \\"
echo "    -v ./data/cursor:/tmp/cursor:rw \\"
echo "    -e WECHAT_WEBHOOK_URL='your_webhook_url' \\"
echo "    $IMAGE_NAME:$TAG"
echo ""
echo "或者使用 docker-compose："
echo "  services:"
echo "    fn-message-bot:"
echo "      image: $IMAGE_NAME:$TAG"
echo "      # ... 其他配置"