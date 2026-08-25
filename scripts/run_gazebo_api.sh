#!/bin/bash
# Gazebo 全链路 API 编排：gzserver → move_to server → 轻量 API（浏览器可访问）
#
# 用法（ROS 容器内，.bashrc 已配 gazebo/ROS/workspace 环境；需 pip install fastapi uvicorn）：
#   bash scripts/run_gazebo_api.sh
# 之后浏览器打开 http://<容器IP>:8001/index3d.html
#   （容器 IP 查询：docker inspect <容器ID> --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'）
#
# 与 run_demo.sh 的区别：run_demo 跑完就退出，本脚本常驻——uvicorn 前台运行，
# ^C 触发清理（杀 server / 杀 gzserver），适合长时间演示。
set -u
cd "$(dirname "$0")/.."

ROBOTS="agv_1 agv_2 agv_3"
API_PORT=8001

cleanup() {
    echo "[gazebo_api] 清理..."
    pkill -9 -f start_move_to_server 2>/dev/null || true
    pkill -9 -f "spawn_entity.py" 2>/dev/null || true
    pkill -9 -f "uvicorn scripts.sim_api_gazebo" 2>/dev/null || true
    pkill -9 -x gzserver 2>/dev/null || true
    echo "[gazebo_api] 清理完成"
}
trap cleanup EXIT

# 1) gzserver（带 ROS 桥插件；先强杀假死残留，避免 11345 端口被占）
pkill -9 -x gzserver 2>/dev/null || true
sleep 1
nohup gzserver app/models/state_world.world \
  -s libgazebo_ros_init.so -s libgazebo_ros_factory.so -s libgazebo_ros_force_system.so \
  > /tmp/gzserver.log 2>&1 &
echo "[gazebo_api] gzserver 启动中..."
sleep 10

# 2) 每车 move_to 服务端（脚本自带同名残留自愈）
for r in $ROBOTS; do
    python3 scripts/ros2_examples/start_move_to_server.py "$r" >/tmp/srv_$r.log 2>&1 &
done
sleep 3

# 3) 轻量 API（前台，^C 触发清理）
echo "[gazebo_api] API 就绪: http://0.0.0.0:$API_PORT （宿主机用容器 IP 访问）"
SIM_BACKEND=gazebo uvicorn scripts.sim_api_gazebo:app \
    --host 0.0.0.0 --port $API_PORT --workers 1
