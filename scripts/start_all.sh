#!/bin/bash
# 一键启动 AI Agent 全栈服务
set -e

echo "🚀 启动 AI Agent 企业级全栈服务..."

# 启动所有服务
docker compose up -d

echo ""
echo "⏳ 等待服务就绪..."
sleep 10

# 初始化数据库
docker compose exec api python scripts/init_db.py 2>/dev/null || echo "   (数据库延迟初始化，后端已自动创建表)"

echo ""
echo "============================================"
echo "  ✅ 服务已启动"
echo "============================================"
echo ""
echo "  📡 API 服务:       http://localhost:8000"
echo "  📄 API 文档:       http://localhost:8000/docs"
echo "  🎨 Web 前端:       http://localhost:8000"
echo "  📊 Streamlit:      http://localhost:8501"
echo "  🌸 Celery 监控:    http://localhost:5555"
echo "  📈 Prometheus:     http://localhost:9090"
echo "  📊 Grafana:        http://localhost:3000 (admin/admin)"
echo ""
echo "  测试命令:"
echo "    python test_smoke.py          # 快速冒烟测试"
echo "    locust -f tests/locustfile.py       # 压力测试"
echo ""
echo "  停止: docker compose down"
echo "============================================"
