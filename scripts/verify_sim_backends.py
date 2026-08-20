"""
仿真后端冒烟验证 — 验证当前 SIM_BACKEND 对应的后端可用

用法：
    python3 scripts/verify_sim_backends.py                    # 默认 pybullet 冒烟
    SIM_BACKEND=pybullet python3 scripts/verify_sim_backends.py
    SIM_BACKEND=gazebo python3 scripts/verify_sim_backends.py  # 需 ROS 2 环境

验证内容：
    1. 后端类型正确（PyBulletBackend / GazeboBackend）
    2. 创建 AGV → 移动到 C 区 → 到达 → 区域判定正确
    3. 防穿模：目标点与货架冲突被拒绝
    4. check_distance 结果合理
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.sim_engine import get_sim

BACKEND = os.getenv("SIM_BACKEND", "pybullet").strip().lower()
EXPECTED_CLASS = "GazeboBackend" if BACKEND in ("gazebo", "ros2") else "PyBulletBackend"


def main():
    sim = get_sim()
    try:
        cls = type(sim).__name__
        assert cls == EXPECTED_CLASS, f"后端类型错误: {cls} != {EXPECTED_CLASS}"
        print(f"[1] 后端类型: {cls} OK")

        r = sim.create_robot("agv_verify", 0.0, 0.0, color="blue")
        assert "error" not in r, r
        print("[2] 创建 AGV (URDF) OK:", r)

        r = sim.move_robot("agv_verify", -2.5, -2.5)   # C 区
        assert "error" not in r, r
        status = sim.wait_arrival("agv_verify", timeout=60)
        assert status == "arrived", f"到达状态异常: {status}"
        print("[3] 移动 → C 区, wait_arrival:", status)

        pose = sim.get_robot_pose("agv_verify")
        assert pose["zone"] == "C", f"区域判定错误: {pose['zone']}"
        print("[4] 位姿 zone=C OK:", pose["position"])

        r = sim.move_robot("agv_verify", 3.0, 0.0)    # 货架位置 → 应拒绝
        assert "error" in r, "防穿模校验失效"
        print("[5] 防穿模拒绝 OK:", r["error"][:50])

        d = sim.check_distance("agv_verify", 2.5, 2.5)
        assert "error" not in d, d
        print("[6] check_distance OK:", d["distance"], "m")

        print(f"\nVERIFY_ALL_PASS ({BACKEND})")
    finally:
        # 无论成败都清理，避免 rclpy 未 shutdown 导致 C 层析构崩溃
        try:
            sim.remove_robot("agv_verify")
        except Exception:
            pass
        try:
            sim.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
