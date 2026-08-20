#!/bin/bash
# 一键演示编排：清场 → 起 move_to server → 跑 demo → 统一清理（含 ^C）
#
# 用法（容器内，需已 source ROS 2 环境）：
#   bash scripts/run_demo.sh
#
# 清场范围：残留车 / 旧 server / 僵尸 spawn_entity，杜绝"幽灵车漂移"与同名节点冲突。
set -u
cd "$(dirname "$0")/.."

ROBOTS="agv_1 agv_2 agv_3"

cleanup() {
    echo "[run_demo] 清理现场..."
    # 1) 发零速停车（车可能还在，覆盖 diff_drive 保持的最后指令）
    for r in $ROBOTS; do
        timeout 5 ros2 topic pub -1 /$r/cmd_vel geometry_msgs/msg/Twist \
            "{linear: {x: 0.0}, angular: {z: 0.0}}" >/dev/null 2>&1 || true
    done
    # 2) 删残留车（车不存在/服务无响应均容错）
    for r in $ROBOTS; do
        timeout 5 ros2 service call /delete_entity gazebo_msgs/srv/DeleteEntity \
            "{name: '$r'}" >/dev/null 2>&1 || true
    done
    # 3) 杀残留 server 与僵尸 spawn_entity
    pkill -9 -f start_move_to_server 2>/dev/null || true
    pkill -9 -f "spawn_entity.py" 2>/dev/null || true
    echo "[run_demo] 清理完成"
}

# 退出/中断（^C）时兜底清理；^C 会先中断前台 demo，随后走到这里
trap cleanup EXIT

# 1) 先清场，避免上一轮残留干扰
cleanup
sleep 2

# 2) 启动 3 台车的 move_to 服务端（脚本自带同名残留自愈）
for r in $ROBOTS; do
    python3 scripts/ros2_examples/start_move_to_server.py "$r" >/tmp/srv_$r.log 2>&1 &
done
sleep 3

# 3) 跑演示（三车两轮交叉调度，全部 arrived 后自动清理退出）
SIM_BACKEND=gazebo python3 scripts/sim_demo.py
