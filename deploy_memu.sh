#!/bin/bash
echo "=========================================="
echo "  MemU Server 部署脚本"
echo "=========================================="
source /home/dream/memory-system/.env
if [ -z "$OPENAI_API_KEY" ]; then
    echo "错误: 未设置 OPENAI_API_KEY"
    exit 1
fi
docker stop memu-server 2>/dev/null
docker rm memu-server 2>/dev/null
echo "正在拉取MemU镜像..."
docker pull nevamindai/memu-server:latest
mkdir -p /home/dream/memory-system/memu-data
echo "正在启动MemU Server..."
docker run -d \
    --name memu-server \
    --restart always \
    -p 8000:8000 \
    -e OPENAI_API_KEY=$OPENAI_API_KEY \
    -v /home/dream/memory-system/memu-data:/app/data \
    nevamindai/memu-server:latest
echo ""
echo "等待服务启动..."
sleep 5
if curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "✅ MemU Server 启动成功！"
    echo "   端口: 8000"
else
    echo "⚠️ 服务可能还在启动中，请稍后验证"
fi
