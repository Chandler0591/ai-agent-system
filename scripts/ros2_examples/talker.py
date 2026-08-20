"""
最小发布者示例（talker）
运行：python3 talker.py（需 ROS 2 环境）
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class Talker(Node):
    def __init__(self):
        super().__init__('talker')                              # 1. 创建节点
        self.pub = self.create_publisher(String, 'chatter', 10)  # 2. 创建发布者
        self.create_timer(0.5, self.cb)                         # 每 0.5s 触发

    def cb(self):
        msg = String()
        msg.data = 'hello ros2'
        self.pub.publish(msg)                                   # 3. 发布
        self.get_logger().info(f'发了: {msg.data}')


def main():
    rclpy.init()
    rclpy.spin(Talker())   # spin 保持节点存活，定时器持续触发
    rclpy.shutdown()


if __name__ == '__main__':
    main()
