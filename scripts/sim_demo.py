"""
仿真交互式 Demo — 可视化调试
用法: SIM_MODE=gui python3 scripts/sim_demo.py
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sim_engine import get_sim, ZONES

print("🚀 启动仿真场景...")
sim = get_sim()

# 创建 3 台 AGV
sim.create_robot("agv_1", 0, 0, color="blue")
sim.create_robot("agv_2", -3, -3, color="orange")
sim.create_robot("agv_3", 3, 2, color="green")

print("\n场景就绪！请在 3D 窗口中：")
print("  🖱 右键拖拽 → 旋转视角")
print("  🖱 中键/滚轮 → 缩放")
print("  🖱 Ctrl+左键 → 平移")
print()

# 逐个移动演示
steps = [
    ("agv_1", "A区", ZONES["A"][0], ZONES["A"][1]),
    ("agv_2", "B区", ZONES["B"][0], ZONES["B"][1]),
    ("agv_3", "C区", ZONES["C"][0], ZONES["C"][1]),
]

for robot_id, zone, tx, ty in steps:
    print(f"→ {robot_id} 前往 {zone} ({tx}, {ty})")
    sim.move_robot(robot_id, tx, ty)
    time.sleep(1.5)

# 第二步：交叉移动
print("\n→ 第二轮：交叉调度")
sim.move_robot("agv_1", ZONES["D"][0], ZONES["D"][1])
time.sleep(1.5)
sim.move_robot("agv_2", ZONES["A"][0], ZONES["A"][1])
time.sleep(1.5)
sim.move_robot("agv_3", ZONES["B"][0], ZONES["B"][1])
time.sleep(1.5)

# 最终状态
print("\n✅ 演示完成，窗口保持打开")
print("   关闭 3D 窗口即可退出")

# 每隔 1 秒探测一次状态（检测窗口是否关闭），最长等 60 秒
try:
    for i in range(60):
        pose = sim.get_robot_pose("agv_1")
        if "error" in pose:
            break
        time.sleep(1)
except KeyboardInterrupt:
    pass

sim.close()
print("👋 已退出")
