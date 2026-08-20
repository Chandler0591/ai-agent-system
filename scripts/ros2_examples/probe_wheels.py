#!/usr/bin/env python3
"""轮子探针：spawn 单台车 → 前进/转向测试 → odom 与 Gazebo 地面真值对比，定位"车不动"根因

用法（容器内，已 source ROS 环境，Gazebo 已运行）:
    python3 scripts/ros2_examples/probe_wheels.py

结论判读（阶段 A/B 各输出一条）:
    真值位移 > 0.3m / 增量累加转角 > 57° → 驱动正常（有牵引力）
    odom 位移大、真值小           → 轮子空转（摩擦不足，odom 是轮子编码器积分）
    两者都小                      → 插件未驱动轮子（速度指令未生效）
"""
import math
import re
import subprocess
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from gazebo_msgs.msg import LinkStates

ROBOT = "probe_agv"


def call(args, tolerant=False, tries=3, timeout=12):
    """ROS 2 CLI 调用（带重试）：容器内 DDS 发现间歇性抽风，服务偶发不可见"""
    last_err = f"超时 {timeout}s"
    for attempt in range(1, tries + 1):
        try:
            r = subprocess.run([str(a) for a in args], capture_output=True,
                               text=True, timeout=timeout)
            if r.returncode == 0:
                return r
            last_err = r.stderr.strip()[:300]
        except subprocess.TimeoutExpired:
            last_err = f"超时 {timeout}s"
        if attempt < tries:
            print(f"  [重试 {attempt}/{tries}] {' '.join(map(str, args[:2]))} ...")
            time.sleep(2.0)
    if tolerant:
        return None
    print(f"[FAIL] {' '.join(args)}\n  {last_err}")
    sys.exit(1)


NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def entity_state():
    """Gazebo /get_entity_state 地面真值 (x, y, z, yaw)，服务不可用/失败返回 None

    注意：humble 版 ros2cli 的响应是 Python repr 格式（x=0.5 而非 x: 0.5），
    且小值用科学计数法（2.57e-05），正则必须同时兼容等号与冒号、指数形式。
    """
    r = call(["ros2", "service", "call", "/get_entity_state",
              "gazebo_msgs/srv/GetEntityState",
              f"{{name: '{ROBOT}', reference_frame: 'world'}}"], tolerant=True)
    if r is None or r.returncode != 0:
        return None
    out = r.stdout
    if "success=False" in out:
        return None
    # humble 响应格式：orientation=geometry_msgs.msg.Quaternion(...)（等号不是冒号）
    sep = "orientation=" if "orientation=" in out else "orientation:"
    pos_part = out.split(sep)[0]
    ori_part = out.split(sep)[-1]

    def vec(part):
        m = re.search(rf"x[:=]\s*({NUM}).*?y[:=]\s*({NUM}).*?z[:=]\s*({NUM})", part, re.S)
        return tuple(float(v) for v in m.groups()) if m else (0.0, 0.0, 0.0)

    x, y, z = vec(pos_part)
    qm = re.search(
        rf"x[:=]\s*({NUM}).*?y[:=]\s*({NUM}).*?z[:=]\s*({NUM}).*?w[:=]\s*({NUM})",
        ori_part, re.S)
    qx, qy, qz, qw = tuple(float(v) for v in qm.groups()) if qm else (0.0, 0.0, 0.0, 1.0)
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return x, y, z, yaw


def drive(pub, node, linear, angular, seconds):
    """以 ~20Hz 发布 Twist 指令 seconds 秒，结束发零指令"""
    twist = Twist()
    twist.linear.x = linear
    twist.angular.z = angular
    stop = time.time() + seconds
    while time.time() < stop:
        pub.publish(twist)
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.02)
    pub.publish(Twist())


def main():
    # 0) 清残留 + spawn（z=0.117 高于触地 2mm，超过 ODE min_depth 1mm 接触阈值；
    #    0.13 落地冲击大、1/3 概率车轮接触异常）
    call(["ros2", "service", "call", "/delete_entity", "gazebo_msgs/srv/DeleteEntity",
          f"{{name: '{ROBOT}'}}"], tolerant=True)
    time.sleep(1.0)
    call(["ros2", "run", "gazebo_ros", "spawn_entity.py", "-entity", ROBOT,
          "-file", "/workspace/app/models/agv.urdf",
          "-robot_namespace", ROBOT, "-x", "0.0", "-y", "0.0", "-z", "0.117"])
    print(f"[OK] {ROBOT} spawn 完成，等待 odom ...")

    # 1) rclpy 探针节点
    rclpy.init()
    node = Node("probe_wheels")
    pub = node.create_publisher(Twist, f"/{ROBOT}/cmd_vel", 10)
    cache = {"pos": None, "yaw": None, "vel": None}

    def on_odom(m):
        q = m.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        cache["pos"] = (m.pose.pose.position.x, m.pose.pose.position.y)
        cache["yaw"] = math.atan2(siny, cosy)
        cache["vel"] = m.twist.twist.linear.x

    node.create_subscription(Odometry, f"/{ROBOT}/odom", on_odom, 10)

    # 诊断：link_states 世界 yaw（与 entity_state 交叉验证）
    ls_cache = {"yaw": None}

    def on_links(m):
        try:
            i = m.name.index(f"{ROBOT}::base_link")
        except ValueError:
            return
        q = m.pose[i].orientation
        ls_cache["yaw"] = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                                      1.0 - 2.0 * (q.y * q.y + q.z * q.z))

    node.create_subscription(LinkStates, "/link_states", on_links, 10)

    t0 = time.time()
    while time.time() - t0 < 20 and cache["pos"] is None:
        rclpy.spin_once(node, timeout_sec=0.2)
    if cache["pos"] is None:
        print("[FAIL] 20s 内无 odom")
        sys.exit(1)
    print(f"[OK] 首条 odom: pos={cache['pos']}")

    # 2) cmd_vel 订阅者数
    r = call(["ros2", "topic", "info", f"/{ROBOT}/cmd_vel", "-v"], tolerant=True)
    if r is not None:
        for line in r.stdout.splitlines():
            if "Subscription count" in line:
                print(f"[INFO] {line.strip()}")
                break
    else:
        print("[INFO] 无法查询 cmd_vel 订阅者（DDS 发现失败，不影响探针）")

    # 3) 阶段 A：前进 5s
    st = entity_state()
    if st:
        print(f"[真值] 初始 (x={st[0]:.3f}, y={st[1]:.3f}, z={st[2]:.3f}, "
              f"yaw={math.degrees(st[3]):.1f}°)")
    pos_before = cache["pos"]
    print("=== 阶段 A: 前进 linear.x=0.5, 5s ===")
    drive(pub, node, 0.5, 0.0, 5.0)
    rclpy.spin_once(node, timeout_sec=1.0)
    st_after = entity_state()
    odom_d = math.hypot(cache["pos"][0] - pos_before[0], cache["pos"][1] - pos_before[1])
    truth_d = 0.0
    truth_ok = bool(st and st_after)
    if truth_ok:
        truth_d = math.hypot(st_after[0] - st[0], st_after[1] - st[1])
        print(f"[真值] 当前 z={st_after[2]:.3f}（正常落地应 ~0.115；若 ~0.13 说明车悬空未触地）")
    else:
        print("[真值] 真值不可用（/get_entity_state 失败），结论仅参考 odom")
    print(f"[odom] odom 自报车速 vel.x={cache['vel']:.3f}（插件认为的车速）")
    print(f"odom 位移: {odom_d:.3f}    真值位移: {truth_d:.3f}")
    if not truth_ok:
        print("→ 真值缺失，无法判定车是否真动")
    elif truth_d > 0.3:
        print("→ 驱动正常 ✓（轮子有牵引力）")
    elif odom_d > 0.3:
        print("→ 轮子空转：odom 认为走了、真值没动 → 摩擦不足")
    else:
        print("→ 插件未驱动轮子：odom 与真值都不动 → 速度指令未生效")

    # 3.5) 停稳：等轮子速度归零再测转向，否则轮速差未建立、转角读数失真
    pub.publish(Twist())
    time.sleep(2.5)
    rclpy.spin_once(node, timeout_sec=0.5)

    # 4) 阶段 B：原地转向 5s
    st_b = entity_state()
    yaw_before = cache["yaw"]
    ls_b = ls_cache["yaw"]
    print("=== 阶段 B: 原地转向 angular.z=1.0, 5s ===")
    twist_b = Twist()
    twist_b.angular.z = 1.0
    stop_b = time.time() + 5.0
    yaw_acc = 0.0
    prev_yaw = ls_cache["yaw"]
    while time.time() < stop_b:
        pub.publish(twist_b)
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.02)
        cur = ls_cache["yaw"]
        if prev_yaw is not None and cur is not None:
            d = math.atan2(math.sin(cur - prev_yaw), math.cos(cur - prev_yaw))
            yaw_acc += d
            prev_yaw = cur
    pub.publish(Twist())
    rclpy.spin_once(node, timeout_sec=1.0)
    st_b2 = entity_state()
    ls_a = ls_cache["yaw"]
    yaw_odom_d = abs(math.atan2(math.sin(cache["yaw"] - yaw_before),
                                math.cos(cache["yaw"] - yaw_before)))
    yaw_truth_d = 0.0
    truth_ok_b = bool(st_b and st_b2)
    if truth_ok_b:
        yaw_truth_d = abs(math.atan2(math.sin(st_b2[3] - st_b[3]),
                                     math.cos(st_b2[3] - st_b[3])))
    if yaw_acc != 0.0:
        print(f"odom 转角: {math.degrees(yaw_odom_d):.1f}°    "
              f"真值转角（link_states 增量累加）: {math.degrees(yaw_acc):.1f}°")
        print(f"  （entity_state 首末差 {math.degrees(yaw_truth_d):.1f}° 为 atan2 折叠值，仅供参考）")
    else:
        print(f"odom 转角: {math.degrees(yaw_odom_d):.1f}°    真值转角: {math.degrees(yaw_truth_d):.1f}°")
    if ls_b is not None and ls_a is not None:
        yaw_ls_d = abs(math.atan2(math.sin(ls_a - ls_b), math.cos(ls_a - ls_b)))
        print(f"[link_states] 首末 yaw 差（可能折叠）: {math.degrees(yaw_ls_d):.1f}°"
              f"（前 {math.degrees(ls_b):.1f}° → 后 {math.degrees(ls_a):.1f}°）")
    # 判读优先用增量累加（entity_state 首末差会 atan2 折叠：实转 250° 只显示 83°）
    yaw_judge = yaw_acc if yaw_acc != 0.0 else (yaw_truth_d if truth_ok_b else 0.0)
    if yaw_acc == 0.0 and not truth_ok_b:
        print("→ 真值缺失，无法判定车是否真转")
    elif yaw_judge > 1.0:
        print("→ 转向正常 ✓（5s 真值转角 > 57°，即角速度 > 0.2 rad/s）")
    elif yaw_judge > 0.2:
        print("→ 转向有牵引力但偏弱（< 57°/5s）")
    elif yaw_odom_d > 0.2:
        print("→ 轮子空转（odom 认为转了、真值没转）→ 摩擦不足")
    else:
        print("→ 插件未驱动轮子（角速度指令未生效）")

    # 5) 清理
    call(["ros2", "service", "call", "/delete_entity", "gazebo_msgs/srv/DeleteEntity",
          f"{{name: '{ROBOT}'}}"], tolerant=True)
    node.destroy_node()
    rclpy.shutdown()
    print("\n[OK] 探针完成，车辆已删除")


if __name__ == "__main__":
    main()
