#!/bin/bash
# Docker 镜像构建与推送（可选指定平台：amd64 / arm64）

set -e

echo "FN Message Bots - Docker 镜像发布"
echo "=================================="

if ! command -v docker &> /dev/null; then
    echo "错误: 未找到 Docker"
    exit 1
fi

if [ $# -eq 0 ]; then
    echo "用法: $0 <镜像名> [tag] [平台]"
    echo "  平台: 留空=当前架构, amd64, arm64"
    echo "示例: $0 sunanang/fn-message-bots latest"
    echo "      $0 sunanang/fn-message-bots latest amd64"
    exit 1
fi

IMAGE_NAME=$1
TAG=${2:-"latest"}
PLATFORM=${3:-""}

echo "镜像: $IMAGE_NAME:$TAG ${PLATFORM:+平台: $PLATFORM}"

BUILD_OPTS="-t $IMAGE_NAME:$TAG ."
[ -n "$PLATFORM" ] && BUILD_OPTS="--platform linux/$PLATFORM -t $IMAGE_NAME:$TAG ."

echo "构建中..."
docker build $BUILD_OPTS

echo "推送中..."
docker push $IMAGE_NAME:$TAG

echo ""
echo "发布完成。使用: docker compose up -d 或见 README。"
