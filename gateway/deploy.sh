#!/bin/bash
# ============================================
# Memory System 一键部署脚本
# 部署 Gateway + MemU
# ============================================

set -e

echo "🚀 Memory System 一键部署"
echo "=========================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查目录
PROJECT_DIR="/home/dream/memory-system"
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}❌ 未找到项目目录: $PROJECT_DIR${NC}"
    exit 1
fi

cd "$PROJECT_DIR"

# ============ Step 1: 检查环境变量 ============
echo -e "${YELLOW}📋 Step 1: 检查环境变量${NC}"

if [ ! -f ".env" ]; then
    echo -e "${RED}❌ 未找到 .env 文件${NC}"
    echo "请先创建 .env 文件，参考 .env.template"
    exit 1
fi

source .env

# 检查必要变量
MISSING_VARS=""

if [ -z "$SUPABASE_URL" ]; then MISSING_VARS="$MISSING_VARS SUPABASE_URL"; fi
if [ -z "$SUPABASE_KEY" ]; then MISSING_VARS="$MISSING_VARS SUPABASE_KEY"; fi
if [ -z "$LLM_API_KEY" ]; then MISSING_VARS="$MISSING_VARS LLM_API_KEY"; fi

if [ -n "$MISSING_VARS" ]; then
    echo -e "${RED}❌ 缺少必要环境变量:$MISSING_VARS${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 环境变量检查通过${NC}"

# 检查可选变量
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  未配置 OPENROUTER_API_KEY，GPT-4o/Claude 将不可用${NC}"
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  未配置 OPENAI_API_KEY（硅基流动Key），MemU语义搜索将不可用${NC}"
fi

echo ""

# ============ Step 2: 备份旧文件 ============
echo -e "${YELLOW}📦 Step 2: 备份现有文件${NC}"

BACKUP_DIR="$PROJECT_DIR/backup_$(date +%Y%m%d_%H%M%S)"
if [ -d "$PROJECT_DIR/gateway" ]; then
    mkdir -p "$BACKUP_DIR"
    cp -r "$PROJECT_DIR/gateway" "$BACKUP_DIR/"
    echo -e "${GREEN}✅ 已备份到 $BACKUP_DIR${NC}"
else
    echo "无需备份（新安装）"
fi

echo ""

# ============ Step 3: 停止旧服务 ============
echo -e "${YELLOW}🛑 Step 3: 停止旧服务${NC}"

pkill -f "python3 main.py" 2>/dev/null || true
docker stop memu-server 2>/dev/null || true
docker rm memu-server 2>/dev/null || true

echo -e "${GREEN}✅ 旧服务已停止${NC}"
echo ""

# ============ Step 4: 更新Gateway代码 ============
echo -e "${YELLOW}📝 Step 4: 更新Gateway代码${NC}"

# 如果是从脚本同目录部署
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/main.py" ]; then
    echo "从本地复制文件..."
    mkdir -p "$PROJECT_DIR/gateway/services"
    mkdir -p "$PROJECT_DIR/gateway/routers"
    
    cp "$SCRIPT_DIR/main.py" "$PROJECT_DIR/gateway/"
    cp "$SCRIPT_DIR/config.py" "$PROJECT_DIR/gateway/"
    cp "$SCRIPT_DIR/requirements.txt" "$PROJECT_DIR/gateway/"
    cp "$SCRIPT_DIR/services/"*.py "$PROJECT_DIR/gateway/services/"
    cp "$SCRIPT_DIR/routers/"*.py "$PROJECT_DIR/gateway/routers/"
    
    echo -e "${GREEN}✅ Gateway代码已更新${NC}"
else
    echo -e "${RED}❌ 未找到源代码文件，请手动复制${NC}"
    exit 1
fi

echo ""

# ============ Step 5: 安装依赖 ============
echo -e "${YELLOW}📦 Step 5: 安装Python依赖${NC}"

cd "$PROJECT_DIR/gateway"
pip3 install -r requirements.txt -q

echo -e "${GREEN}✅ 依赖安装完成${NC}"
echo ""

# ============ Step 6: 部署MemU ============
echo -e "${YELLOW}🧠 Step 6: 部署MemU语义搜索服务${NC}"

if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  跳过MemU部署（未配置硅基流动Key）${NC}"
    echo "Gateway将使用关键词搜索作为fallback"
else
    echo "启动MemU Docker容器..."
    
    docker run -d \
        --name memu-server \
        --restart always \
        -p 8000:8000 \
        -e OPENAI_API_KEY="$OPENAI_API_KEY" \
        -e OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.siliconflow.cn/v1}" \
        -e EMBED_MODEL="${EMBED_MODEL:-BAAI/bge-large-zh-v1.5}" \
        -e POSTGRES_URL="$SUPABASE_DB_URL" \
        nevamindai/memu-server:latest
    
    echo "等待MemU启动..."
    sleep 15
    
    if curl -s http://localhost:8000/ > /dev/null 2>&1; then
        echo -e "${GREEN}✅ MemU启动成功${NC}"
    else
        echo -e "${YELLOW}⚠️  MemU可能还在启动中，请稍后检查: docker logs memu-server${NC}"
    fi
fi

echo ""

# ============ Step 7: 启动Gateway ============
echo -e "${YELLOW}🌐 Step 7: 启动Gateway${NC}"

cd "$PROJECT_DIR/gateway"
nohup python3 main.py > ../gateway.log 2>&1 &

sleep 3

if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Gateway启动成功${NC}"
else
    echo -e "${RED}❌ Gateway启动失败，查看日志: tail -f $PROJECT_DIR/gateway.log${NC}"
    exit 1
fi

echo ""

# ============ 完成 ============
echo "============================================"
echo -e "${GREEN}🎉 部署完成！${NC}"
echo "============================================"
echo ""
echo "📊 服务状态："
echo "   Gateway: http://localhost:8001"
echo "   MemU:    http://localhost:8000"
echo ""
echo "📝 支持的模型："
curl -s http://localhost:8001/models | python3 -c "import sys,json; d=json.load(sys.stdin); print('   ' + ', '.join(d.get('models',[])))" 2>/dev/null || echo "   deepseek-chat, gpt-4o, claude-3.5-sonnet, ..."
echo ""
echo "📋 常用命令："
echo "   查看Gateway日志: tail -f $PROJECT_DIR/gateway.log"
echo "   查看MemU日志:    docker logs -f memu-server"
echo "   重启Gateway:     pkill -f 'python3 main.py' && cd $PROJECT_DIR/gateway && nohup python3 main.py > ../gateway.log 2>&1 &"
echo "   重启MemU:        docker restart memu-server"
echo ""
echo "🔧 Kelivo配置："
echo "   API Base URL: http://你的服务器IP:8001/v1"
echo "   MCP URL:      http://你的服务器IP:8001/mcp"
echo ""
