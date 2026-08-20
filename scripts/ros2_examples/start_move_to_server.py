"""
move_to 服务端启动入口（每台车一个进程）

用法（需 ROS 2 环境 + 已编译 sim_interfaces）：
    python3 start_move_to_server.py agv_1
    python3 start_move_to_server.py agv_2

自愈：启动前自动 SIGKILL 同名残留进程（防旧死锁进程抢 Service 请求）。
"""
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.sim_gazebo_srv import MoveToServer


def kill_stale_servers(robot_id: str) -> int:
    """SIGKILL 清理同名残留服务端进程，返回清理数量

    死锁版旧进程卡在阻塞回调里，SIGTERM（pkill 默认）退不掉，
    会在 DDS 上留下同名 Service 提供者抢请求 → 客户端纯超时。
    这里用 SIGKILL 强制清理，只杀同名（同车）残留，不动其他车的进程。
    """
    killed = 0
    try:
        out = subprocess.run(
            ["pgrep", "-fa", "start_move_to_server"],
            capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            pid = int(parts[0])
            if pid == os.getpid():          # 跳过自己（pgrep 会列出本进程）
                continue
            if robot_id in parts[2:]:       # 命令行参数里含同车 robot_id
                print(f"[自愈] 清理同名残留服务端进程 pid={pid}")
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                except ProcessLookupError:
                    pass
    except Exception as e:
        print(f"[自愈] 残留扫描失败（可忽略）: {e}")
    return killed


def main():
    robot_id = sys.argv[1] if len(sys.argv) > 1 else "agv_1"
    if kill_stale_servers(robot_id):
        # SIGKILL 不会给 DDS 留退出声明，僵尸节点要等发现租约（约 20s）
        # 过期才从图中消失；立即重启会与僵尸同名节点并存，请求被路由吞掉
        print("[自愈] 等待 DDS 发现租约过期（约 20s）...")
        time.sleep(20.0)
    MoveToServer.spin(robot_id)


if __name__ == "__main__":
    main()
