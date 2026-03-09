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

IMAGE_NAME="$1"
TAG="${2:-latest}"
# 推送为 tag-amd64，与 arm64 的 tag-arm64 并存，互不覆盖
TAG_ARCH="${TAG}-amd64"
FULL_IMAGE="${IMAGE_NAME}:${TAG_ARCH}"

echo "镜像名称: $FULL_IMAGE（保留 amd64，不与 arm64 覆盖）"
echo ""

# 构建 AMD64 架构的镜像
echo "正在构建 AMD64 镜像 $FULL_IMAGE ..."
docker build --platform linux/amd64 -t "$FULL_IMAGE" .

# 推送镜像
echo "正在推送 $FULL_IMAGE ..."
docker push "$FULL_IMAGE"

echo ""
echo "AMD64 架构镜像发布完成！"
echo "已推送: $FULL_IMAGE"
echo "再运行 ./publish-arm64.sh $IMAGE_NAME $TAG 可保留 arm64；最后运行 ./publish-manifest.sh $IMAGE_NAME $TAG 可生成多架构 latest"
echo ""
echo "你可以通过以下命令使用镜像："
echo "  docker run -d --platform linux/amd64 --network=host \\"
echo "    -v /var/log/journal:/var/log/journal:ro \\"
echo "    -v /run/log/journal:/run/log/journal:ro \\"
echo "    -v /var/log/syslog:/var/log/syslog:ro \\"
echo "    -v ./data/logs:/app/logs:rw \\"
echo "    -v ./data/cursor:/tmp/cursor:rw \\"
echo "    -e WECHAT_WEBHOOK_URL='your_webhook_url' \\"
echo "    $FULL_IMAGE"
echo ""
echo "或者使用 docker-compose："
echo "  docker-compose -f docker-compose.yml up -d"