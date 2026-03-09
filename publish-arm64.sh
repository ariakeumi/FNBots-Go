#!/bin/bash

# ARM64 架构镜像发布脚本

set -e  # 遇到错误时退出

echo "FN Message Bot ARM64 Docker 镜像发布脚本"
echo "=================================="

# 检查是否安装了 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: 未找到 Docker，请先安装 Docker"
    exit 1
fi

# 检查是否提供了镜像名称参数
if [ $# -eq 0 ]; then
    echo "用法: $0 <docker-image-name> [tag]"
    echo "示例: $0 sunanang/fn-message-bots latest   # 与 publish-amd64.sh 使用相同镜像名"
    echo "      $0 registry.cn-hangzhou.aliyuncs.com/命名空间/fn-message-bots latest"
    echo ""
    echo "推送前请先登录: docker login <仓库地址>；镜像名勿写错（如 sunanang 不要写成 csunanang）"
    exit 1
fi

IMAGE_NAME="$1"
TAG="${2:-latest}"
# 推送为 tag-arm64，与 amd64 的 tag-amd64 并存，互不覆盖
TAG_ARCH="${TAG}-arm64"
FULL_IMAGE="${IMAGE_NAME}:${TAG_ARCH}"

echo "镜像名称: $FULL_IMAGE（保留 arm64，不与 amd64 覆盖）"
echo ""

# 国内拉取 base 镜像易超时，默认使用 DaoCloud 镜像源；海外可设 USE_DOCKER_HUB_MIRROR=0
BASE_IMAGE_ARG=""
if [ "${USE_DOCKER_HUB_MIRROR:-1}" = "1" ]; then
    BASE_IMAGE_ARG="--build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim"
    echo "使用国内镜像源拉取 base（USE_DOCKER_HUB_MIRROR=0 则用 Docker Hub）"
fi

# 与 publish-amd64.sh 一致：docker build 再本机 docker push
echo "正在构建 ARM64 镜像 $FULL_IMAGE ..."
if ! docker build --platform linux/arm64 $BASE_IMAGE_ARG -t "$FULL_IMAGE" .; then
    echo "构建失败。"
    exit 1
fi
echo "正在推送 $FULL_IMAGE ..."
if ! docker push "$FULL_IMAGE"; then
    echo ""
    echo "推送失败。请检查: 1) docker login 是否已登录  2) 镜像名与 amd64 一致（如 sunanang/fn-message-bots）"
    exit 1
fi

echo ""
echo "ARM64 架构镜像发布完成！"
echo "已推送: $FULL_IMAGE"
echo "amd64 与 arm64 已分别保留；可运行 ./publish-manifest.sh $IMAGE_NAME $TAG 生成多架构 tag（如 latest）"
echo ""
echo "你可以通过以下命令使用镜像："
echo "  docker run -d --platform linux/arm64 --network=host \\"
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