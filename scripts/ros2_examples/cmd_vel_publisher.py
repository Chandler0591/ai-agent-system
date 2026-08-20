"""
发布 /cmd_vel 控制小车移动示例
运行：python3 cmd_vel_publisher.py [/cmd_vel 或 /agv_1/cmd_vel]（需 Gazebo + 车模型运行中）

对应本项目 SimBackend.move_robot_by_velocity() 的 Gazebo 底层实现。
"""
import sys
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class CmdVelPublisher(Node):
    def __init__(self, topic: str = '/cmd_vel'):
        super().__init__('cmd_vel_pub')
        self.pub = self.create_publisher(Twist, topic, 10)

    def go(self, vx: float = 0.2, seconds: float = 5.0):
        """前进 vx m/s，持续 seconds 秒后自动停车"""
        msg = Twist()
        msg.linear.x = vx          # 前进速度
        # msg.angular.z = 0.5      # 可加旋转（rad/s）
        self.pub.publish(msg)
        self.get_logger().info(f'前进 {vx} m/s，{seconds}s 后停车')
        self.create_timer(seconds, self.stop)   # 定时停车

    def stop(self):
        self.pub.publish(Twist())  # 全零 Twist = 停（ROS 2 约定）
        self.get_logger().info('已停车')


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else '/cmd_vel'
    rclpy.init()
    node = CmdVelPublisher(topic)
    node.go(vx=0.2, seconds=5.0)
    rclpy.spin(node)               # 保持节点存活等待定时器
    rclpy.shutdown()


if __name__ == '__main__':
    main()
