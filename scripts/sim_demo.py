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


def _cleanup():
    """中断时清理现场：Gazebo 删车重置，PyBullet 直接关场景"""
    try:
        if getattr(sim, "mode", None) == "gazebo":
            sim.reset()
    except Exception as e:
        print(f"⚠️ 清理异常（可忽略）: {e}")


try:
    # 创建 3 台 AGV
    sim.create_robot("agv_1", 0, 0, color="blue")
    sim.create_robot("agv_2", -3, -3, color="orange")
    sim.create_robot("agv_3", 3, 2, color="green")

    print("\n场景就绪！请在 3D 窗口中：")
    print("  🖱 右键拖拽 → 旋转视角")
    print("  🖱 中键/滚轮 → 缩放")
    print("  🖱 Ctrl+左键 → 平移")
    print()

    # 第一轮：三车前往各自区域
    # 注意：直线路径不能贴货架（后端有路径防穿模校验），agv_2 出生点 (-3,-3)
    # 直飞 B 区会贴货架 (-3,0)，故经中转点绕行
    print("→ agv_1 前往 A区 (2.5, 2.5)")
    sim.move_robot("agv_1", ZONES["A"][0], ZONES["A"][1])
    print("→ agv_2 前往 B区（经中转 -1.5,0 绕行货架）")
    sim.move_robot("agv_2", -1.5, 0.0)
    print("→ agv_3 前往 C区 (-2.5, -2.5)")
    sim.move_robot("agv_3", ZONES["C"][0], ZONES["C"][1])
    for rid, zone in [("agv_1", "A区"), ("agv_2", "中转点"), ("agv_3", "C区")]:
        print(f"  {rid} 到达 {zone}: {sim.wait_arrival(rid, timeout=90)}")
    # agv_2 第二段：中转 → B 区
    sim.move_robot("agv_2", ZONES["B"][0], ZONES["B"][1])
    print(f"  agv_2 到达 B区: {sim.wait_arrival('agv_2', timeout=90)}")

    # 第二轮：交叉调度（交叉直线都贴货架，全部经中转绕行）
    print("\n→ 第二轮：交叉调度（绕行中转点）")
    sim.move_robot("agv_1", 1.5, 0.0)     # A → 中转 → D
    sim.move_robot("agv_2", 0.0, 1.5)     # B → 中转 → A
    sim.move_robot("agv_3", -1.5, 0.0)    # C → 中转 → B
    for rid in ["agv_1", "agv_2", "agv_3"]:
        print(f"  {rid} 到达中转点: {sim.wait_arrival(rid, timeout=90)}")
    sim.move_robot("agv_1", ZONES["D"][0], ZONES["D"][1])
    sim.move_robot("agv_2", ZONES["A"][0], ZONES["A"][1])
    sim.move_robot("agv_3", ZONES["B"][0], ZONES["B"][1])
    for rid, zone in [("agv_1", "D区"), ("agv_2", "A区"), ("agv_3", "B区")]:
        print(f"  {rid} 到达 {zone}: {sim.wait_arrival(rid, timeout=90)}")

    # 最终状态
    print("\n✅ 演示完成")

    # GUI 模式保持窗口打开；无头（direct）/ Gazebo 模式直接结束
    if getattr(sim, "mode", "direct") == "gui":
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
except KeyboardInterrupt:
    print("\n⚠️ 演示被中断，正在清理现场...")
    _cleanup()
    sim.close()
    print("👋 已退出")
    sys.exit(130)

# Gazebo 后端：演示完清掉世界里的车（pybullet 的 close 会连场景一起关）
if getattr(sim, "mode", None) == "gazebo":
    sim.reset()

sim.close()
print("👋 已退出")
