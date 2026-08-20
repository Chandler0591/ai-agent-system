"""
订阅 /odom 读取小车位置示例
运行：python3 odom_reader.py [/odom 或 /agv_1/odom]（需 odom 话题存在）

对应本项目 SimBackend.get_robot_pose() 的 Gazebo 数据源。
"""
import math
import sys
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry


def quat_to_yaw(w: float, x: float, y: float, z: float) -> float:
    """四元数 → 绕 Z 轴 yaw 角（弧度），ROS 2 标准套路"""
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny, cosy)


class OdomReader(Node):
    def __init__(self, topic: str = '/odom'):
        super().__init__('odom_reader')
        self.sub = self.create_subscription(Odometry, topic, self.cb, 10)
        self.last = None   # (x, y, yaw_deg) 缓存

    def cb(self, msg: Odometry):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        yaw_deg = math.degrees(quat_to_yaw(ori.w, ori.x, ori.y, ori.z))
        self.last = (pos.x, pos.y, yaw_deg)
        self.get_logger().info(f'位置: x={pos.x:.2f} y={pos.y:.2f} yaw={yaw_deg:.1f}°')


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else '/odom'
    rclpy.init()
    rclpy.spin(OdomReader(topic))
    rclpy.shutdown()


if __name__ == '__main__':
    main()
