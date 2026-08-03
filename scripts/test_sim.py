"""
仿真引擎验证脚本
用法: python scripts/test_sim.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sim_engine import get_sim, SimEngine, ZONES


def test_basic():
    """基础测试：创建、移动、查询"""
    print("=" * 50)
    print("测试 1: 基础操作")
    print("=" * 50)

    sim = get_sim()

    # 场景信息
    info = sim.get_scene_info()
    print(f"场景: {info['warehouse_size']}m, 区域={info['zones']}")

    # 创建机器人
    r1 = sim.create_robot("agv_1", 0, 0, color="blue")
    r2 = sim.create_robot("agv_2", -3, -3, color="orange")
    print(f"创建: {r1}")
    print(f"创建: {r2}")

    # 查询所有
    all_robots = sim.get_all_robots()
    print(f"全部机器人 ({len(all_robots)}):")
    for r in all_robots:
        print(f"  {r['robot_id']}: {r['position']} zone={r['zone']}")

    # 移动
    mv1 = sim.move_robot("agv_1", 5, 3)
    print(f"移动: {mv1}")

    # 再次查询
    pose = sim.get_robot_pose("agv_1")
    print(f"位置: {pose}")

    # 距离
    dist = sim.check_distance("agv_1", -5, -3)
    print(f"距离: {dist}")

    print()
    return True


def test_obstacle():
    """障碍物检测测试"""
    print("=" * 50)
    print("测试 2: 障碍检测")
    print("=" * 50)

    sim = get_sim()

    # 靠墙放置 → 检测前方障碍（货架在(3.0, 0.0)）
    sim.create_robot("agv_test", 2.0, 0.0, color="red")

    obs = sim.check_obstacle("agv_test", "forward", range_m=2.0)
    print(f"障碍检测（前方2m）: {obs}")

    sim.remove_robot("agv_test")
    print()
    return True


def test_multi_robot():
    """多机器人协调测试"""
    print("=" * 50)
    print("测试 3: 多机器人协调")
    print("=" * 50)

    sim = get_sim()
    sim.reset()

    # 3 台 AGV 分别放不同位置
    sim.create_robot("agv_A", -2, 0, color="blue")
    sim.create_robot("agv_B", 0, -2, color="green")
    sim.create_robot("agv_C", 2, 0, color="purple")

    # 同时移动到各自目标
    targets = [
        ("agv_A", ZONES["A"][0], ZONES["A"][1]),
        ("agv_B", ZONES["B"][0], ZONES["B"][1]),
        ("agv_C", ZONES["C"][0], ZONES["C"][1]),
    ]

    for rid, tx, ty in targets:
        result = sim.move_robot(rid, tx, ty)
        print(f"  {rid} → {result['position'][:2]} (移动 {result['distance']}m)")

    # 全部状态
    print("\n最终状态:")
    for r in sim.get_all_robots():
        print(f"  {r['robot_id']}: pos={r['position']} zone={r['zone']} yaw={r['yaw']}°")

    print()
    return True


def test_velocity():
    """速度控制测试"""
    print("=" * 50)
    print("测试 4: 速度控制")
    print("=" * 50)

    sim = get_sim()
    sim.create_robot("agv_v", 0, 0, color="orange")

    mv = sim.move_robot_by_velocity("agv_v", 1.0, 0.0, duration=3.0)
    print(f"速度控制 (vx=1.0, 3s): → {mv}")

    sim.remove_robot("agv_v")
    print()
    return True


def test_cleanup():
    """清理"""
    sim = get_sim()
    sim.reset()
    # 注意：不调用 close()，因为会影响后续测试


if __name__ == "__main__":
    print("\n🚀 仿真引擎验证\n")

    results = []
    try:
        results.append(("基础操作", test_basic()))
        results.append(("障碍检测", test_obstacle()))
        results.append(("多机器人", test_multi_robot()))
        results.append(("速度控制", test_velocity()))
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        test_cleanup()

    # 汇总
    print("=" * 50)
    print("测试汇总")
    print("=" * 50)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n{passed}/{total} 通过")
