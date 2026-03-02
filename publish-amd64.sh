#!/bin/bash

# AMD64 架构镜像发布脚本

set -e  # 遇到错误时退出

echo "FN Message Bot AMD64 Docker 镜像发布脚本"
echo "=================================="

# 检查是否安装了 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: 未找到 Docker，请先安装 Docker"
    exit 1
fi

# 检查是否提供了镜像名称参数
if [ $# -eq 0 ]; then
    echo "用法: $0 <docker-image-name> [tag]"
    echo "示例: $0 your-registry/image-name"
    echo "      $0 crpi-ys9neflc9z1wqyy7.cn-hangzhou.personal.cr.aliyuncs.com/sunanang/fn_message_bots"
    exit 1
fi

IMAGE_NAME=$1
TAG=${2:-"latest"}

echo "镜像名称: $IMAGE_NAME:$TAG"

# 构建 AMD64 架构的镜像
echo "正在构建 AMD64 架构镜像 $IMAGE_NAME:$TAG ..."
docker build --platform linux/amd64 -t $IMAGE_NAME:$TAG .

# 推送镜像
echo "正在推送 AMD64 架构镜像 $IMAGE_NAME:$TAG ..."
docker push $IMAGE_NAME:$TAG

echo ""
echo "AMD64 架构镜像发布完成！"
echo "镜像现在可在 AMD64/x86_64 架构的机器上运行"
echo ""
echo "你可以通过以下命令使用镜像："
echo "  docker run -d --platform linux/amd64 --network=host \\"
echo "    -v /var/log/journal:/var/log/journal:ro \\"
echo "    -v /run/log/journal:/run/log/journal:ro \\"
echo "    -v /var/log/syslog:/var/log/syslog:ro \\"
echo "    -v ./data/logs:/app/logs:rw \\"
echo "    -v ./data/cursor:/tmp/cursor:rw \\"
echo "    -e WECHAT_WEBHOOK_URL='your_webhook_url' \\"
echo "    $IMAGE_NAME:$TAG"
echo ""
echo "或者使用 docker-compose："
echo "  docker-compose -f docker-compose.yml up -d"