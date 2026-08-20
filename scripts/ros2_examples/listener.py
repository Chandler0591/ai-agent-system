"""
最小订阅者示例（listener）
运行：python3 listener.py（需 ROS 2 环境，配合 talker.py）
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class Listener(Node):
    def __init__(self):
        super().__init__('listener')
        # 订阅 + 回调（第三个参数是回调函数，第四个是 QoS 深度）
        self.sub = self.create_subscription(String, 'chatter', self.cb, 10)

    def cb(self, msg):
        self.get_logger().info(f'收到: {msg.data}')


def main():
    rclpy.init()
    rclpy.spin(Listener())
    rclpy.shutdown()


if __name__ == '__main__':
    main()
